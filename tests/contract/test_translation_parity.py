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


def _error_keys_set_by_flows() -> set[str]:
    """Collect every literal key the flows put on ``errors["base"]``."""
    # Both spellings the handlers use: ``errors={"base": "x"}`` and
    # ``errors["base"] = "x"``.
    return _literals_matching(r'"base"\]?\s*[:=]\s*["\']([A-Za-z0-9_]+)["\']')


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


def test_every_error_and_abort_the_flows_raise_has_a_translation() -> None:
    """No form error or abort dialog renders as a raw translation key.

    Only the options flow reaches ``config_handlers/``; the config flow builds
    its one step inline, which is why both are checked against ``options``.
    """
    options = _load(STRINGS_PATH)["options"]

    untranslated_errors = sorted(_error_keys_set_by_flows() - set(options["error"]))
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
