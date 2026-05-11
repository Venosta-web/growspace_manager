"""Tests for the AI Assistant services."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.const import CONF_AI_ENABLED, CONF_ASSISTANT_ID
from custom_components.growspace_manager.models import EnvironmentConfig, Growspace
from custom_components.growspace_manager.services.ai_assistant import (
    GrowAssistant,
    handle_analyze_all_growspaces,
    handle_ask_grow_advice,
    handle_strain_recommendation,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

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
            environment_config=EnvironmentConfig(
                temperature_sensor="sensor.temp",
                humidity_sensor="sensor.humidity",
            ),
        )
    }
    coordinator.options = {
        "ai_settings": {
            CONF_AI_ENABLED: True,
            CONF_ASSISTANT_ID: "test_agent",
        }
    }
    coordinator.get_growspace_plants.return_value = []
    coordinator.serializer.calculate_days_in_stage.return_value = 10
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
    hass.data = {}

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


async def test_get_grow_advice_success(
    assistant: GrowAssistant, mock_hass: MagicMock
) -> None:
    """Test getting grow advice successfully."""
    with patch(
        "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse"
    ) as mock_converse:
        mock_result = MagicMock()
        mock_result.response.speech = {"plain": {"speech": "AI Advice"}}
        mock_converse.return_value = mock_result

        response = await assistant.get_grow_advice(GROWSPACE_ID, "Query")

        assert response == "AI Advice"
        mock_converse.assert_awaited_once()


async def test_get_grow_advice_no_ai_config(
    assistant: GrowAssistant, mock_coordinator: MagicMock
) -> None:
    """Test getting advice with AI disabled."""
    mock_coordinator.options = {}

    with pytest.raises(ServiceValidationError, match="AI assistant is not enabled"):
        await assistant.get_grow_advice(GROWSPACE_ID, "Query")


async def test_get_grow_advice_empty_response(
    assistant: GrowAssistant, mock_hass: MagicMock
) -> None:
    """Test getting empty response from AI."""
    with patch(
        "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse"
    ) as mock_converse:
        mock_result = MagicMock()
        mock_result.response.speech = {"plain": {"speech": ""}}  # Empty
        mock_converse.return_value = mock_result

        # Should raise ServiceValidationError
        with pytest.raises(
            ServiceValidationError, match="AI assistant returned an empty response"
        ):
            await assistant.get_grow_advice(GROWSPACE_ID, "Query")


async def test_handle_ask_grow_advice(
    mock_hass, mock_coordinator, mock_strain_library
) -> None:
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
) -> None:
    """Test handle_analyze_all_growspaces service."""
    call = ServiceCall(
        mock_hass,
        "growspace_manager",
        "analyze_all_growspaces",
        {},
        context=MagicMock(),
    )

    with patch(
        "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse"
    ) as mock_converse:
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
) -> None:
    """Test handle_strain_recommendation service."""
    call = ServiceCall(
        mock_hass,
        "growspace_manager",
        "recommend_strains",
        {"preferences": {"type": "Sativa"}},
        context=MagicMock(),
    )

    with patch(
        "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse"
    ) as mock_converse:
        mock_result = MagicMock()
        mock_result.response.speech = {"plain": {"speech": "Strain Recommendation"}}
        mock_converse.return_value = mock_result

        response = await handle_strain_recommendation(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

        assert response["response"] == "Strain Recommendation"
        assert response["strains_analyzed"] == 1


def test_format_context_data(assistant: GrowAssistant) -> None:
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


def testget_ai_settings_missing_agent(
    assistant: GrowAssistant, mock_coordinator: MagicMock
) -> None:
    """Test getting AI settings with missing agent ID."""
    mock_coordinator.options = {
        "ai_settings": {
            CONF_AI_ENABLED: True,
            # No agent ID
        }
    }
    assert assistant.get_ai_settings() is None


def testgather_growspace_data_missing(assistant: GrowAssistant) -> None:
    """Test gathering data for missing growspace."""
    with pytest.raises(ServiceValidationError):
        assistant.gather_growspace_data("missing_id")


def test_format_context_data_extended(assistant: GrowAssistant) -> None:
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
) -> None:
    """Test truncation of grow advice."""
    with patch(
        "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse"
    ) as mock_converse:
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
) -> None:
    """Test analyze all growspaces with issues and truncation."""
    # Setup mock data with issues
    mock_coordinator.growspaces = {
        "gs1": Growspace(
            id="gs1",
            name="GS1",
            rows=3,
            plants_per_row=3,
            environment_config=EnvironmentConfig(),
        )
    }

    # Mock gather_growspace_data to return data with issues
    with patch(
        "custom_components.growspace_manager.services.ai_assistant.GrowAssistant.gather_growspace_data"
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
            "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse"
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
) -> None:
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

    with patch(
        "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse"
    ) as mock_converse:
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
) -> None:
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
) -> None:
    """Test strain recommendation with no agent configured."""
    mock_coordinator.options = {}  # No AI settings

    call = ServiceCall(
        mock_hass,
        "growspace_manager",
        "recommend_strains",
        {},
        context=MagicMock(),
    )

    with patch.object(assistant, "get_ai_settings", return_value=None):
        response = await handle_strain_recommendation(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

    assert "AI Assistant not configured" in response["response"]


async def testgather_growspace_data_with_plants(
    assistant: GrowAssistant,
    mock_coordinator: MagicMock,
    mock_strain_library: MagicMock,
) -> None:
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
    mock_coordinator.serializer.calculate_days_in_stage.return_value = 10

    # Mock strain library
    mock_strain_library.get_all.return_value = {
        "Strain A": {
            "meta": {},
            "phenotypes": {
                "Pheno 1": {"harvests": [{"veg_days": 30, "flower_days": 60}]}
            },
        }
    }

    data = assistant.gather_growspace_data(GROWSPACE_ID)

    assert data["plants"]["count"] == 2
    assert data["plants"]["stages"]["veg"] == 1
    assert data["plants"]["stages"]["flower"] == 1
    assert "Strain A" in data["strain_analytics"]
    assert data["strain_analytics"]["Strain A"]["avg_veg_days"] == 30


async def test_handle_analyze_all_growspaces_optimal(
    mock_hass, mock_coordinator, mock_strain_library
) -> None:
    """Test analyze all growspaces with optimal conditions."""
    mock_coordinator.growspaces = {
        "gs1": Growspace(
            id="gs1",
            name="GS1",
            rows=3,
            plants_per_row=3,
            environment_config=EnvironmentConfig(),
        )
    }

    with patch(
        "custom_components.growspace_manager.services.ai_assistant.GrowAssistant.gather_growspace_data"
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
            "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse"
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
) -> None:
    """Test exceptions in analyze all growspaces."""
    mock_coordinator.growspaces = {
        "gs1": Growspace(
            id="gs1",
            name="GS1",
            rows=3,
            plants_per_row=3,
            environment_config=EnvironmentConfig(),
        ),
        "gs2": Growspace(
            id="gs2",
            name="GS2",
            rows=3,
            plants_per_row=3,
            environment_config=EnvironmentConfig(),
        ),
    }

    with patch(
        "custom_components.growspace_manager.services.ai_assistant.GrowAssistant.gather_growspace_data",
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
            "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse"
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
) -> None:
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
            "custom_components.growspace_manager.services.ai_assistant.GrowAssistant.gather_growspace_data",
            side_effect=Exception("Gather Error"),
        ),
        patch(
            "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse"
        ) as mock_converse,
    ):
        # Test empty response from AI (missing speech)
        mock_result = MagicMock()
        mock_result.response.speech = {}  # Empty speech
        mock_converse.return_value = mock_result

        response = await handle_strain_recommendation(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

        assert "AI assistant returned an empty response" in response["response"]


async def test_get_grow_advice_exception_fallback(
    assistant: GrowAssistant, mock_hass: MagicMock
) -> None:
    """Test get_grow_advice fallback on exception (covers lines 379-382)."""
    with patch(
        "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse",
        side_effect=Exception("API Error"),
    ):
        response = await assistant.get_grow_advice(GROWSPACE_ID, "Query")
        assert "AI Assistant Error: API Error" in response


async def test_validate_ai_settings_missing_id(
    assistant: GrowAssistant, mock_coordinator: MagicMock
) -> None:
    """Test _validate_ai_settings with AI enabled but no ID (covers lines 393-396)."""
    mock_coordinator.options = {"ai_settings": {CONF_AI_ENABLED: True}}
    # No CONF_ASSISTANT_ID
    with pytest.raises(
        ServiceValidationError,
        match="AI assistant enabled but no assistant ID selected",
    ):
        assistant._validate_ai_settings(None)


async def test_validate_ai_settings_incomplete(
    assistant: GrowAssistant, mock_coordinator: MagicMock
) -> None:
    """Test _validate_ai_settings with incomplete settings (covers lines 397-398)."""
    # Both are truthy in raw_settings, but ai_settings (the argument) is None
    mock_coordinator.options = {
        "ai_settings": {CONF_AI_ENABLED: True, CONF_ASSISTANT_ID: "agent"}
    }
    with pytest.raises(ServiceValidationError, match="AI settings are invalid"):
        assistant._validate_ai_settings(None)


async def test_execute_conversation_no_agent(assistant: GrowAssistant) -> None:
    """Test _execute_conversation with missing agent_id (covers line 406)."""
    with pytest.raises(ServiceValidationError, match="AI assistant is not enabled"):
        await assistant._execute_conversation("Prompt", "", 100, "gs1")


async def test_gather_growspace_data_legacy_dict(
    assistant: GrowAssistant, mock_coordinator: MagicMock, mock_hass: MagicMock
) -> None:
    """Test gathering data with legacy dict environment config (covers line 87)."""
    growspace = mock_coordinator.growspaces[GROWSPACE_ID]
    # Set environment_config to a dict
    growspace.environment_config = {
        "temperature_sensor": "sensor.legacy_temp",
        "humidity_sensor": "sensor.legacy_humidity",
    }

    # Mock states.get specifically for legacy sensors
    def side_effect(entity_id):
        if entity_id == "sensor.legacy_temp":
            m = MagicMock()
            m.state = "22"
            m.attributes = {"unit_of_measurement": "C"}
            return m
        return None

    mock_hass.states.get.side_effect = side_effect

    data = assistant.gather_growspace_data(GROWSPACE_ID)
    assert data["environment"]["sensors"]["temperature_sensor"] == "22 C"


async def test_get_strain_specific_context_full(
    assistant: GrowAssistant,
    mock_coordinator: MagicMock,
    mock_strain_library: MagicMock,
) -> None:
    """Test full strain context (covers lines 253-268, 274-303, 358-360)."""
    # Mock plants
    plant1 = MagicMock()
    plant1.strain = "OG Kush"
    plant2 = MagicMock()
    plant2.strain = "OG Kush"  # Duplicate to hit line 260 (seen_strains)
    plant3 = MagicMock()
    plant3.strain = "Unknown Strain"  # Missing to hit line 260 (not in all_strains)

    mock_coordinator.get_growspace_plants.return_value = [plant1, plant2, plant3]

    # Mock strain library with rich metadata
    mock_strain_library.get_all.return_value = {
        "OG Kush": {
            "meta": {
                "breeder_notes": "Very pungent flavor.",
                "flowering_days_min": 55,
                "flowering_days_max": 65,
                "ideal_temp_range": "20-26C",
                "ideal_humidity_range": "40-50%",
                "lineage": "Chemdawg x Hindu Kush",
            },
            "phenotypes": {
                "Lemon Pheno": {
                    "notes": "Citrus scent" * 20  # Long notes for truncation check
                }
            },
        }
    }

    # This will trigger _get_strain_specific_context via gather_growspace_data and _format_context_data integration
    data = assistant.gather_growspace_data(GROWSPACE_ID)
    context = assistant._format_context_data(data)

    assert "STRAIN-SPECIFIC GUIDANCE:" in context
    assert "OG Kush" in context
    assert "Very pungent flavor" in context
    assert "55-65 days" in context
    assert "20-26C" in context
    assert "40-50%" in context
    assert "Chemdawg x Hindu Kush" in context
    assert "Lemon Pheno" in context
    assert "..." in context  # Check truncation


async def test_generate_alert_message(assistant: GrowAssistant) -> None:
    """Test generating diagnostic alert message (covers lines 420-426)."""
    with patch.object(
        assistant, "get_grow_advice", return_value="Alert advice"
    ) as mock_advice:
        msg = await assistant.generate_alert_message(
            GROWSPACE_ID, "mold", ["High humidity"]
        )
        assert msg == "Alert advice"
        mock_advice.assert_called_once()
        _, kwargs = mock_advice.call_args
        assert "mold" in kwargs["user_query"]
        assert "High humidity" in kwargs["user_query"]
        assert kwargs["context_type"] == "diagnostic"


async def test_get_grow_advice_config_missing_paths(
    assistant: GrowAssistant, mock_coordinator: MagicMock
) -> None:
    """Test get_grow_advice with missing config (covers lines 455, 458)."""
    # Patch _validate_ai_settings to do nothing so we can reach the fallbacks
    with patch.object(assistant, "_validate_ai_settings"):
        # Path where get_ai_settings returns None
        with patch.object(assistant, "get_ai_settings", return_value=None):
            res = await assistant.get_grow_advice(GROWSPACE_ID)
            assert res == "AI settings not configured."

        # Path where agent_id is missing within settings
        with patch.object(assistant, "get_ai_settings", return_value={"enabled": True}):
            res = await assistant.get_grow_advice(GROWSPACE_ID)
            assert res == "AI Assistant ID not configured."


async def test_handle_analyze_all_growspaces_exception_path(
    mock_hass, mock_coordinator, mock_strain_library
) -> None:
    """Test exception fallback in handle_analyze_all_growspaces (covers lines 658-661)."""
    call = ServiceCall(mock_hass, "gsm", "analyze", {})

    mock_coordinator.growspaces = {GROWSPACE_ID: MagicMock()}

    with (
        patch(
            "custom_components.growspace_manager.services.ai_assistant.GrowAssistant.gather_growspace_data",
            side_effect=Exception("Major Fail"),
        ),
        patch(
            "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse",
            side_effect=Exception("Conv Fail"),
        ),
    ):
        res = await handle_analyze_all_growspaces(
            mock_hass, mock_coordinator, mock_strain_library, call
        )
        assert "Error analyzing growspaces: Conv Fail" in res["response"]
        assert "FACILITY OVERVIEW" in res["response"]


async def test_handle_strain_recommendation_exception_path(
    mock_hass, mock_coordinator, mock_strain_library
) -> None:
    """Test exception fallback in handle_strain_recommendation (covers lines 804-806)."""
    call = ServiceCall(mock_hass, "gsm", "recommend", {})

    with patch(
        "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse",
        side_effect=Exception("Strain Fail"),
    ):
        res = await handle_strain_recommendation(
            mock_hass, mock_coordinator, mock_strain_library, call
        )
        assert "Error getting strain recommendation: Strain Fail" in res["response"]
        assert "AVAILABLE STRAINS" in res["response"]
