"""Tests for new GrowspaceFacade methods (irrigation/dehumidifier coordinators, biological metrics)."""

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.services.growspace_facade import GrowspaceFacade


def _make_coordinator() -> MagicMock:
    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.subsystem_manager = MagicMock()
    coordinator.subsystem_manager.irrigation_coordinators = {}
    coordinator.subsystem_manager.dehumidifier_coordinators = {}
    coordinator.environment_analyzer = MagicMock()
    return coordinator


# ---------------------------------------------------------------------------
# get_irrigation_coordinator
# ---------------------------------------------------------------------------


def test_get_irrigation_coordinator_returns_coord_when_present() -> None:
    """Returns the irrigation coordinator for a known growspace."""
    irr_coord = MagicMock()
    coordinator = _make_coordinator()
    coordinator.subsystem_manager.irrigation_coordinators = {"tent1": irr_coord}
    facade = GrowspaceFacade(coordinator)

    result = facade.get_irrigation_coordinator("tent1")

    assert result is irr_coord


def test_get_irrigation_coordinator_returns_none_for_unknown_growspace() -> None:
    """Returns None when the growspace has no irrigation coordinator."""
    coordinator = _make_coordinator()
    facade = GrowspaceFacade(coordinator)

    assert facade.get_irrigation_coordinator("unknown") is None


# ---------------------------------------------------------------------------
# get_dehumidifier_coordinator
# ---------------------------------------------------------------------------


def test_get_dehumidifier_coordinator_returns_coord_when_present() -> None:
    """Returns the dehumidifier coordinator for a known growspace."""
    dehum_coord = MagicMock()
    coordinator = _make_coordinator()
    coordinator.subsystem_manager.dehumidifier_coordinators = {"tent1": dehum_coord}
    facade = GrowspaceFacade(coordinator)

    result = facade.get_dehumidifier_coordinator("tent1")

    assert result is dehum_coord


def test_get_dehumidifier_coordinator_returns_none_for_unknown_growspace() -> None:
    """Returns None when the growspace has no dehumidifier coordinator."""
    coordinator = _make_coordinator()
    facade = GrowspaceFacade(coordinator)

    assert facade.get_dehumidifier_coordinator("unknown") is None


# ---------------------------------------------------------------------------
# calculate_biological_metrics
# ---------------------------------------------------------------------------


def test_calculate_biological_metrics_delegates_to_environment_analyzer() -> None:
    """calculate_biological_metrics delegates to environment_analyzer with all args."""
    metrics = {"vpd": 1.2, "dli": 30.0}
    coordinator = _make_coordinator()
    coordinator.environment_analyzer.calculate_biological_metrics.return_value = metrics
    facade = GrowspaceFacade(coordinator)

    result = facade.calculate_biological_metrics("tent1", plants=[], env_config=MagicMock())

    assert result is metrics
    coordinator.environment_analyzer.calculate_biological_metrics.assert_called_once()


def test_calculate_biological_metrics_passes_kwargs_through() -> None:
    """All keyword arguments are forwarded to environment_analyzer unchanged."""
    coordinator = _make_coordinator()
    coordinator.environment_analyzer.calculate_biological_metrics.return_value = {}
    facade = GrowspaceFacade(coordinator)
    env_cfg = MagicMock()

    facade.calculate_biological_metrics("tent1", plants=["p1"], env_config=env_cfg, extra_arg=42)

    _, kwargs = coordinator.environment_analyzer.calculate_biological_metrics.call_args
    assert kwargs["plants"] == ["p1"]
    assert kwargs["env_config"] is env_cfg
    assert kwargs["extra_arg"] == 42
