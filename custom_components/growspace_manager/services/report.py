"""Report generation services for Growspace Manager.

Handles extracting timeline events, calculating averages, and generating
comprehensive PDF or JSON reports for individual plants.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import DOMAIN, GrowspaceService
from custom_components.growspace_manager.exceptions import GrowspaceError
from custom_components.growspace_manager.models import Plant
from custom_components.growspace_manager.schemas import EXPORT_GROW_REPORT_SCHEMA
from homeassistant.components.persistent_notification import (
    async_create as create_notification,
)
from homeassistant.components.recorder import get_instance
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util

from ._definition import ServiceDefinition

# Imports moved to function scope to avoid circular dependency with websocket.py

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


async def handle_export_grow_report(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle export grow report service call."""
    plant_id = call.data.get("plant_id")
    growspace_id = call.data.get("growspace_id")
    export_format = call.data.get("format", "pdf")

    if not plant_id and not growspace_id:
        raise HomeAssistantError("Neither plant_id nor growspace_id provided")

    # Validate identifiers and get basic data before entering the try block
    if plant_id:
        plant = coordinator.data_repository.get_plant(plant_id)
        if not plant:
            raise HomeAssistantError(f"Plant {plant_id} not found")
        safe_name = f"{plant.genetics.strain_name}_{plant.phenotype}"
    else:
        growspace = coordinator.data_repository.get_growspace(growspace_id)  # type: ignore[arg-type]
        if not growspace:
            raise HomeAssistantError(f"Growspace {growspace_id} not found")
        safe_name = growspace.name

    try:
        report_data: dict[str, Any]
        if plant_id:
            report_data = await _aggregate_plant_data(hass, coordinator, plant)
        else:
            report_data = await _aggregate_growspace_data(
                hass, coordinator, growspace_id
            )  # type: ignore[arg-type]

        output_dir = Path(hass.config.path("www", "growspace_manager", "reports"))
        await hass.async_add_executor_job(output_dir.mkdir, 511, True, True)

        timestamp = dt_util.now().strftime("%Y%m%d_%H%M%S")
        safe_name = safe_name.replace(" ", "_").replace("/", "_")
        filename = f"{safe_name}_{timestamp}.{export_format}"
        file_path = output_dir / filename

        if export_format == "json":
            await hass.async_add_executor_job(
                _export_as_json, report_data, str(file_path)
            )
        else:
            await hass.async_add_executor_job(
                _export_as_pdf, report_data, str(file_path)
            )

        # Calculate web accessible path
        relative_path = str(file_path).replace(hass.config.path("www"), "/local")

        _LOGGER.info("Exported grow report to %s (web: %s)", file_path, relative_path)

        hass.bus.async_fire(
            f"{DOMAIN}_grow_report_exported",
            {
                "plant_id": plant_id,
                "growspace_id": growspace_id,
                "file_path": file_path,
                "url": relative_path,
                "format": export_format,
            },
        )

        create_notification(
            hass,
            f"Grow report exported successfully.\nPath: {file_path}",
            title="Grow Report Export",
        )

    except (AttributeError, KeyError, ValueError, ServiceValidationError, GrowspaceError) as err:
        _LOGGER.exception("Failed to export grow report")
        create_notification(
            hass,
            f"Failed to export grow report: {err!s}",
            title="Growspace Manager Error",
        )
        raise HomeAssistantError(f"Failed to export grow report: {err}") from err


async def _aggregate_plant_data(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, plant: Plant
) -> dict[str, Any]:
    """Aggregate all data needed for the report."""
    growspace = coordinator.data_repository.get_growspace(plant.growspace_id)
    if not growspace:
        raise HomeAssistantError(f"Growspace {plant.growspace_id} not found")

    # 1. Setup time range
    start_time = None
    if plant.stage_history:
        parsed = dt_util.parse_datetime(plant.stage_history[0]["start"])
        if parsed:
            start_time = dt_util.as_utc(parsed)
    if not start_time and plant.created_at:
        parsed = dt_util.parse_datetime(plant.created_at)
        if parsed:
            start_time = dt_util.as_utc(parsed)
    if not start_time:
        start_time = dt_util.utcnow()

    end_time = dt_util.utcnow()

    # 2. Fetch Timeline Events
    timeline = await _get_plant_timeline_events(
        hass, plant, growspace.id, start_time, end_time
    )

    # 3. Calculate Environmental Averages per Stage
    averages = await _get_plant_environmental_stats(
        hass, plant, growspace.environment_config, start_time, end_time
    )

    return {
        "plant_info": {
            "id": plant.plant_id,
            "strain": plant.genetics.strain_name,
            "phenotype": plant.genetics.phenotype_name,
            "growspace": growspace.name,
            "stage": str(plant.stage),
            "created_at": plant.created_at,
            "harvested_at": getattr(plant, "dry_start", None)
            or getattr(plant, "cure_start", None),
        },
        "stage_history": plant.stage_history,
        "timeline_events": timeline,
        "environmental_averages": averages,
    }


async def _get_plant_timeline_events(
    hass: HomeAssistant,
    plant: Plant,
    growspace_id: str,
    start_time: datetime,
    end_time: datetime,
) -> list[dict[str, Any]]:
    """Fetch and filter timeline events for a plant."""
    try:
        from custom_components.growspace_manager.websocket import (
            _query_logbook_events_impl,
        )

        recorder = get_instance(hass)
        evts = await recorder.async_add_executor_job(
            _query_logbook_events_impl,
            hass,
            start_time,
            end_time,
            1000,
            growspace_id,
            {"optimal", "stress", "mold", "environment"},
            None,
            2,
        )

        plant_evts = []
        for e in evts:
            pid = e.get("plant_id")
            if (
                pid == plant.plant_id
                or (isinstance(pid, list) and plant.plant_id in pid)
                or (not pid and e.get("growspace_id") == growspace_id)
            ):
                plant_evts.append(e)

    except HomeAssistantError:
        raise
    except (AttributeError, KeyError, ValueError, ServiceValidationError, GrowspaceError) as err:
        _LOGGER.warning("Could not fetch logbook events for report: %s", err)
        return []

    return plant_evts


async def _get_plant_environmental_stats(
    hass: HomeAssistant,
    plant: Plant,
    env_config: Any,
    start_time: datetime,
    end_time: datetime,
) -> dict[str, Any]:
    """Calculate environmental statistics for a plant's stages."""
    averages: dict[str, Any] = {}
    if not env_config or not plant.stage_history:
        return averages

    entities_to_track = []
    if env_config.temperature_sensor:
        entities_to_track.append(env_config.temperature_sensor)
    if env_config.humidity_sensor:
        entities_to_track.append(env_config.humidity_sensor)
    if env_config.vpd_sensor:
        entities_to_track.append(env_config.vpd_sensor)

    if not entities_to_track:
        return averages

    try:
        from custom_components.growspace_manager.websocket import _get_statistics_data

        stats = await _get_statistics_data(
            hass, entities_to_track, start_time, end_time, 60
        )
        if not stats:
            return averages

        for stage in plant.stage_history:
            stage_name = stage["stage"]
            parsed_start = dt_util.parse_datetime(stage["start"])
            if not parsed_start:
                continue
            s_start = dt_util.as_utc(parsed_start)

            s_end = end_time
            if stage.get("end"):
                parsed_end = dt_util.parse_datetime(stage["end"])
                if parsed_end:
                    s_end = dt_util.as_utc(parsed_end)

            stage_stats = {"temperature": None, "humidity": None, "vpd": None}

            # Map sensors to keys
            sensor_map = {
                "temperature": env_config.temperature_sensor,
                "humidity": env_config.humidity_sensor,
                "vpd": env_config.vpd_sensor,
            }

            for key, sensor_id in sensor_map.items():
                if sensor_id and sensor_id in stats:
                    points = [
                        float(p["s"])
                        for p in stats[sensor_id]
                        if s_start.isoformat() <= p["lu"] <= s_end.isoformat()
                    ]
                    if points:
                        stage_stats[key] = round(sum(points) / len(points), 2)  # type: ignore[reassigned]

            averages[stage_name] = stage_stats

    except HomeAssistantError:
        raise
    except (AttributeError, KeyError, ValueError, ServiceValidationError, GrowspaceError) as err:
        _LOGGER.warning("Could not fetch statistics for the report: %s", err)

    return averages


async def _aggregate_growspace_data(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, growspace_id: str
) -> dict[str, Any]:
    """Aggregate data for a whole growspace report."""
    growspace = coordinator.data_repository.get_growspace(growspace_id)
    if not growspace:
        raise HomeAssistantError(f"Growspace {growspace_id} not found")

    plants = [p for p in coordinator.plants.values() if p.growspace_id == growspace_id]

    # Calculate summary
    strains = sorted({p.genetics.strain_name for p in plants})
    stages: dict[str, int] = {}
    for p in plants:
        stage_str = str(p.stage)
        stages[stage_str] = stages.get(stage_str, 0) + 1

    # Calculate harvest totals
    total_wet = sum(getattr(p, "wet_weight", 0) or 0 for p in plants)
    total_dry = sum(getattr(p, "dry_weight", 0) or 0 for p in plants)
    total_trim = sum(getattr(p, "trim_weight", 0) or 0 for p in plants)
    top_thc = max([getattr(p, "thc_percentage", 0) or 0 for p in plants] + [0])

    data: dict[str, Any] = {
        "plant_info": {
            "id": growspace_id,
            "strain": "Multiple Strains",
            "phenotype": "Summary View",
            "growspace": growspace.name,
            "stage": "Various",
            "created_at": None,
            "harvested_at": None,
        },
        "summary": {
            "plant_count": len(plants),
            "strains": strains,
            "stages": stages,
        },
        "harvest": {
            "total_wet_weight": round(total_wet, 2),
            "total_dry_weight": round(total_dry, 2),
            "total_trim_weight": round(total_trim, 2),
            "top_thc": top_thc,
        },
        "environment": {
            "temperature_avg": None,
            "humidity_avg": None,
            "vpd_avg": None,
        },
        "environmental_averages": {},
        "timeline_events": [],
    }

    # Fetch environmental averages (last 30 days or since first plant)
    env_config = growspace.environment_config
    if env_config:
        entities = []
        if env_config.temperature_sensor:
            entities.append(env_config.temperature_sensor)
        if env_config.humidity_sensor:
            entities.append(env_config.humidity_sensor)
        if env_config.vpd_sensor:
            entities.append(env_config.vpd_sensor)

        if entities:
            end_time = dt_util.utcnow()
            start_time = end_time - timedelta(days=30)
            if plants:
                created_dates = []
                for p in plants:
                    if p.created_at:
                        parsed = dt_util.parse_datetime(p.created_at)
                        if parsed:
                            created_dates.append(dt_util.as_utc(parsed))
                first_plant_date = min([*created_dates, end_time])
                start_time = max(start_time, first_plant_date)

            try:
                from custom_components.growspace_manager.websocket import (
                    _get_statistics_data,
                )

                stats = await _get_statistics_data(
                    hass, entities, start_time, end_time, 60
                )
                if stats:
                    if env_config.temperature_sensor in stats:
                        pts = [
                            float(p["s"]) for p in stats[env_config.temperature_sensor]
                        ]
                        if pts:
                            data["environment"]["temperature_avg"] = round(
                                sum(pts) / len(pts), 2
                            )
                    if env_config.humidity_sensor in stats:
                        pts = [float(p["s"]) for p in stats[env_config.humidity_sensor]]
                        if pts:
                            data["environment"]["humidity_avg"] = round(
                                sum(pts) / len(pts), 2
                            )
                    if env_config.vpd_sensor in stats:
                        pts = [float(p["s"]) for p in stats[env_config.vpd_sensor]]
                        if pts:
                            data["environment"]["vpd_avg"] = round(
                                sum(pts) / len(pts), 2
                            )
            except (AttributeError, KeyError, ValueError, ServiceValidationError, GrowspaceError) as err:
                _LOGGER.warning(
                    "Could not fetch env stats for growspace report: %s", err
                )

    return data


async def async_websocket_get_grow_report(
    hass: HomeAssistant,
    connection: Any,
    msg: dict[str, Any],
) -> None:
    """Handle WebSocket grow report request."""

    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

    try:
        coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
        plant_id = msg.get("plant_id")
        growspace_id = msg.get("growspace_id")

        if plant_id:
            plant = coordinator.data_repository.get_plant(plant_id)
            if not plant:
                connection.send_error(
                    msg["id"], "not_found", f"Plant {plant_id} not found"
                )
                return
            report_data = await _aggregate_plant_data(hass, coordinator, plant)
        elif growspace_id:
            report_data = await _aggregate_growspace_data(
                hass, coordinator, growspace_id
            )
        else:
            connection.send_error(
                msg["id"], "invalid_request", "No plant_id or growspace_id"
            )
            return

        connection.send_result(msg["id"], report_data)

    except (AttributeError, KeyError, ValueError, ServiceValidationError, GrowspaceError) as err:
        _LOGGER.exception("Error generating grow report for WebSocket")
        connection.send_error(msg["id"], "unknown_error", str(err))


def _export_as_json(data: dict[str, Any], file_path: str) -> None:
    """Export the report data as a JSON file."""
    with Path(file_path).open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _export_as_pdf(data: dict[str, Any], file_path: str) -> None:
    """Generate a PDF report using fpdf2."""
    try:
        from fpdf import FPDF  # noqa: PLC0415
    except ImportError as err:
        from homeassistant.exceptions import HomeAssistantError  # noqa: PLC0415
        raise HomeAssistantError(
            "PDF export requires the 'fpdf2' package. Install it with: pip install fpdf2>=2.7.9"
        ) from err
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Title
    pdf.set_font("helvetica", "B", 24)
    pdf.cell(0, 15, "Grow Report", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("helvetica", "", 12)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(
        0,
        10,
        f"Generated: {dt_util.now().strftime('%Y-%m-%d %H:%M')}",
        align="C",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(10)

    # Plant Info
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("helvetica", "B", 16)
    pdf.cell(0, 10, "Plant Information", new_x="LMARGIN", new_y="NEXT")
    pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 190, pdf.get_y())
    pdf.ln(5)

    pdf.set_font("helvetica", "", 12)
    info = data["plant_info"]
    labels = [
        ("Strain/Pheno", f"{info['strain']} - {info['phenotype']}"),
        ("Growspace", info["growspace"]),
        ("Current Stage", info["stage"]),
        ("Started On", info["created_at"][:10] if info["created_at"] else "N/A"),
    ]

    for label, val in labels:
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(40, 8, f"{label}:")
        pdf.set_font("helvetica", "", 12)
        pdf.cell(0, 8, str(val), new_x="LMARGIN", new_y="NEXT")

    pdf.ln(10)

    # Environment
    if data["environmental_averages"]:
        pdf.set_font("helvetica", "B", 16)
        pdf.cell(
            0, 10, "Environmental Averages (per Stage)", new_x="LMARGIN", new_y="NEXT"
        )
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 190, pdf.get_y())
        pdf.ln(5)

        pdf.set_font("helvetica", "B", 10)
        pdf.cell(40, 8, "Stage", border=1)
        pdf.cell(30, 8, "Temp (°C)", border=1, align="C")
        pdf.cell(30, 8, "Humidity (%)", border=1, align="C")
        pdf.cell(30, 8, "VPD (kPa)", border=1, align="C")
        pdf.ln()

        pdf.set_font("helvetica", "", 10)
        for stage, stats in data["environmental_averages"].items():
            pdf.cell(40, 8, stage.title(), border=1)
            pdf.cell(30, 8, str(stats["temperature"] or "-"), border=1, align="C")
            pdf.cell(30, 8, str(stats["humidity"] or "-"), border=1, align="C")
            pdf.cell(30, 8, str(stats["vpd"] or "-"), border=1, align="C")
            pdf.ln()

        pdf.ln(10)

    # Timeline Summary (Last 50 events)
    events = data["timeline_events"]
    if events:
        pdf.set_font("helvetica", "B", 16)
        pdf.cell(0, 10, "Event Timeline", new_x="LMARGIN", new_y="NEXT")
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 190, pdf.get_y())
        pdf.ln(5)

        pdf.set_font("helvetica", "", 10)
        for evt in sorted(events, key=lambda x: x.get("timestamp", 0))[-50:]:
            ts = evt.get("timestamp")
            date_str = (
                dt_util.as_local(dt_util.utc_from_timestamp(ts / 1000)).strftime(
                    "%Y-%m-%d"
                )
                if ts
                else "Unknown"
            )
            cat = evt.get("category", "").title()
            msg = (
                evt.get("notes") or evt.get("sensor_type", "").replace("_", " ").title()
            )

            # Simple formatting
            pdf.set_font("helvetica", "B", 10)
            pdf.cell(25, 6, date_str)
            pdf.cell(20, 6, cat)
            pdf.set_font("helvetica", "", 10)
            pdf.multi_cell(0, 6, str(msg))
            pdf.ln(2)

    pdf.output(file_path)


SERVICES = [
    ServiceDefinition(
        GrowspaceService.EXPORT_GROW_REPORT,
        handle_export_grow_report,
        EXPORT_GROW_REPORT_SCHEMA,
    ),
]
