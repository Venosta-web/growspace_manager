"""The golden raster matrix as a release gate (hub issue #230).

What this suite refuses, and why each refusal is a separate test:

- a shipped profile, Factory Template, family, context, rotation or date order
  with no golden -- coverage is derived from the catalogues, not remembered;
- a label whose raster inputs changed while every recorded identity stayed the
  same -- the silent change to what prints that goldens exist to catch;
- an identity that moved without the goldens being recorded again under it;
- a recording nobody reviewed, or one that changed output without naming a
  different identity than the recording before it; and
- evidence that is not the PNG of the payload beside it.

Nothing here imports `imagespec`, and nothing here is reachable from the card:
the card's contract is the Render Result, never the renderer's payload.
"""

from __future__ import annotations

from datetime import date
import hashlib
from typing import Any

import pytest

from custom_components.growspace_manager.labels.canonical import (
    FACTORY_TEMPLATES,
    PROFILES,
    REPRESENTATIVE_FAMILIES,
    SUPPORTED_LOCALES,
    ElementKind,
)
from tests.labels import golden_matrix as matrix

CASES = matrix.golden_cases()
MANIFEST = matrix.load_manifest()
HISTORY: list[dict[str, Any]] = MANIFEST["history"]
LATEST = HISTORY[-1] if HISTORY else None


def _ids(case: matrix.GoldenCase) -> str:
    return case.id


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


def test_every_profiled_stock_has_an_element_kind_coverage_layout() -> None:
    assert matrix.uncovered_stocks() == ()


def test_the_coverage_layouts_carry_every_element_kind() -> None:
    for label_size_id in matrix.COVERAGE_LAYOUTS:
        layout = matrix.coverage_layout(label_size_id, 0)
        assert {str(element.kind) for element in layout.elements} == {
            str(kind) for kind in ElementKind
        }


def test_the_matrix_crosses_every_shipped_dimension() -> None:
    profiled = {profile.label_size_id for profile in PROFILES.values()}
    assert {case.profile.id for case in CASES} == set(PROFILES)
    assert {
        name for case in CASES if (name := case.layout_name).startswith("factory-")
    } == {
        f"factory-{template.id.rsplit('.', 1)[-1]}-r{template.revision}"
        for template in FACTORY_TEMPLATES.values()
        if template.label_size_id in profiled
    }
    assert {case.family for case in CASES} == set(REPRESENTATIVE_FAMILIES)
    assert {case.context for case in CASES} == {
        str(context)
        for subjects in REPRESENTATIVE_FAMILIES.values()
        for context in subjects
    }
    for profile in PROFILES.values():
        assert {
            case.layout_name
            for case in CASES
            if case.profile is profile and case.layout_name.startswith("coverage-")
        } == {
            f"coverage-{profile.label_size.id.split('.')[2]}-rot{rotation}"
            for rotation in profile.supported_element_rotations
        }


def test_every_distinct_date_order_has_a_witness() -> None:
    """en-US is the one month-first locale, so it is the one witness today."""
    assert matrix.witness_locales() == ("en-US",)
    assert {case.locale for case in CASES} == {matrix.BASE_LOCALE, "en-US"}


def test_a_new_locale_with_its_own_date_order_would_join_the_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def iso_for_sweden(value: date, style: str, locale: str) -> str:
        return value.isoformat() if locale == "sv-SE" else f"{locale}:{style}"

    monkeypatch.setattr(matrix, "SUPPORTED_LOCALES", (*SUPPORTED_LOCALES, "sv-SE"))
    monkeypatch.setattr(matrix, "format_date", iso_for_sweden)
    assert "sv-SE" in matrix.witness_locales()


def test_the_recorded_set_is_exactly_the_matrix() -> None:
    recorded = {path.stem for path in matrix.GOLDEN_DIRECTORY.glob("*.json")} - {
        "manifest"
    }
    assert recorded == {case.id for case in CASES}, (
        "The golden set and the matrix disagree. Record the goldens again "
        "(see tests/labels/golden_matrix.py)."
    )


# ---------------------------------------------------------------------------
# Output never moves without an identity moving
# ---------------------------------------------------------------------------


def test_the_goldens_were_recorded_under_the_current_identity() -> None:
    assert LATEST is not None, "No goldens have been recorded."
    moved = matrix.identity_changes(LATEST["identity"], matrix.current_identity())
    assert not moved, (
        f"These identities moved since the goldens were recorded: {moved}. "
        "Record the goldens again (tests/labels/golden_matrix.py) and review "
        "every changed PNG."
    )


@pytest.mark.parametrize("case", CASES, ids=_ids)
async def test_each_label_still_compiles_to_its_golden(
    case: matrix.GoldenCase,
) -> None:
    recorded = matrix.load_case(case.id)
    assert recorded is not None
    produced = matrix.normalized(await matrix.async_compile_case(case))
    unchanged_identity = LATEST is not None and not matrix.identity_changes(
        LATEST["identity"], matrix.current_identity()
    )
    assert produced["raster_inputs"] == recorded["raster_inputs"], (
        "This label now prints differently, but no compiler, renderer, font, "
        "asset, policy, profile or layout identity changed. Bump the identity "
        "whose behaviour changed, then record the goldens again."
        if unchanged_identity
        else "This label prints differently under a new identity. Record the "
        "goldens again and review the changed PNGs."
    )
    for key in (
        "raster_input_digest",
        "outcomes",
        "diagnostics",
        "content_identity",
        "layout",
        "profile",
        "subject",
        "locale",
    ):
        assert produced[key] == recorded[key], key


def test_the_latest_recording_describes_the_recorded_files() -> None:
    assert LATEST is not None
    digests = {
        case.id: recorded["raster_input_digest"]
        for case in CASES
        if (recorded := matrix.load_case(case.id)) is not None
    }
    assert matrix.goldens_digest(digests) == LATEST["goldens_digest"], (
        "A golden file was edited without a recording. Goldens are written "
        "by tests/labels/golden_matrix.py, never by hand."
    )


# ---------------------------------------------------------------------------
# Every recording is reviewed and explained
# ---------------------------------------------------------------------------


def test_the_recorded_history_keeps_both_rules() -> None:
    assert matrix.history_problems(HISTORY) == []


def _entry(identity: dict[str, Any], goldens: str, **overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "identity": identity,
        "identity_changes": ["initial"],
        "evidence": {"renderer": "imagespec 0.4.0", "fonts": {}},
        "goldens_digest": goldens,
        "review": {"reviewer": "someone", "date": "2026-09-21", "reason": "why"},
    }
    entry.update(overrides)
    return entry


def test_changed_output_under_the_same_identity_is_refused() -> None:
    history = [
        _entry({"compiler": "v1"}, "a"),
        _entry({"compiler": "v1"}, "b", identity_changes=[]),
    ]
    assert "recording 1 changed output without moving an identity" in (
        matrix.history_problems(history)
    )


def test_changed_output_under_a_new_identity_is_accepted() -> None:
    history = [
        _entry({"compiler": "v1"}, "a"),
        _entry({"compiler": "v2"}, "b", identity_changes=["compiler"]),
    ]
    assert matrix.history_problems(history) == []


def test_a_new_evidence_renderer_alone_is_a_recording() -> None:
    history = [
        _entry({"compiler": "v1"}, "a"),
        _entry(
            {"compiler": "v1"},
            "a",
            identity_changes=[],
            evidence={"renderer": "imagespec 0.5.0", "fonts": {}},
        ),
    ]
    assert matrix.history_problems(history) == []


def test_a_recording_that_changes_nothing_is_refused() -> None:
    history = [
        _entry({"compiler": "v1"}, "a"),
        _entry({"compiler": "v1"}, "a", identity_changes=[]),
    ]
    assert matrix.history_problems(history) == [
        "recording 1 changed neither an identity nor the evidence"
    ]


def test_a_misstated_identity_change_is_refused() -> None:
    history = [
        _entry({"compiler": "v1", "fonts": "x"}, "a"),
        _entry({"compiler": "v2", "fonts": "x"}, "b", identity_changes=["fonts"]),
    ]
    assert matrix.history_problems(history) == [
        "recording 1 misstates which identities moved"
    ]


def test_an_unreviewed_recording_is_refused() -> None:
    history = [
        _entry(
            {"compiler": "v1"},
            "a",
            review={"reviewer": " ", "date": "someday", "reason": ""},
        )
    ]
    assert matrix.history_problems(history) == [
        "recording 0 names no reviewer",
        "recording 0 gives no reason",
        "recording 0 has no review date",
    ]


def test_a_first_recording_must_say_it_is_the_first() -> None:
    history = [_entry({"compiler": "v1"}, "a", identity_changes=[])]
    assert matrix.history_problems(history) == [
        "the first recording is not marked initial"
    ]


def test_no_history_is_no_golden_set() -> None:
    assert matrix.history_problems([]) == ["no goldens have been recorded"]


def test_nested_identity_changes_are_named_by_path() -> None:
    assert matrix.identity_changes(
        {"layouts": {"a": "1", "b": "2"}, "compiler": "v1"},
        {"layouts": {"a": "1", "b": "3"}, "compiler": "v1", "renderer": "v1"},
    ) == ["layouts.b", "renderer"]


def test_the_evidence_was_drawn_by_the_renderer_the_printer_pins() -> None:
    assert LATEST is not None
    assert LATEST["evidence"]["renderer"] == (
        f"{matrix.EVIDENCE_RENDERER} {matrix.EVIDENCE_RENDERER_VERSION}"
    )
    assert matrix.EVIDENCE_DEFAULT_FONT in LATEST["evidence"]["fonts"]


# ---------------------------------------------------------------------------
# The evidence is the PNG of the payload beside it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_each_golden_carries_its_rendered_evidence(case: matrix.GoldenCase) -> None:
    recorded = matrix.load_case(case.id)
    assert recorded is not None
    evidence = matrix.case_path(case.id, ".png").read_bytes()
    assert hashlib.sha256(evidence).hexdigest() == recorded["evidence"]["sha256"]
    assert recorded["evidence"]["rendered_from"] == recorded["raster_input_digest"]
    size, colours = matrix.png_facts(evidence)
    inputs = recorded["raster_inputs"]
    assert size == (inputs["width"], inputs["height"])
    assert size[0] <= case.profile.printhead_pixels
    assert colours <= 2


def test_the_goldens_never_leave_the_backend() -> None:
    """The payload is the renderer's; no contract fixture may carry it."""
    contract = matrix.GOLDEN_DIRECTORY.parent.parent / "contract"
    for path in contract.glob("label_*.json"):
        assert '"imagespec' not in path.read_text(), path.name


# ---------------------------------------------------------------------------
# The recorder refuses what the suite refuses
# ---------------------------------------------------------------------------


def _png() -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("1", (384, 240), 1).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def scratch(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    """A recorder writing to a temporary directory with a stand-in renderer."""
    directory = tmp_path / "golden"
    monkeypatch.setattr(matrix, "GOLDEN_DIRECTORY", directory)
    monkeypatch.setattr(matrix, "MANIFEST_PATH", directory / "manifest.json")
    monkeypatch.setattr(
        matrix,
        "evidence_identity",
        lambda fonts: {"renderer": "imagespec 0.4.0", "fonts": {"ppb.ttf": "x"}},
    )
    monkeypatch.setattr(matrix, "rasterize", lambda inputs, fonts: _png())
    return directory


def _record(tmp_path: Any, reason: str = "because") -> int:
    return matrix.record(tmp_path, "reviewer", reason)


def test_a_first_recording_writes_every_case_and_its_evidence(
    scratch: Any, tmp_path: Any
) -> None:
    assert _record(tmp_path) == 0
    history = matrix.load_manifest()["history"]
    assert len(history) == 1
    assert history[0]["identity_changes"] == ["initial"]
    assert len(history[0]["changed_cases"]) == len(CASES)
    for case in CASES:
        assert matrix.case_path(case.id, ".png").exists()
        recorded = matrix.load_case(case.id)
        assert recorded is not None
        assert recorded["evidence"]["rendered_from"] == recorded["raster_input_digest"]
    assert matrix.history_problems(history) == []


def test_recording_again_with_nothing_changed_writes_nothing(
    scratch: Any, tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    _record(tmp_path)
    assert _record(tmp_path) == 0
    assert len(matrix.load_manifest()["history"]) == 1
    assert "nothing to record" in capsys.readouterr().out


def test_the_recorder_refuses_output_that_moved_without_an_identity(
    scratch: Any,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _record(tmp_path)
    before = matrix.MANIFEST_PATH.read_text()
    compile_case = matrix.compile_case

    def drifted(case: matrix.GoldenCase) -> dict[str, Any]:
        item = compile_case(case)
        item["raster_inputs"] = {**item["raster_inputs"], "rotate": 90}
        return item

    monkeypatch.setattr(matrix, "compile_case", drifted)
    assert _record(tmp_path) == 1
    assert matrix.MANIFEST_PATH.read_text() == before
    assert "no compiler, renderer, font" in capsys.readouterr().err


def test_the_recorder_accepts_output_that_moved_with_its_identity(
    scratch: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _record(tmp_path)
    compile_case = matrix.compile_case
    identity = matrix.current_identity()

    def drifted(case: matrix.GoldenCase) -> dict[str, Any]:
        item = compile_case(case)
        item["raster_inputs"] = {**item["raster_inputs"], "rotate": 90}
        return item

    monkeypatch.setattr(matrix, "compile_case", drifted)
    monkeypatch.setattr(
        matrix, "current_identity", lambda: {**identity, "compiler": "next"}
    )
    assert _record(tmp_path, "compiler v2 rotates the canvas") == 0
    history = matrix.load_manifest()["history"]
    assert [entry["identity_changes"] for entry in history] == [
        ["initial"],
        ["compiler"],
    ]
    assert matrix.history_problems(history) == []


def test_a_new_evidence_renderer_is_recorded_without_moving_output(
    scratch: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _record(tmp_path)
    monkeypatch.setattr(
        matrix,
        "evidence_identity",
        lambda fonts: {"renderer": "imagespec 0.4.0", "fonts": {"ppb.ttf": "y"}},
    )
    assert _record(tmp_path, "the printer integration ships a new bold face") == 0
    history = matrix.load_manifest()["history"]
    assert len(history) == 2
    assert history[1]["changed_cases"] == []
    assert matrix.history_problems(history) == []


def test_a_case_that_left_the_matrix_is_removed(
    scratch: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _record(tmp_path)
    for suffix in (".json", ".png"):
        (scratch / f"retired{suffix}").write_text("{}")
    identity = matrix.current_identity()
    monkeypatch.setattr(matrix, "current_identity", lambda: {**identity, "layouts": {}})
    assert _record(tmp_path, "a layout was retired") == 0
    assert not (scratch / "retired.json").exists()
    assert not (scratch / "retired.png").exists()


def test_verify_reports_evidence_that_does_not_reproduce(
    scratch: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _record(tmp_path)
    assert matrix.verify(tmp_path) == 0
    monkeypatch.setattr(matrix, "rasterize", lambda inputs, fonts: b"other")
    assert matrix.verify(tmp_path) == 1


def test_the_command_line_insists_on_fonts_a_reviewer_and_a_reason(
    tmp_path: Any,
) -> None:
    with pytest.raises(SystemExit):
        matrix.main(
            ["record", "--fonts", str(tmp_path), "--reviewer", "a", "--reason", "b"]
        )
    (tmp_path / matrix.EVIDENCE_DEFAULT_FONT).write_bytes(b"")
    with pytest.raises(SystemExit):
        matrix.main(
            ["record", "--fonts", str(tmp_path), "--reviewer", " ", "--reason", "b"]
        )
