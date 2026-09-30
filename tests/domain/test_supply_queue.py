"""Zero-mock arbitration: due minutes, grower order, manual FIFO and fairness."""

from datetime import UTC, datetime, timedelta

from custom_components.growspace_manager.domain.supply_queue import SupplyQueue

DUE = datetime(2026, 9, 30, 9, tzinfo=UTC)
ORDER = ("red", "blue", "green", "white", "black", "gold")


def test_fifo_minutes_and_zone_order():
    """Earlier due minutes win; simultaneous claims follow the grower's order."""
    queue = SupplyQueue()
    queue.claim("red", DUE + timedelta(minutes=1), "schedule")
    for zone in reversed(ORDER[1:]):
        queue.claim(zone, DUE + timedelta(seconds=45), "steering")
    assert [c.zone_id for c in queue.ordered(ORDER)] == [*ORDER[1:], "red"]
    assert queue.release(ORDER).as_dict() == {
        "zone_id": "blue",
        "due_at": DUE.isoformat(),
        "source": "steering",
    }


def test_duplicate_automatic_claim_has_no_second_shot():
    """One automatic claim per zone, regardless of automatic trigger."""
    queue = SupplyQueue()
    claim = queue.claim("red", DUE, "steering")
    assert queue.claim("red", DUE + timedelta(minutes=1), "schedule") is None
    assert queue.contains("red")
    assert not queue.contains("blue")
    assert queue.release(ORDER) == claim
    assert queue.release(ORDER) is None


def test_manual_priority_is_fifo_and_outside_zone_limit():
    """Manual requests precede automatic claims, preserving each person's turn."""
    queue = SupplyQueue()
    automatic = queue.claim("red", DUE, "steering")
    first = queue.claim("red", DUE + timedelta(minutes=3), "manual")
    second = queue.claim("red", DUE + timedelta(minutes=2), "manual")
    assert queue.release(ORDER) == first
    assert queue.release(ORDER) == second
    assert queue.release(ORDER) == automatic


def test_served_zone_rejoins_back_even_within_same_minute():
    """Six competing zones each get a turn before a served zone can repeat."""
    queue = SupplyQueue()
    for zone in reversed(ORDER):
        queue.claim(zone, DUE, "steering")
    for zone in ORDER:
        assert queue.release(ORDER).zone_id == zone
        queue.claim(zone, DUE, "steering")
    assert [c.zone_id for c in queue.ordered(ORDER)] == list(ORDER)
    queue.clear()
    assert not queue.ordered(ORDER)
    assert queue.release(ORDER) is None


def test_unknown_zone_orders_after_configured_ties():
    """A stale zone id cannot displace a configured zone with the same due minute."""
    queue = SupplyQueue()
    queue.claim("removed", DUE, "schedule")
    queue.claim("red", DUE, "schedule")
    assert queue.release(ORDER).zone_id == "red"
