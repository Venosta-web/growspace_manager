"""The read-only Factory Template preview a card enters the template path on.

Issue #224. The card may show a template preview only once it has negotiated
the complete capability, and the preview it shows has to be the backend's own
raster rather than a drawing of a layout. These are the wire-level claims that
makes: what it refuses, what it returns, and what it leaves untouched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from freezegun import freeze_time
import pytest

from custom_components.growspace_manager.labels.canonical import (
    CAPABILITY_GENERATION,
    LABEL_SIZES,
    LONG_CONTENT,
    PROFILES,
)
from custom_components.growspace_manager.labels.capability import (
    CAPABILITY_FAMILY,
    contract_identity,
)
from custom_components.growspace_manager.labels.library.store import STORAGE_KEY_PREFIX
from custom_components.growspace_manager.websocket.labels import (
    COMMANDS,
    WS_TYPE_GET_LABEL_TEMPLATE_CAPABILITY,
    WS_TYPE_PREVIEW_LABEL_FACTORY_TEMPLATE,
    websocket_preview_label_factory_template,
)
from homeassistant.core import HomeAssistant

#: The stock the shipped Capability Profile can render. Every other Label Size
#: is catalogued and has a Factory Template, and none of them has a profile
#: yet -- which is a state this command has to answer honestly.
PROFILED_SIZE = next(iter(PROFILES.values())).label_size_id
UNPROFILED_SIZES = tuple(
    size_id
    for size_id in LABEL_SIZES
    if not any(profile.label_size_id == size_id for profile in PROFILES.values())
)


def _message(**overrides: Any) -> dict[str, Any]:
    """One command message with every optional field defaulted as the schema does."""
    message: dict[str, Any] = {
        "contract": contract_identity(),
        "label_size_id": PROFILED_SIZE,
        "context": "strain",
        "fixture_family": "typical",
        "density": "normal",
        "locale": "en",
    }
    message.update(overrides)
    return message


async def _preview(hass: HomeAssistant, **overrides: Any) -> dict[str, Any]:
    return await websocket_preview_label_factory_template(
        hass,
        None,  # type: ignore[arg-type]
        _message(**overrides),
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_discovery_and_preview_are_the_two_label_commands() -> None:
    assert [command.type for command in COMMANDS] == [
        WS_TYPE_GET_LABEL_TEMPLATE_CAPABILITY,
        WS_TYPE_PREVIEW_LABEL_FACTORY_TEMPLATE,
    ]


def test_only_discovery_is_reachable_without_a_negotiated_contract() -> None:
    """Discovery is how a card finds out; everything else is gated on knowing."""
    discovery, preview = COMMANDS
    assert "contract" not in discovery.schema.schema
    assert "contract" in preview.schema.schema


# ---------------------------------------------------------------------------
# What it refuses, and how legibly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("contract", "reason"),
    [
        ({}, "unknown"),
        ({"family": "some.other.product", "major": 1, "generation": 1}, "unknown"),
        ({"family": CAPABILITY_FAMILY, "major": 99, "generation": 1}, "unknown"),
        (
            {
                "family": CAPABILITY_FAMILY,
                "major": 1,
                "generation": CAPABILITY_GENERATION - 1,
            },
            "stale",
        ),
    ],
)
async def test_a_stale_or_unknown_contract_is_refused_before_anything_renders(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    contract: dict[str, Any],
    reason: str,
) -> None:
    payload = await _preview(hass, contract=contract)

    assert payload["outcome"] == "refused"
    assert payload["refusal"]["code"] == "label_template.contract_incompatible"
    assert payload["refusal"]["reason"] == reason
    assert payload["refusal"]["recovery"] == "refresh_capability"
    assert payload["refusal"]["current"] == contract_identity()
    # Refused before starting: nothing reached the printer adapter.
    assert printer == []


@pytest.mark.parametrize("label_size_id", UNPROFILED_SIZES)
async def test_a_stock_no_profile_can_render_says_so_rather_than_previewing_another(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    label_size_id: str,
) -> None:
    payload = await _preview(hass, label_size_id=label_size_id)

    assert payload["outcome"] == "refused"
    assert payload["refusal"]["code"] == "label_template.no_capability_profile"
    assert payload["refusal"]["label_size_id"] == label_size_id
    assert payload["refusal"]["recovery"] == "choose_another_label_size"
    assert printer == []


async def test_an_uncatalogued_stock_is_refused_as_a_capability_mismatch(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
) -> None:
    payload = await _preview(hass, label_size_id="growspace.stock.99x99.v1")

    assert payload["refusal"]["code"] == "label_template.unknown_label_size"
    assert payload["refusal"]["recovery"] == "refresh_capability"
    assert printer == []


async def test_an_unsupported_print_locale_blocks_the_preview(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
) -> None:
    """It never silently prints English under another locale's name."""
    payload = await _preview(hass, locale="zxx-Zzzz")

    assert payload["refusal"]["code"] == "label_template.unsupported_locale"
    assert payload["refusal"]["locale"] == "zxx-Zzzz"
    assert printer == []


async def test_an_unknown_print_context_is_refused(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    payload = await _preview(hass, context="terrarium")

    assert payload["refusal"]["code"] == "label_template.unknown_print_context"
    assert printer == []


async def test_an_unknown_fixture_family_is_refused(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    payload = await _preview(hass, fixture_family="pathological")

    assert payload["refusal"]["code"] == "label_template.unknown_fixture"
    assert printer == []


# ---------------------------------------------------------------------------
# What it returns
# ---------------------------------------------------------------------------


async def test_the_preview_is_the_backend_s_own_raster(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    payload = await _preview(hass)

    assert payload["outcome"] == "rendered"
    assert payload["contract"] == contract_identity()
    raster = payload["render"]["raster"]
    assert raster["content_type"] == "image/png"
    assert raster["image"].startswith("data:image/png;base64,")
    assert raster["monochrome"] is True
    assert len(printer) == 1


async def test_the_preview_names_the_exact_shipped_template_it_drew(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    payload = await _preview(hass)

    template = payload["template"]
    assert template["label_size_id"] == PROFILED_SIZE
    assert template["revision"] >= 1
    assert (
        template["layout_digest"]
        == payload["render"]["render_context"]["layout_digest"]
    )


async def test_the_preview_carries_the_render_context_and_eligibility(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    """The raster alone cannot say what it may authorize; the result must."""
    payload = await _preview(hass)

    render = payload["render"]
    assert render["render_context"]["operation"] == "preview"
    assert render["profile"]["id"] == next(iter(PROFILES))
    assert render["profile"]["evidence"] == "product_verified"
    # A factory preview is of a fixture, and no printer here was measured.
    assert render["printable"] is False
    assert render["eligibility"]["single_print"]["allowed"] is False


async def test_the_fixture_family_chooses_the_subject_that_was_drawn(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    typical = await _preview(hass)
    long_content = await _preview(hass, fixture_family=LONG_CONTENT)

    assert typical["subject"] != long_content["subject"]
    assert long_content["fixture_family"] == LONG_CONTENT
    assert (
        typical["render"]["render_context"]["content_identity"]
        != long_content["render"]["render_context"]["content_identity"]
    )


async def test_the_preview_creates_no_template_state(
    hass: HomeAssistant, printer: list[dict[str, Any]], tmp_path: Path
) -> None:
    """A read-only preview is not a way to acquire a library you did not ask for."""
    await _preview(hass)
    await hass.async_block_till_done()

    written = Path(hass.config.config_dir, ".storage")
    assert not list(written.glob(f"{STORAGE_KEY_PREFIX}*"))


# ---------------------------------------------------------------------------
# The shape the card is held to
# ---------------------------------------------------------------------------

FIXTURE_PATH = (
    Path(__file__).parent.parent
    / "fixtures"
    / "contract"
    / "label_factory_template_preview_v1.json"
)

REFUSAL_FIXTURE_PATH = FIXTURE_PATH.with_name(
    "label_factory_template_preview_refused_v1.json"
)


@freeze_time("2026-09-18T00:00:00+00:00")
async def test_the_shared_preview_fixture_is_exact(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    pytestconfig: pytest.Config,
) -> None:
    """One recorded response the card's schema is parsed against.

    Frozen, because a Render Context is supposed to carry the instant it was
    taken -- and a fixture that re-records itself on every run proves nothing
    about the shape the card reads.
    """
    hass.config.time_zone = "UTC"
    payload = await _preview(hass)

    if pytestconfig.getoption("regenerate_contract_fixture"):
        FIXTURE_PATH.write_text(
            f"{json.dumps(payload, indent=2, sort_keys=True)}\n", encoding="utf-8"
        )
    assert FIXTURE_PATH.exists()
    assert payload == json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@freeze_time("2026-09-18T00:00:00+00:00")
async def test_the_shared_refusal_fixture_is_exact(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    pytestconfig: pytest.Config,
) -> None:
    """The other half of the union, recorded for the same reason."""
    payload = await _preview(
        hass,
        contract={
            "family": CAPABILITY_FAMILY,
            "major": 1,
            "generation": CAPABILITY_GENERATION - 1,
        },
    )

    if pytestconfig.getoption("regenerate_contract_fixture"):
        REFUSAL_FIXTURE_PATH.write_text(
            f"{json.dumps(payload, indent=2, sort_keys=True)}\n", encoding="utf-8"
        )
    assert REFUSAL_FIXTURE_PATH.exists()
    assert payload == json.loads(REFUSAL_FIXTURE_PATH.read_text(encoding="utf-8"))
