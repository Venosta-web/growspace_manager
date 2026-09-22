"""The Classic `print_label` request raises a Repairs issue, once per run."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.labels.classic_deprecation import (
    ISSUE_ID,
    PRINT_LABEL_MIGRATION_URL,
    PRINT_LABEL_REMOVAL_VERSION,
    TRANSLATION_KEY,
)
from custom_components.growspace_manager.services.strain_library import (
    handle_print_label,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import issue_registry as ir

COMPONENT = Path(__file__).parents[2] / "custom_components" / "growspace_manager"
COMPATIBILITY_PRINT = (
    "custom_components.growspace_manager.services.strain_library."
    "async_compatibility_print"
)


async def _print(hass: HomeAssistant, times: int = 1) -> AsyncMock:
    """Make `times` Classic calls and return the adapter they reached."""
    call = ServiceCall(hass, DOMAIN, "print_label", {"strain": "Strain A"})
    with patch(COMPATIBILITY_PRINT, new=AsyncMock(return_value=None)) as adapter:
        for _ in range(times):
            await handle_print_label(hass, MagicMock(), MagicMock(), call)
    return adapter


async def _restart(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    """Persist the issue registry and read it back, as the next start does."""
    registry = ir.async_get(hass)
    hass_storage[ir.STORAGE_KEY] = {
        "version": ir.STORAGE_VERSION_MAJOR,
        "minor_version": ir.STORAGE_VERSION_MINOR,
        "key": ir.STORAGE_KEY,
        "data": registry._data_to_save(),
    }
    await registry.async_load()


def _issue(hass: HomeAssistant) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_ID)


async def test_first_classic_call_raises_one_issue(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """The first call raises the issue; the rest neither duplicate nor re-warn."""
    adapter = await _print(hass, times=3)

    issues = [
        issue
        for (domain, _), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN
    ]
    assert len(issues) == 1
    issue = issues[0]
    assert issue.issue_id == ISSUE_ID
    assert issue.active
    assert not issue.is_persistent
    assert not issue.is_fixable
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_key == TRANSLATION_KEY
    assert issue.learn_more_url == PRINT_LABEL_MIGRATION_URL
    assert issue.translation_placeholders == {
        "removal_version": PRINT_LABEL_REMOVAL_VERSION,
        "migration_url": PRINT_LABEL_MIGRATION_URL,
    }
    assert PRINT_LABEL_REMOVAL_VERSION == "2.0.0"

    warnings = [r for r in caplog.records if "is deprecated" in r.getMessage()]
    assert len(warnings) == 1
    assert PRINT_LABEL_REMOVAL_VERSION in warnings[0].getMessage()
    assert "docs/deprecations/print-label.md" in warnings[0].getMessage()

    # Printing is untouched while the issue is open.
    assert adapter.await_count == 3


async def test_issue_clears_after_a_run_without_a_classic_call(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A run in which nothing called the Classic service carries no issue."""
    await _print(hass)
    assert _issue(hass).active

    await _restart(hass, hass_storage)

    issue = _issue(hass)
    assert issue is not None
    assert not issue.active


async def test_a_later_run_with_a_classic_call_raises_it_again(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Once per run means once in every run that still makes the call."""
    await _print(hass)
    await _restart(hass, hass_storage)
    caplog.clear()

    await _print(hass, times=2)

    assert _issue(hass).active
    warnings = [r for r in caplog.records if "is deprecated" in r.getMessage()]
    assert len(warnings) == 1


async def test_an_ignored_issue_stays_ignored_for_the_run(
    hass: HomeAssistant,
) -> None:
    """Dismissing it is Home Assistant's own gesture, and later calls respect it."""
    await _print(hass)
    ir.async_ignore_issue(hass, DOMAIN, ISSUE_ID, True)

    await _print(hass)

    assert _issue(hass).dismissed_version is not None


@pytest.mark.parametrize("path", ["strings.json", "translations/en.json"])
def test_issue_text_is_translated(path: str) -> None:
    """The message comes from the integration's strings and uses its placeholders."""
    strings = json.loads((COMPONENT / path).read_text(encoding="utf-8"))
    entry = strings["issues"][TRANSLATION_KEY]

    assert set(entry) == {"title", "description"}
    text = entry["title"] + entry["description"]
    assert set(re.findall(r"\{(\w+)\}", text)) == {
        "removal_version",
        "migration_url",
    }
    assert "{removal_version}" in entry["title"]
    assert "growspace_manager.print_label_template" in entry["description"]
    assert "card" in entry["description"]
