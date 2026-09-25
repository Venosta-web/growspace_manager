"""Edge paths of the continuity notifier the checkup pipeline cannot reach."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.capture_continuity_monitor import (
    ActivationOrigin,
    ContinuityActivation,
)
from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.continuity_notifier import (
    ContinuityNotifier,
    continuity_notification_id,
)
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

ACTIVATED_AT = datetime(2026, 9, 1, 12, tzinfo=UTC)


class _MemoryStore:
    def __init__(self, data: dict | None = None) -> None:
        self.data = data
        self.saves = 0

    async def async_load(self) -> dict | None:
        return self.data

    async def async_save(self, data: dict) -> None:
        self.data = data
        self.saves += 1


def _activation(
    growspace_id: str = "tent1",
    camera_id: str = "camera.canopy",
    activation_id: str = "capture-1",
    origin: ActivationOrigin = ActivationOrigin.NEW,
) -> ContinuityActivation:
    return ContinuityActivation(
        activation_id=activation_id,
        growspace_id=growspace_id,
        camera_id=camera_id,
        activated_at=ACTIVATED_AT,
        origin=origin,
    )


def _row(
    activation_id: str, status: str, growspace_id: str = "tent1", **channels
) -> dict:
    return {
        "activation_id": activation_id,
        "growspace_id": growspace_id,
        "camera_id": "camera.canopy",
        "activated_at": ACTIVATED_AT.isoformat(),
        "channels": {
            "home_assistant": {"status": status, "attempts": 0},
            **channels,
        },
    }


@pytest.fixture
async def notifier(hass: HomeAssistant):
    """A notifier over a real Home Assistant with no growspace configured."""
    assert await async_setup_component(hass, "persistent_notification", {})
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    enabled: dict[str, bool] = {}
    coordinator = SimpleNamespace(
        config_entry=entry,
        growspaces={},
        services=SimpleNamespace(
            notifications=SimpleNamespace(
                is_notifications_enabled=lambda growspace_id: enabled.get(
                    growspace_id, True
                )
            )
        ),
    )
    store = _MemoryStore()
    subject = ContinuityNotifier(hass, coordinator, store)
    subject.store = store  # type: ignore[attr-defined]
    yield subject
    subject.async_stop()


async def test_unreadable_rows_cost_only_themselves(notifier) -> None:
    """A garbled row is discarded; a channel this version lacks is left out."""
    notifier.store.data = {
        "deliveries": [
            _row("capture-1", "delivered", device={"status": "pending"}),
            _row("capture-2", "no such status"),
            {"activation_id": "capture-3"},
            "not a row",
        ]
    }

    await notifier.async_start([_activation(origin=ActivationOrigin.HISTORICAL)])

    assert notifier.store.data == {"deliveries": [_row("capture-1", "delivered")]}


async def test_start_keeps_unfinished_and_current_records_only(notifier) -> None:
    """Finished records of conditions that are gone have nothing left to guard."""
    notifier.store.data = {
        "deliveries": [
            _row("capture-1", "delivered"),
            _row("capture-2", "failed"),
            _row("capture-3", "suppressed", growspace_id="tent2"),
        ]
    }
    await notifier.async_start(
        [
            _activation(activation_id="capture-2"),
            _activation(growspace_id="tent3", origin=ActivationOrigin.HISTORICAL),
        ]
    )

    assert [row["activation_id"] for row in notifier.store.data["deliveries"]] == [
        "capture-2"
    ]


async def test_the_same_activation_is_announced_once(hass, notifier) -> None:
    """A second report of one activation neither re-records nor re-sends it."""
    await notifier.async_start([])
    await notifier.async_announce(_activation())
    await hass.async_block_till_done(wait_background_tasks=True)
    saves = notifier.store.saves

    await notifier.async_announce(_activation())

    assert notifier.store.saves == saves


async def test_muting_touches_only_that_growspace(hass, notifier) -> None:
    """Another growspace's delivery goes ahead; nothing to mute saves nothing."""
    notifier.store.data = {
        "deliveries": [
            _row("capture-1", "pending"),
            _row("capture-2", "pending", growspace_id="tent2"),
            _row("capture-3", "delivered", growspace_id="tent3"),
        ]
    }
    notifier._spawn = lambda *_args: None
    await notifier.async_start(
        [
            _activation(
                growspace_id="tent3",
                activation_id="capture-3",
                origin=ActivationOrigin.HISTORICAL,
            )
        ]
    )

    await notifier.async_mute("tent1")
    saves = notifier.store.saves
    await notifier.async_mute("tent3")

    assert notifier.store.saves == saves
    statuses = {
        row["activation_id"]: row["channels"]["home_assistant"]["status"]
        for row in notifier.store.data["deliveries"]
    }
    assert statuses == {
        "capture-1": "suppressed",
        "capture-2": "pending",
        "capture-3": "delivered",
    }


async def test_identity_falls_back_to_ids(hass, notifier) -> None:
    """Without a configured growspace or a camera state, the ids are named."""
    await notifier.async_start([])

    await notifier.async_announce(_activation(growspace_id="gone"))
    await hass.async_block_till_done(wait_background_tasks=True)

    notification = hass.data["persistent_notification"][
        continuity_notification_id("gone", "camera.canopy", "capture-1")
    ]
    assert notification["title"].endswith(": gone")
    assert notification["message"].endswith(
        "\n\nCamera: camera.canopy\nGrowspace: gone"
    )
