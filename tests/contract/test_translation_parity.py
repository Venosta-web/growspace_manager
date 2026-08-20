"""Keep ``strings.json`` and ``translations/en.json`` from drifting apart.

Home Assistant loads a custom component's translations from
``translations/<lang>.json``; ``strings.json`` is only the source a translation
generator would read. This repository has no generator, so both files are
hand-maintained and a key added to one but not the other renders in the UI as a
raw translation key. These tests are what makes that drift fail loudly.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

COMPONENT_DIR = Path(__file__).parents[2] / "custom_components" / "growspace_manager"
STRINGS_PATH = COMPONENT_DIR / "strings.json"
EN_PATH = COMPONENT_DIR / "translations" / "en.json"

# Steps whose form fields are named after the user's own entities, so no static
# translation can cover them. The step's title and description are translated;
# the individual fields are intentionally left raw.
STEPS_WITH_GENERATED_FIELDS = frozenset(
    {"configure_advanced_bayesian", "configure_sensor_placement"}
)

# Step entries deliberately kept although no flow shows them — a step being
# reintroduced shortly, say. JSON carries no comments, so the reason lives
# here. Empty is the healthy state: an entry nothing renders is dead weight
# that reads as a live screen to whoever finds it next.
STEPS_TRANSLATED_BUT_NOT_SHOWN: frozenset[str] = frozenset()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _leaf_keys(value: Any, prefix: str = "") -> set[str]:
    """Flatten a translation tree into dotted paths to its leaf strings."""
    if not isinstance(value, dict):
        return {prefix}
    return {
        key
        for name, child in value.items()
        for key in _leaf_keys(child, f"{prefix}.{name}" if prefix else name)
    }


def _literals_matching(pattern: str) -> set[str]:
    """Collect every string literal the component matches against ``pattern``."""
    return {
        match
        for source in COMPONENT_DIR.rglob("*.py")
        for match in re.findall(pattern, source.read_text(encoding="utf-8"))
    }


def _step_ids_shown_by_flows() -> set[str]:
    """Collect every literal ``step_id`` the config and options flows show."""
    return _literals_matching(r'step_id\s*=\s*["\']([A-Za-z0-9_]+)["\']')


_STEP_ID_ASSIGNMENT = re.compile(r"step_id\s*=\s*([^,)\n]+)")


def _step_id_values_used_by_flows() -> set[str]:
    """Collect the raw source text of every value passed as ``step_id``."""
    return {
        match.strip()
        for source in COMPONENT_DIR.rglob("*.py")
        for match in _STEP_ID_ASSIGNMENT.findall(source.read_text(encoding="utf-8"))
    }


# Both spellings the flows use: ``errors={"base": "x"}`` and
# ``errors["base"] = "x"``. The value is captured loosely so a non-literal can
# be spotted rather than silently skipped.
_ERROR_ASSIGNMENT = re.compile(r'"base"\]?\s*[:=]\s*([^,}\n]+)')
_PLAIN_STRING = re.compile(r'^["\'][A-Za-z0-9_]+["\']$')


def _error_values_set_by_flows() -> set[str]:
    """Collect the raw source text of every value assigned to ``errors["base"]``."""
    return {
        match.strip()
        for source in COMPONENT_DIR.rglob("*.py")
        for match in _ERROR_ASSIGNMENT.findall(source.read_text(encoding="utf-8"))
    }


def _error_keys_set_by_flows() -> set[str]:
    """Collect every literal key the flows put on ``errors["base"]``."""
    return {
        value.strip("\"'")
        for value in _error_values_set_by_flows()
        if _PLAIN_STRING.match(value)
    }


def _abort_reasons_raised_by_flows() -> set[str]:
    """Collect every literal reason the flows abort with."""
    return _literals_matching(r'reason\s*=\s*["\']([A-Za-z0-9_]+)["\']')


def test_strings_and_en_translations_have_the_same_keys() -> None:
    """Every key in one file exists in the other, across all sections."""
    strings_keys = _leaf_keys(_load(STRINGS_PATH))
    en_keys = _leaf_keys(_load(EN_PATH))

    missing_from_en = sorted(strings_keys - en_keys)
    missing_from_strings = sorted(en_keys - strings_keys)

    assert not missing_from_en, (
        f"keys in strings.json missing from translations/en.json: {missing_from_en}"
    )
    assert not missing_from_strings, (
        f"keys in translations/en.json missing from strings.json: "
        f"{missing_from_strings}"
    )


def test_every_shown_step_has_a_translation() -> None:
    """No flow step renders as a raw translation key."""
    strings = _load(STRINGS_PATH)
    translated = set(strings["config"]["step"]) | set(strings["options"]["step"])
    untranslated = sorted(_step_ids_shown_by_flows() - translated)

    assert not untranslated, (
        f"steps shown by a flow with no strings.json entry: {untranslated}"
    )


def test_step_ids_are_literals() -> None:
    """A ``step_id`` built at runtime is invisible to the two step checks.

    Both compare translation keys against the literals found in the source. A
    computed ``step_id=f"edit_{kind}"`` would make the shown-but-untranslated
    check miss a raw key, and make the translated-but-unshown check condemn an
    entry that is in fact live. Keeping every step id a literal is what
    licenses them.
    """
    non_literals = sorted(
        value
        for value in _step_id_values_used_by_flows()
        if not _PLAIN_STRING.match(value)
    )

    assert not non_literals, (
        f"step_id must be a string literal, not an expression: {non_literals}"
    )


def test_every_translated_step_is_shown_by_a_flow() -> None:
    """No step entry describes a screen the flows can no longer reach.

    The reverse of ``test_every_shown_step_has_a_translation``. A stale entry
    breaks nothing at runtime, which is exactly why it survives: it reads as a
    live screen and sends the next reader looking for a step that isn't there.
    """
    strings = _load(STRINGS_PATH)
    shown = _step_ids_shown_by_flows() | STEPS_TRANSLATED_BUT_NOT_SHOWN
    for section in ("config", "options"):
        unshown = sorted(set(strings[section]["step"]) - shown)
        assert not unshown, (
            f"{section}.step entries no flow shows: {unshown} — delete them, or "
            "add them to STEPS_TRANSLATED_BUT_NOT_SHOWN with the reason"
        )


def test_error_values_are_translation_keys_not_interpolated_strings() -> None:
    """A key built with an f-string can never match a strings.json entry.

    ``errors={"base": f"Error: {err}"}`` looks like it works and renders the
    raw text; the key check below cannot see it, because there is no literal
    to compare.
    """
    non_literals = sorted(
        value
        for value in _error_values_set_by_flows()
        if not _PLAIN_STRING.match(value)
    )

    assert not non_literals, (
        "errors['base'] must be given a literal translation key, not an"
        f" expression: {non_literals}"
    )


def test_every_error_and_abort_the_flows_raise_has_a_translation() -> None:
    """No form error or abort dialog renders as a raw translation key.

    Errors are checked against both sections' keys because the two flows share
    ``config_flow.py``; aborts only against ``options``, since every
    ``config_handlers/`` abort is reached from ``OptionsFlowHandler``.
    """
    strings = _load(STRINGS_PATH)
    options = strings["options"]
    error_keys = set(options["error"]) | set(strings["config"].get("error", {}))

    untranslated_errors = sorted(_error_keys_set_by_flows() - error_keys)
    untranslated_aborts = sorted(
        _abort_reasons_raised_by_flows() - set(options["abort"])
    )

    assert not untranslated_errors, (
        f"errors raised by a flow with no strings.json entry: {untranslated_errors}"
    )
    assert not untranslated_aborts, (
        f"aborts raised by a flow with no strings.json entry: {untranslated_aborts}"
    )


def test_translated_steps_carry_a_title() -> None:
    """A step entry without a title is drift that the key check cannot see."""
    strings = _load(STRINGS_PATH)
    for section in ("config", "options"):
        for step_id, step in strings[section]["step"].items():
            assert "title" in step, f"{section}.step.{step_id} has no title"


def test_step_fields_are_translated_unless_generated() -> None:
    """Steps whose fields come from a static schema label all of them."""
    strings = _load(STRINGS_PATH)
    for step_id in STEPS_WITH_GENERATED_FIELDS:
        assert step_id in strings["options"]["step"], (
            f"{step_id} is listed as having generated fields but has no entry"
        )
        assert "data" not in strings["options"]["step"][step_id], (
            f"{step_id} has generated field names; drop its 'data' block or "
            "remove it from STEPS_WITH_GENERATED_FIELDS"
        )
