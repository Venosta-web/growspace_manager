"""AI Assistant services for Growspace Manager.

This module provides advanced AI-powered features using Home Assistant's
conversation/LLM integration for grow advice, diagnostics, and recommendations.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import conversation
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from ..const import CONF_AI_ENABLED, CONF_ASSISTANT_ID, DOMAIN
from ..coordinator import GrowspaceCoordinator
from ..strain_library import StrainLibrary

_LOGGER = logging.getLogger(__name__)


class GrowAssistant:
    """AI-powered grow assistant for environmental analysis and recommendations."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: GrowspaceCoordinator,
        strain_library: StrainLibrary,
    ):
        """Initialize the grow assistant."""
        self.hass = hass
        self.coordinator = coordinator
        self.strain_library = strain_library

    def _get_ai_settings(self) -> dict[str, Any]:
        """Get and validate AI settings from coordinator options."""
        ai_settings = self.coordinator.options.get("ai_settings", {})

        if not ai_settings.get(CONF_AI_ENABLED):
            raise ServiceValidationError(
                "AI assistant is not enabled. Please enable it in integration settings."
            )

        agent_id = ai_settings.get(CONF_ASSISTANT_ID)
        if not agent_id:
            raise ServiceValidationError(
                "No AI assistant configured. Please select an assistant in integration settings."
            )

        return ai_settings

    def _gather_growspace_data(self, growspace_id: str) -> dict[str, Any]:
        """Gather comprehensive data about a growspace for AI analysis."""
        growspace = self.coordinator.growspaces.get(growspace_id)
        if not growspace:
            raise ServiceValidationError(f"Growspace {growspace_id} not found.")

        # Environment sensor data
        env_config = getattr(growspace, "environment_config", {})
        sensor_data = {}
        sensor_states = {}

        for key in [
            "temperature_sensor",
            "humidity_sensor",
            "vpd_sensor",
            "co2_sensor",
            "light_sensor",
            "circulation_fan",
        ]:
            entity_id = env_config.get(key)
            if entity_id:
                state = self.hass.states.get(entity_id)
                if state and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                    value = state.state
                    unit = state.attributes.get("unit_of_measurement", "")
                    sensor_data[key] = f"{value} {unit}".strip()
                    sensor_states[key] = {
                        "value": value,
                        "unit": unit,
                        "attributes": dict(state.attributes),
                    }

        # Bayesian sensor analysis
        bayesian_data = self._gather_bayesian_sensor_data(growspace_id)

        # Plant data
        plants = self.coordinator.get_growspace_plants(growspace_id)
        plant_summary = self._summarize_plants(plants)

        # Strain analytics
        strain_analytics = self._get_strain_analytics(plants)

        return {
            "growspace": {
                "id": growspace_id,
                "name": growspace.name,
                "size": f"{growspace.rows}x{growspace.plants_per_row}",
                "total_plants": len(plants),
            },
            "environment": {
                "sensors": sensor_data,
                "raw_states": sensor_states,
            },
            "analysis": bayesian_data,
            "plants": plant_summary,
            "strain_analytics": strain_analytics,
        }

    def _gather_bayesian_sensor_data(self, growspace_id: str) -> dict[str, Any]:
        """Gather data from Bayesian environmental sensors."""
        bayesian_data = {
            "stress": {"active": False, "reasons": []},
            "mold_risk": {"active": False, "reasons": []},
            "optimal": {"active": False, "reasons": []},
            "light_schedule": {"correct": False},
        }

        sensor_types = {
            "stress": "plants_under_stress",
            "mold_risk": "high_mold_risk",
            "optimal": "optimal_conditions",
        }

        for key, sensor_suffix in sensor_types.items():
            entity_id = f"binary_sensor.{growspace_id}_{sensor_suffix}"
            state = self.hass.states.get(entity_id)

            if state:
                is_on = state.state == "on"
                bayesian_data[key]["active"] = is_on
                bayesian_data[key]["probability"] = state.attributes.get(
                    "probability", 0
                )
                bayesian_data[key]["reasons"] = state.attributes.get("reasons", [])

        # Light schedule verification
        light_entity_id = f"binary_sensor.{growspace_id}_light_schedule_correct"
        light_state = self.hass.states.get(light_entity_id)
        if light_state:
            bayesian_data["light_schedule"]["correct"] = light_state.state == "on"
            bayesian_data["light_schedule"]["expected"] = light_state.attributes.get(
                "expected_schedule", "Unknown"
            )

        return bayesian_data

    def _summarize_plants(self, plants: list) -> dict[str, Any]:
        """Create a summary of plants in the growspace."""
        if not plants:
            return {"count": 0, "stages": {}, "strains": []}

        stages = {}
        strains = set()

        for plant in plants:
            stage = getattr(plant, "stage", "unknown")
            stages[stage] = stages.get(stage, 0) + 1
            strains.add(plant.strain)

            # Calculate stage durations
            veg_days = self.coordinator.calculate_days_in_stage(plant, "veg")
            flower_days = self.coordinator.calculate_days_in_stage(plant, "flower")

        return {
            "count": len(plants),
            "stages": stages,
            "strains": list(strains),
            "max_veg_days": max(
                (
                    self.coordinator.calculate_days_in_stage(p, "veg")
                    for p in plants
                    if p.veg_start
                ),
                default=0,
            ),
            "max_flower_days": max(
                (
                    self.coordinator.calculate_days_in_stage(p, "flower")
                    for p in plants
                    if p.flower_start
                ),
                default=0,
            ),
        }

    def _get_strain_analytics(self, plants: list) -> dict[str, Any]:
        """Get analytics for strains currently growing."""
        analytics = {}
        all_strains = self.strain_library.get_all()

        for plant in plants:
            strain_name = plant.strain
            if strain_name not in analytics and strain_name in all_strains:
                strain_data = all_strains[strain_name]
                phenotypes = strain_data.get("phenotypes", {})

                # Calculate averages across all phenotypes
                all_harvests = []
                for pheno_data in phenotypes.values():
                    all_harvests.extend(pheno_data.get("harvests", []))

                if all_harvests:
                    avg_veg = sum(h.get("veg_days", 0) for h in all_harvests) / len(
                        all_harvests
                    )
                    avg_flower = sum(
                        h.get("flower_days", 0) for h in all_harvests
                    ) / len(all_harvests)

                    analytics[strain_name] = {
                        "avg_veg_days": round(avg_veg),
                        "avg_flower_days": round(avg_flower),
                        "total_harvests": len(all_harvests),
                        "meta": strain_data.get("meta", {}),
                    }

        return analytics

    def _build_system_prompt(self, context_type: str) -> str:
        """Build the system prompt based on context type."""
        base_prompt = (
            "You are an expert cannabis cultivation advisor with deep knowledge of:\n"
            "- Environmental control (temperature, humidity, VPD, CO2)\n"
            "- Plant health diagnostics and stress identification\n"
            "- Growth stage management (seedling, veg, flower, dry, cure)\n"
            "- Pest and disease prevention\n"
            "- Nutrient management\n"
            "- Light cycle optimization\n"
            "- Harvest timing and curing techniques\n\n"
        )

        context_prompts = {
            "general": base_prompt
            + "Provide practical, actionable advice based on the provided data.",
            "diagnostic": base_prompt
            + "Focus on identifying issues and providing specific solutions. "
            + "Prioritize urgent problems first.",
            "optimization": base_prompt
            + "Focus on optimization opportunities and ways to improve yields. "
            + "Consider both current state and historical data.",
            "planning": base_prompt
            + "Help with grow planning, scheduling, and strain selection. "
            + "Use historical data to inform recommendations.",
        }

        return context_prompts.get(context_type, context_prompts["general"])

    def _format_context_data(self, data: dict[str, Any]) -> str:
        """Format growspace data into a clear context string for the AI."""
        lines = [
            f"GROWSPACE: {data['growspace']['name']} ({data['growspace']['size']})",
            f"TOTAL PLANTS: {data['growspace']['total_plants']}",
            "",
            "CURRENT ENVIRONMENT:",
        ]

        # Add sensor readings
        for sensor, reading in data["environment"]["sensors"].items():
            sensor_name = sensor.replace("_sensor", "").replace("_", " ").title()
            lines.append(f"  {sensor_name}: {reading}")

        lines.append("")

        # Add Bayesian analysis
        analysis = data["analysis"]
        if analysis["stress"]["active"]:
            lines.append("⚠️ STRESS DETECTED:")
            for reason in analysis["stress"]["reasons"]:
                lines.append(f"  - {reason}")
            lines.append("")

        if analysis["mold_risk"]["active"]:
            lines.append("🍄 MOLD RISK DETECTED:")
            for reason in analysis["mold_risk"]["reasons"]:
                lines.append(f"  - {reason}")
            lines.append("")

        if analysis["optimal"]["active"]:
            lines.append("✅ Optimal conditions achieved")
            lines.append("")

        # Add plant summary
        plants = data["plants"]
        if plants["count"] > 0:
            lines.append("PLANTS:")
            lines.append(f"  Total: {plants['count']}")
            lines.append(f"  Strains: {', '.join(plants['strains'])}")
            if plants["max_veg_days"] > 0:
                lines.append(f"  Max Veg: Day {plants['max_veg_days']}")
            if plants["max_flower_days"] > 0:
                lines.append(
                    f"  Max Flower: Day {plants['max_flower_days']} (Week {plants['max_flower_days'] // 7})"
                )
            lines.append("")

        # Add strain analytics if available
        if data["strain_analytics"]:
            lines.append("STRAIN HISTORY:")
            for strain, stats in data["strain_analytics"].items():
                lines.append(
                    f"  {strain}: Avg {stats['avg_veg_days']}d veg, "
                    f"{stats['avg_flower_days']}d flower ({stats['total_harvests']} harvests)"
                )

        return "\n".join(lines)

    async def get_grow_advice(
        self,
        growspace_id: str,
        user_query: str | None = None,
        context_type: str = "general",
    ) -> str:
        """Get AI-powered grow advice for a growspace.

        Args:
            growspace_id: The ID of the growspace to analyze
            user_query: Optional specific question from the user
            context_type: Type of advice context (general, diagnostic, optimization, planning)

        Returns:
            AI-generated advice string
        """
        ai_settings = self._get_ai_settings()
        agent_id = ai_settings.get(CONF_ASSISTANT_ID)

        # Gather all relevant data
        data = self._gather_growspace_data(growspace_id)
        context = self._format_context_data(data)

        # Build the prompt
        system_prompt = self._build_system_prompt(context_type)
        user_prompt = user_query or "Provide a status update and recommendations."

        full_prompt = f"{system_prompt}\n\n{context}\n\nUser Question: {user_prompt}"

        _LOGGER.debug("Sending prompt to AI assistant (length: %d)", len(full_prompt))

        # Call the conversation API
        try:
            result = await conversation.async_converse(
                self.hass,
                text=full_prompt,
                conversation_id=None,
                context=Context(),
                agent_id=agent_id,
            )

            if (
                result
                and result.response
                and result.response.speech
                and result.response.speech.get("plain")
            ):
                response = result.response.speech["plain"]["speech"]
                _LOGGER.info(
                    "AI assistant provided advice for growspace %s", growspace_id
                )
                return response
            else:
                raise ServiceValidationError(
                    "AI assistant returned an empty response"
                )

        except Exception as err:
            _LOGGER.error("Error getting AI advice: %s", err)
            raise ServiceValidationError(f"Failed to get AI advice: {str(err)}")


async def handle_ask_grow_advice(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> dict:
    """Handle the ask_grow_advice service call.

    This service provides AI-powered analysis and recommendations for a growspace.
    """
    growspace_id = call.data["growspace_id"]
    user_query = call.data.get("user_query")
    context_type = call.data.get("context_type", "general")

    assistant = GrowAssistant(hass, coordinator, strain_library)
    response = await assistant.get_grow_advice(growspace_id, user_query, context_type)

    return {"response": response}


async def handle_analyze_all_growspaces(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> dict:
    """Analyze all growspaces and provide a comprehensive report.

    This service scans all active growspaces and provides prioritized recommendations.
    """
    assistant = GrowAssistant(hass, coordinator, strain_library)
    ai_settings = assistant._get_ai_settings()
    agent_id = ai_settings.get(CONF_ASSISTANT_ID)

    # Gather data for all growspaces
    all_data = []
    issues_found = []

    for growspace_id, growspace in coordinator.growspaces.items():
        try:
            data = assistant._gather_growspace_data(growspace_id)
            all_data.append(data)

            # Flag issues
            if data["analysis"]["stress"]["active"]:
                issues_found.append(
                    f"{data['growspace']['name']}: Stress detected - "
                    f"{', '.join(data['analysis']['stress']['reasons'][:2])}"
                )
            if data["analysis"]["mold_risk"]["active"]:
                issues_found.append(
                    f"{data['growspace']['name']}: Mold risk - "
                    f"{', '.join(data['analysis']['mold_risk']['reasons'][:2])}"
                )
        except Exception as err:
            _LOGGER.warning("Error analyzing growspace %s: %s", growspace_id, err)

    # Build comprehensive summary
    summary_lines = ["FACILITY OVERVIEW:", f"Total Growspaces: {len(all_data)}", ""]

    if issues_found:
        summary_lines.append("⚠️ ISSUES REQUIRING ATTENTION:")
        for issue in issues_found:
            summary_lines.append(f"  - {issue}")
        summary_lines.append("")

    for data in all_data:
        summary_lines.append(f"• {data['growspace']['name']}:")
        summary_lines.append(f"  Plants: {data['plants']['count']}")
        if data["analysis"]["optimal"]["active"]:
            summary_lines.append("  Status: ✅ Optimal")
        elif data["analysis"]["stress"]["active"] or data["analysis"]["mold_risk"][
            "active"
        ]:
            summary_lines.append("  Status: ⚠️ Needs Attention")
        else:
            summary_lines.append("  Status: 📊 Normal")
        summary_lines.append("")

    context = "\n".join(summary_lines)

    # Ask AI for comprehensive analysis
    prompt = (
        "You are analyzing an entire cannabis cultivation facility. "
        "Provide a prioritized action plan focusing on:\n"
        "1. Urgent issues that need immediate attention\n"
        "2. Optimization opportunities\n"
        "3. Preventive measures\n"
        "4. Schedule recommendations\n\n"
        f"{context}\n\n"
        "Provide a structured report with specific, actionable recommendations."
    )

    try:
        result = await conversation.async_converse(
            hass,
            text=prompt,
            conversation_id=None,
            context=Context(),
            agent_id=agent_id,
        )

        if (
            result
            and result.response
            and result.response.speech
            and result.response.speech.get("plain")
        ):
            response = result.response.speech["plain"]["speech"]
            return {
                "response": response,
                "issues_count": len(issues_found),
                "growspaces_analyzed": len(all_data),
            }
        else:
            raise ServiceValidationError("AI assistant returned an empty response")

    except Exception as err:
        _LOGGER.error("Error analyzing all growspaces: %s", err)
        raise ServiceValidationError(f"Failed to analyze growspaces: {str(err)}")


async def handle_strain_recommendation(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> dict:
    """Recommend strains based on user preferences and historical data.

    This service analyzes the strain library and suggests strains for the next grow.
    """
    assistant = GrowAssistant(hass, coordinator, strain_library)
    ai_settings = assistant._get_ai_settings()
    agent_id = ai_settings.get(CONF_ASSISTANT_ID)

    preferences = call.data.get("preferences", {})
    growspace_id = call.data.get("growspace_id")
    user_query = call.data.get("user_query")

    # Get strain library data
    all_strains = strain_library.get_all()

    # Build strain summary
    strain_lines = ["AVAILABLE STRAINS:"]
    for strain_name, strain_data in all_strains.items():
        meta = strain_data.get("meta", {})
        phenotypes = strain_data.get("phenotypes", {})

        # Calculate average performance
        all_harvests = []
        for pheno_data in phenotypes.values():
            all_harvests.extend(pheno_data.get("harvests", []))

        if all_harvests:
            avg_veg = sum(h.get("veg_days", 0) for h in all_harvests) / len(
                all_harvests
            )
            avg_flower = sum(h.get("flower_days", 0) for h in all_harvests) / len(
                all_harvests
            )
            total_days = avg_veg + avg_flower

            strain_lines.append(
                f"\n{strain_name}:"
                f"\n  Type: {meta.get('type', 'Unknown')}"
                f"\n  Avg Total Time: {round(total_days)} days ({round(avg_veg)}d veg + {round(avg_flower)}d flower)"
                f"\n  Harvests: {len(all_harvests)}"
                f"\n  Breeder: {meta.get('breeder', 'Unknown')}"
            )

    context = "\n".join(strain_lines)

    # Build preferences string
    pref_str = ""
    if preferences:
        pref_lines = ["USER PREFERENCES (Structured):"]
        for key, value in preferences.items():
            pref_lines.append(f"  {key}: {value}")
        pref_str = "\n".join(pref_lines)

    # Build User Query String
    query_str = ""
    if user_query:
        query_str = f"\nUSER REQUEST: {user_query}" # <--- ADD THIS

    # Include growspace context if provided
    growspace_context = ""
    # ... (keep growspace logic) ...

    prompt = (
        "You are a cannabis cultivation expert helping select strains for the next grow. "
        "Based on historical performance data and user preferences, recommend the best strains.\n\n"
        f"{context}\n\n"
        f"{pref_str}\n"
        f"{query_str}\n"  # <--- INJECT IT HERE
        f"{growspace_context}\n\n"
        "Provide:\n"
        "1. Top 3 strain recommendations with reasoning\n"
        "2. Expected timeline for each\n"
        "3. Any special considerations\n"
        "4. Phenotype recommendations if applicable"
    )

    try:
        result = await conversation.async_converse(
            hass,
            text=prompt,
            conversation_id=None,
            context=Context(),
            agent_id=agent_id,
        )

        if (
            result
            and result.response
            and result.response.speech
            and result.response.speech.get("plain")
        ):
            response = result.response.speech["plain"]["speech"]
            return {"response": response, "strains_analyzed": len(all_strains)}
        else:
            raise ServiceValidationError("AI assistant returned an empty response")

    except Exception as err:
        _LOGGER.error("Error getting strain recommendations: %s", err)
        raise ServiceValidationError(f"Failed to get recommendations: {str(err)}")