"""Global fixtures for integration tests."""

from freezegun.api import FrozenDateTimeFactory
import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def freeze_time(freezer: FrozenDateTimeFactory) -> None:
    """Freeze time to a fixed value to avoid off-by-one date errors.

    We choose a time in the middle of the day to avoid UTC midnight issues.
    Today is 2026-01-12 according to system context.
    """
    freezer.move_to("2026-01-12 12:00:00")
