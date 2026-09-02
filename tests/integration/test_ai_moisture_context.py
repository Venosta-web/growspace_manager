"""Tests for band-aware soil-moisture context shared by AI consumers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.const import CONF_AI_ENABLED, CONF_ASSISTANT_ID
from custom_components.growspace_manager.domain.vision_explainer_prompt import (
    ObservationPassInput,
    build_observation_prompt,
)
from custom_components.growspace_manager.models import EnvironmentConfig, Growspace
from custom_components.growspace_manager.models.vision_evidence import LightWindow
from custom_components.growspace_manager.services.ai_assistant import GrowAssistant


def _assistant(
    reading: str,
    unit: str | None,
    minimum: float | None = None,
    maximum: float | None = None,
) -> tuple[GrowAssistant, MagicMock, Growspace]:
    """Build an assistant with one configured soil-moisture sensor."""
    growspace = Growspace(
        id="tent1",
        name="Tent 1",
        rows=2,
        plants_per_row=2,
        environment_config=EnvironmentConfig(
            soil_moisture_sensor="sensor.soil",
            soil_moisture_min=minimum,
            soil_moisture_max=maximum,
        ),
    )
    coordinator = MagicMock()
    coordinator.options = {
        "ai_settings": {
            CONF_AI_ENABLED: True,
            CONF_ASSISTANT_ID: "conversation.test",
        }
    }
    coordinator.growspaces = {growspace.id: growspace}
    coordinator._data_repository.get_growspace.return_value = growspace
    coordinator._data_repository.get_growspace_plants.return_value = []
    coordinator.services.config.strain_library.get_all.return_value = {}

    moisture_state = MagicMock()
    moisture_state.state = reading
    moisture_state.attributes = {} if unit is None else {"unit_of_measurement": unit}
    hass = MagicMock()
    hass.states.get.side_effect = lambda entity_id: (
        moisture_state if entity_id == "sensor.soil" else None
    )

    strain_library = MagicMock()
    strain_library.get_all.return_value = {}
    return GrowAssistant(hass, coordinator, strain_library), coordinator, growspace


@pytest.mark.parametrize(
    ("reading", "expected_classification", "expected_interpretation"),
    [
        pytest.param(
            "15",
            "too_dry",
            "15% is below the effective minimum of 20%",
            id="below-inherited-band",
        ),
        pytest.param(
            "65",
            "too_wet",
            "65% is above the effective maximum of 60%",
            id="above-inherited-band",
        ),
    ],
)
def test_out_of_band_context_names_effective_boundary(
    reading: str,
    expected_classification: str,
    expected_interpretation: str,
) -> None:
    """Low and high readings explain the inherited boundary they cross."""
    assistant, _, _ = _assistant(reading, "%")

    data = assistant.gather_growspace_data("tent1")
    moisture = data["environment"]["soil_moisture"]
    context = assistant._format_context_data(data)

    assert moisture == {
        "reading": float(reading),
        "unit": "%",
        "band": {"min": 20.0, "max": 60.0, "is_custom": False},
        "classification": expected_classification,
    }
    assert "20–60% (inherited default, inclusive)" in context
    assert expected_interpretation in context


@pytest.mark.parametrize(
    "unit", [pytest.param("%", id="percent"), pytest.param(None, id="legacy-no-unit")]
)
def test_custom_in_band_context_rejects_absolute_wetness_inference(
    unit: str | None,
) -> None:
    """A high absolute reading is healthy when the custom band says it is."""
    assistant, _, _ = _assistant("90", unit, 80.0, 95.0)

    data = assistant.gather_growspace_data("tent1")
    context = assistant._format_context_data(data)

    assert data["environment"]["soil_moisture"]["classification"] == "in_band"
    assert "Raw reading: 90%" in context
    assert "80–95% (custom, inclusive)" in context
    assert "Classification: within the acceptable band" in context
    assert (
        "The absolute reading alone is not evidence of overwatering or underwatering."
        in context
    )


def test_incompatible_unit_is_not_exposed_as_moisture_percentage() -> None:
    """An explicitly non-percentage reading is absent from AI context."""
    assistant, _, _ = _assistant("90", "mV", 80.0, 95.0)

    data = assistant.gather_growspace_data("tent1")
    context = assistant._format_context_data(data)

    assert data["environment"]["soil_moisture"] is None
    assert "Soil Moisture" not in context
    assert "90" not in context
    assert "mV" not in context


async def test_general_advice_receives_canonical_moisture_context() -> None:
    """General advice receives the same formatted interpretation."""
    assistant, _, _ = _assistant("90", "%", 80.0, 95.0)
    result = MagicMock()
    result.response.speech = {"plain": {"speech": "Looks good."}}

    with patch(
        "homeassistant.components.conversation.async_converse", return_value=result
    ) as converse:
        await assistant.get_grow_advice("tent1")

    prompt = converse.call_args.kwargs["text"]
    assert "Raw reading: 90%" in prompt
    assert "80–95% (custom, inclusive)" in prompt
    assert "Classification: within the acceptable band" in prompt


@pytest.mark.parametrize(
    "check_type",
    [pytest.param("early", id="scheduled"), pytest.param("manual", id="manual")],
)
def test_vision_prompts_share_context_and_preserve_visible_symptom_authority(
    check_type: str,
) -> None:
    """Moisture context cannot enter the image-only observation pass."""
    prompt = build_observation_prompt(
        ObservationPassInput(
            light_window=LightWindow(check_type),
            photograph_count=1,
        )
    )

    assert "Raw reading: 90%" not in prompt
    assert "80–95%" not in prompt
    assert "moisture" not in prompt.lower()


def test_band_change_only_changes_future_context() -> None:
    """Rebuilding context uses the new band without rewriting stored history."""
    assistant, _, growspace = _assistant("70", "%")
    stored_history = [MagicMock(analysis="Original analysis")]
    growspace.vision_checkup_history = stored_history

    before = assistant._format_context_data(assistant.gather_growspace_data("tent1"))
    growspace.environment_config.soil_moisture_min = 65.0
    growspace.environment_config.soil_moisture_max = 80.0
    after = assistant._format_context_data(assistant.gather_growspace_data("tent1"))

    assert "Classification: above the acceptable band" in before
    assert "Classification: within the acceptable band" in after
    assert growspace.vision_checkup_history is stored_history
