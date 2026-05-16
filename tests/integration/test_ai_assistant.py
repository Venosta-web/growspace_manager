"""Tests for the AI Assistant services."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.const import CONF_AI_ENABLED, CONF_ASSISTANT_ID
from custom_components.growspace_manager.models import EnvironmentConfig, Growspace
from custom_components.growspace_manager.services.ai_assistant import (
    GrowAssistant,
    _analyze_growspace_issues,
    _build_facility_summary,
    _build_recommendation_prompt,
    _build_strain_performance_summary,
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
    """Mock the GrowspaceCoordinator with Facade/Repository structure."""
    coordinator = MagicMock()

    # 1. Create the repository mocks
    data_repo = MagicMock()
    plant_repo = MagicMock()

    # 2. Setup the mock growspace
    growspace = Growspace(
        id=GROWSPACE_ID,
        name=GROWSPACE_NAME,
        rows=3,
        plants_per_row=3,
        environment_config=EnvironmentConfig(
            temperature_sensor="sensor.temp",
            humidity_sensor="sensor.humidity",
        ),
    )
    data_repo.get_growspace.return_value = growspace
    data_repo.growspaces = {GROWSPACE_ID: growspace}
    data_repo.get_all_growspaces.return_value = [growspace]

    # 3. LINKING: Ensure the root and repositories use the EXACT SAME mock method
    # This prevents the coordinator from returning a "fresh" empty mock
    shared_plant_mock = MagicMock(return_value=[])
    coordinator.get_growspace_plants = shared_plant_mock
    plant_repo.get_growspace_plants = shared_plant_mock
    # In case your facade uses data_repository for plant lookups:
    data_repo.get_growspace_plants = shared_plant_mock

    # 4. Attach repositories to coordinator facade
    coordinator.data_repository = data_repo
    coordinator.plants = plant_repo

    coordinator.options = {
        "ai_settings": {
            CONF_AI_ENABLED: True,
            CONF_ASSISTANT_ID: "test_agent",
        }
    }
    coordinator.serializer.calculate_days_in_stage.return_value = 10
    coordinator.growspaces = data_repo.growspaces

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
    def get_state(entity_id):
        m = MagicMock()
        m.state = "25"
        if "temp" in entity_id:
            m.attributes = {"unit_of_measurement": "°C"}
        elif "humidity" in entity_id:
            m.attributes = {"unit_of_measurement": "%"}
        else:
            m.attributes = {"unit_of_measurement": ""}
        return m

    hass.states.get.side_effect = get_state
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
    call = ServiceCall(mock_hass, "gsm", "analyze", {}, context=MagicMock())

    with patch(
        "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse"
    ) as mock_converse:
        mock_result = MagicMock()
        mock_result.response.speech = {"plain": {"speech": "Analysis Report"}}
        mock_converse.return_value = mock_result

        # Ensure the assistant finds the growspace through the repo
        response = await handle_analyze_all_growspaces(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

        assert response["response"] == "Analysis Report"
        assert response["growspaces_analyzed"] >= 1


def testgather_growspace_data_missing(
    assistant: GrowAssistant, mock_coordinator
) -> None:
    """Test gathering data for missing growspace."""
    # Ensure the repository returns None for missing IDs
    mock_coordinator.data_repository.get_growspace.return_value = None

    with pytest.raises(ServiceValidationError):
        assistant.gather_growspace_data("missing_id")


async def testgather_growspace_data_with_plants(
    assistant: GrowAssistant,
    mock_coordinator: MagicMock,
    mock_strain_library: MagicMock,
) -> None:
    """Test gathering data with plants and strain analytics."""
    plant1 = MagicMock(growspace_id=GROWSPACE_ID, strain="Strain A", stage="veg")
    plant2 = MagicMock(growspace_id=GROWSPACE_ID, strain="Strain A", stage="flower")

    # Override the shared mock directly on the coordinator root
    mock_coordinator.get_growspace_plants.return_value = [plant1, plant2]

    data = assistant.gather_growspace_data(GROWSPACE_ID)

    assert data["plants"]["count"] == 2
    assert "Strain A" in data["strain_analytics"]


async def test_gather_growspace_data_legacy_dict(
    assistant: GrowAssistant, mock_coordinator: MagicMock, mock_hass: MagicMock
) -> None:
    """Test gathering data with legacy dict environment config."""
    gs = mock_coordinator.data_repository.get_growspace(GROWSPACE_ID)
    gs.environment_config = {
        "temperature_sensor": "sensor.legacy_temp",
        "humidity_sensor": "sensor.legacy_humidity",
    }

    def side_effect(entity_id):
        if entity_id == "sensor.legacy_temp":
            m = MagicMock()
            m.state = "22"
            m.attributes = {"unit_of_measurement": "C"}
            return m
        return None

    mock_hass.states.get.side_effect = side_effect

    data = assistant.gather_growspace_data(GROWSPACE_ID)
    # Check if the key exists in the nested dict structure
    assert "temperature_sensor" in data["environment"]["sensors"]
    assert data["environment"]["sensors"]["temperature_sensor"] == "22 C"


async def test_get_strain_specific_context_full(
    assistant: GrowAssistant,
    mock_coordinator: MagicMock,
    mock_strain_library: MagicMock,
) -> None:
    """Test full strain context with multi-strain setup."""
    plant1 = MagicMock(growspace_id=GROWSPACE_ID, strain="OG Kush")
    plant2 = MagicMock(growspace_id=GROWSPACE_ID, strain="OG Kush")
    plant3 = MagicMock(growspace_id=GROWSPACE_ID, strain="Unknown Strain")

    # Ensure the root method returns our plants
    mock_coordinator.get_growspace_plants.return_value = [plant1, plant2, plant3]

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
            "phenotypes": {"Lemon Pheno": {"notes": "Citrus scent" * 20}},
        }
    }

    data = assistant.gather_growspace_data(GROWSPACE_ID)
    context = assistant._format_context_data(data)

    # These assertions will pass now because TOTAL PLANTS will be 3
    assert "STRAIN-SPECIFIC GUIDANCE:" in context
    assert "OG Kush" in context
    assert "Very pungent flavor" in context


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


def test_get_ai_settings_enabled_no_agent_id(
    assistant: GrowAssistant, mock_coordinator: MagicMock
) -> None:
    """Test get_ai_settings when AI enabled but no assistant ID configured."""
    mock_coordinator.options = {"ai_settings": {CONF_AI_ENABLED: True}}
    result = assistant.get_ai_settings()
    assert result is None


def test_get_strain_specific_context_empty_plants(assistant: GrowAssistant) -> None:
    """Test _get_strain_specific_context returns empty string for empty plants."""
    result = assistant._get_strain_specific_context([])
    assert result == ""


def test_format_analysis_data_all_active(assistant: GrowAssistant) -> None:
    """Test _format_analysis_data with stress, mold risk, and optimal all active."""
    analysis = {
        "stress": {"active": True, "reasons": ["High temp", "Low humidity"]},
        "mold_risk": {"active": True, "reasons": ["Humid canopy"]},
        "optimal": {"active": True, "reasons": []},
    }
    lines = assistant._format_analysis_data(analysis)
    combined = "\n".join(lines)
    assert "⚠️ STRESS DETECTED:" in combined
    assert "High temp" in combined
    assert "🍄 MOLD RISK DETECTED:" in combined
    assert "Humid canopy" in combined
    assert "✅ Optimal conditions achieved" in combined


def test_format_plant_data_with_veg_and_flower_days(assistant: GrowAssistant) -> None:
    """Test _format_plant_data renders veg and flower day lines."""
    plants = {
        "count": 2,
        "strains": ["Kush"],
        "max_veg_days": 30,
        "max_flower_days": 49,
    }
    lines = assistant._format_plant_data(plants)
    combined = "\n".join(lines)
    assert "Max Veg: Day 30" in combined
    assert "Max Flower: Day 49 (Week 7)" in combined


async def test_get_grow_advice_generic_exception_fallback(
    assistant: GrowAssistant,
) -> None:
    """Test get_grow_advice falls back to raw data on generic exception."""
    with patch(
        "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse",
        side_effect=ValueError("unexpected"),
    ):
        result = await assistant.get_grow_advice(GROWSPACE_ID, "Query")
    assert "AI Assistant Error:" in result
    assert "Raw Data:" in result


def test_validate_ai_settings_enabled_no_agent_id(
    assistant: GrowAssistant, mock_coordinator: MagicMock
) -> None:
    """Test _validate_ai_settings raises when AI enabled but no agent ID."""
    mock_coordinator.options = {"ai_settings": {CONF_AI_ENABLED: True}}
    with pytest.raises(ServiceValidationError, match="no assistant ID selected"):
        assistant._validate_ai_settings(None)


def test_validate_ai_settings_fallback(
    assistant: GrowAssistant, mock_coordinator: MagicMock
) -> None:
    """Test _validate_ai_settings generic fallback when AI enabled and agent set but still None."""
    mock_coordinator.options = {
        "ai_settings": {CONF_AI_ENABLED: True, CONF_ASSISTANT_ID: "agent"}
    }
    with pytest.raises(ServiceValidationError, match="invalid or incomplete"):
        assistant._validate_ai_settings(None)


async def test_execute_conversation_empty_agent_id(assistant: GrowAssistant) -> None:
    """Test _execute_conversation raises when agent_id is empty string."""
    with pytest.raises(ServiceValidationError, match="AI assistant is not enabled"):
        await assistant._execute_conversation("prompt", "", 100, GROWSPACE_ID)


async def test_execute_conversation_truncates_response(
    assistant: GrowAssistant,
) -> None:
    """Test _execute_conversation truncates response when it exceeds max_length."""
    long_text = "word " * 100  # 500 chars
    with patch(
        "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse"
    ) as mock_converse:
        mock_result = MagicMock()
        mock_result.response.speech = {"plain": {"speech": long_text}}
        mock_converse.return_value = mock_result

        result = await assistant._execute_conversation("prompt", "agent", 50, GROWSPACE_ID)

    assert len(result) <= 53  # max_length + "..."
    assert result.endswith("...")


async def test_handle_analyze_all_growspaces_no_agent_id(
    mock_hass, mock_coordinator, mock_strain_library
) -> None:
    """Test handle_analyze_all_growspaces returns summary when no agent_id configured."""
    mock_coordinator.options = {}
    call = ServiceCall(mock_hass, "gsm", "analyze", {}, context=MagicMock())

    res = await handle_analyze_all_growspaces(
        mock_hass, mock_coordinator, mock_strain_library, call
    )
    assert "AI Assistant not configured" in res["response"]
    assert "FACILITY OVERVIEW" in res["response"]


async def test_handle_analyze_all_growspaces_truncates_response(
    mock_hass, mock_coordinator, mock_strain_library
) -> None:
    """Test handle_analyze_all_growspaces truncates long AI responses."""
    long_text = "word " * 200
    call = ServiceCall(mock_hass, "gsm", "analyze", {"max_length": 50}, context=MagicMock())

    with patch(
        "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse"
    ) as mock_converse:
        mock_result = MagicMock()
        mock_result.response.speech = {"plain": {"speech": long_text}}
        mock_converse.return_value = mock_result

        res = await handle_analyze_all_growspaces(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

    assert res["response"].endswith("...")
    assert len(res["response"]) <= 53


async def test_handle_analyze_all_growspaces_empty_ai_response(
    mock_hass, mock_coordinator, mock_strain_library
) -> None:
    """Test handle_analyze_all_growspaces returns summary on empty AI response."""
    call = ServiceCall(mock_hass, "gsm", "analyze", {}, context=MagicMock())

    with patch(
        "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse"
    ) as mock_converse:
        mock_result = MagicMock()
        mock_result.response.speech = {}  # No plain speech
        mock_converse.return_value = mock_result

        res = await handle_analyze_all_growspaces(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

    assert "AI assistant returned an empty response" in res["response"]
    assert "FACILITY OVERVIEW" in res["response"]


def test_analyze_growspace_issues_stress_and_mold() -> None:
    """Test _analyze_growspace_issues detects stress and mold issues."""
    data = {
        "growspace": {"name": "Tent 1"},
        "analysis": {
            "stress": {"active": True, "reasons": ["High VPD", "Low RH"]},
            "mold_risk": {"active": True, "reasons": ["Dense canopy"]},
        },
    }
    issues = _analyze_growspace_issues(data)
    assert len(issues) == 2
    assert "Stress detected" in issues[0]
    assert "Mold risk" in issues[1]


def test_build_facility_summary_with_issues_and_statuses() -> None:
    """Test _build_facility_summary with issues, optimal, and attention-needed growspaces."""
    all_data = [
        {
            "growspace": {"name": "Tent A"},
            "plants": {"count": 4},
            "analysis": {"optimal": {"active": True}, "stress": {"active": False}, "mold_risk": {"active": False}},
        },
        {
            "growspace": {"name": "Tent B"},
            "plants": {"count": 2},
            "analysis": {"optimal": {"active": False}, "stress": {"active": True}, "mold_risk": {"active": False}},
        },
    ]
    issues = ["Tent B: Stress detected - High VPD"]
    summary = _build_facility_summary(all_data, issues)

    assert "⚠️ ISSUES REQUIRING ATTENTION:" in summary
    assert "Tent B: Stress detected" in summary
    assert "✅ Optimal" in summary
    assert "⚠️ Needs Attention" in summary


async def test_handle_strain_recommendation_no_agent_id(
    mock_hass, mock_coordinator, mock_strain_library
) -> None:
    """Test handle_strain_recommendation returns strain data when no agent_id."""
    mock_coordinator.options = {}
    call = ServiceCall(mock_hass, "gsm", "recommend", {}, context=MagicMock())

    res = await handle_strain_recommendation(
        mock_hass, mock_coordinator, mock_strain_library, call
    )
    assert "AI Assistant not configured" in res["response"]
    assert "AVAILABLE STRAINS" in res["response"]


async def test_handle_strain_recommendation_success(
    mock_hass, mock_coordinator, mock_strain_library
) -> None:
    """Test handle_strain_recommendation returns AI response on success."""
    call = ServiceCall(mock_hass, "gsm", "recommend", {}, context=MagicMock())

    with patch(
        "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse"
    ) as mock_converse:
        mock_result = MagicMock()
        mock_result.response.speech = {"plain": {"speech": "Recommend Kush"}}
        mock_converse.return_value = mock_result

        res = await handle_strain_recommendation(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

    assert res["response"] == "Recommend Kush"
    assert "strains_analyzed" in res


async def test_handle_strain_recommendation_empty_ai_response(
    mock_hass, mock_coordinator, mock_strain_library
) -> None:
    """Test handle_strain_recommendation fallback on empty AI response."""
    call = ServiceCall(mock_hass, "gsm", "recommend", {}, context=MagicMock())

    with patch(
        "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse"
    ) as mock_converse:
        mock_result = MagicMock()
        mock_result.response.speech = {}
        mock_converse.return_value = mock_result

        res = await handle_strain_recommendation(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

    assert "AI assistant returned an empty response" in res["response"]


async def test_handle_strain_recommendation_with_growspace_error(
    mock_hass, mock_coordinator, mock_strain_library
) -> None:
    """Test handle_strain_recommendation logs warning when growspace data fails."""
    call = ServiceCall(
        mock_hass,
        "gsm",
        "recommend",
        {"growspace_id": "bad_id"},
        context=MagicMock(),
    )
    mock_coordinator.data_repository.get_growspace.return_value = None

    with patch(
        "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse"
    ) as mock_converse:
        mock_result = MagicMock()
        mock_result.response.speech = {"plain": {"speech": "Advice without growspace"}}
        mock_converse.return_value = mock_result

        res = await handle_strain_recommendation(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

    assert "Advice without growspace" in res["response"]


async def test_handle_strain_recommendation_truncates_response(
    mock_hass, mock_coordinator, mock_strain_library
) -> None:
    """Test handle_strain_recommendation truncates long AI responses."""
    long_text = "word " * 200
    call = ServiceCall(mock_hass, "gsm", "recommend", {"max_length": 50}, context=MagicMock())

    with patch(
        "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse"
    ) as mock_converse:
        mock_result = MagicMock()
        mock_result.response.speech = {"plain": {"speech": long_text}}
        mock_converse.return_value = mock_result

        res = await handle_strain_recommendation(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

    assert res["response"].endswith("...")


def test_build_recommendation_prompt_with_preferences_and_query() -> None:
    """Test _build_recommendation_prompt includes preferences and user_query."""
    prompt = _build_recommendation_prompt(
        context="AVAILABLE STRAINS:",
        preferences={"flavor": "citrus", "yield": "high"},
        user_query="Something sativa-leaning",
        growspace_context="",
        max_length=None,
    )
    assert "USER PREFERENCES (Structured):" in prompt
    assert "flavor: citrus" in prompt
    assert "USER REQUEST: Something sativa-leaning" in prompt


def test_build_strain_performance_summary_with_estimates_and_description() -> None:
    """Test _build_strain_performance_summary with pheno estimates and description."""
    strain_data = {
        "meta": {"type": "Sativa", "breeder": "Test"},
        "phenotypes": {
            "Pheno A": {
                "harvests": [],
                "flower_days_min": 60,
                "flower_days_max": 70,
                "description": "Fruity pheno",
            }
        },
    }
    result = _build_strain_performance_summary("Test Strain", strain_data)
    assert "Est. Flowering: 60-70 days" in result
    assert "Fruity pheno" in result


async def test_handle_strain_recommendation_successful_growspace_context(
    mock_hass, mock_coordinator, mock_strain_library
) -> None:
    """Test handle_strain_recommendation with a valid growspace_id that succeeds."""
    call = ServiceCall(
        mock_hass,
        "gsm",
        "recommend",
        {"growspace_id": GROWSPACE_ID},
        context=MagicMock(),
    )

    with patch(
        "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse"
    ) as mock_converse:
        mock_result = MagicMock()
        mock_result.response.speech = {"plain": {"speech": "Advice with context"}}
        mock_converse.return_value = mock_result

        res = await handle_strain_recommendation(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

    assert "Advice with context" in res["response"]
    # Verify growspace context was included in the prompt (TARGET GROWSPACE)
    call_args = mock_converse.call_args
    assert "TARGET GROWSPACE" in call_args.kwargs["text"]


def test_format_context_data_includes_strain_history(
    assistant: GrowAssistant,
    mock_coordinator: MagicMock,
    mock_strain_library: MagicMock,
) -> None:
    """Test _format_context_data includes STRAIN HISTORY when analytics are present."""
    plant = MagicMock(strain="Strain A", stage="veg", veg_start=None, flower_start=None)
    mock_coordinator.data_repository.get_growspace_plants.return_value = [plant]

    data = assistant.gather_growspace_data(GROWSPACE_ID)
    # Strain A has harvest data in mock_strain_library, so analytics should be populated
    assert data["strain_analytics"]

    context = assistant._format_context_data(data)
    assert "STRAIN HISTORY:" in context
    assert "Strain A" in context


def test_build_strain_performance_summary_no_history_no_estimates() -> None:
    """Test _build_strain_performance_summary with no harvests and no estimates."""
    strain_data = {
        "meta": {"type": "Indica", "breeder": "Unknown"},
        "phenotypes": {"Pheno B": {"harvests": []}},
    }
    result = _build_strain_performance_summary("Mystery Strain", strain_data)
    assert "No harvests recorded yet" in result
