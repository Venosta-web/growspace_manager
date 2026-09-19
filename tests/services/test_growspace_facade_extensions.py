"""Tests for new GrowspaceFacade methods (irrigation/dehumidifier coordinators, biological metrics)."""

from unittest.mock import MagicMock

from custom_components.growspace_manager.data_access.growspace_repository import (
    GrowspaceRepository,
)
from custom_components.growspace_manager.domain.stage import StageDays
from custom_components.growspace_manager.models import Growspace
from custom_components.growspace_manager.services.growspace_facade import (
    GrowspaceFacade,
)


def _make_coordinator() -> MagicMock:
    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator._subsystem_manager = MagicMock()
    coordinator._subsystem_manager.irrigation_coordinators = {}
    coordinator._subsystem_manager.get_dehumidifier_controller.return_value = None
    coordinator.environment_analyzer = MagicMock()
    return coordinator


# ---------------------------------------------------------------------------
# get_irrigation_coordinator
# ---------------------------------------------------------------------------


def test_get_irrigation_coordinator_returns_coord_when_present() -> None:
    """Returns the irrigation coordinator for a known growspace."""
    irr_coord = MagicMock()
    coordinator = _make_coordinator()
    coordinator._subsystem_manager.irrigation_coordinators = {"tent1": irr_coord}
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
    coordinator._subsystem_manager.get_dehumidifier_controller.return_value = (
        dehum_coord
    )
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
    """calculate_biological_metrics delegates to environment_analyzer with growspace and StageDays."""
    metrics = {"vpd": 1.2, "dli": 30.0}
    coordinator = _make_coordinator()
    coordinator.environment_analyzer.calculate_biological_metrics.return_value = metrics
    facade = GrowspaceFacade(coordinator)
    growspace = MagicMock()
    days = StageDays(veg=10)

    result = facade.calculate_biological_metrics("tent1", growspace, days)

    assert result is metrics
    coordinator.environment_analyzer.calculate_biological_metrics.assert_called_once_with(
        growspace, days
    )


def test_calculate_biological_metrics_passes_stage_days_through() -> None:
    """StageDays is forwarded to environment_analyzer unchanged."""
    coordinator = _make_coordinator()
    coordinator.environment_analyzer.calculate_biological_metrics.return_value = {}
    facade = GrowspaceFacade(coordinator)
    growspace = MagicMock()
    days = StageDays(flower=30, veg=-1)

    facade.calculate_biological_metrics("tent1", growspace, days)

    coordinator.environment_analyzer.calculate_biological_metrics.assert_called_once_with(
        growspace, days
    )


# ---------------------------------------------------------------------------
# get_substrate_tracker
# ---------------------------------------------------------------------------


def _coordinator_holding(*growspaces: Growspace) -> MagicMock:
    """A coordinator over a real repository, which is what the facade reads."""
    coordinator = _make_coordinator()
    repository = GrowspaceRepository()
    for growspace in growspaces:
        repository.add_growspace(growspace)
    coordinator._data_repository = repository
    return coordinator


def test_get_substrate_tracker_returns_none_for_unknown_growspace() -> None:
    """There is no substrate history to track for a growspace that is gone."""
    facade = GrowspaceFacade(_coordinator_holding())

    assert facade.get_substrate_tracker("unknown") is None


def test_get_substrate_tracker_caches_one_instance_per_growspace() -> None:
    """One tracker per growspace, because they share mutable state.

    The tracker reads and writes ``growspace.substrate_history`` in place, so
    a second instance over the same growspace would be a second view of one
    history — and the steering loop and the sensor would disagree about what
    the substrate has done.
    """
    growspace = Growspace(id="tent1", name="Tent 1")
    facade = GrowspaceFacade(_coordinator_holding(growspace))

    first = facade.get_substrate_tracker("tent1")
    second = facade.get_substrate_tracker("tent1")

    assert first is not None
    assert first is second
    assert first.growspace is growspace


def test_get_substrate_tracker_rebinds_when_the_growspace_is_replaced() -> None:
    """A reload builds new `Growspace` objects, and the tracker must follow.

    The cached instance holds the old object. Keeping it would leave the
    tracker writing history onto a growspace nothing else reads any more,
    which looks exactly like a tracker that silently stopped working.
    """
    coordinator = _coordinator_holding(Growspace(id="tent1", name="Tent 1"))
    facade = GrowspaceFacade(coordinator)
    before = facade.get_substrate_tracker("tent1")

    reloaded = Growspace(id="tent1", name="Tent 1")
    coordinator._data_repository.add_growspace(reloaded)
    after = facade.get_substrate_tracker("tent1")

    assert after is not before
    assert after is not None
    assert after.growspace is reloaded
