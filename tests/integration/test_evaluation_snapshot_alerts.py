"""Evaluation Snapshot to persisted Triage Inbox integration tests."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.alert_monitor import AlertMonitor
from custom_components.growspace_manager.notification_manager import NotificationManager
from custom_components.growspace_manager.notification_rewriter import (
    AINotificationRewriter,
)
from custom_components.growspace_manager.notifications.evaluation_snapshot import (
    EvaluationSnapshot,
)
from custom_components.growspace_manager.services.notifications_facade import (
    NotificationsFacade,
)
from custom_components.growspace_manager.websocket.ai_assistant import (
    websocket_get_ai_alerts,
)


def _snapshot(
    *,
    sensor_type: str = "stress",
    is_on: bool = True,
    probability: float = 0.8,
) -> EvaluationSnapshot:
    """Build an evaluation snapshot with independently specified known values."""
    return EvaluationSnapshot(
        growspace_id="tent1",
        sensor_type=sensor_type,
        sensor_name=f"Tent 1 {sensor_type}",
        probability=probability,
        threshold=0.7,
        is_on=is_on,
        reasons=[(0.9, "High VPD: 1.8 kPa"), (0.7, "Fan off")],
        sensor_states={"vpd": 1.8, "is_lights_on": True},
        lights_on=True,
        notification_title="Stress detected",
        notification_message="High VPD: 1.8 kPa; Fan off",
    )


class _MemoryStore:
    """In-memory stand-in for the Home Assistant Store boundary."""

    def __init__(self) -> None:
        self.data: dict[str, Any] | None = None

    async def async_load(self) -> dict[str, Any] | None:
        """Load a detached copy of persisted data."""
        return deepcopy(self.data)

    async def async_save(self, data: dict[str, Any]) -> None:
        """Persist a detached copy of alert data."""
        self.data = deepcopy(data)


class _AlertPipeline:
    """Exercise the real snapshot facade, monitor, persistence, and Inbox seam."""

    def __init__(
        self,
        store: Any,
        *,
        options: dict[str, Any] | None = None,
        ai_assistant_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._coroutines: list[Coroutine[Any, Any, Any]] = []
        self.hass = SimpleNamespace(async_create_task=self._capture_task)
        self.coordinator = SimpleNamespace(options=options or {})
        growspaces = SimpleNamespace(
            get_growspace_plants=lambda _growspace_id: [object()]
        )
        self.manager = NotificationManager(
            self.hass, self.coordinator, AINotificationRewriter(self.hass)
        )
        self.coordinator._notification_manager = self.manager
        self.coordinator.services = SimpleNamespace(growspaces=growspaces)
        self.coordinator.alert_monitor = AlertMonitor(
            self.hass,
            self.coordinator,
            store,
            ai_assistant_factory=ai_assistant_factory,
        )
        self.coordinator.services.notifications = NotificationsFacade(self.coordinator)

    def _capture_task(
        self, coro: Coroutine[Any, Any, Any], *_args: Any, **_kwargs: Any
    ) -> None:
        self._coroutines.append(coro)

    async def async_start(self) -> None:
        """Load persisted Inbox state."""
        await self.coordinator.alert_monitor.async_start()

    async def report(self, snapshot: EvaluationSnapshot) -> None:
        """Submit a snapshot and finish its scheduled persistence work."""
        self.coordinator.services.notifications.report_evaluation(snapshot)
        coroutines, self._coroutines = self._coroutines, []
        for coro in coroutines:
            await coro

    def latest_evaluation(self, sensor_type: str) -> EvaluationSnapshot | None:
        """Read the capture-facing snapshot through the public facade."""
        return self.coordinator.services.notifications.latest_evaluation(
            "tent1", sensor_type
        )

    async def inbox(self, message_id: int) -> list[dict[str, Any]]:
        """Read alerts through the public Inbox WebSocket handler."""
        return await websocket_get_ai_alerts(
            self.hass,
            self.coordinator,
            {"id": message_id, "type": "growspace_manager/get_ai_alerts"},
        )

    def close(self) -> None:
        """Break the lightweight test coordinator's reference cycle."""
        self.manager.shutdown()
        self.coordinator.services.notifications = None
        self.coordinator.alert_monitor = None
        self.manager.coordinator = None


@pytest.mark.parametrize(
    ("sensor_type", "severity"),
    [
        pytest.param("stress", "danger", id="stress"),
        pytest.param("mold", "warning", id="mold"),
    ],
)
async def test_active_snapshot_appears_once_in_triage_inbox(
    sensor_type: str, severity: str
) -> None:
    """An active stress or mold evaluation is persisted and exposed by the Inbox."""
    store = MagicMock()
    store.async_load = AsyncMock(return_value=None)
    store.async_save = AsyncMock()
    pipeline = _AlertPipeline(store)
    await pipeline.async_start()

    await pipeline.report(_snapshot(sensor_type=sensor_type))

    alerts = await pipeline.inbox(1)
    assert len(alerts) == 1
    assert alerts[0] | {"id": "ignored", "timestamp": 0} == {
        "id": "ignored",
        "growspace_id": "tent1",
        "type": sensor_type,
        "severity": severity,
        "bayesian_reasons": ["High VPD: 1.8 kPa", "Fan off"],
        "bayesian_probability": 0.8,
        "ai_reasoning": None,
        "timestamp": 0,
        "resolved": False,
        "resolution_note": None,
    }

    pipeline.close()


async def test_latest_evaluation_retains_inactive_snapshot_for_vision() -> None:
    """Inactive measured evidence remains available outside alert batching."""
    store = MagicMock()
    store.async_load = AsyncMock(return_value=None)
    store.async_save = AsyncMock()
    pipeline = _AlertPipeline(store)
    await pipeline.async_start()
    snapshot = _snapshot(is_on=False, probability=0.1)

    await pipeline.report(snapshot)

    assert pipeline.latest_evaluation("stress") is snapshot
    pipeline.close()


async def test_stress_snapshot_deduplicates_and_resolved_snapshot_rearms() -> None:
    """Active evaluations deduplicate until a resolved evaluation re-arms intake."""
    store = MagicMock()
    store.async_load = AsyncMock(return_value=None)
    store.async_save = AsyncMock()
    pipeline = _AlertPipeline(store)
    await pipeline.async_start()

    await pipeline.report(_snapshot())
    await pipeline.report(_snapshot(probability=0.85))
    assert len(await pipeline.inbox(2)) == 1

    await pipeline.report(_snapshot(is_on=False))
    await pipeline.report(_snapshot(probability=0.75))
    assert len(await pipeline.inbox(3)) == 2

    pipeline.close()


async def test_active_first_evaluation_after_restart_creates_one_new_alert() -> None:
    """Startup-active behavior creates one alert and deduplicates later snapshots."""
    store = _MemoryStore()
    first_run = _AlertPipeline(store)
    await first_run.async_start()
    await first_run.report(_snapshot())
    first_run.close()

    restarted = _AlertPipeline(store)
    await restarted.async_start()
    await restarted.report(_snapshot(probability=0.75))
    await restarted.report(_snapshot(probability=0.85))

    alerts = await restarted.inbox(4)
    assert [alert["bayesian_probability"] for alert in alerts] == [0.8, 0.75]

    restarted.close()


async def test_ai_failure_keeps_snapshot_alert_in_triage_inbox() -> None:
    """AI failure cannot prevent snapshot alert persistence or Inbox visibility."""
    assistant = SimpleNamespace(
        generate_alert_message=AsyncMock(side_effect=RuntimeError("AI unavailable"))
    )
    pipeline = _AlertPipeline(
        _MemoryStore(),
        options={"ai_enabled": True, "ai_auto_alerts": True},
        ai_assistant_factory=lambda: assistant,
    )
    await pipeline.async_start()

    await pipeline.report(_snapshot(sensor_type="mold"))

    alerts = await pipeline.inbox(5)
    assert len(alerts) == 1
    assert alerts[0]["ai_reasoning"] is None
    assert alerts[0]["bayesian_reasons"] == ["High VPD: 1.8 kPa", "Fan off"]

    pipeline.close()
