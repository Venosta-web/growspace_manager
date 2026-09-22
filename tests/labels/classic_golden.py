"""The Classic compatibility golden matrix: every legacy size x visible fields.

A Classic request names one of five legacy Label Sizes and five visibility
flags, and the Compatibility Adapter maps each of those 5 x 32 combinations to
its own versioned compatibility layout (hub #240). This module pins what every
one of them prints: the raster inputs the adapter hands the printer
integration, their digest, and the PNG those inputs really rasterize to.

Each golden is taken from the **canonical** path -- the compatibility layout,
content snapshot and profile compiled by `compile_layout` -- and the suite then
holds two things to it:

1. the canonical path still produces exactly these inputs, and
2. the retired fixed-coordinate renderer produces them too, byte for byte.

The second is the proof the fixed renderer can go (hub #232): the moment the
two disagree, a Classic label has changed.

Every case prints the same fully populated plant, so every flag decides
something: three body lines, a logo and a QR code are all available to show
or suppress.

Recording needs `imagespec` and the `niimbot` fonts, as the Template goldens
do:

    uv run --no-project --python ../../.venv/bin/python \\
        --with "imagespec[datamatrix]==0.4.0" \\
        python -m tests.labels.classic_golden record \\
        --fonts <niimbot checkout>/custom_components/niimbot/fonts \\
        --reviewer <name> --reason "<which identity moved, and why>"

`verify` re-rasterizes every recorded payload and checks each PNG reproduces.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from itertools import product
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun import freeze_time

from custom_components.growspace_manager.labels.canonical import (
    COMPILER_VERSION,
    digest,
)
from custom_components.growspace_manager.labels.canonical.compatibility import (
    CLASSIC_CANVASES,
    COMPATIBILITY_LAYOUT_VERSION,
    DETAIL_LINES,
    FIELD_FLAGS,
    layout_id,
)
from custom_components.growspace_manager.labels.classic import (
    compile_classic,
    resolve_classic_request,
)
from custom_components.growspace_manager.labels.model import LabelContent
from custom_components.growspace_manager.labels.niimbot import async_raster_inputs
from custom_components.growspace_manager.labels.renderer import render
from homeassistant.core import HomeAssistant

from .golden_matrix import EVIDENCE_RENDERER, EVIDENCE_RENDERER_VERSION, rasterize

GOLDEN_DIRECTORY = (
    Path(__file__).parent.parent / "fixtures" / "labels" / "classic_golden"
)
MANIFEST_PATH = GOLDEN_DIRECTORY / "manifest.json"
PAYLOADS_PATH = GOLDEN_DIRECTORY / "payloads.json"

#: Midday, so the printed-on stamp is the same date in every time zone.
FROZEN_NOW = "2026-09-18 12:00:00"
INTERNAL_URL = "http://homeassistant.local:8123"

PLANT_ID = "plant-1"
STRAIN = "Northern Lights"
PHENOTYPE = "Pheno A"
BREEDER = "Sensi"
LINEAGE = "Afghani x Thai"
#: A 32x32 one-bit ring, inline so rasterizing needs no network.
LOGO = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgAQAAAABbAUdZAAAAXUlEQVR4"
    "nH3OsQ3CQBQE0efFAZndAS6FzmjNJVCCSzgkAgeWP8EhQpLRBLPSDoVAvGbxfFOUk0dO1hxs2afWe"
    "tfYu20c3+1fLIzdZq4BO7eMLAl3RcV6odpUw+/VB10AGi98N9JcAAAAAElFTkSuQmCC"
)


@dataclass(frozen=True, slots=True)
class ClassicCase:
    """One legacy size with one set of fields left visible."""

    size: str
    visible: frozenset[str]

    @property
    def id(self) -> str:
        """The case's stable name: the layout identity without its version."""
        return (
            layout_id(self.size, self.visible)
            .removeprefix(f"{COMPATIBILITY_LAYOUT_VERSION}/")
            .replace("/", ".")
        )

    @property
    def fields(self) -> dict[str, bool]:
        """The `fields` object a Classic request sends for this case."""
        return {flag: flag in self.visible for flag in FIELD_FLAGS}


def classic_cases() -> tuple[ClassicCase, ...]:
    """Every legacy size crossed with every combination of the five flags."""
    return tuple(
        ClassicCase(
            size,
            frozenset(
                flag for flag, shown in zip(FIELD_FLAGS, flags, strict=True) if shown
            ),
        )
        for size in CLASSIC_CANVASES
        for flags in product((True, False), repeat=len(FIELD_FLAGS))
    )


def current_identity() -> dict[str, Any]:
    """The identities a Classic golden was recorded under."""
    return {
        "compatibility_layout_version": COMPATIBILITY_LAYOUT_VERSION,
        "compiler_version": COMPILER_VERSION,
        "renderer": EVIDENCE_RENDERER,
        "renderer_version": EVIDENCE_RENDERER_VERSION,
    }


def _hass() -> MagicMock:
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *a: func(*a))
    return hass


async def async_canonical_inputs(case: ClassicCase) -> dict[str, Any]:
    """The raster inputs the Compatibility Adapter compiles for one case."""
    coordinator = MagicMock()
    coordinator.plants = {
        PLANT_ID: SimpleNamespace(
            genetics=SimpleNamespace(strain_name=STRAIN, phenotype_name=PHENOTYPE)
        )
    }
    library = MagicMock()
    library.load = AsyncMock()
    library.get_all = MagicMock(
        return_value={
            STRAIN: {
                "meta": {"breeder": BREEDER, "lineage": LINEAGE, "breeder_logo": LOGO}
            }
        }
    )
    hass = _hass()
    with patch(
        "custom_components.growspace_manager.labels.classic.get_url",
        return_value=INTERNAL_URL,
    ):
        request = await resolve_classic_request(
            hass,
            coordinator,
            library,
            {"plant_id": PLANT_ID, "label_size": case.size, "fields": case.fields},
        )
    return await async_raster_inputs(hass, compile_classic(request).plan)


async def async_fixed_inputs(case: ClassicCase) -> dict[str, Any]:
    """The raster inputs the retired fixed-coordinate renderer paints."""
    lines = {"phenotype": PHENOTYPE, "breeder": BREEDER, "lineage": LINEAGE}
    content = LabelContent(
        title=STRAIN,
        info_lines=tuple(lines[line] for line in DETAIL_LINES if line in case.visible),
        logo=LOGO if "logo" in case.visible else None,
        qr_data=(f"{INTERNAL_URL}/plant/{PLANT_ID}" if "qr" in case.visible else None),
        printed_on="18.09.2026",
    )
    return await async_raster_inputs(
        _hass(), render(content, label_size=case.size, density="normal")
    )


def _run(coroutine: Any) -> dict[str, Any]:
    """Run one case on a private loop.

    Not `asyncio.run`, which would also clear the thread's current loop out
    from under a test harness that owns one.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coroutine)
    finally:
        loop.close()


def canonical_inputs(case: ClassicCase) -> dict[str, Any]:
    """Compile one case through the canonical path, at the frozen instant."""
    with freeze_time(FROZEN_NOW):
        return _run(async_canonical_inputs(case))


def fixed_inputs(case: ClassicCase) -> dict[str, Any]:
    """Paint one case with the retired fixed renderer."""
    return _run(async_fixed_inputs(case))


def png_path(case_id: str) -> Path:
    """Where one case's reviewed raster lives."""
    return GOLDEN_DIRECTORY / f"{case_id}.png"


def load_manifest() -> dict[str, Any]:
    """The recorded manifest, or an empty one."""
    if not MANIFEST_PATH.exists():
        return {"identity": {}, "cases": {}, "history": []}
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def load_payloads() -> dict[str, Any]:
    """Every recorded case's raster inputs."""
    if not PAYLOADS_PATH.exists():
        return {}
    return json.loads(PAYLOADS_PATH.read_text(encoding="utf-8"))


def _sha256(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _say(message: str, *, error: bool = False) -> None:
    (sys.stderr if error else sys.stdout).write(f"{message}\n")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def record(fonts: Path, reviewer: str, reason: str) -> int:
    """Record every case from the canonical path, refusing silent changes."""
    manifest = load_manifest()
    identity = current_identity()
    payloads: dict[str, Any] = {}
    cases: dict[str, Any] = {}
    for case in classic_cases():
        inputs = canonical_inputs(case)
        if inputs != fixed_inputs(case):
            _say(
                f"{case.id}: the canonical path and the fixed renderer differ",
                error=True,
            )
            return 1
        image = rasterize(inputs, fonts)
        png_path(case.id).write_bytes(image)
        payloads[case.id] = inputs
        cases[case.id] = {
            "raster_inputs": digest(inputs),
            "png_sha256": _sha256(image),
        }

    moved = {
        key for key, value in identity.items() if manifest["identity"].get(key) != value
    }
    changed = [
        case_id
        for case_id, entry in cases.items()
        if manifest["cases"].get(case_id, {}).get("raster_inputs")
        not in (None, entry["raster_inputs"])
    ]
    if changed and not moved:
        _say(
            f"{len(changed)} Classic goldens changed with no identity moving: "
            + ", ".join(changed[:5]),
            error=True,
        )
        return 1

    manifest["identity"] = identity
    manifest["cases"] = cases
    manifest["history"].append(
        {
            "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "reviewer": reviewer,
            "reason": reason,
            "identity": identity,
            "changed": sorted(changed),
        }
    )
    _write_json(PAYLOADS_PATH, payloads)
    _write_json(MANIFEST_PATH, manifest)
    _say(f"Recorded {len(cases)} Classic goldens; {len(changed)} changed.")
    return 0


def verify(fonts: Path) -> int:
    """Re-rasterize every recorded payload and compare the PNG bytes."""
    manifest = load_manifest()
    failures = 0
    for case_id, inputs in load_payloads().items():
        if (
            _sha256(rasterize(inputs, fonts))
            != manifest["cases"][case_id]["png_sha256"]
        ):
            _say(f"{case_id}: the recorded PNG does not reproduce", error=True)
            failures += 1
    _say(f"Verified {len(manifest['cases']) - failures} Classic goldens.")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    """Record or verify the Classic compatibility goldens."""
    parser = argparse.ArgumentParser(prog="python -m tests.labels.classic_golden")
    commands = parser.add_subparsers(dest="command", required=True)
    recording = commands.add_parser("record")
    recording.add_argument("--fonts", type=Path, required=True)
    recording.add_argument("--reviewer", required=True)
    recording.add_argument("--reason", required=True)
    verifying = commands.add_parser("verify")
    verifying.add_argument("--fonts", type=Path, required=True)
    arguments = parser.parse_args(argv)
    GOLDEN_DIRECTORY.mkdir(parents=True, exist_ok=True)
    if arguments.command == "record":
        return record(arguments.fonts, arguments.reviewer, arguments.reason)
    return verify(arguments.fonts)


if __name__ == "__main__":
    sys.exit(main())
