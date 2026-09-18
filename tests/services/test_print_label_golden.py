"""Golden regression for the Classic ``print_label`` request (hub issue #213).

The Classic Path is the compatibility behaviour every released card still
speaks: one ``growspace_manager.print_label`` service call (or the websocket
command that forwards to it) per strain, plant, or batch item, previewed or
printed. Its output is the exact ``niimbot.print`` service data.

These cases pin that output byte for byte against
``tests/fixtures/labels/classic_print_label_golden.json``, which was captured
from the fixed-coordinate implementation before the canonical rendering seam
was introduced. Nothing here asserts that the layout is *good* — only that
refactoring behind the seam leaves it unchanged.

A deliberate Classic output change must regenerate the fixture in the same
commit that changes the renderer, so the diff shows exactly which labels move.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun import freeze_time
import pytest

from custom_components.growspace_manager.services.strain_library import (
    handle_print_label,
)
from homeassistant.core import HomeAssistant, ServiceCall

GOLDEN_PATH = (
    Path(__file__).parent.parent
    / "fixtures"
    / "labels"
    / "classic_print_label_golden.json"
)

# Frozen so the label's printed-on stamp is stable; midday keeps the local date
# equal to the UTC one for every timezone the suite might run in.
FROZEN_NOW = "2026-09-18 12:00:00"
INTERNAL_URL = "http://homeassistant.local:8123"

SMALL_LOGO_DATA_URI = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="

SENSI_META = {
    "breeder": "Sensi",
    "lineage": "Afghani x Thai",
    "breeder_logo": "http://example.test/sensi.png",
}

# Each case is the complete Classic request plus the world it resolves against:
# ``plants`` puts the canonical plant in the coordinator, ``library`` is what
# the strain library returns for meta fallback.
CASES: dict[str, dict[str, Any]] = {
    # --- strain-library entry point -------------------------------------
    "strain_minimal": {"data": {"strain": "Blue Dream"}},
    "strain_full_overrides": {
        "data": {
            "strain": "Wedding Cake",
            "phenotype": "Pheno 3",
            "breeder": "Seed Junky",
            "lineage": "TK91 x Animal Mints",
            "breeder_logo": "http://example.test/logo.png",
        }
    },
    "strain_library_meta_fallback": {
        "data": {"strain": "Gelato"},
        "library": {
            "Gelato": {
                "meta": {
                    "breeder": "Cookie Fam",
                    "lineage": "Sunset Sherbet x TK",
                    "breeder_logo": "http://example.test/cookiefam.png",
                }
            }
        },
    },
    "strain_phenotype_default_collapses": {
        "data": {"strain": "Blue Dream", "phenotype": "default"}
    },
    "strain_small_data_uri_logo": {
        "data": {"strain": "Blue Dream", "breeder_logo": SMALL_LOGO_DATA_URI}
    },
    # --- plant entry point ----------------------------------------------
    "plant_web_qr": {"data": {"plant_id": "plant-1"}, "plants": True},
    "plant_base_url_qr": {
        "data": {"plant_id": "plant-1", "base_url": "https://grow.example.test/p"},
        "plants": True,
    },
    "plant_deeplink_qr": {
        "data": {"plant_id": "plant-1", "qr_target": "deeplink"},
        "plants": True,
    },
    # --- field visibility flags -----------------------------------------
    "plant_all_fields_off": {
        "data": {
            "plant_id": "plant-1",
            "fields": {
                "phenotype": False,
                "breeder": False,
                "lineage": False,
                "logo": False,
                "qr": False,
            },
        },
        "plants": True,
        "library": {"Northern Lights": {"meta": SENSI_META}},
    },
    "plant_qr_off_logo_on": {
        "data": {"plant_id": "plant-1", "fields": {"qr": False}},
        "plants": True,
        "library": {"Northern Lights": {"meta": SENSI_META}},
    },
    "plant_lineage_off": {
        "data": {"plant_id": "plant-1", "fields": {"lineage": False}},
        "plants": True,
        "library": {
            "Northern Lights": {
                "meta": {"breeder": "Sensi", "lineage": "Afghani x Thai"}
            }
        },
    },
    # --- density ---------------------------------------------------------
    "density_low": {"data": {"strain": "Blue Dream", "density": "low"}},
    "density_high": {"data": {"strain": "Blue Dream", "density": "high"}},
    "density_unknown_falls_back": {
        "data": {"strain": "Blue Dream", "density": "scorching"}
    },
    # --- label sizes and their coordinate scaling ------------------------
    "size_50x30": {"data": {"strain": "Blue Dream", "label_size": "50x30"}},
    "size_40x30": {"data": {"strain": "Blue Dream", "label_size": "40x30"}},
    "size_50x50": {"data": {"strain": "Blue Dream", "label_size": "50x50"}},
    "size_50x80": {"data": {"strain": "Blue Dream", "label_size": "50x80"}},
    "size_50x15": {"data": {"strain": "Blue Dream", "label_size": "50x15"}},
    "size_unknown_falls_back": {
        "data": {"strain": "Blue Dream", "label_size": "99x99"}
    },
    "size_50x50_with_logo_and_qr": {
        "data": {"plant_id": "plant-1", "label_size": "50x50"},
        "plants": True,
        "library": {"Northern Lights": {"meta": SENSI_META}},
    },
    # --- transport-level request fields ----------------------------------
    "preview_true": {"data": {"strain": "Blue Dream", "preview": True}},
    "device_id_targeted": {
        "data": {"strain": "Blue Dream", "device_id": "niimbot-b21"}
    },
}


def _canonical_plant() -> SimpleNamespace:
    return SimpleNamespace(
        genetics=SimpleNamespace(
            strain_name="Northern Lights", phenotype_name="Pheno A"
        )
    )


async def _capture(spec: dict[str, Any]) -> dict[str, Any]:
    """Run one Classic request and return the niimbot call it produced."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock(return_value={"status": "ok"})
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *a: func(*a))

    coordinator = MagicMock()
    coordinator.plants = {"plant-1": _canonical_plant()} if spec.get("plants") else {}

    library = MagicMock()
    library.load = AsyncMock()
    library.get_all = MagicMock(return_value=spec.get("library", {}))

    call = MagicMock(spec=ServiceCall)
    call.data = spec["data"]

    with (
        patch(
            "custom_components.growspace_manager.services.strain_library.get_url",
            return_value=INTERNAL_URL,
        ),
        freeze_time(FROZEN_NOW),
    ):
        await handle_print_label(hass, coordinator, library, call)

    domain, service, service_data = hass.services.async_call.call_args.args[:3]
    return {"domain": domain, "service": service, "service_data": service_data}


@pytest.fixture(scope="module")
def golden() -> dict[str, Any]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def test_golden_fixture_covers_exactly_the_case_matrix(golden: dict[str, Any]) -> None:
    """A case added here without regenerating the fixture is a silent gap."""
    assert sorted(golden) == sorted(CASES)


@pytest.mark.parametrize("name", sorted(CASES))
@pytest.mark.asyncio
async def test_classic_request_matches_golden(
    name: str, golden: dict[str, Any]
) -> None:
    """Every supported Classic case produces its recorded niimbot payload."""
    assert await _capture(CASES[name]) == golden[name]
