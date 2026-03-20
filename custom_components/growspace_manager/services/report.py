"""Report generation services for Growspace Manager.

Handles extracting timeline events, calculating averages, and generating
comprehensive PDF or JSON reports for individual plants.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fpdf import FPDF

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.models import Plant
from homeassistant.components.persistent_notification import (
    async_create as create_notification,
)
from homeassistant.components.recorder import get_instance
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

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
        plant = coordinator.get_plant(plant_id)
        if not plant:
            raise HomeAssistantError(f"Plant {plant_id} not found")
        safe_name = f"{plant.genetics.strain_name}_{plant.phenotype}"
    else:
        growspace = coordinator.get_growspace(growspace_id)  # type: ignore[arg-type]
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
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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

    except Exception as err:
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
    growspace = coordinator.get_growspace(plant.growspace_id)
    if not growspace:
        raise HomeAssistantError(f"Growspace {plant.growspace_id} not found")

    # 1. Basic Plant Info
    data: dict[str, Any] = {
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
        "timeline_events": [],
        "environmental_averages": {},
    }

    # Setup time range
    start_time = None
    if plant.stage_history:
        with contextlib.suppress(ValueError):
            start_time = datetime.fromisoformat(plant.stage_history[0]["start"])
    if not start_time and plant.created_at:
        with contextlib.suppress(ValueError):
            start_time = datetime.fromisoformat(plant.created_at)
    if not start_time:
        start_time = datetime.now()

    end_time = datetime.now()

    # 2. Fetch Timeline Events (Watering, Training, IPM, Notes)
    try:
        from custom_components.growspace_manager.websocket import (
            _get_statistics_data,
            _query_logbook_events_impl,
        )

        recorder = get_instance(hass)
        # Fetch events for the plant's growspace
        evts = await recorder.async_add_executor_job(
            _query_logbook_events_impl,
            hass,
            start_time,
            end_time,
            1000,  # limit
            growspace.id,
            {"optimal", "stress", "mold", "environment"},  # exclude categories
            None,
            2,
        )

        # Filter events specific to this plant or space-wide events that affect it
        plant_evts = []
        for e in evts:
            pid = e.get("plant_id")
            if pid == plant.plant_id or (
                isinstance(pid, list) and plant.plant_id in pid
            ):
                plant_evts.append(e)
            elif not pid and e.get("growspace_id") == growspace.id:
                # Include whole-growspace events like space watering
                plant_evts.append(e)

        data["timeline_events"] = plant_evts

    except HomeAssistantError:
        raise
    except Exception as err:
        _LOGGER.warning("Could not fetch logbook events for report: %s", err)

    # 3. Calculate Environmental Averages per Stage
    env_config = growspace.environment_config
    if env_config:
        entities_to_track = []
        if env_config.temperature_sensor:
            entities_to_track.append(env_config.temperature_sensor)
        if env_config.humidity_sensor:
            entities_to_track.append(env_config.humidity_sensor)
        if env_config.vpd_sensor:
            entities_to_track.append(env_config.vpd_sensor)

        if entities_to_track and plant.stage_history:
            try:
                # We use a 1-hour interval for long term stats
                stats = await _get_statistics_data(
                    hass, entities_to_track, start_time, end_time, 60
                )
                if stats:
                    for stage in plant.stage_history:
                        stage_name = stage["stage"]
                        s_start = datetime.fromisoformat(stage["start"])
                        s_end = (
                            datetime.fromisoformat(stage["end"])
                            if stage.get("end")
                            else end_time
                        )

                        stage_stats = {
                            "temperature": None,
                            "humidity": None,
                            "vpd": None,
                        }

                        # Filter stats points within the stage window and calculate mean
                        if env_config.temperature_sensor in stats:
                            points = [
                                float(p["s"])
                                for p in stats[env_config.temperature_sensor]
                                if s_start.isoformat() <= p["lu"] <= s_end.isoformat()
                            ]
                            if points:
                                stage_stats["temperature"] = round(
                                    sum(points) / len(points), 2
                                )

                        if env_config.humidity_sensor in stats:
                            points = [
                                float(p["s"])
                                for p in stats[env_config.humidity_sensor]
                                if s_start.isoformat() <= p["lu"] <= s_end.isoformat()
                            ]
                            if points:
                                stage_stats["humidity"] = round(
                                    sum(points) / len(points), 2
                                )

                        if env_config.vpd_sensor in stats:
                            points = [
                                float(p["s"])
                                for p in stats[env_config.vpd_sensor]
                                if s_start.isoformat() <= p["lu"] <= s_end.isoformat()
                            ]
                            if points:
                                stage_stats["vpd"] = round(sum(points) / len(points), 2)

                        data["environmental_averages"][stage_name] = stage_stats

            except HomeAssistantError:
                raise
            except Exception as err:
                _LOGGER.warning("Could not fetch statistics for the report: %s", err)

    return data


async def _aggregate_growspace_data(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, growspace_id: str
) -> dict[str, Any]:
    """Aggregate data for a whole growspace report."""
    growspace = coordinator.get_growspace(growspace_id)
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
            from custom_components.growspace_manager.websocket import (
                _get_statistics_data,
            )

            end_time = datetime.now()
            start_time = end_time - timedelta(days=30)
            if plants:
                first_plant_date = min(
                    [
                        datetime.fromisoformat(p.created_at)
                        for p in plants
                        if p.created_at
                    ]
                    + [end_time]
                )
                start_time = max(start_time, first_plant_date)

            try:
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
            except Exception as err:
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
            plant = coordinator.get_plant(plant_id)
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

    except Exception as err:
        _LOGGER.exception("Error generating grow report for WebSocket")
        connection.send_error(msg["id"], "unknown_error", str(err))


def _export_as_json(data: dict[str, Any], file_path: str) -> None:
    """Export the report data as a JSON file."""
    with Path(file_path).open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _export_as_pdf(data: dict[str, Any], file_path: str) -> None:
    """Generate a PDF report using fpdf2."""
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
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
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
                datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
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
