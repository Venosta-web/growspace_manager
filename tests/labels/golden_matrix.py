"""The golden raster matrix: what every shipped label prints, pinned (hub #230).

A golden here is the complete set of raster inputs the adapter hands the
printer integration -- canvas, density and the `imagespec` payload -- for one
layout, one profile, one representative subject and one locale, together with
the PNG that payload really rasterizes to. The inputs are what CI holds to; the
PNG is the reviewed visual evidence that those inputs print what they should.

Two rules make the set a release gate rather than a snapshot suite that gets
regenerated whenever it goes red:

1. **Output does not move without an identity moving.** The manifest records
   the compiler, renderer, adapter, font, asset and policy identities the
   goldens were recorded under. A payload that differs while every one of them
   is unchanged is a silent change to what labels print, and nothing -- neither
   this module's `record` command nor the test suite -- accepts it.
2. **Every recording is reviewed.** Recording appends to the manifest's
   history with a named reviewer and a reason, and it rasterizes every case
   through the renderer the printer integration pins so the PR carries the
   PNGs for a reviewer to look at. A history entry whose goldens changed must
   name a different identity than the entry before it.

The matrix is derived from the catalogues rather than listed, so shipping a
profile, a Factory Template, a representative family, a print context, an
element rotation or a locale with its own date order adds cases the suite then
refuses to run without. Density is deliberately not a raster dimension: it
changes the device level and never the bitmap, and the manifest pins each
profile's whole definition -- density map included -- in its identity.

Recording needs the renderer and its fonts, which belong to the `niimbot`
integration and are not installed in this suite. Layer them on for one run:

    uv run --no-project --python ../../.venv/bin/python \\
        --with "imagespec[datamatrix]==0.4.0" \\
        python -m tests.labels.golden_matrix record \\
        --fonts <niimbot checkout>/custom_components/niimbot/fonts \\
        --reviewer <name> --reason "<which identity moved, and why>"

`verify` re-rasterizes every recorded payload and checks each PNG reproduces
byte for byte, which is how a reviewer confirms the evidence was rendered
rather than edited.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from PIL import Image

from custom_components.growspace_manager.labels.canonical import (
    ADAPTER_VERSION,
    BINDING_CATALOGUE_VERSION,
    COMPILER_VERSION,
    FACTORY_TEMPLATES,
    FIXTURE_CATALOGUE_VERSION,
    LABEL_SIZE_CATALOGUE_VERSION,
    PROFILE_CATALOGUE_VERSION,
    PROFILES,
    QR_MODEL_VERSION,
    RENDERER_VERSION,
    REPRESENTATIVE_FAMILIES,
    SAFETY_POLICY_VERSION,
    STYLE_TOKEN_CATALOGUE_VERSION,
    SUPPORTED_LOCALES,
    TEXT_TOOLCHAIN_VERSION,
    CapabilityProfile,
    LabelLayout,
    compile_layout,
    digest,
    validate_document,
)
from custom_components.growspace_manager.labels.canonical.content import format_date
from custom_components.growspace_manager.labels.niimbot import async_raster_inputs
from homeassistant.core import HomeAssistant

GOLDEN_DIRECTORY = Path(__file__).parent.parent / "fixtures" / "labels" / "golden"
MANIFEST_PATH = GOLDEN_DIRECTORY / "manifest.json"

#: The instant every golden is taken at, so a printed date is a constant.
AS_OF = datetime(2026, 9, 18, tzinfo=UTC)
TIME_ZONE = "UTC"
#: The locale every family is recorded in. Other locales are recorded only
#: where they print differently, and only for the typical family: their
#: formatting rules have exhaustive unit tests of their own, so the matrix
#: needs one witness per distinct civil order, not a Cartesian product.
BASE_LOCALE = SUPPORTED_LOCALES[0]
WITNESS_FAMILY = "typical"
DENSITY = "normal"

#: The renderer the `niimbot` integration pins, and how it calls it.
EVIDENCE_RENDERER = "imagespec"
EVIDENCE_RENDERER_VERSION = "0.4.0"
EVIDENCE_DEFAULT_FONT = "ppb.ttf"


# ---------------------------------------------------------------------------
# The element-kind coverage layouts
# ---------------------------------------------------------------------------


def _coverage_50x30(rotation: int) -> dict[str, Any]:
    """Every element kind on 50x30, each bound so the contexts differ.

    The shipped 50x30 layout carries text and a divider only, so this is what
    puts a logo and a QR on paper. The QR is bound to `plant.link`, which a
    strain cannot resolve -- the strain case therefore pins how a missing QR
    target is left off the raster, which is a golden in its own right.
    """

    def text(
        element_id: str,
        binding: str,
        parameters: Mapping[str, str],
        y_mm: float,
        *,
        size_mm: float = 3.2,
        minimum_mm: float = 2.2,
        height_mm: float = 4.4,
        maximum_lines: int = 1,
        font: str = "growspace.sans.regular.v1",
    ) -> dict[str, Any]:
        return {
            "id": element_id,
            "kind": "text",
            "frame": {
                "x_mm": 2.0,
                "y_mm": y_mm,
                "width_mm": 30.0,
                "height_mm": height_mm,
            },
            "rotation": rotation,
            "content": {"binding": binding, "parameters": dict(parameters)},
            "style": {
                "font": font,
                "font_size_mm": size_mm,
                "horizontal_align": "left",
                "vertical_align": "center",
                "line_spacing": "growspace.spacing.compact.v1",
                "overflow": "shrink_ellipsis",
                "minimum_font_size_mm": minimum_mm,
                "maximum_lines": maximum_lines,
            },
        }

    return {
        "schema": "growspace.label-layout",
        "version": 1,
        "label_size_id": "growspace.stock.50x30.v1",
        "elements": [
            text(
                "golden.coverage.strain-name",
                "strain.name",
                {},
                2.0,
                size_mm=5.6,
                minimum_mm=3.0,
                height_mm=8.4,
                maximum_lines=2,
                font="growspace.sans.bold.v1",
            ),
            {
                "id": "golden.coverage.breeder-logo",
                "kind": "logo",
                "frame": {
                    "x_mm": 34.0,
                    "y_mm": 2.0,
                    "width_mm": 12.0,
                    "height_mm": 8.0,
                },
                "rotation": rotation,
                "content": {"binding": "strain.breeder.logo", "parameters": {}},
                "style": {
                    "monochrome": "growspace.mono.threshold.v1",
                    "fit": "contain",
                },
            },
            {
                "id": "golden.coverage.rule",
                "kind": "divider",
                "frame": {
                    "x_mm": 2.0,
                    "y_mm": 11.0,
                    "width_mm": 30.0,
                    "height_mm": 0.4,
                },
                "rotation": rotation,
                "style": {"fill": "black"},
            },
            text(
                "golden.coverage.stage-age",
                "plant.stage_and_age",
                {},
                12.2,
            ),
            text(
                "golden.coverage.stage-started",
                "plant.stage_started_on",
                {"presentation": "labeled", "date_style": "medium"},
                17.0,
            ),
            text(
                "golden.coverage.print-date",
                "print.date",
                {"date_style": "short"},
                21.8,
            ),
            {
                "id": "golden.coverage.plant-link",
                "kind": "qr",
                "frame": {
                    "x_mm": 34.0,
                    "y_mm": 12.0,
                    "width_mm": 12.0,
                    "height_mm": 12.0,
                },
                "rotation": rotation,
                "content": {
                    "binding": "plant.link",
                    "parameters": {"target": "dashboard_url"},
                },
                "style": {"error_correction": "medium", "quiet_zone_modules": 4},
            },
        ],
    }


#: One coverage layout per stock a profile exists for. A profile on a stock
#: missing here fails the matrix rather than quietly going without a logo or
#: a QR golden.
COVERAGE_LAYOUTS: Mapping[str, Callable[[int], dict[str, Any]]] = {
    "growspace.stock.50x30.v1": _coverage_50x30,
}


def coverage_layout(label_size_id: str, rotation: int) -> LabelLayout:
    """Validate one coverage document, refusing to pin an invalid layout."""
    result = validate_document(COVERAGE_LAYOUTS[label_size_id](rotation))
    if result.layout is None:
        codes = [item.code for item in result.diagnostics]
        raise ValueError(f"coverage layout for {label_size_id} is invalid: {codes}")
    return result.layout


# ---------------------------------------------------------------------------
# The matrix
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GoldenCase:
    """One cell of the matrix."""

    layout_name: str
    layout: LabelLayout
    profile: CapabilityProfile
    family: str
    context: str
    locale: str

    @property
    def id(self) -> str:
        """The case's file stem, readable in a PR's file list."""
        profile = self.profile.id.removeprefix("growspace.profile.")
        return (
            f"{self.layout_name}.{profile}.{self.family}.{self.context}.{self.locale}"
        )


def witness_locales() -> tuple[str, ...]:
    """Every supported locale that prints a date differently from the base.

    Probed rather than listed, so a new locale with its own civil order joins
    the matrix without anyone remembering to add it. A day above twelve keeps
    day-first and month-first from printing the same string.
    """
    probe = date(2026, 1, 23)

    def printed(locale: str) -> tuple[str, ...]:
        return tuple(format_date(probe, style, locale) for style in ("short", "medium"))

    seen = {printed(BASE_LOCALE)}
    witnesses: list[str] = []
    for locale in SUPPORTED_LOCALES:
        if (shape := printed(locale)) not in seen:
            seen.add(shape)
            witnesses.append(locale)
    return tuple(witnesses)


def _layouts_for(profile: CapabilityProfile) -> list[tuple[str, LabelLayout]]:
    """Every shipped layout on this profile's stock, and its coverage layouts."""
    layouts = [
        (
            f"factory-{template.id.rsplit('.', 1)[-1]}-r{template.revision}",
            template.layout,
        )
        for template in FACTORY_TEMPLATES.values()
        if template.label_size_id == profile.label_size_id
    ]
    layouts.extend(
        (
            f"coverage-{profile.label_size.id.split('.')[2]}-rot{rotation}",
            coverage_layout(profile.label_size_id, rotation),
        )
        for rotation in profile.supported_element_rotations
    )
    return layouts


def golden_cases() -> tuple[GoldenCase, ...]:
    """The whole matrix, in a stable order."""
    cases: list[GoldenCase] = []
    witnesses = witness_locales()
    for profile in PROFILES.values():
        for layout_name, layout in _layouts_for(profile):
            for family, subjects in REPRESENTATIVE_FAMILIES.items():
                for context in subjects:
                    locales = (BASE_LOCALE,)
                    if family == WITNESS_FAMILY:
                        locales += witnesses
                    cases.extend(
                        GoldenCase(
                            layout_name, layout, profile, family, str(context), locale
                        )
                        for locale in locales
                    )
    return tuple(cases)


def uncovered_stocks() -> tuple[str, ...]:
    """Profiled stocks with no coverage layout, which the suite refuses."""
    return tuple(
        sorted(
            {profile.label_size_id for profile in PROFILES.values()}
            - set(COVERAGE_LAYOUTS)
        )
    )


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def current_identity() -> dict[str, Any]:
    """Everything a golden's bytes may legitimately depend on, by name.

    Versions are the declared identities; the digests are what makes a
    profile or layout edit without a version bump visible anyway, because
    both change output as surely as a compiler does.
    """
    layouts: dict[str, str] = {}
    for profile in PROFILES.values():
        for name, layout in _layouts_for(profile):
            layouts[name] = layout.digest
    return {
        "compiler": COMPILER_VERSION,
        "renderer": RENDERER_VERSION,
        "adapter": ADAPTER_VERSION,
        "text_toolchain": TEXT_TOOLCHAIN_VERSION,
        "style_tokens": STYLE_TOKEN_CATALOGUE_VERSION,
        "qr_model": QR_MODEL_VERSION,
        "fixtures": FIXTURE_CATALOGUE_VERSION,
        "bindings": BINDING_CATALOGUE_VERSION,
        "safety_policy": SAFETY_POLICY_VERSION,
        "profiles": PROFILE_CATALOGUE_VERSION,
        "label_sizes": LABEL_SIZE_CATALOGUE_VERSION,
        "profile_definitions": {
            profile.id: digest(profile.as_dict()) for profile in PROFILES.values()
        },
        "layouts": dict(sorted(layouts.items())),
    }


def identity_changes(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    """Name every identity that differs, nested ones by path."""
    changed: list[str] = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if isinstance(old, Mapping) and isinstance(new, Mapping):
            changed.extend(f"{key}.{inner}" for inner in identity_changes(old, new))
        elif old != new:
            changed.append(key)
    return changed


def history_problems(history: list[Mapping[str, Any]]) -> list[str]:
    """Every way a recording history breaks the two rules, in order.

    Checked from the manifest alone, so CI can hold a pull request to it
    without knowing what the goldens looked like on another branch.
    """
    problems: list[str] = []
    if not history:
        return ["no goldens have been recorded"]
    for index, entry in enumerate(history):
        review = entry.get("review") or {}
        if not str(review.get("reviewer", "")).strip():
            problems.append(f"recording {index} names no reviewer")
        if not str(review.get("reason", "")).strip():
            problems.append(f"recording {index} gives no reason")
        try:
            date.fromisoformat(str(review.get("date")))
        except ValueError:
            problems.append(f"recording {index} has no review date")
        if index == 0:
            if entry.get("identity_changes") != ["initial"]:
                problems.append("the first recording is not marked initial")
            continue
        before = history[index - 1]
        moved = identity_changes(before["identity"], entry["identity"])
        if entry.get("identity_changes") != moved:
            problems.append(f"recording {index} misstates which identities moved")
        if entry["goldens_digest"] != before["goldens_digest"] and not moved:
            problems.append(
                f"recording {index} changed output without moving an identity"
            )
        if not moved and entry["evidence"] == before["evidence"]:
            problems.append(
                f"recording {index} changed neither an identity nor the evidence"
            )
    return problems


def goldens_digest(payload_digests: Mapping[str, str]) -> str:
    """One digest over every case's raster-input digest."""
    return digest(dict(sorted(payload_digests.items())))


# ---------------------------------------------------------------------------
# Compiling one case
# ---------------------------------------------------------------------------


def _hass() -> MagicMock:
    """Enough of Home Assistant for the adapter to build its inputs."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *a: func(*a))
    return hass


async def async_compile_case(case: GoldenCase) -> dict[str, Any]:
    """Return one case's golden record, without the evidence."""
    subject = REPRESENTATIVE_FAMILIES[case.family][case.context]  # type: ignore[index]
    snapshot = subject.snapshot(as_of=AS_OF, locale=case.locale, time_zone=TIME_ZONE)
    compiled = compile_layout(case.layout, snapshot, case.profile, density=DENSITY)
    inputs = await async_raster_inputs(_hass(), compiled.plan)
    return {
        "case": case.id,
        "layout": {"name": case.layout_name, "digest": case.layout.digest},
        "profile": case.profile.id,
        "subject": subject.id,
        "family": case.family,
        "context": case.context,
        "locale": case.locale,
        "as_of": AS_OF.isoformat(),
        "density": DENSITY,
        "content_identity": snapshot.identity,
        "raster_inputs": inputs,
        "raster_input_digest": digest(inputs),
        "outcomes": [item.as_dict() for item in compiled.outcomes],
        "diagnostics": sorted(
            {(item.code, str(item.severity)) for item in compiled.diagnostics}
        ),
    }


def compile_case(case: GoldenCase) -> dict[str, Any]:
    """Synchronous wrapper for the command line.

    A private loop rather than `asyncio.run`, which would also clear the
    thread's current loop out from under a test harness that owns one.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(async_compile_case(case))
    finally:
        loop.close()


def normalized(record: Mapping[str, Any]) -> Any:
    """A record as it round-trips through JSON, so tuples compare as lists."""
    return json.loads(json.dumps(record))


# ---------------------------------------------------------------------------
# Reading what is recorded
# ---------------------------------------------------------------------------


def case_path(case_id: str, suffix: str) -> Path:
    """Where one case's record or evidence lives."""
    return GOLDEN_DIRECTORY / f"{case_id}{suffix}"


def load_manifest() -> dict[str, Any]:
    """Return the manifest, or an empty one before anything was recorded."""
    if not MANIFEST_PATH.exists():
        return {"history": []}
    return json.loads(MANIFEST_PATH.read_text())


def load_case(case_id: str) -> dict[str, Any] | None:
    """Return one recorded case, if it was recorded."""
    path = case_path(case_id, ".json")
    return json.loads(path.read_text()) if path.exists() else None


def png_facts(data: bytes) -> tuple[tuple[int, int], int]:
    """Return a PNG's size and how many colours it uses."""
    with Image.open(BytesIO(data)) as image:
        return image.size, len(image.getcolors(256) or ())


# ---------------------------------------------------------------------------
# Rasterizing evidence -- only where the renderer is installed
# ---------------------------------------------------------------------------


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence_identity(fonts: Path) -> dict[str, Any]:
    """The renderer and the exact font files the evidence was drawn with."""
    import imagespec

    version = getattr(imagespec, "__version__", None)
    if version is None:
        from importlib.metadata import version as _version

        version = _version("imagespec")
    if version != EVIDENCE_RENDERER_VERSION:
        raise SystemExit(
            f"imagespec {version} is installed; the printer integration pins "
            f"{EVIDENCE_RENDERER_VERSION}. Evidence from another renderer is "
            "not evidence of what prints."
        )
    return {
        "renderer": f"{EVIDENCE_RENDERER} {version}",
        "fonts": {
            path.name: _file_sha256(path) for path in sorted(fonts.glob("*.ttf"))
        },
    }


def rasterize(inputs: Mapping[str, Any], fonts: Path) -> bytes:
    """Draw raster inputs exactly as the printer integration's `render_image`."""
    from imagespec import RenderContext, render

    def resolve(name: str) -> str | None:
        path = fonts / Path(name).name
        return str(path) if path.exists() else None

    image = render(
        payload=inputs["payload"],
        width=inputs["width"],
        height=inputs["height"],
        rotate=inputs["rotate"],
        rotate_mode="image",
        background="white",
        dither=False,
        context=RenderContext(
            font_resolver=resolve,
            history_provider=None,
            default_font=EVIDENCE_DEFAULT_FONT,
            palette=["black", "white"],
        ),
    )
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def _say(message: str, *, error: bool = False) -> None:
    """Report to whoever ran the command."""
    (sys.stderr if error else sys.stdout).write(f"{message}\n")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def record(fonts: Path, reviewer: str, reason: str) -> int:
    """Record the matrix, refusing an output change no identity explains."""
    manifest = load_manifest()
    history: list[dict[str, Any]] = manifest["history"]
    previous = history[-1] if history else None
    identity = current_identity()
    evidence = evidence_identity(fonts)

    records = {case.id: normalized(compile_case(case)) for case in golden_cases()}
    payload_digests = {
        case_id: item["raster_input_digest"] for case_id, item in records.items()
    }
    changed_cases = sorted(
        case_id
        for case_id, item in records.items()
        if (recorded := load_case(case_id)) is None
        or recorded["raster_inputs"] != item["raster_inputs"]
    )

    if previous is not None:
        moved = identity_changes(previous["identity"], identity)
        if changed_cases and not moved:
            _say(
                "Refusing to record: these cases print differently, but no "
                "compiler, renderer, font, asset, policy, profile or layout "
                "identity changed.\n  "
                + "\n  ".join(changed_cases)
                + "\nBump the identity whose behaviour changed, then record again.",
                error=True,
            )
            return 1
        stale = sorted(
            {path.stem for path in GOLDEN_DIRECTORY.glob("*.json")}
            - {"manifest"}
            - set(records)
        )
        if (
            not moved
            and not changed_cases
            and not stale
            and previous["evidence"] == evidence
        ):
            _say("Goldens are current; nothing to record.")
            return 0

    GOLDEN_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for path in GOLDEN_DIRECTORY.glob("*.*"):
        if path.name != MANIFEST_PATH.name and path.stem not in records:
            path.unlink()
    for case_id, item in records.items():
        png = rasterize(item["raster_inputs"], fonts)
        item["evidence"] = {
            "sha256": hashlib.sha256(png).hexdigest(),
            "rendered_from": item["raster_input_digest"],
        }
        case_path(case_id, ".png").write_bytes(png)
        _write_json(case_path(case_id, ".json"), item)

    history.append(
        {
            "identity": identity,
            "identity_changes": (
                identity_changes(previous["identity"], identity)
                if previous
                else ["initial"]
            ),
            "evidence": evidence,
            "goldens_digest": goldens_digest(payload_digests),
            "changed_cases": changed_cases,
            "review": {
                "reviewer": reviewer,
                "date": datetime.now(UTC).date().isoformat(),
                "reason": reason,
            },
        }
    )
    _write_json(MANIFEST_PATH, {**manifest, "history": history})
    _say(
        f"Recorded {len(records)} goldens ({len(changed_cases)} changed). "
        "Review every changed PNG in the pull request before it merges."
    )
    return 0


def verify(fonts: Path) -> int:
    """Re-rasterize every recorded payload and compare the evidence bytes."""
    failures = []
    for case in golden_cases():
        recorded = load_case(case.id)
        if recorded is None:
            failures.append(f"{case.id}: not recorded")
            continue
        png = rasterize(recorded["raster_inputs"], fonts)
        if hashlib.sha256(png).hexdigest() != recorded["evidence"]["sha256"]:
            failures.append(f"{case.id}: evidence does not reproduce")
    for failure in failures:
        _say(failure, error=True)
    _say(f"{len(golden_cases()) - len(failures)} goldens reproduce.")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    """Record or verify the golden matrix."""
    parser = argparse.ArgumentParser(prog="python -m tests.labels.golden_matrix")
    commands = parser.add_subparsers(dest="command", required=True)
    record_parser = commands.add_parser("record", help="record the matrix")
    record_parser.add_argument("--fonts", type=Path, required=True)
    record_parser.add_argument("--reviewer", required=True)
    record_parser.add_argument("--reason", required=True)
    verify_parser = commands.add_parser("verify", help="reproduce the evidence")
    verify_parser.add_argument("--fonts", type=Path, required=True)
    arguments = parser.parse_args(argv)
    if not (arguments.fonts / EVIDENCE_DEFAULT_FONT).exists():
        parser.error(f"{arguments.fonts} holds no {EVIDENCE_DEFAULT_FONT}")
    if arguments.command == "record":
        if not arguments.reviewer.strip() or not arguments.reason.strip():
            parser.error("a recording names its reviewer and its reason")
        return record(arguments.fonts, arguments.reviewer, arguments.reason)
    return verify(arguments.fonts)


if __name__ == "__main__":
    sys.exit(main())
