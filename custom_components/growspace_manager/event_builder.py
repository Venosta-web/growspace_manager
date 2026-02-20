"""Event builder for creating GrowspaceEvent instances.

This module provides a centralized way to build GrowspaceEvent objects
with proper formatting for the logbook.
"""

from __future__ import annotations

from homeassistant.util import dt as dt_util

from .const import CATEGORY_IPM, CATEGORY_TRAINING, CATEGORY_WATERING
from .models import GrowspaceEvent, IPMPreset, Plant


class EventBuilder:
    """Builder for creating formatted GrowspaceEvent instances for the logbook.

    This class provides centralized event creation logic for all event types
    (watering, training, IPM) to ensure consistent formatting and structure
    across the integration.

    All methods return fully configured GrowspaceEvent objects ready to be
    logged to the Home Assistant event bus.
    """

    @staticmethod
    def create_watering_event(
        plant: Plant,
        amount: float,
        preset_name: str | None,
        final_nutrients: dict[str, float],
    ) -> GrowspaceEvent:
        """Create a watering event for the logbook.

        Args:
            plant: The plant that was watered.
            amount: Amount of water in liters.
            preset_name: Optional nutrient preset name.
            final_nutrients: Final nutrient mix applied.

        Returns:
            GrowspaceEvent configured for watering.
        """
        now_iso = dt_util.now().isoformat()
        reasons = EventBuilder._build_watering_reasons(
            plant, amount, preset_name, final_nutrients
        )

        return GrowspaceEvent(
            sensor_type="irrigation",
            growspace_id=plant.growspace_id,
            start_time=now_iso,
            end_time=now_iso,
            duration_sec=0,
            severity=0.0,
            category=CATEGORY_WATERING,
            reasons=reasons,
        )

    @staticmethod
    def _build_watering_reasons(
        plant: Plant,
        amount: float,
        preset_name: str | None,
        final_nutrients: dict[str, float],
    ) -> list[str]:
        """Build the reasons list for a watering event."""
        reasons = []
        reasons.append(f"plant_id:{plant.plant_id}")

        plant_info = f"Plant: {plant.strain}"
        if plant.phenotype:
            plant_info += f" ({plant.phenotype})"
        reasons.append(plant_info)

        reasons.append(f"Watered with {amount}L")
        if preset_name:
            reasons.append(f"Preset: {preset_name}")

        if final_nutrients:
            nutrient_details = []
            for name, conc in final_nutrients.items():
                total_ml = round(amount * conc, 2)
                nutrient_details.append(f"{name}: {conc}ml/L (Total: {total_ml}ml)")
            reasons.append(f"Nutrients: {', '.join(nutrient_details)}")

        return reasons

    @staticmethod
    def create_training_event(
        growspace_id: str,
        technique: str,
        notes: str,
        plant_ids: list[str],
        affected_plants: list[Plant],
        all_growspace_plants: list[Plant],
    ) -> GrowspaceEvent:
        """Create a training event for the logbook.

        Args:
            growspace_id: ID of the growspace.
            technique: Training technique applied.
            notes: Optional user notes.
            plant_ids: List of plant IDs (may be subset).
            affected_plants: Plants affected in this growspace.
            all_growspace_plants: All plants in the growspace.

        Returns:
            GrowspaceEvent configured for training.
        """
        now = dt_util.now().isoformat()
        reasons = EventBuilder._build_training_reasons(
            technique, notes, plant_ids, affected_plants, all_growspace_plants
        )

        return GrowspaceEvent(
            sensor_type=technique,
            growspace_id=growspace_id,
            start_time=now,
            end_time=now,
            duration_sec=0,
            severity=0.5,
            category=CATEGORY_TRAINING,
            reasons=reasons,
        )

    @staticmethod
    def _build_training_reasons(
        technique: str,
        notes: str,
        plant_ids: list[str],
        affected_plants: list[Plant],
        all_growspace_plants: list[Plant],
    ) -> list[str]:
        """Generate reason strings for training events."""
        reasons = [f"plant_id:{p.plant_id}" for p in affected_plants]
        reasons.append(f"Technique: {technique.replace('_', ' ').title()}")

        if notes:
            reasons.append(f"Notes: {notes}")

        # Only add plant names if it's a subset of the growspace
        if plant_ids and len(plant_ids) < len(all_growspace_plants):
            affected_names = [p.strain for p in affected_plants]
            if affected_names:
                reasons.append(f"Plants: {', '.join(affected_names)}")

        return reasons

    @staticmethod
    def create_ipm_event(
        growspace_id: str,
        preset: IPMPreset,
        notes: str | None,
        plant_ids: list[str] | None,
        affected_plants: list[Plant],
        all_growspace_plants: list[Plant],
    ) -> GrowspaceEvent:
        """Create an IPM application event for the logbook.

        Args:
            growspace_id: ID of the growspace.
            preset: IPM preset that was applied.
            notes: Optional user notes.
            plant_ids: List of plant IDs (may be subset).
            affected_plants: Plants affected in this growspace.
            all_growspace_plants: All plants in the growspace.

        Returns:
            GrowspaceEvent configured for IPM application.
        """
        now = dt_util.now().isoformat()
        reasons = EventBuilder._build_ipm_reasons(
            preset, notes, plant_ids, affected_plants, all_growspace_plants
        )

        return GrowspaceEvent(
            sensor_type=f"ipm_{preset.type}",
            growspace_id=growspace_id,
            start_time=now,
            end_time=now,
            duration_sec=0,
            severity=0.5,
            category=CATEGORY_IPM,
            reasons=reasons,
        )

    @staticmethod
    def _build_ipm_reasons(
        preset: IPMPreset,
        notes: str | None,
        plant_ids: list[str] | None,
        affected_plants: list[Plant],
        all_growspace_plants: list[Plant],
    ) -> list[str]:
        """Generate reason strings for IPM events."""
        recipe_str = ", ".join(
            [f"{i['name']} ({i['dose_amount']}{i['dose_unit']})" for i in preset.items]
        )
        reasons = [
            f"IPM Treatment: {preset.name}",
            f"Type: {preset.type}",
            f"Recipe: {recipe_str}",
        ]
        reasons.extend([f"plant_id:{p.plant_id}" for p in affected_plants])

        # Only add plant names if it's a subset of the growspace
        if plant_ids and len(plant_ids) < len(all_growspace_plants):
            affected_names = [p.strain for p in affected_plants]
            if affected_names:
                reasons.append(f"Plants: {', '.join(affected_names)}")

        if notes:
            reasons.append(f"Notes: {notes}")

        return reasons
