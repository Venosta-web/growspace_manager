"""Collect Home Assistant reports for an irrigation attempt's Metering Window."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
import math

from homeassistant.const import STATE_OFF
from homeassistant.core import (
    Event,
    EventStateChangedData,
    EventStateReportedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_state_report_event,
)

from .domain.delivery_attempt import DeliveryAttempt, MeterEvidence
from .domain.flow_meter import FlowMeterMetadata, classify_flow_meter
from .domain.metering_window import (
    METERING_TAIL,
    MeterAbsence,
    MeteringWindow,
    MeterReading,
    integrate_meter,
)
from .models.flow_meter import FlowMeter


@dataclass(slots=True)
class _Meter:
    config: FlowMeter
    metadata: FlowMeterMetadata | None
    readings: list[MeterReading] = field(default_factory=list)

    def record(self, at: datetime, state: State | None) -> None:
        value = None
        if state is not None:
            try:
                metadata = classify_flow_meter(state.entity_id, state.attributes)
                if self.metadata is None:
                    self.metadata = metadata
                if metadata == self.metadata:
                    converted = metadata.convert(float(state.state))
                    if math.isfinite(converted) and converted >= 0:
                        value = converted
            except ValueError, OverflowError:
                pass  # Unknown, unavailable or invalid metadata/value.
        self.readings.append(MeterReading(at, value))

    def measure(self, window: MeteringWindow) -> MeterEvidence:
        metadata = self.metadata
        return MeterEvidence(
            self.config.entity_id,
            metadata.kind if metadata else None,
            metadata.unit if metadata else None,
            integrate_meter(metadata.kind, window, self.readings)
            if metadata
            else MeterAbsence.UNAVAILABLE,
        )


class AttemptMetering:
    """Own the listeners and tail for one supply attempt."""

    def __init__(
        self, hass: HomeAssistant, *, zone: FlowMeter | None, supply: FlowMeter | None
    ) -> None:
        """Snapshot each instrument and subscribe before the supply command."""
        self._hass = hass
        self._zone = _Meter(zone, metadata=None) if zone else None
        self._supply = _Meter(supply, metadata=None) if supply else None
        self._meters = [meter for meter in (self._zone, self._supply) if meter]
        self._cancel: list[Callable[[], None]] = []
        self._closed: DeliveryAttempt | None = None
        self._on_finish: Callable[[DeliveryAttempt], None] | None = None
        for meter in self._meters:
            state = hass.states.get(meter.config.entity_id)
            if state is not None:
                meter.record(state.last_reported, state)

        entity_ids = {meter.config.entity_id for meter in self._meters}
        self._cancel = [
            async_track_state_change_event(hass, entity_ids, self._changed),
            async_track_state_report_event(hass, entity_ids, self._reported),
        ]

    @callback
    def _changed(self, event: Event[EventStateChangedData]) -> None:
        self._record(event.data["entity_id"], event.time_fired, event.data["new_state"])

    @callback
    def _reported(self, event: Event[EventStateReportedData]) -> None:
        self._record(
            event.data["entity_id"],
            event.data["last_reported"],
            event.data["new_state"],
        )

    def _record(self, entity_id: str, at: datetime, state: State | None) -> None:
        for meter in self._meters:
            if meter.config.entity_id == entity_id:
                meter.record(at, state)

    def close(
        self, attempt: DeliveryAttempt, on_finish: Callable[[DeliveryAttempt], None]
    ) -> None:
        """Start the tail at OFF readback, including any delayed readback."""
        self._closed = attempt
        self._on_finish = on_finish
        if attempt.off_confirmed_at is not None:
            self._schedule_end(attempt.off_confirmed_at)
            return
        # Keep collecting while the existing OFF retry owns the output. The
        # recorded attempt can still be read as estimated during that wait.
        self._cancel.append(
            async_track_state_change_event(
                self._hass, attempt.output, self._pump_changed
            )
        )
        state = self._hass.states.get(attempt.output)
        if state is not None and state.state in (STATE_OFF, "closed"):
            assert attempt.off_commanded_at is not None
            self._read_off(max(state.last_changed, attempt.off_commanded_at))

    def _schedule_end(self, off_confirmed_at: datetime) -> None:
        self._cancel.append(
            async_track_point_in_utc_time(
                self._hass, self._expired, off_confirmed_at + METERING_TAIL
            )
        )

    @callback
    def _pump_changed(self, event: Event[EventStateChangedData]) -> None:
        state = event.data["new_state"]
        if state is not None and state.state in (STATE_OFF, "closed"):
            self._read_off(event.time_fired)

    def _read_off(self, at: datetime) -> None:
        attempt = self._closed
        if attempt is not None and attempt.off_confirmed_at is None:
            self._closed = attempt.read_back_off(at)
            self._schedule_end(at)

    @callback
    def _expired(self, _now: datetime) -> None:
        self.finish()

    def _metered_attempt(
        self,
        attempt: DeliveryAttempt,
        *,
        cutoff: datetime | None = None,
        observed_at: datetime | None = None,
    ) -> DeliveryAttempt:
        assert attempt.on_confirmed_at is not None
        window = MeteringWindow(
            attempt.on_confirmed_at, attempt.off_confirmed_at, cutoff, observed_at
        )
        zone = self._zone.measure(window) if self._zone else None
        supply = self._supply.measure(window) if self._supply else None
        if zone is not None and isinstance(zone.result, float):
            secondary = (
                supply.result if supply and isinstance(supply.result, float) else None
            )
            return attempt.with_meter_evidence(zone, secondary)
        if supply and (
            isinstance(supply.result, float)
            or zone is None
            or supply.result is MeterAbsence.UNAVAILABLE
        ):
            return attempt.with_meter_evidence(supply)
        assert zone is not None
        return attempt.with_meter_evidence(zone)

    def additional_charge(self, now: datetime, day: date) -> float:
        """Conservatively include usable evidence received before the cap check.

        A refused request leaves the tail open. The final recorded charge
        still uses the full window and its preferred instrument.
        """
        attempt = self._closed
        if attempt is None or attempt.charge_date != day:
            return 0.0
        measured = self._metered_attempt(attempt, observed_at=now)
        return measured.charged_l - attempt.charged_l

    @callback
    def finish(self, cutoff: datetime | None = None) -> None:
        """Detach listeners, then record one final result if the pump actuated."""
        for cancel in self._cancel:
            cancel()
        self._cancel.clear()
        if self._closed is not None and self._on_finish is not None:
            self._on_finish(self._metered_attempt(self._closed, cutoff=cutoff))
            self._on_finish = None
