"""Lossless compaction retains cap accounting and rejects corrupt documents."""

import base64
from dataclasses import replace
from unittest.mock import AsyncMock, patch
import zlib

import pytest

from custom_components.growspace_manager.delivery_attempt_store import (
    GrowspaceDeliveries,
)
from tests.delivery_helpers import charged_attempt


def history():
    deliveries = GrowspaceDeliveries("tent")
    deliveries.attempts = [
        charged_attempt("tent", attempt_id=f"a{i}", liters=0.1) for i in range(200)
    ]
    return deliveries


def test_large_history_roundtrips_and_updates_cached_tail():
    deliveries = history()
    # Closed prefix, followed by a write-before-ON/charged tail.
    deliveries.attempts[:-1] = [
        row.interrupted(row.on_confirmed_at) for row in deliveries.attempts[:-1]
    ]
    doc = deliveries._document()
    assert "attempts_zlib" in doc
    assert deliveries._decode(doc) == deliveries.attempts
    deliveries.attempts[-1] = replace(deliveries.attempts[-1], charged_l=0.2)
    assert deliveries._decode(deliveries._document()) == deliveries.attempts
    deliveries.attempts[-1] = deliveries.attempts[-1].interrupted(
        deliveries.attempts[-1].on_confirmed_at
    )
    assert deliveries._decode(deliveries._document()) == deliveries.attempts
    # An old row corrected on recovery or the oldest pruned forces a reset.
    deliveries.attempts[0] = replace(deliveries.attempts[0], reason="recovered")
    assert deliveries._decode(deliveries._document()) == deliveries.attempts
    deliveries.attempts.pop(0)
    assert deliveries._decode(deliveries._document()) == deliveries.attempts
    # One new open row follows the reusable closed prefix.
    deliveries.attempts.append(charged_attempt("tent", attempt_id="new"))
    assert deliveries._decode(deliveries._document()) == deliveries.attempts


def test_small_legacy_documents_remain_readable():
    deliveries = history()
    deliveries.attempts = deliveries.attempts[:1]
    document = deliveries._document()
    assert document["attempts"] == [deliveries.attempts[0].as_dict()]
    assert deliveries._decode(document) == deliveries.attempts
    deliveries.attempts = []
    assert deliveries._decode(deliveries._document()) == []


@pytest.mark.parametrize(
    "encoded",
    [
        None,
        12,
        "not base64!",
        base64.b64encode(b"invalid").decode(),
        base64.b64encode(zlib.compress(b"[]")[:-2]).decode(),
        base64.b64encode(zlib.compress(b"[]") + b"trailing").decode(),
        base64.b64encode(zlib.compress(b"invalid JSON")).decode(),
        base64.b64encode(zlib.compress(b'[{"attempt_id": 3}]')).decode(),
    ],
)
async def test_corrupt_compressed_history_fails_closed(hass, encoded):
    deliveries = GrowspaceDeliveries("tent", hass=hass, entry_id="test")
    deliveries._store.async_load = AsyncMock(
        return_value={"growspace_id": "tent", "attempts_zlib": encoded}
    )
    deliveries._store.async_save = AsyncMock()
    await deliveries.async_load()
    assert deliveries.unreadable
    assert deliveries.attempts == []
    deliveries._store.async_save.assert_not_awaited()


def test_decompression_is_bounded():
    encoded = base64.b64encode(zlib.compress(b" " * 1024)).decode()
    with (
        patch(
            "custom_components.growspace_manager.delivery_attempt_store.MAX_EXPANDED_BYTES",
            32,
        ),
        pytest.raises(ValueError, match="oversized"),
    ):
        GrowspaceDeliveries._expand_attempts(encoded)


def test_row_pressure_preserves_every_charge_of_the_local_day(freezer):
    from datetime import timedelta

    from custom_components.growspace_manager.domain.delivery_attempt import ROW_LIMIT
    from homeassistant.util import dt as dt_util

    freezer.move_to("2026-06-15T12:00:00+00:00")
    current = dt_util.utcnow()
    yesterday = dt_util.now().date() - timedelta(days=1)
    deliveries = GrowspaceDeliveries("tent")
    deliveries.attempts = [
        charged_attempt(
            "tent",
            attempt_id=f"old{i}",
            at=current - timedelta(days=1, seconds=i),
            day=yesterday,
        )
        for i in range(ROW_LIMIT)
    ]
    today = [charged_attempt("tent", attempt_id=f"today{i}") for i in range(240)]
    deliveries.attempts.extend(today)
    deliveries._prune()
    assert len(deliveries.attempts) == ROW_LIMIT
    assert {a.attempt_id for a in today} <= {a.attempt_id for a in deliveries.attempts}
    assert deliveries.dispensed().cycles == 240
    assert deliveries._decode(deliveries._document()) == deliveries.attempts


def test_dispensed_cache_tracks_every_public_list_edit_and_midnight(freezer):
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    freezer.move_to("2026-06-15T12:00:00+00:00")
    deliveries = history()
    assert deliveries.dispensed().cycles == 200
    first = deliveries.dispensed()
    assert deliveries.dispensed() is first
    # Replacement of an old row must invalidate even with the same list length.
    deliveries.attempts[0] = replace(deliveries.attempts[0], charged_l=1)
    assert deliveries.dispensed().liters == pytest.approx(20.9)
    deliveries.attempts.append(
        charged_attempt("tent", attempt_id="appended", liters=0.1)
    )
    assert deliveries.dispensed().cycles == 201
    deliveries.attempts.pop()
    assert deliveries.dispensed().cycles == 200
    freezer.tick(timedelta(days=1))
    assert deliveries.dispensed().cycles == 0
    deliveries.attempts = [charged_attempt("tent", attempt_id="tomorrow", liters=0.5)]
    assert deliveries.dispensed().cycles == 1
    assert deliveries.dispensed().liters == 0.5
    deliveries.attempts.clear()
    assert deliveries.dispensed().cycles == 0
    assert dt_util.now().date().isoformat() == "2026-06-16"
