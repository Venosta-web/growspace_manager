"""Tests for the AI Assistant service module."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.exceptions import ServiceValidationError

from custom_components.growspace_manager.models import Growspace, Plant
from custom_components.growspace_manager.services.ai_assistant import (
    GrowAssistant,
    handle_analyze_all_growspaces,
    handle_ask_grow_advice,
    handle_strain_recommendation,
)


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.states = MagicMock()
    return hass


@pytest.fixture
def mock_coordinator():
    """Create a mock GrowspaceCoordinator."""
    coordinator = MagicMock()
    coordinator.options = {
        "ai_settings": {
            "ai_enabled": True,
            "assistant_id": "conversation.openai",
        }
    }
    coordinator.growspaces = {}
    coordinator.plants = {}
    coordinator.get_growspace_plants = MagicMock(return_value=[])
    coordinator.calculate_days_in_stage = MagicMock(return_value=10)
    return coordinator


@pytest.fixture
def mock_strain_library():
    """Create a mock StrainLibrary."""
    library = MagicMock()
    library.get_all = MagicMock(return_value={})
    return library


@pytest.fixture
def grow_assistant(mock_hass, mock_coordinator, mock_strain_library):
    """Create a GrowAssistant instance with mocked dependencies."""
    return GrowAssistant(mock_hass, mock_coordinator, mock_strain_library)


class TestGrowAssistantInit:
    """Tests for GrowAssistant initialization."""

    def test_init(self, mock_hass, mock_coordinator, mock_strain_library):
        """Test GrowAssistant initializes correctly."""
        assistant = GrowAssistant(mock_hass, mock_coordinator, mock_strain_library)
        assert assistant.hass is mock_hass
        assert assistant.coordinator is mock_coordinator
        assert assistant.strain_library is mock_strain_library


class TestGetAISettings:
    """Tests for _get_ai_settings method."""

    def test_get_ai_settings_success(self, grow_assistant):
        """Test getting AI settings when properly configured."""
        settings = grow_assistant._get_ai_settings()
        assert settings["ai_enabled"] is True
        assert settings["assistant_id"] == "conversation.openai"

    def test_get_ai_settings_not_enabled(self, grow_assistant):
        """Test error when AI is not enabled."""
        grow_assistant.coordinator.options = {"ai_settings": {"ai_enabled": False}}
        with pytest.raises(ServiceValidationError, match="AI assistant is not enabled"):
            grow_assistant._get_ai_settings()

    def test_get_ai_settings_no_assistant_id(self, grow_assistant):
        """Test error when no assistant ID configured."""
        grow_assistant.coordinator.options = {
            "ai_settings": {"ai_enabled": True, "assistant_id": None}
        }
        with pytest.raises(ServiceValidationError, match="No AI assistant configured"):
            grow_assistant._get_ai_settings()

    def test_get_ai_settings_empty_options(self, grow_assistant):
        """Test error when no AI settings exist."""
        grow_assistant.coordinator.options = {}
        with pytest.raises(ServiceValidationError, match="AI assistant is not enabled"):
            grow_assistant._get_ai_settings()


class TestGatherGrowspaceData:
    """Tests for _gather_growspace_data method."""

    def test_gather_growspace_data_not_found(self, grow_assistant):
        """Test error when growspace not found."""
        with pytest.raises(
            ServiceValidationError, match="Growspace nonexistent not found"
        ):
            grow_assistant._gather_growspace_data("nonexistent")

    def test_gather_growspace_data_success(self, grow_assistant):
        """Test successful data gathering for a growspace."""
        # Setup growspace
        gs = Growspace(id="gs1", name="Test Tent", rows=3, plants_per_row=3)
        gs.environment_config = {
            "temperature_sensor": "sensor.temp",
            "humidity_sensor": "sensor.humidity",
        }
        grow_assistant.coordinator.growspaces = {"gs1": gs}

        # Mock sensor states
        temp_state = MagicMock()
        temp_state.state = "25.5"
        temp_state.attributes = {"unit_of_measurement": "°C"}

        humidity_state = MagicMock()
        humidity_state.state = "60"
        humidity_state.attributes = {"unit_of_measurement": "%"}

        def get_state(entity_id):
            if entity_id == "sensor.temp":
                return temp_state
            if entity_id == "sensor.humidity":
                return humidity_state
            return None

        grow_assistant.hass.states.get = get_state

        # Mock plant data
        grow_assistant.coordinator.get_growspace_plants.return_value = []

        data = grow_assistant._gather_growspace_data("gs1")

        assert data["growspace"]["id"] == "gs1"
        assert data["growspace"]["name"] == "Test Tent"
        assert data["growspace"]["size"] == "3x3"
        assert "temperature_sensor" in data["environment"]["sensors"]
        assert data["environment"]["sensors"]["temperature_sensor"] == "25.5 °C"

    def test_gather_growspace_data_unavailable_sensors(self, grow_assistant):
        """Test handling of unavailable sensors."""
        gs = Growspace(id="gs1", name="Test", rows=2, plants_per_row=2)
        gs.environment_config = {"temperature_sensor": "sensor.temp"}
        grow_assistant.coordinator.growspaces = {"gs1": gs}

        unavailable_state = MagicMock()
        unavailable_state.state = STATE_UNAVAILABLE

        grow_assistant.hass.states.get = MagicMock(return_value=unavailable_state)

        data = grow_assistant._gather_growspace_data("gs1")

        # Sensor should not be included when unavailable
        assert "temperature_sensor" not in data["environment"]["sensors"]


class TestGatherBayesianSensorData:
    """Tests for _gather_bayesian_sensor_data method."""

    def test_gather_bayesian_data_no_sensors(self, grow_assistant):
        """Test when no Bayesian sensors exist."""
        grow_assistant.hass.states.get = MagicMock(return_value=None)

        data = grow_assistant._gather_bayesian_sensor_data("gs1")

        assert data["stress"]["active"] is False
        assert data["mold_risk"]["active"] is False
        assert data["optimal"]["active"] is False
        assert data["light_schedule"]["correct"] is False

    def test_gather_bayesian_data_stress_detected(self, grow_assistant):
        """Test when stress is detected."""
        stress_state = MagicMock()
        stress_state.state = "on"
        stress_state.attributes = {
            "probability": 0.85,
            "reasons": ["High temperature", "Low humidity"],
        }

        def get_state(entity_id):
            if "plants_under_stress" in entity_id:
                return stress_state
            return None

        grow_assistant.hass.states.get = get_state

        data = grow_assistant._gather_bayesian_sensor_data("gs1")

        assert data["stress"]["active"] is True
        assert data["stress"]["probability"] == 0.85
        assert "High temperature" in data["stress"]["reasons"]

    def test_gather_bayesian_data_light_schedule(self, grow_assistant):
        """Test light schedule verification sensor."""
        light_state = MagicMock()
        light_state.state = "on"
        light_state.attributes = {"expected_schedule": "18/6"}

        def get_state(entity_id):
            if "light_schedule_correct" in entity_id:
                return light_state
            return None

        grow_assistant.hass.states.get = get_state

        data = grow_assistant._gather_bayesian_sensor_data("gs1")

        assert data["light_schedule"]["correct"] is True
        assert data["light_schedule"]["expected"] == "18/6"


class TestSummarizePlants:
    """Tests for _summarize_plants method."""

    def test_summarize_empty_plants(self, grow_assistant):
        """Test summary for empty plant list."""
        summary = grow_assistant._summarize_plants([])
        assert summary["count"] == 0
        assert summary["stages"] == {}
        assert summary["strains"] == []

    def test_summarize_plants_with_data(self, grow_assistant):
        """Test summary with multiple plants."""
        plant1 = MagicMock()
        plant1.stage = "flower"
        plant1.strain = "Blue Dream"
        plant1.veg_start = date.today()
        plant1.flower_start = date.today()

        plant2 = MagicMock()
        plant2.stage = "flower"
        plant2.strain = "OG Kush"
        plant2.veg_start = date.today()
        plant2.flower_start = date.today()

        plant3 = MagicMock()
        plant3.stage = "veg"
        plant3.strain = "Blue Dream"
        plant3.veg_start = date.today()
        plant3.flower_start = None

        grow_assistant.coordinator.calculate_days_in_stage.return_value = 14

        summary = grow_assistant._summarize_plants([plant1, plant2, plant3])

        assert summary["count"] == 3
        assert summary["stages"]["flower"] == 2
        assert summary["stages"]["veg"] == 1
        assert "Blue Dream" in summary["strains"]
        assert "OG Kush" in summary["strains"]


class TestGetStrainAnalytics:
    """Tests for _get_strain_analytics method."""

    def test_get_strain_analytics_empty(self, grow_assistant):
        """Test analytics with no plants."""
        analytics = grow_assistant._get_strain_analytics([])
        assert analytics == {}

    def test_get_strain_analytics_with_history(self, grow_assistant):
        """Test analytics with harvest history."""
        plant = MagicMock()
        plant.strain = "Blue Dream"

        grow_assistant.strain_library.get_all.return_value = {
            "Blue Dream": {
                "meta": {"type": "Hybrid", "breeder": "DJ Short"},
                "phenotypes": {
                    "default": {
                        "harvests": [
                            {"veg_days": 30, "flower_days": 56},
                            {"veg_days": 28, "flower_days": 60},
                        ]
                    }
                },
            }
        }

        analytics = grow_assistant._get_strain_analytics([plant])

        assert "Blue Dream" in analytics
        assert analytics["Blue Dream"]["avg_veg_days"] == 29
        assert analytics["Blue Dream"]["avg_flower_days"] == 58
        assert analytics["Blue Dream"]["total_harvests"] == 2

    def test_get_strain_analytics_no_history(self, grow_assistant):
        """Test analytics when strain has no harvest history."""
        plant = MagicMock()
        plant.strain = "New Strain"

        grow_assistant.strain_library.get_all.return_value = {
            "New Strain": {"meta": {}, "phenotypes": {"default": {"harvests": []}}}
        }

        analytics = grow_assistant._get_strain_analytics([plant])

        # Strain should not be in analytics if no harvests
        assert "New Strain" not in analytics


class TestBuildSystemPrompt:
    """Tests for _build_system_prompt method."""

    def test_build_system_prompt_general(self, grow_assistant):
        """Test general context prompt."""
        prompt = grow_assistant._build_system_prompt("general")
        assert "cannabis cultivation advisor" in prompt
        assert "actionable advice" in prompt

    def test_build_system_prompt_diagnostic(self, grow_assistant):
        """Test diagnostic context prompt."""
        prompt = grow_assistant._build_system_prompt("diagnostic")
        assert "identifying issues" in prompt
        assert "urgent problems" in prompt

    def test_build_system_prompt_optimization(self, grow_assistant):
        """Test optimization context prompt."""
        prompt = grow_assistant._build_system_prompt("optimization")
        assert "optimization opportunities" in prompt
        assert "improve yields" in prompt

    def test_build_system_prompt_planning(self, grow_assistant):
        """Test planning context prompt."""
        prompt = grow_assistant._build_system_prompt("planning")
        assert "planning" in prompt
        assert "scheduling" in prompt

    def test_build_system_prompt_unknown_falls_back_to_general(self, grow_assistant):
        """Test unknown context type falls back to general."""
        prompt = grow_assistant._build_system_prompt("unknown_type")
        assert "actionable advice" in prompt


class TestFormatContextData:
    """Tests for _format_context_data method."""

    def test_format_context_data_basic(self, grow_assistant):
        """Test basic context formatting."""
        data = {
            "growspace": {"name": "Flower Tent", "size": "4x4", "total_plants": 12},
            "environment": {"sensors": {"temperature_sensor": "25°C"}},
            "analysis": {
                "stress": {"active": False, "reasons": []},
                "mold_risk": {"active": False, "reasons": []},
                "optimal": {"active": True, "reasons": []},
            },
            "plants": {
                "count": 12,
                "strains": ["Strain A"],
                "max_veg_days": 0,
                "max_flower_days": 21,
            },
            "strain_analytics": {},
        }

        formatted = grow_assistant._format_context_data(data)

        assert "GROWSPACE: Flower Tent" in formatted
        assert "TOTAL PLANTS: 12" in formatted
        assert "Temperature: 25°C" in formatted
        assert "Optimal conditions achieved" in formatted

    def test_format_context_data_with_stress(self, grow_assistant):
        """Test formatting with stress indicators."""
        data = {
            "growspace": {"name": "Test", "size": "2x2", "total_plants": 2},
            "environment": {"sensors": {}},
            "analysis": {
                "stress": {"active": True, "reasons": ["High temp", "Low humidity"]},
                "mold_risk": {"active": False, "reasons": []},
                "optimal": {"active": False, "reasons": []},
            },
            "plants": {
                "count": 2,
                "strains": ["Test"],
                "max_veg_days": 0,
                "max_flower_days": 0,
            },
            "strain_analytics": {},
        }

        formatted = grow_assistant._format_context_data(data)

        assert "STRESS DETECTED" in formatted
        assert "High temp" in formatted

    def test_format_context_data_with_strain_analytics(self, grow_assistant):
        """Test formatting with strain analytics."""
        data = {
            "growspace": {"name": "Test", "size": "2x2", "total_plants": 1},
            "environment": {"sensors": {}},
            "analysis": {
                "stress": {"active": False, "reasons": []},
                "mold_risk": {"active": False, "reasons": []},
                "optimal": {"active": False, "reasons": []},
            },
            "plants": {
                "count": 1,
                "strains": ["Blue Dream"],
                "max_veg_days": 30,
                "max_flower_days": 0,
            },
            "strain_analytics": {
                "Blue Dream": {
                    "avg_veg_days": 28,
                    "avg_flower_days": 56,
                    "total_harvests": 5,
                }
            },
        }

        formatted = grow_assistant._format_context_data(data)

        assert "STRAIN HISTORY" in formatted
        assert "Blue Dream" in formatted
        assert "28d veg" in formatted


class TestGetGrowAdvice:
    """Tests for get_grow_advice async method."""

    @pytest.mark.asyncio
    async def test_get_grow_advice_success(self, grow_assistant):
        """Test successful AI advice retrieval."""
        # Setup growspace
        gs = Growspace(id="gs1", name="Test", rows=2, plants_per_row=2)
        gs.environment_config = {}
        grow_assistant.coordinator.growspaces = {"gs1": gs}

        grow_assistant.hass.states.get = MagicMock(return_value=None)

        # Mock conversation response
        mock_response = MagicMock()
        mock_response.response.speech = {
            "plain": {"speech": "Your plants look healthy!"}
        }

        with patch(
            "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse",
            return_value=mock_response,
        ):
            advice = await grow_assistant.get_grow_advice("gs1")

        assert advice == "Your plants look healthy!"

    @pytest.mark.asyncio
    async def test_get_grow_advice_with_max_length(self, grow_assistant):
        """Test advice truncation with max_length."""
        gs = Growspace(id="gs1", name="Test", rows=2, plants_per_row=2)
        gs.environment_config = {}
        grow_assistant.coordinator.growspaces = {"gs1": gs}

        grow_assistant.hass.states.get = MagicMock(return_value=None)

        long_response = "A" * 500

        mock_response = MagicMock()
        mock_response.response.speech = {"plain": {"speech": long_response}}

        with patch(
            "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse",
            return_value=mock_response,
        ):
            advice = await grow_assistant.get_grow_advice("gs1", max_length=100)

        assert len(advice) <= 103  # 100 + "..."

    @pytest.mark.asyncio
    async def test_get_grow_advice_empty_response(self, grow_assistant):
        """Test error handling for empty AI response."""
        gs = Growspace(id="gs1", name="Test", rows=2, plants_per_row=2)
        gs.environment_config = {}
        grow_assistant.coordinator.growspaces = {"gs1": gs}

        grow_assistant.hass.states.get = MagicMock(return_value=None)

        mock_response = MagicMock()
        mock_response.response = None

        with patch(
            "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse",
            return_value=mock_response,
        ):
            with pytest.raises(ServiceValidationError, match="empty response"):
                await grow_assistant.get_grow_advice("gs1")

    @pytest.mark.asyncio
    async def test_get_grow_advice_api_error(self, grow_assistant):
        """Test error handling for API failures."""
        gs = Growspace(id="gs1", name="Test", rows=2, plants_per_row=2)
        gs.environment_config = {}
        grow_assistant.coordinator.growspaces = {"gs1": gs}

        grow_assistant.hass.states.get = MagicMock(return_value=None)

        with patch(
            "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse",
            side_effect=Exception("API Error"),
        ):
            with pytest.raises(ServiceValidationError, match="Failed to get AI advice"):
                await grow_assistant.get_grow_advice("gs1")


class TestHandleAskGrowAdvice:
    """Tests for handle_ask_grow_advice service handler."""

    @pytest.mark.asyncio
    async def test_handle_ask_grow_advice(
        self, mock_hass, mock_coordinator, mock_strain_library
    ):
        """Test the service handler."""
        gs = Growspace(id="gs1", name="Test", rows=2, plants_per_row=2)
        gs.environment_config = {}
        mock_coordinator.growspaces = {"gs1": gs}

        mock_hass.states.get = MagicMock(return_value=None)

        call = MagicMock()
        call.data = {
            "growspace_id": "gs1",
            "user_query": "How are my plants?",
            "context_type": "general",
        }

        mock_response = MagicMock()
        mock_response.response.speech = {"plain": {"speech": "Looking good!"}}

        with patch(
            "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse",
            return_value=mock_response,
        ):
            result = await handle_ask_grow_advice(
                mock_hass, mock_coordinator, mock_strain_library, call
            )

        assert result["response"] == "Looking good!"


class TestHandleAnalyzeAllGrowspaces:
    """Tests for handle_analyze_all_growspaces service handler."""

    @pytest.mark.asyncio
    async def test_handle_analyze_all_empty(
        self, mock_hass, mock_coordinator, mock_strain_library
    ):
        """Test analyzing with no growspaces."""
        mock_coordinator.growspaces = {}
        mock_hass.states.get = MagicMock(return_value=None)

        call = MagicMock()
        call.data = {}

        mock_response = MagicMock()
        mock_response.response.speech = {"plain": {"speech": "No issues found."}}

        with patch(
            "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse",
            return_value=mock_response,
        ):
            result = await handle_analyze_all_growspaces(
                mock_hass, mock_coordinator, mock_strain_library, call
            )

        assert "response" in result
        assert result["growspaces_analyzed"] == 0

    @pytest.mark.asyncio
    async def test_handle_analyze_all_with_issues(
        self, mock_hass, mock_coordinator, mock_strain_library
    ):
        """Test analyzing growspaces with detected issues."""
        gs = Growspace(id="gs1", name="Problem Tent", rows=2, plants_per_row=2)
        gs.environment_config = {}
        mock_coordinator.growspaces = {"gs1": gs}

        # Create stress sensor state
        stress_state = MagicMock()
        stress_state.state = "on"
        stress_state.attributes = {"probability": 0.9, "reasons": ["High temperature"]}

        def get_state(entity_id):
            if "plants_under_stress" in entity_id:
                return stress_state
            return None

        mock_hass.states.get = get_state

        call = MagicMock()
        call.data = {}

        mock_response = MagicMock()
        mock_response.response.speech = {"plain": {"speech": "Issues detected!"}}

        with patch(
            "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse",
            return_value=mock_response,
        ):
            result = await handle_analyze_all_growspaces(
                mock_hass, mock_coordinator, mock_strain_library, call
            )

        assert result["issues_count"] == 1
        assert result["growspaces_analyzed"] == 1


class TestHandleStrainRecommendation:
    """Tests for handle_strain_recommendation service handler."""

    @pytest.mark.asyncio
    async def test_handle_strain_recommendation_basic(
        self, mock_hass, mock_coordinator, mock_strain_library
    ):
        """Test basic strain recommendation."""
        mock_strain_library.get_all.return_value = {
            "Blue Dream": {
                "meta": {"type": "Hybrid", "breeder": "DJ Short"},
                "phenotypes": {
                    "default": {
                        "harvests": [{"veg_days": 30, "flower_days": 56}],
                        "description": "Classic strain",
                    }
                },
            }
        }

        call = MagicMock()
        call.data = {"preferences": {"type": "Hybrid"}}

        mock_response = MagicMock()
        mock_response.response.speech = {"plain": {"speech": "Try Blue Dream!"}}

        with patch(
            "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse",
            return_value=mock_response,
        ):
            result = await handle_strain_recommendation(
                mock_hass, mock_coordinator, mock_strain_library, call
            )

        assert result["response"] == "Try Blue Dream!"

    @pytest.mark.asyncio
    async def test_handle_strain_recommendation_with_growspace(
        self, mock_hass, mock_coordinator, mock_strain_library
    ):
        """Test strain recommendation with growspace context."""
        gs = Growspace(id="gs1", name="Flower Tent", rows=4, plants_per_row=4)
        gs.environment_config = {}
        mock_coordinator.growspaces = {"gs1": gs}

        mock_hass.states.get = MagicMock(return_value=None)
        mock_strain_library.get_all.return_value = {}

        call = MagicMock()
        call.data = {"growspace_id": "gs1", "user_query": "What should I grow?"}

        mock_response = MagicMock()
        mock_response.response.speech = {"plain": {"speech": "Recommendations..."}}

        with patch(
            "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse",
            return_value=mock_response,
        ):
            result = await handle_strain_recommendation(
                mock_hass, mock_coordinator, mock_strain_library, call
            )

        assert "response" in result
