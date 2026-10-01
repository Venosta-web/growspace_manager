"""Flow-meter configuration and HA metadata classification (ADR-0064)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from homeassistant.const import UnitOfVolume, UnitOfVolumeFlowRate
from homeassistant.util.unit_conversion import (
    BaseUnitConverter,
    VolumeConverter,
    VolumeFlowRateConverter,
)

from ..models.flow_meter import FlowMeter


class FlowMeterError(ValueError):
    """A meter cannot be configured as declared."""


def parse_flow_meters(raw: Any) -> list[FlowMeter]:
    """Require the exact wire shape, including on non-schema write paths."""
    if not isinstance(raw, list):
        raise FlowMeterError("flow_meters must be a list of {entity_id, placement}")
    result = []
    for entry in raw:
        if isinstance(entry, FlowMeter):
            entry = entry.to_dict()
        if not isinstance(entry, Mapping) or set(entry) != {"entity_id", "placement"}:
            raise FlowMeterError(
                "Each flow meter needs only entity_id and placement; no kind or unit override"
            )
        entity_id, placement = entry["entity_id"], entry["placement"]
        if (
            not isinstance(entity_id, str)
            or not entity_id.startswith("sensor.")
            or not entity_id[7:]
        ):
            raise FlowMeterError("A flow meter entity_id must name a sensor")
        if not isinstance(placement, str) or not placement:
            raise FlowMeterError(
                "A flow meter placement must be supply or an irrigation zone ID"
            )
        result.append(FlowMeter(entity_id, placement))
    return result


def validate_meter_placements(meters: Sequence[FlowMeter], zone_ids: set[str]) -> None:
    """At most one instrument on the supply and on each existing zone."""
    seen = set()
    for meter in meters:
        if meter.placement != "supply" and meter.placement not in zone_ids:
            raise FlowMeterError(
                f"Flow meter {meter.entity_id}: unknown irrigation zone {meter.placement}"
            )
        if meter.placement in seen:
            raise FlowMeterError(
                f"At most one flow meter is allowed at {meter.placement}"
            )
        seen.add(meter.placement)


@dataclass(frozen=True)
class FlowMeterMetadata:
    """A live classification, never an override persisted with the placement."""

    kind: Literal["cumulative_total", "rate"]
    unit: str

    def convert(self, value: float) -> float:
        """Convert a reading to litres or litres/second using HA's converters."""
        if self.kind == "cumulative_total":
            return VolumeConverter.convert(value, self.unit, UnitOfVolume.LITERS)
        return VolumeFlowRateConverter.convert(
            value, self.unit, UnitOfVolumeFlowRate.LITERS_PER_SECOND
        )


def classify_flow_meter(
    entity_id: str, attributes: Mapping[str, Any]
) -> FlowMeterMetadata:
    """Refuse unclassifiable instruments and name the HA-side correction."""
    kind: Literal["cumulative_total", "rate"]
    converter: type[BaseUnitConverter]
    device_class = attributes.get("device_class")
    state_class = attributes.get("state_class")
    unit = attributes.get("unit_of_measurement")
    if device_class in {"water", "volume"} and state_class in {
        "total",
        "total_increasing",
    }:
        kind = "cumulative_total"
        converter = VolumeConverter
    elif device_class == "volume_flow_rate":
        kind = "rate"
        converter = VolumeFlowRateConverter
    else:
        raise FlowMeterError(
            f"Flow meter {entity_id} needs water/volume with total/total_increasing, or volume_flow_rate. Fix its metadata with a template or utility_meter sensor, or customize."
        )
    if not isinstance(unit, str) or unit not in converter.VALID_UNITS:
        raise FlowMeterError(
            f"Flow meter {entity_id} has unsupported {device_class} unit {unit!r}. Fix unit_of_measurement with a template or utility_meter sensor, or customize."
        )
    return FlowMeterMetadata(kind, unit)
