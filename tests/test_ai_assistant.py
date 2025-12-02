"""Tests for the AI Assistant services."""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from custom_components.growspace_manager.const import CONF_AI_ENABLED, CONF_ASSISTANT_ID
from custom_components.growspace_manager.models import Growspace
from custom_components.growspace_manager.services.ai_assistant import (
    GrowAssistant,
    handle_analyze_all_growspaces,
    handle_ask_grow_advice,
    handle_strain_recommendation,
)

GROWSPACE_ID = "test_growspace"
GROWSPACE_NAME = "Test Growspace"


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Mock the GrowspaceCoordinator."""
    coordinator = MagicMock()
    coordinator.growspaces = {
        GROWSPACE_ID: Growspace(
            id=GROWSPACE_ID,
            name=GROWSPACE_NAME,
            rows=3,
            plants_per_row=3,
            environment_config={
                "temperature_sensor": "sensor.temp",
                "humidity_sensor": "sensor.humidity",
            },
        )
    }
    coordinator.options = {
        "ai_settings": {
            CONF_AI_ENABLED: True,
            CONF_ASSISTANT_ID: "test_agent",
        }
    }
    coordinator.get_growspace_plants.return_value = []
    coordinator.calculate_days_in_stage.return_value = 10
    return coordinator


@pytest.fixture
def mock_strain_library() -> MagicMock:
    """Mock the StrainLibrary."""
    library = MagicMock()
    library.get_all.return_value = {
        "Strain A": {
            "meta": {"type": "Hybrid", "breeder": "Breeder X"},
            "phenotypes": {
                "Pheno 1": {"harvests": [{"veg_days": 30, "flower_days": 60}]}
            },
        }
    }
    return library


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()

    # Mock sensor states
    mock_state = MagicMock()
    mock_state.state = "25"
    mock_state.attributes = {"unit_of_measurement": "°C"}
    hass.states.get.return_value = mock_state

    return hass


@pytest.fixture
def assistant(mock_hass, mock_coordinator, mock_strain_library) -> GrowAssistant:
    """Fixture for GrowAssistant."""
    return GrowAssistant(mock_hass, mock_coordinator, mock_strain_library)


async def test_get_grow_advice_success(assistant: GrowAssistant, mock_hass: MagicMock):
    """Test getting grow advice successfully."""
    with patch("homeassistant.components.conversation.async_converse") as mock_converse:
        mock_result = MagicMock()
        mock_result.response.speech = {"plain": {"speech": "AI Advice"}}
        mock_converse.return_value = mock_result

        response = await assistant.get_grow_advice(GROWSPACE_ID, "Query")

        assert response == "AI Advice"
        mock_converse.assert_awaited_once()


async def test_get_grow_advice_no_ai_config(
    assistant: GrowAssistant, mock_coordinator: MagicMock
):
    """Test getting advice with AI disabled."""
    mock_coordinator.options = {}

    with pytest.raises(ServiceValidationError, match="AI assistant is not enabled"):
        await assistant.get_grow_advice(GROWSPACE_ID, "Query")


async def test_get_grow_advice_empty_response(
    assistant: GrowAssistant, mock_hass: MagicMock
):
    """Test getting empty response from AI."""
    with patch("homeassistant.components.conversation.async_converse") as mock_converse:
        mock_result = MagicMock()
        mock_result.response.speech = {"plain": {"speech": ""}}  # Empty
        mock_converse.return_value = mock_result

        # Should raise ServiceValidationError
        with pytest.raises(
            ServiceValidationError, match="AI assistant returned an empty response"
        ):
            await assistant.get_grow_advice(GROWSPACE_ID, "Query")


async def test_handle_ask_grow_advice(mock_hass, mock_coordinator, mock_strain_library):
    """Test handle_ask_grow_advice service."""
    call = ServiceCall(
        mock_hass,
        "growspace_manager",
        "ask_grow_advice",
        {"growspace_id": GROWSPACE_ID, "user_query": "Query"},
        context=MagicMock(),
    )

    with patch(
        "custom_components.growspace_manager.services.ai_assistant.GrowAssistant.get_grow_advice",
        return_value="Advice",
    ) as mock_get_advice:
        response = await handle_ask_grow_advice(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

        assert response == {"response": "Advice"}
        mock_get_advice.assert_awaited_once()


async def test_handle_analyze_all_growspaces(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test handle_analyze_all_growspaces service."""
    call = ServiceCall(
        mock_hass,
        "growspace_manager",
        "analyze_all_growspaces",
        {},
        context=MagicMock(),
    )

    with patch("homeassistant.components.conversation.async_converse") as mock_converse:
        mock_result = MagicMock()
        mock_result.response.speech = {"plain": {"speech": "Analysis Report"}}
        mock_converse.return_value = mock_result

        response = await handle_analyze_all_growspaces(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

        assert response["response"] == "Analysis Report"
        assert response["growspaces_analyzed"] == 1


async def test_handle_strain_recommendation(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test handle_strain_recommendation service."""
    call = ServiceCall(
        mock_hass,
        "growspace_manager",
        "recommend_strains",
        {"preferences": {"type": "Sativa"}},
        context=MagicMock(),
    )

    with patch("homeassistant.components.conversation.async_converse") as mock_converse:
        mock_result = MagicMock()
        mock_result.response.speech = {"plain": {"speech": "Strain Recommendation"}}
        mock_converse.return_value = mock_result

        response = await handle_strain_recommendation(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

        assert response["response"] == "Strain Recommendation"
        assert response["strains_analyzed"] == 1


def test_format_context_data(assistant: GrowAssistant):
    """Test formatting context data."""
    data = {
        "growspace": {
            "id": GROWSPACE_ID,
            "name": GROWSPACE_NAME,
            "size": "3x3",
            "total_plants": 5,
        },
        "environment": {
            "sensors": {"temp_sensor": "25 °C"},
            "raw_states": {},
        },
        "analysis": {
            "stress": {"active": True, "reasons": ["High VPD"]},
            "mold_risk": {"active": False},
            "optimal": {"active": False},
        },
        "plants": {
            "count": 5,
            "strains": ["Strain A"],
            "max_veg_days": 20,
            "max_flower_days": 0,
        },
        "strain_analytics": {
            "Strain A": {"avg_veg_days": 30, "avg_flower_days": 60, "total_harvests": 1}
        },
    }

    context = assistant._format_context_data(data)

    assert "GROWSPACE: Test Growspace" in context
    assert "Temp: 25 °C" in context
    assert "⚠️ STRESS DETECTED:" in context
    assert "- High VPD" in context
    assert "Strain A: Avg 30d veg" in context


def test_get_ai_settings_missing_agent(
    assistant: GrowAssistant, mock_coordinator: MagicMock
):
    """Test getting AI settings with missing agent ID."""
    mock_coordinator.options = {
        "ai_settings": {
            CONF_AI_ENABLED: True,
            # No agent ID
        }
    }
    assert assistant._get_ai_settings() is None


def test_gather_growspace_data_missing(assistant: GrowAssistant):
    """Test gathering data for missing growspace."""
    with pytest.raises(ServiceValidationError):
        assistant._gather_growspace_data("missing_id")


def test_format_context_data_extended(assistant: GrowAssistant):
    """Test formatting context data with more details."""
    data = {
        "growspace": {
            "id": GROWSPACE_ID,
            "name": GROWSPACE_NAME,
            "size": "3x3",
            "total_plants": 5,
        },
        "environment": {
            "sensors": {"temp_sensor": "25 °C"},
            "raw_states": {},
        },
        "analysis": {
            "stress": {"active": False, "reasons": []},
            "mold_risk": {"active": True, "reasons": ["High Humidity"]},
            "optimal": {"active": True},
        },
        "plants": {
            "count": 5,
            "strains": ["Strain A"],
            "max_veg_days": 20,
            "max_flower_days": 45,
        },
        "strain_analytics": {},
    }

    context = assistant._format_context_data(data)

    assert "🍄 MOLD RISK DETECTED:" in context
    assert "- High Humidity" in context
    assert "✅ Optimal conditions achieved" in context
    assert "Max Flower: Day 45 (Week 6)" in context


async def test_get_grow_advice_truncation(
    assistant: GrowAssistant, mock_hass: MagicMock
):
    """Test truncation of grow advice."""
    with patch("homeassistant.components.conversation.async_converse") as mock_converse:
        mock_result = MagicMock()
        # Create a long response
        long_response = "Word " * 100
        mock_result.response.speech = {"plain": {"speech": long_response}}
        mock_converse.return_value = mock_result

        response = await assistant.get_grow_advice(GROWSPACE_ID, "Query", max_length=50)

        assert len(response) <= 53  # 50 + "..."
        assert response.endswith("...")


async def test_handle_analyze_all_growspaces_extended(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test analyze all growspaces with issues and truncation."""
    # Setup mock data with issues
    mock_coordinator.growspaces = {
        "gs1": Growspace(
            id="gs1",
            name="GS1",
            rows=3,
            plants_per_row=3,
            environment_config={},
        )
    }

    # Mock gather_growspace_data to return data with issues
    with patch(
        "custom_components.growspace_manager.services.ai_assistant.GrowAssistant._gather_growspace_data"
    ) as mock_gather:
        mock_gather.return_value = {
            "growspace": {"id": "gs1", "name": "GS1", "size": "3x3", "total_plants": 5},
            "environment": {"sensors": {}, "raw_states": {}},
            "analysis": {
                "stress": {"active": True, "reasons": ["Stress"]},
                "mold_risk": {"active": True, "reasons": ["Mold"]},
                "optimal": {"active": False},
            },
            "plants": {"count": 5},
            "strain_analytics": {},
        }

        call = ServiceCall(
            mock_hass,
            "growspace_manager",
            "analyze_all_growspaces",
            {"max_length": 20},
            context=MagicMock(),
        )

        with patch(
            "homeassistant.components.conversation.async_converse"
        ) as mock_converse:
            mock_result = MagicMock()
            mock_result.response.speech = {
                "plain": {"speech": "Long Analysis Report Extra"}
            }
            mock_converse.return_value = mock_result

            response = await handle_analyze_all_growspaces(
                mock_hass, mock_coordinator, mock_strain_library, call
            )

            assert "..." in response["response"]
            assert response["issues_count"] == 2


async def test_handle_strain_recommendation_extended(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test strain recommendation with extended data."""
    call = ServiceCall(
        mock_hass,
        "growspace_manager",
        "recommend_strains",
        {
            "preferences": {"type": "Sativa"},
            "growspace_id": GROWSPACE_ID,
            "user_query": "Best yield",
            "max_length": 20,
        },
        context=MagicMock(),
    )

    # Mock strain library with more data
    mock_strain_library.get_all.return_value = {
        "Strain A": {
            "meta": {"type": "Sativa", "breeder": "Breeder", "description": "Desc"},
            "phenotypes": {
                "Pheno 1": {
                    "flower_days_min": 60,
                    "flower_days_max": 70,
                    "description": "Pheno Desc",
                }
            },
        }
    }

    with patch("homeassistant.components.conversation.async_converse") as mock_converse:
        mock_result = MagicMock()
        mock_result.response.speech = {"plain": {"speech": "Long Recommendation Extra"}}
        mock_converse.return_value = mock_result

        response = await handle_strain_recommendation(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

        assert "..." in response["response"]
        assert response["strains_analyzed"] == 1


async def test_handle_analyze_all_growspaces_no_agent(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test analyze all growspaces with no agent configured."""
    mock_coordinator.options = {}  # No AI settings

    call = ServiceCall(
        mock_hass,
        "growspace_manager",
        "analyze_all_growspaces",
        {},
        context=MagicMock(),
    )

    response = await handle_analyze_all_growspaces(
        mock_hass, mock_coordinator, mock_strain_library, call
    )

    assert "AI Assistant not configured" in response["response"]

    assert "AI Assistant not configured" in response["response"]


async def test_handle_strain_recommendation_no_agent(
    assistant: GrowAssistant, mock_hass, mock_coordinator, mock_strain_library
):
    """Test strain recommendation with no agent configured."""
    mock_coordinator.options = {}  # No AI settings

    call = ServiceCall(
        mock_hass,
        "growspace_manager",
        "recommend_strains",
        {},
        context=MagicMock(),
    )

    with patch.object(assistant, "_get_ai_settings", return_value=None):
        response = await handle_strain_recommendation(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

    assert "AI Assistant not configured" in response["response"]


async def test_gather_growspace_data_with_plants(
    assistant: GrowAssistant,
    mock_coordinator: MagicMock,
    mock_strain_library: MagicMock,
):
    """Test gathering data with plants and strain analytics."""
    # Mock plants
    plant1 = MagicMock()
    plant1.strain = "Strain A"
    plant1.stage = "veg"
    plant1.veg_start = "2023-01-01"
    plant2 = MagicMock()
    plant2.strain = "Strain A"
    plant2.stage = "flower"
    plant2.flower_start = "2023-02-01"

    mock_coordinator.get_growspace_plants.return_value = [plant1, plant2]
    mock_coordinator.calculate_days_in_stage.return_value = 10

    # Mock strain library
    mock_strain_library.get_all.return_value = {
        "Strain A": {
            "meta": {},
            "phenotypes": {
                "Pheno 1": {"harvests": [{"veg_days": 30, "flower_days": 60}]}
            },
        }
    }

    data = assistant._gather_growspace_data(GROWSPACE_ID)

    assert data["plants"]["count"] == 2
    assert data["plants"]["stages"]["veg"] == 1
    assert data["plants"]["stages"]["flower"] == 1
    assert "Strain A" in data["strain_analytics"]
    assert data["strain_analytics"]["Strain A"]["avg_veg_days"] == 30


async def test_handle_analyze_all_growspaces_optimal(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test analyze all growspaces with optimal conditions."""
    mock_coordinator.growspaces = {
        "gs1": Growspace(
            id="gs1", name="GS1", rows=3, plants_per_row=3, environment_config={}
        )
    }

    with patch(
        "custom_components.growspace_manager.services.ai_assistant.GrowAssistant._gather_growspace_data"
    ) as mock_gather:
        mock_gather.return_value = {
            "growspace": {"id": "gs1", "name": "GS1", "size": "3x3", "total_plants": 5},
            "environment": {"sensors": {}, "raw_states": {}},
            "analysis": {
                "stress": {"active": False},
                "mold_risk": {"active": False},
                "optimal": {"active": True},
            },
            "plants": {"count": 5},
            "strain_analytics": {},
        }

        call = ServiceCall(
            mock_hass,
            "growspace_manager",
            "analyze_all_growspaces",
            {},
            context=MagicMock(),
        )

        with patch(
            "homeassistant.components.conversation.async_converse"
        ) as mock_converse:
            mock_result = MagicMock()
            mock_result.response.speech = {"plain": {"speech": "Report"}}
            mock_converse.return_value = mock_result

            response = await handle_analyze_all_growspaces(
                mock_hass, mock_coordinator, mock_strain_library, call
            )

            assert "Report" in response["response"]


async def test_handle_analyze_all_growspaces_exceptions(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test exceptions in analyze all growspaces."""
    mock_coordinator.growspaces = {
        "gs1": Growspace(
            id="gs1", name="GS1", rows=3, plants_per_row=3, environment_config={}
        ),
        "gs2": Growspace(
            id="gs2", name="GS2", rows=3, plants_per_row=3, environment_config={}
        ),
    }

    with patch(
        "custom_components.growspace_manager.services.ai_assistant.GrowAssistant._gather_growspace_data",
        side_effect=[
            Exception("Gather Error"),
            {
                "growspace": {"name": "GS2"},
                "plants": {"count": 0},
                "analysis": {
                    "stress": {"active": False},
                    "mold_risk": {"active": False},
                    "optimal": {"active": False},
                },
            },
        ],
    ):
        call = ServiceCall(
            mock_hass,
            "growspace_manager",
            "analyze_all_growspaces",
            {},
            context=MagicMock(),
        )

        # Test empty response from AI (missing speech)
        with patch(
            "homeassistant.components.conversation.async_converse"
        ) as mock_converse:
            mock_result = MagicMock()
            mock_result.response.speech = {}  # Empty speech
            mock_converse.return_value = mock_result

            response = await handle_analyze_all_growspaces(
                mock_hass, mock_coordinator, mock_strain_library, call
            )

            assert "Error analyzing growspaces" in response["response"]
            assert "AI assistant returned an empty response" in response["response"]


async def test_handle_strain_recommendation_exceptions(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test exceptions in strain recommendation."""
    call = ServiceCall(
        mock_hass,
        "growspace_manager",
        "recommend_strains",
        {"growspace_id": GROWSPACE_ID},
        context=MagicMock(),
    )

    # Mock strain library with no history
    mock_strain_library.get_all.return_value = {
        "Strain B": {"meta": {}, "phenotypes": {"Pheno 1": {"description": "Desc"}}}
    }

    # Mock gather_growspace_data exception
    with (
        patch(
            "custom_components.growspace_manager.services.ai_assistant.GrowAssistant._gather_growspace_data",
            side_effect=Exception("Gather Error"),
        ),
        patch("homeassistant.components.conversation.async_converse") as mock_converse,
    ):
        # Test empty response from AI (missing speech)
        mock_result = MagicMock()
        mock_result.response.speech = {}  # Empty speech
        mock_converse.return_value = mock_result

        response = await handle_strain_recommendation(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

        assert "Error getting recommendations" in response["response"]
        assert "AI assistant returned an empty response" in response["response"]
