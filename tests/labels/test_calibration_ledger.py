"""Tests for the calibration ledger (hub issue #221).

Built over the real `hass` and the real Home Assistant `Store`, because the
store is what is under test: a measurement that survives a restart and a
history that is never rewritten are both claims about persistence, and a
double would prove neither.

The claim running through all of it is that **nothing is destroyed to make
something work**. Re-calibrating appends; the superseded record stays, because
"what was this printer measured at when that label printed?" has to keep
having an answer for as long as the label is in the grow room.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.growspace_manager.labels.calibration import (
    ABSENT,
    CURRENT,
    SHEET_VERSION,
    STALE,
    STORE_VERSION,
    CalibrationDependencies,
    CalibrationLedgerState,
    IncompatibleCalibrationStore,
    LocalCalibration,
    LocalCalibrationLedger,
    MeasurementInvalid,
    PlacementMeasurement,
    async_get_calibration_ledger,
    async_release_calibration_ledger,
    evaluate,
    storage_key,
)
from custom_components.growspace_manager.labels.canonical import NIIMBOT_B1_50X30
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import Unauthorized

PROFILE = NIIMBOT_B1_50X30
DEVICE = "printer-a"
OTHER_DEVICE = "printer-b"
FONTS = {"ppb.ttf": "sha256:aaa", "rbm.ttf": "sha256:bbb"}
NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)

FIRST = PlacementMeasurement(
    top_mm=0.5, right_mm=0.5, bottom_mm=0.0, left_mm=0.5, feed_mm=-0.4
)
SECOND = PlacementMeasurement(
    top_mm=1.0, right_mm=0.0, bottom_mm=0.5, left_mm=1.0, feed_mm=0.8
)


def _dependencies(profile=PROFILE, *, device_id: str = DEVICE, **overrides):
    return CalibrationDependencies.for_profile(
        profile,
        device_id=device_id,
        sheet_version=overrides.pop("sheet_version", SHEET_VERSION),
        font_identity=overrides.pop("font_identity", FONTS),
    )


async def _record(
    ledger: LocalCalibrationLedger,
    admin,
    measurement=FIRST,
    dependencies=None,
    **kwargs,
):
    return await ledger.async_record(
        admin,
        measurement=measurement,
        dependencies=dependencies or _dependencies(),
        sheet_raster_identity=kwargs.pop("sheet_raster_identity", "sha256:sheet"),
        printed_density=kwargs.pop("printed_density", "normal"),
        **kwargs,
    )


@pytest.fixture
def ledgers(hass: HomeAssistant):
    """A factory for ledgers, by config entry ID.

    Calling it twice with one entry ID builds two instances over the same
    stored document, which is how a restart is exercised without one.
    """

    def build(entry_id: str = "entry-a") -> LocalCalibrationLedger:
        return LocalCalibrationLedger(hass, entry_id)

    return build


@pytest.fixture
async def ledger(ledgers) -> LocalCalibrationLedger:
    """One loaded, empty ledger for the default config entry."""
    built = ledgers()
    await built.async_load()
    return built


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


async def test_a_measurement_captures_the_actor_the_time_and_every_dependency(
    ledger, admin
) -> None:
    record = await _record(ledger, admin)
    assert record.measurement == FIRST
    assert record.recorded_by == "admin-user"
    assert datetime.fromisoformat(record.recorded_at).tzinfo is not None
    assert record.dependencies == _dependencies()
    assert record.sheet_raster_identity == "sha256:sheet"
    assert record.printed_density == "normal"


async def test_only_an_administrator_may_record_one(ledger, viewer, nobody) -> None:
    for actor in (viewer, nobody):
        with pytest.raises(Unauthorized):
            await _record(ledger, actor)
    assert (await ledger.async_load()).records == ()


async def test_authority_is_asked_at_the_mutation_rather_than_held(
    ledger, admin
) -> None:
    """An administrator demoted while the calibration flow is open keeps the
    sheet in their hand and loses the write."""
    await _record(ledger, admin)
    demoted = replace(admin, is_admin=False)
    with pytest.raises(Unauthorized):
        await _record(ledger, demoted, SECOND)
    assert len((await ledger.async_load()).records) == 1


async def test_an_impossible_measurement_is_refused_before_anything_is_written(
    ledger, admin
) -> None:
    with pytest.raises(MeasurementInvalid):
        await _record(ledger, admin, replace(FIRST, top_mm=-1.0))
    assert (await ledger.async_load()).records == ()


async def test_a_measurement_is_judged_against_the_geometry_it_was_taken_on(
    ledger, admin
) -> None:
    """Not against whichever profile happens to be selected now."""
    narrow = _dependencies(replace(PROFILE, printable_width_mm=6.0))
    with pytest.raises(MeasurementInvalid):
        await _record(ledger, admin, replace(FIRST, left_mm=8.0), narrow)


# ---------------------------------------------------------------------------
# Nothing is rewritten
# ---------------------------------------------------------------------------


async def test_recalibrating_appends_and_leaves_the_earlier_record_alone(
    ledger, admin
) -> None:
    first = await _record(ledger, admin, FIRST)
    second = await _record(ledger, admin, SECOND)
    history = await ledger.async_history(_dependencies().scope)
    assert [item.id for item in history] == [first.id, second.id]
    assert history[0].measurement == FIRST


async def test_the_newest_measurement_is_the_one_a_print_is_judged_against(
    ledger, admin
) -> None:
    await _record(ledger, admin, FIRST)
    await _record(ledger, admin, SECOND)
    status = await ledger.async_status(required=_dependencies(), now=NOW)
    assert status.record is not None
    assert status.record.measurement == SECOND


async def test_a_committed_measurement_survives_a_restart(
    ledgers, ledger, admin
) -> None:
    await _record(ledger, admin)
    reopened = ledgers()
    status = await reopened.async_status(required=_dependencies(), now=NOW)
    assert status.state == CURRENT
    assert status.record is not None
    assert status.record.measurement == FIRST


# ---------------------------------------------------------------------------
# Scope selects; the fingerprint judges
# ---------------------------------------------------------------------------


async def test_another_printer_is_not_a_stale_calibration_of_this_one(
    ledger, admin
) -> None:
    """It is a calibration of something else, so the answer is that this one
    has never been measured."""
    await _record(ledger, admin, dependencies=_dependencies(device_id=OTHER_DEVICE))
    status = await ledger.async_status(required=_dependencies(), now=NOW)
    assert status.state == ABSENT
    assert status.stale_reasons == ()


async def test_a_different_stock_is_a_different_scope(ledger, admin) -> None:
    await _record(ledger, admin)
    other_stock = _dependencies(
        replace(PROFILE, label_size_id="growspace.stock.40x30.v1")
    )
    assert (await ledger.async_status(required=other_stock, now=NOW)).state == ABSENT


async def test_a_changed_dependency_within_one_scope_is_stale_and_named(
    ledger, admin
) -> None:
    await _record(ledger, admin)
    moved = replace(_dependencies(), adapter_version="growspace.niimbot-adapter.v2")
    status = await ledger.async_status(required=moved, now=NOW)
    assert status.state == STALE
    assert status.stale_reasons == ("adapter_version",)
    assert status.identity is None


async def test_recalibrating_after_a_dependency_moved_makes_it_current_again(
    ledger, admin
) -> None:
    await _record(ledger, admin, FIRST)
    moved = replace(_dependencies(), dpi=300)
    assert (await ledger.async_status(required=moved, now=NOW)).state == STALE

    await _record(ledger, admin, SECOND, moved)
    status = await ledger.async_status(required=moved, now=NOW)
    assert status.state == CURRENT
    assert status.record is not None
    assert status.record.measurement == SECOND
    # And the superseded record is still on file.
    assert len(await ledger.async_history(moved.scope)) == 2


# ---------------------------------------------------------------------------
# One entry's ledger is its own
# ---------------------------------------------------------------------------


async def test_two_config_entries_keep_two_histories(ledgers, admin) -> None:
    first = ledgers("entry-a")
    second = ledgers("entry-b")
    await _record(first, admin)
    assert (
        await second.async_status(required=_dependencies(), now=NOW)
    ).state == ABSENT


def test_the_storage_key_carries_the_config_entry() -> None:
    assert storage_key("abc123").endswith(".abc123")
    assert storage_key("abc123") != storage_key("def456")


async def test_the_history_is_readable_by_any_authenticated_user(
    ledger, admin, viewer, nobody
) -> None:
    """What a printer was measured at explains why a print is refused, and
    hiding it from the person holding the refusal makes it unexplainable."""
    await _record(ledger, admin)
    snapshot = await ledger.async_snapshot(viewer)
    assert len(snapshot["records"]) == 1
    assert snapshot["records"][0]["identity"]
    with pytest.raises(Unauthorized):
        await ledger.async_snapshot(nobody)


async def test_the_shared_ledger_is_one_instance_per_entry(hass, admin) -> None:
    opened = await async_get_calibration_ledger(hass, "entry-shared")
    assert await async_get_calibration_ledger(hass, "entry-shared") is opened
    await _record(opened, admin)
    async_release_calibration_ledger(hass, "entry-shared")
    reopened = await async_get_calibration_ledger(hass, "entry-shared")
    assert reopened is not opened
    # Releasing forgets the instance and never the document.
    assert len((await reopened.async_load()).records) == 1


async def test_an_age_warning_never_becomes_a_refusal(ledger, admin) -> None:
    await _record(ledger, admin)
    much_later = NOW + timedelta(days=500)
    status = await ledger.async_status(required=_dependencies(), now=much_later)
    assert status.state == CURRENT
    assert status.warnings


# ---------------------------------------------------------------------------
# A store this version cannot read
# ---------------------------------------------------------------------------


async def test_a_newer_store_is_left_untouched_rather_than_read_loosely(
    hass, hass_storage
) -> None:
    """A best-effort read of a newer document is how it quietly becomes a
    lossy older one, and this one is an audit record."""
    hass_storage[storage_key("entry-newer")] = {
        "version": STORE_VERSION + 1,
        "key": storage_key("entry-newer"),
        "data": {"records": []},
    }
    with pytest.raises(IncompatibleCalibrationStore) as refusal:
        await LocalCalibrationLedger(hass, "entry-newer").async_load()
    assert refusal.value.found == STORE_VERSION + 1
    assert refusal.value.supported == STORE_VERSION


async def test_an_unreadable_store_contains_itself_rather_than_failing_setup(
    hass, hass_storage
) -> None:
    """Setting up a config entry must not fail because its calibration
    history was written by a newer version. Every call that needed to read it
    raises for itself."""
    hass_storage[storage_key("entry-contained")] = {
        "version": STORE_VERSION + 1,
        "key": storage_key("entry-contained"),
        "data": {"records": []},
    }
    ledger = await async_get_calibration_ledger(hass, "entry-contained")
    with pytest.raises(IncompatibleCalibrationStore):
        await ledger.async_load()


async def test_a_document_with_no_records_reads_as_an_empty_history(hass) -> None:
    assert CalibrationLedgerState.from_dict(None).records == ()
    assert CalibrationLedgerState.from_dict({}).records == ()
    assert CalibrationLedgerState.from_dict({"records": "not a list"}).records == ()


async def test_removing_a_config_entry_removes_its_document(
    hass, hass_storage, ledger, admin
) -> None:
    """For the enclosing Home Assistant data lifecycle, and never as a way to
    correct a measurement."""
    await _record(ledger, admin)
    assert storage_key("entry-a") in hass_storage
    await ledger._store.async_remove()
    assert storage_key("entry-a") not in hass_storage


def test_a_status_serializes_for_the_wire() -> None:
    status = evaluate(None, required=_dependencies(), now=NOW)
    wire = status.as_dict()
    assert set(wire) == {
        "state",
        "identity",
        "stale_reasons",
        "warnings",
        "age_days",
        "record",
    }
    assert wire["state"] == ABSENT
    assert wire["record"] is None


def test_a_naive_timestamp_reports_no_age_rather_than_an_invented_one() -> None:
    record = LocalCalibration(
        id="01NAIVE",
        recorded_at=datetime(2026, 1, 1, 12, 0).isoformat(),
        recorded_by="admin-user",
        measurement=FIRST,
        dependencies=_dependencies(),
        sheet_raster_identity="sha256:sheet",
        printed_density="normal",
    )
    status = evaluate(record, required=_dependencies(), now=NOW)
    assert status.state == CURRENT
    assert status.age_days is None
