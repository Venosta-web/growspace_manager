"""AI Assistant services for Growspace Manager.

This module provides advanced AI-powered features using Home Assistant's
conversation/LLM integration for grow advice, diagnostics, and recommendations.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import (
    CONF_AI_ENABLED,
    CONF_ASSISTANT_ID,
    GrowspaceService,
)
from custom_components.growspace_manager.domain import resolve_lifetime_stage_days
from custom_components.growspace_manager.domain.moisture_band import (
    interpret_moisture_reading,
)
from custom_components.growspace_manager.schemas import (
    ANALYZE_ALL_GROWSPACES_SCHEMA,
    ASK_GROW_ADVICE_SCHEMA,
    STRAIN_RECOMMENDATION_SCHEMA,
)
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Context, HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from ._definition import ServiceDefinition
from .strain_library import StrainLibrary

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


class GrowAssistant:
    """AI-powered grow assistant for environmental analysis and recommendations."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: GrowspaceCoordinator,
        strain_library: StrainLibrary,
    ) -> None:
        """Initialize the grow assistant."""
        self.hass = hass
        self.coordinator = coordinator
        self.strain_library = strain_library

    def get_ai_settings(self) -> dict[str, Any] | None:
        """Get and validate AI settings from coordinator options."""
        ai_settings = self.coordinator.options.get("ai_settings", {})
        _LOGGER.debug("Retrieved AI settings from coordinator: %s", ai_settings)

        if not ai_settings.get(CONF_AI_ENABLED):
            _LOGGER.debug("AI features are disabled in settings")
            return None

        agent_id = ai_settings.get(CONF_ASSISTANT_ID)
        if not agent_id:
            _LOGGER.warning("AI enabled but no assistant ID configured")
            return None

        return ai_settings  # type: ignore[no-any-return]

    def gather_growspace_data(self, growspace_id: str) -> dict[str, Any]:
        """Gather comprehensive data about a growspace for AI analysis."""
        growspace = self.coordinator._data_repository.get_growspace(growspace_id)
        if not growspace:
            raise ServiceValidationError(f"Growspace {growspace_id} not found.")

        # Environment sensor data
        env_config = getattr(growspace, "environment_config", None)
        sensor_data = {}
        sensor_states = {}
        moisture_interpretation: dict[str, Any] | None = None

        if env_config:
            # Map of context key -> attribute name in EnvironmentConfig
            # Note: 'circulation_fan' became 'circulation_fan_entity' in the recent refactor
            sensor_map = [
                ("temperature_sensor", "temperature_sensor"),
                ("humidity_sensor", "humidity_sensor"),
                ("vpd_sensor", "vpd_sensor"),
                ("co2_sensor", "co2_sensor"),
                ("light_sensor", "light_sensor"),
                ("circulation_fan", "circulation_fan_entity"),
            ]

            for context_key, attr_name in sensor_map:
                # Robustly handle both legacy dict and new dataclass
                if isinstance(env_config, dict):
                    entity_id = env_config.get(attr_name) or env_config.get(context_key)
                else:
                    entity_id = getattr(env_config, attr_name, None)

                if entity_id:
                    state = self.hass.states.get(entity_id)
                    if state and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                        value = state.state
                        unit = state.attributes.get("unit_of_measurement", "")
                        sensor_data[context_key] = f"{value} {unit}".strip()
                        sensor_states[context_key] = {
                            "value": value,
                            "unit": unit,
                            "attributes": dict(state.attributes),
                        }

            moisture_entity_id = (
                env_config.get("soil_moisture_sensor")
                if isinstance(env_config, dict)
                else getattr(env_config, "soil_moisture_sensor", None)
            )
            if moisture_entity_id:
                moisture_state = self.hass.states.get(moisture_entity_id)
                if moisture_state and moisture_state.state not in (
                    STATE_UNAVAILABLE,
                    STATE_UNKNOWN,
                ):
                    unit = moisture_state.attributes.get("unit_of_measurement")
                    minimum = (
                        env_config.get("soil_moisture_min")
                        if isinstance(env_config, dict)
                        else getattr(env_config, "soil_moisture_min", None)
                    )
                    maximum = (
                        env_config.get("soil_moisture_max")
                        if isinstance(env_config, dict)
                        else getattr(env_config, "soil_moisture_max", None)
                    )
                    interpretation = interpret_moisture_reading(
                        moisture_state.state, unit, minimum, maximum
                    )
                    if interpretation is not None:
                        moisture_interpretation = interpretation.to_dict()

        # Bayesian sensor analysis
        bayesian_data = self._gather_bayesian_sensor_data(growspace_id)

        # Plant data
        plants = self.coordinator._data_repository.get_growspace_plants(growspace_id)
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
                "soil_moisture": moisture_interpretation,
            },
            "analysis": bayesian_data,
            "plants": plant_summary,
            "strain_analytics": strain_analytics,
        }

    def _gather_bayesian_sensor_data(self, growspace_id: str) -> dict[str, Any]:
        """Gather data from Bayesian environmental sensors."""
        bayesian_data: dict[str, Any] = {
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

    def _summarize_plants(self, plants: list[Any]) -> dict[str, Any]:
        """Create a summary of plants in the growspace."""
        if not plants:
            return {"count": 0, "stages": {}, "strains": []}

        stages: dict[str, int] = {}
        strains = set()
        observed_on = dt_util.now().date()
        lifetime_days = [
            resolve_lifetime_stage_days(plant, observed_on=observed_on)
            for plant in plants
        ]

        for plant in plants:
            stage = getattr(plant, "stage", "unknown")
            stages[stage] = stages.get(stage, 0) + 1
            strains.add(plant.strain)

        return {
            "count": len(plants),
            "stages": stages,
            "strains": list(strains),
            "max_veg_days": max((days.veg for days in lifetime_days), default=0),
            "max_flower_days": max((days.flower for days in lifetime_days), default=0),
        }

    def _get_strain_analytics(self, plants: list[Any]) -> dict[str, Any]:
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

    def _get_strain_specific_context(self, plants: list[Any]) -> str:
        """Build strain-specific context from breeder notes for AI prompts.

        Extracts breeder notes, flowering time preferences, and genetic lineage
        for active strains to give the AI more targeted cultivation advice.
        """
        if not plants:
            return ""

        all_strains = self.strain_library.get_all()
        contexts = []
        seen_strains: set[str] = set()

        for plant in plants:
            strain_name = plant.strain
            if strain_name in seen_strains or strain_name not in all_strains:
                continue
            seen_strains.add(strain_name)

            strain_data = all_strains[strain_name]
            context = self._build_single_strain_context(strain_name, strain_data)
            if context:
                contexts.append(context)

        return "\n".join(contexts) if contexts else ""

    def _build_single_strain_context(
        self, strain_name: str, strain_data: dict[str, Any]
    ) -> str | None:
        """Build context string for a single strain."""
        meta = strain_data.get("meta", {})
        phenotypes = strain_data.get("phenotypes", {})

        lines = [f"**{strain_name}**:"]

        if breeder_notes := meta.get("breeder_notes"):
            lines.append(f"  Breeder Notes: {breeder_notes}")

        flower_min = meta.get("flowering_days_min")
        flower_max = meta.get("flowering_days_max")
        if flower_min and flower_max:
            lines.append(f"  Expected Flowering: {flower_min}-{flower_max} days")

        if temp_pref := meta.get("ideal_temp_range"):
            lines.append(f"  Ideal Temp: {temp_pref}")
        if humidity_pref := meta.get("ideal_humidity_range"):
            lines.append(f"  Ideal Humidity: {humidity_pref}")

        if lineage := meta.get("lineage"):
            lines.append(f"  Lineage: {lineage}")

        for pheno_name, pheno_data in phenotypes.items():
            if pheno_notes := pheno_data.get("notes"):
                # Truncate long notes
                display_notes = (
                    f"{pheno_notes[:100]}..." if len(pheno_notes) > 100 else pheno_notes
                )
                lines.append(f"  Pheno '{pheno_name}': {display_notes}")

        return "\n".join(lines) if len(lines) > 1 else None

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
        lines.extend(self._format_sensor_data(data["environment"]["sensors"]))
        if moisture := data["environment"].get("soil_moisture"):
            lines.extend(self._format_moisture_data(moisture))
        lines.append("")

        # Add Bayesian analysis
        lines.extend(self._format_analysis_data(data["analysis"]))

        # Add plant summary
        lines.extend(self._format_plant_data(data["plants"]))

        # Add strain-specific context (breeder notes, preferences)
        if data["plants"]["count"] > 0:
            plants = self.coordinator._data_repository.get_growspace_plants(
                data["growspace"]["id"]
            )
            strain_context = self._get_strain_specific_context(plants)
            if strain_context:
                lines.append("STRAIN-SPECIFIC GUIDANCE:")
                lines.append(strain_context)
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

    def _format_sensor_data(self, sensors: dict[str, Any]) -> list[str]:
        """Format sensor data."""
        lines = []
        for sensor, reading in sensors.items():
            sensor_name = sensor.replace("_sensor", "").replace("_", " ").title()
            lines.append(f"  {sensor_name}: {reading}")
        return lines

    def _format_moisture_data(self, moisture: dict[str, Any]) -> list[str]:
        """Format the canonical Acceptable Moisture Band interpretation."""
        reading = float(moisture["reading"])
        band = moisture["band"]
        minimum = float(band["min"])
        maximum = float(band["max"])
        source = "custom" if band["is_custom"] else "inherited default"
        classification = moisture["classification"]

        lines = [
            "  Soil Moisture:",
            f"    Raw reading: {reading:g}%",
            f"    Effective Acceptable Moisture Band: {minimum:g}–{maximum:g}% ({source}, inclusive)",
        ]
        if classification == "too_dry":
            lines.extend(
                (
                    "    Classification: below the acceptable band (too dry)",
                    f"    Interpretation: {reading:g}% is below the effective minimum of {minimum:g}%.",
                )
            )
        elif classification == "too_wet":
            lines.extend(
                (
                    "    Classification: above the acceptable band (too wet)",
                    f"    Interpretation: {reading:g}% is above the effective maximum of {maximum:g}%.",
                )
            )
        else:
            lines.extend(
                (
                    "    Classification: within the acceptable band",
                    "    Interpretation: This reading is inside the inclusive band. "
                    "The absolute reading alone is not evidence of overwatering or underwatering.",
                )
            )
        return lines

    def _format_analysis_data(self, analysis: dict[str, Any]) -> list[str]:
        """Format analysis data."""
        lines = []
        if analysis["stress"]["active"]:
            lines.append("⚠️ STRESS DETECTED:")
            lines.extend(f"  - {reason}" for reason in analysis["stress"]["reasons"])
            lines.append("")

        if analysis["mold_risk"]["active"]:
            lines.append("🍄 MOLD RISK DETECTED:")
            lines.extend(f"  - {reason}" for reason in analysis["mold_risk"]["reasons"])
            lines.append("")

        if analysis["optimal"]["active"]:
            lines.append("✅ Optimal conditions achieved")
            lines.append("")
        return lines

    def _format_plant_data(self, plants: dict[str, Any]) -> list[str]:
        """Format plant data."""
        lines = []
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
        return lines

    async def generate_alert_message(
        self, growspace_id: str, risk_type: str, reasons: list[str]
    ) -> str:
        """Generate a concise, urgent alert message using the AI."""
        # Setup minimal context for speed and clarity
        reasons_str = ", ".join(reasons)
        user_query = (
            f"URGENT: {risk_type} risk detected due to: {reasons_str}. "
            "Provide ONE clear, actionable recommendation to fix this immediately."
        )

        return await self.get_grow_advice(
            growspace_id=growspace_id,
            user_query=user_query,
            context_type="diagnostic",
            max_length=150,  # Keep it short for notifications
        )

    async def get_grow_advice(
        self,
        growspace_id: str,
        user_query: str | None = None,
        context_type: str = "general",
        max_length: int | None = None,
    ) -> str:
        """Get AI-powered grow advice for a growspace.

        Args:
            growspace_id: The ID of the growspace to analyze
            user_query: Optional specific question from the user
            context_type: Type of advice context (general, diagnostic, optimization, planning)
            max_length: Optional maximum length for the response

        Returns:
            AI-generated advice string
        """
        ai_settings = self.get_ai_settings()
        self._validate_ai_settings(ai_settings)

        if ai_settings is None:
            return "AI settings not configured."
        agent_id = ai_settings.get(CONF_ASSISTANT_ID)
        if not agent_id:
            return "AI Assistant ID not configured."

        if max_length is None:
            max_length = (
                ai_settings.get("max_response_length", 250) if ai_settings else 250
            )

        # Gather all relevant data
        data = self.gather_growspace_data(growspace_id)
        context = self._format_context_data(data)

        # Build the prompt
        system_prompt = self._build_system_prompt(context_type)
        user_prompt = user_query or "Provide a status update and recommendations."

        # Add length constraint to prompt if specified
        length_instruction = ""
        if max_length:
            length_instruction = f"\n\nIMPORTANT: Keep your response concise and under {max_length} characters."

        full_prompt = f"{system_prompt}\n\n{context}\n\nUser Question: {user_prompt}{length_instruction}"

        _LOGGER.debug("Sending prompt to AI assistant (length: %d)", len(full_prompt))

        # Call the conversation API
        try:
            return await self._execute_conversation(
                full_prompt, agent_id, max_length, growspace_id
            )

        except ServiceValidationError:
            raise
        except Exception as err:
            _LOGGER.error("Error getting AI advice: %s", err)
            if any(
                m in str(err)
                for m in (
                    "429",
                    "Too Many Requests",
                    "RESOURCE_EXHAUSTED",
                    "resource_exhausted",
                )
            ):
                raise ServiceValidationError("rate_limited") from err
            # Fallback to context if AI fails
            return f"AI Assistant Error: {err}\n\nRaw Data:\n\n{context}"

    def _validate_ai_settings(self, ai_settings: dict[str, Any] | None) -> None:
        """Validate AI settings and raise specific errors if invalid."""
        if not ai_settings:
            # Check raw options to give better feedback
            raw_settings = self.coordinator.options.get("ai_settings", {})
            if not raw_settings.get(CONF_AI_ENABLED):
                raise ServiceValidationError(
                    "AI assistant is not enabled. Please go to the Growspace Manager integration settings to enable it."
                )
            if not raw_settings.get(CONF_ASSISTANT_ID):
                raise ServiceValidationError(
                    "AI assistant enabled but no assistant ID selected. Please configure an assistant in settings."
                )
            # Fallback
            raise ServiceValidationError("AI settings are invalid or incomplete.")

    async def _execute_conversation(
        self, full_prompt: str, agent_id: str, max_length: int | None, growspace_id: str
    ) -> str:
        """Execute the conversation and process the response."""
        from homeassistant.components import conversation  # noqa: PLC0415

        if not agent_id:
            # Should be caught above, but double check
            raise ServiceValidationError(
                "AI assistant is not enabled. Please go to the Growspace Manager integration settings to enable it."
            )

        result = await conversation.async_converse(
            self.hass,
            text=full_prompt,
            conversation_id=None,
            context=Context(),
            agent_id=agent_id,
        )

        if result and result.response:
            speech_text = (
                result.response.speech.get("plain", {}).get("speech", "")
                if result.response.speech
                else ""
            )
            err_code = getattr(result.response, "error_code", "") or ""
            if any(
                m in speech_text or m.lower() in err_code.lower()
                for m in (
                    "429",
                    "Too Many Requests",
                    "RESOURCE_EXHAUSTED",
                    "resource_exhausted",
                )
            ):
                raise ServiceValidationError("rate_limited")

            if speech_text:
                response = speech_text
                if max_length and len(response) > max_length:
                    response = response[:max_length].rsplit(" ", 1)[0] + "..."
                _LOGGER.info(
                    "AI assistant provided advice for growspace %s", growspace_id
                )
                return response

        raise ServiceValidationError("AI assistant returned an empty response")


async def handle_ask_grow_advice(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> dict[str, Any]:
    """Handle the ask_grow_advice service call.

    This service provides AI-powered analysis and recommendations for a growspace.
    """
    growspace_id = call.data["growspace_id"]
    user_query = call.data.get("user_query")
    context_type = call.data.get("context_type", "general")
    max_length = call.data.get("max_length")

    assistant = GrowAssistant(hass, coordinator, strain_library)
    response = await assistant.get_grow_advice(
        growspace_id, user_query, context_type, max_length
    )

    return {"response": response}


async def handle_analyze_all_growspaces(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> dict[str, Any]:
    """Analyze all growspaces and provide a comprehensive report.

    This service scans all active growspaces and provides prioritized recommendations.
    """
    from homeassistant.components import conversation  # noqa: PLC0415

    assistant = GrowAssistant(hass, coordinator, strain_library)
    ai_settings = assistant.get_ai_settings()
    agent_id = None
    if ai_settings:
        agent_id = ai_settings.get(CONF_ASSISTANT_ID)

    max_length = call.data.get("max_length")

    if max_length is None:
        max_length = ai_settings.get("max_response_length", 250) if ai_settings else 250

    # Gather data for all growspaces
    all_data = []
    issues_found = []

    for growspace_id in (
        gs.id for gs in coordinator._data_repository.get_all_growspaces()
    ):
        try:
            data = assistant.gather_growspace_data(growspace_id)
            all_data.append(data)
            issues_found.extend(_analyze_growspace_issues(data))
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Error analyzing growspace %s: %s", growspace_id, err)

    # Build comprehensive summary
    context = _build_facility_summary(all_data, issues_found)

    # Ask AI for comprehensive analysis
    length_instruction = ""
    if max_length:
        length_instruction = f"\n\nIMPORTANT: Keep your response concise and under {max_length} characters."

    prompt = (
        "You are analyzing an entire cannabis cultivation facility. "
        "Provide a prioritized action plan focusing on:\n"
        "1. Urgent issues that need immediate attention\n"
        "2. Optimization opportunities\n"
        "3. Preventive measures\n"
        "4. Schedule recommendations\n\n"
        f"{context}\n\n"
        f"Provide a structured report with specific, actionable recommendations.{length_instruction}"
    )

    analysis_result = None
    try:
        if not agent_id:
            _LOGGER.info("AI assistant not configured, returning summary report")
            return {
                "response": f"AI Assistant not configured. Summary Report:\n\n{context}",
                "issues_count": len(issues_found),
                "growspaces_analyzed": len(all_data),
            }

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

            # Enforce max length truncation if specified
            if max_length and len(response) > max_length:
                response = response[:max_length].rsplit(" ", 1)[0] + "..."

            analysis_result = {
                "response": response,
                "issues_count": len(issues_found),
                "growspaces_analyzed": len(all_data),
            }

    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Error analyzing all growspaces: %s", err)
        # Fallback to summary
        return {
            "response": f"Error analyzing growspaces: {err}\n\nSummary Report:\n\n{context}",
            "issues_count": len(issues_found),
            "growspaces_analyzed": len(all_data),
        }

    if analysis_result:
        return analysis_result

    return {
        "response": f"Error analyzing growspaces: AI assistant returned an empty response. Summary Report:\n\n{context}",
        "issues_count": len(issues_found),
        "growspaces_analyzed": len(all_data),
    }


def _analyze_growspace_issues(data: dict[str, Any]) -> list[str]:
    """Analyze a single growspace for issues."""
    issues = []
    if data["analysis"]["stress"]["active"]:
        issues.append(
            f"{data['growspace']['name']}: Stress detected - "
            f"{', '.join(data['analysis']['stress']['reasons'][:2])}"
        )
    if data["analysis"]["mold_risk"]["active"]:
        issues.append(
            f"{data['growspace']['name']}: Mold risk - "
            f"{', '.join(data['analysis']['mold_risk']['reasons'][:2])}"
        )
    return issues


def _build_facility_summary(
    all_data: list[dict[str, Any]], issues_found: list[str]
) -> str:
    """Build a text summary of the facility status."""
    summary_lines = ["FACILITY OVERVIEW:", f"Total Growspaces: {len(all_data)}", ""]

    if issues_found:
        summary_lines.append("⚠️ ISSUES REQUIRING ATTENTION:")
        summary_lines.extend(f"  - {issue}" for issue in issues_found)
        summary_lines.append("")

    for data in all_data:
        summary_lines.append(f"• {data['growspace']['name']}:")
        summary_lines.append(f"  Plants: {data['plants']['count']}")
        if data["analysis"]["optimal"]["active"]:
            summary_lines.append("  Status: ✅ Optimal")
        elif (
            data["analysis"]["stress"]["active"]
            or data["analysis"]["mold_risk"]["active"]
        ):
            summary_lines.append("  Status: ⚠️ Needs Attention")
        else:
            summary_lines.append("  Status: 📊 Normal")
        summary_lines.append("")

    return "\n".join(summary_lines)


async def handle_strain_recommendation(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> dict[str, Any]:
    """Recommend strains based on user preferences and historical data.

    This service analyzes the strain library and suggests strains for the next grow.
    """
    from homeassistant.components import conversation  # noqa: PLC0415

    assistant = GrowAssistant(hass, coordinator, strain_library)
    ai_settings = assistant.get_ai_settings()
    agent_id = None
    if ai_settings:
        agent_id = ai_settings.get(CONF_ASSISTANT_ID)

    max_length = call.data.get("max_length")

    if max_length is None:
        max_length = ai_settings.get("max_response_length", 250) if ai_settings else 250

    preferences = call.data.get("preferences", {})
    growspace_id = call.data.get("growspace_id")
    user_query = call.data.get("user_query")

    # Get strain library data
    all_strains = strain_library.get_all()

    # Build strain summary
    context = _build_strain_context(all_strains)

    # Include growspace context if provided
    growspace_context = ""
    if growspace_id:
        try:
            gs_data = assistant.gather_growspace_data(growspace_id)
            growspace_context = f"\nTARGET GROWSPACE: {gs_data['growspace']['name']} ({gs_data['growspace']['size']})"
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "Failed to gather growspace data for strain recommendation for growspace %s: %s",
                growspace_id,
                e,
            )

    # Build prompt
    prompt = _build_recommendation_prompt(
        context, preferences, user_query, growspace_context, max_length
    )

    recommendation_result = None
    try:
        if not agent_id:
            _LOGGER.info("AI assistant not configured, returning strain context")
            return {
                "response": f"AI Assistant not configured. Strain Data:\n\n{context}",
                "strains_analyzed": len(all_strains),
            }

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

            # Enforce max length truncation if specified
            if max_length and len(response) > max_length:
                response = response[:max_length].rsplit(" ", 1)[0] + "..."

            recommendation_result = {
                "response": response,
                "strains_analyzed": len(all_strains),
            }

    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Error getting strain recommendation: %s", err)
        return {
            "response": f"Error getting strain recommendation: {err}\n\nStrain Data:\n\n{context}",
            "strains_analyzed": len(all_strains),
        }

    if recommendation_result:
        return recommendation_result

    return {
        "response": "AI assistant returned an empty response. Strain Data:\n\n"
        + context,
        "strains_analyzed": len(all_strains),
    }


def _build_recommendation_prompt(
    context: str,
    preferences: dict[str, Any],
    user_query: str | None,
    growspace_context: str,
    max_length: int | None,
) -> str:
    """Build the prompt for strain recommendations."""
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
        query_str = f"\nUSER REQUEST: {user_query}"

    length_instruction = ""
    if max_length:
        length_instruction = f"\n\nIMPORTANT: Keep your response concise and under {max_length} characters."

    return (
        "You are a cannabis cultivation expert helping select strains for the next grow. "
        "Based on historical performance data and user preferences, recommend the best strains.\n\n"
        f"{context}\n\n"
        f"{pref_str}\n"
        f"{query_str}\n"
        f"{growspace_context}\n\n"
        "Provide:\n"
        "1. Top 3 strain recommendations with reasoning\n"
        "2. Expected timeline for each\n"
        "3. Any special considerations\n"
        "4. Phenotype recommendations if applicable"
        f"{length_instruction}"
    )


def _build_strain_context(all_strains: dict[str, Any]) -> str:
    """Build a context string from strain library data."""
    strain_lines = ["AVAILABLE STRAINS:"]
    for strain_name, strain_data in all_strains.items():
        strain_info = _build_strain_performance_summary(strain_name, strain_data)
        strain_lines.append(strain_info)

    return "\n".join(strain_lines)


def _build_strain_performance_summary(
    strain_name: str, strain_data: dict[str, Any]
) -> str:
    """Build a summary string for a strain's performance."""
    meta = strain_data.get("meta", {})
    phenotypes = strain_data.get("phenotypes", {})

    # Calculate average performance
    all_harvests = []
    est_flower_min = None
    est_flower_max = None
    description = meta.get("description", "")

    for pheno_data in phenotypes.values():
        all_harvests.extend(pheno_data.get("harvests", []))
        # Capture estimates from phenotypes if available
        if not est_flower_min and pheno_data.get("flower_days_min"):
            est_flower_min = pheno_data["flower_days_min"]
        if not est_flower_max and pheno_data.get("flower_days_max"):
            est_flower_max = pheno_data["flower_days_max"]
        if not description and pheno_data.get("description"):
            description = pheno_data["description"]

    # Start building strain info string
    strain_info = f"\n{strain_name}:"
    strain_info += f"\n  Type: {meta.get('type', 'Unknown')}"
    strain_info += f"\n  Breeder: {meta.get('breeder', 'Unknown')}"
    if description:
        strain_info += (
            f"\n  Description: {description[:100]}..."  # Truncate for token limit
        )

    # Add Performance OR Estimates
    if all_harvests:
        avg_veg = sum(h.get("veg_days", 0) for h in all_harvests) / len(all_harvests)
        avg_flower = sum(h.get("flower_days", 0) for h in all_harvests) / len(
            all_harvests
        )
        total_days = avg_veg + avg_flower

        strain_info += (
            f"\n  Avg Total Time: {round(total_days)} days "
            f"({round(avg_veg)}d veg + {round(avg_flower)}d flower)"
            f"\n  Harvests Recorded: {len(all_harvests)}"
        )
    # No history, use estimates if available
    elif est_flower_min or est_flower_max:
        strain_info += (
            f"\n  Est. Flowering: {est_flower_min or '?'}-{est_flower_max or '?'} days"
        )
    else:
        strain_info += "\n  History: No harvests recorded yet"

    return strain_info


SERVICES = [
    ServiceDefinition(
        GrowspaceService.ASK_GROW_ADVICE,
        handle_ask_grow_advice,
        ASK_GROW_ADVICE_SCHEMA,
        needs_strain_lib=True,
        supports_response=SupportsResponse.ONLY,
    ),
    ServiceDefinition(
        GrowspaceService.STRAIN_RECOMMENDATION,
        handle_strain_recommendation,
        STRAIN_RECOMMENDATION_SCHEMA,
        needs_strain_lib=True,
        supports_response=SupportsResponse.ONLY,
    ),
    ServiceDefinition(
        GrowspaceService.ANALYZE_ALL_GROWSPACES,
        handle_analyze_all_growspaces,
        ANALYZE_ALL_GROWSPACES_SCHEMA,
        needs_strain_lib=True,
        supports_response=SupportsResponse.ONLY,
    ),
]
