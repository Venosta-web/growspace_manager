"""Additional coverage tests for AI Assistant."""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.models import Growspace, Plant
from .conftest import create_plant
from custom_components.growspace_manager.services.ai_assistant import GrowAssistant

GROWSPACE_ID = "gs1"


@pytest.fixture
def mock_deps():
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()  # Ensure states is a mock
    hass.data = {}
    coordinator = MagicMock()
    strain_lib = MagicMock()

    coordinator.growspaces = {
        GROWSPACE_ID: Growspace(id=GROWSPACE_ID, name="GS1", environment_config={})
    }
    # Default options
    coordinator.options = {
        "ai_settings": {"ai_enabled": True, "assistant_id": "agent_id"}
    }

    return hass, coordinator, strain_lib


@pytest.fixture
def assistant(mock_deps):
    return GrowAssistant(*mock_deps)


@pytest.mark.asyncio
async def test_generate_alert_message(assistant) -> None:
    """Test generating a concise alert message."""
    with patch.object(
        assistant, "get_grow_advice", return_value="Fix it now"
    ) as mock_get:
        msg = await assistant.generate_alert_message(
            GROWSPACE_ID, "Mold", ["High Humidity", "No Airflow"]
        )

        assert msg == "Fix it now"
        # Verify call args
        mock_get.assert_awaited_once()
        args, kwargs = mock_get.call_args
        assert kwargs["growspace_id"] == GROWSPACE_ID
        assert kwargs["context_type"] == "diagnostic"
        assert kwargs["max_length"] == 150
        assert "URGENT" in kwargs["user_query"]
        assert "Mold" in kwargs["user_query"]
        assert "High Humidity" in kwargs["user_query"]


def test_build_system_prompt(assistant) -> None:
    """Test system prompt generation for different context types."""
    # General
    p_gen = assistant._build_system_prompt("general")
    assert "expert cannabis cultivation advisor" in p_gen
    assert "Provide practical" in p_gen

    # Diagnostic
    p_diag = assistant._build_system_prompt("diagnostic")
    assert "diagnostics" in p_diag

    # Optimization
    p_opt = assistant._build_system_prompt("optimization")
    assert "optimization" in p_opt

    # Planning
    p_plan = assistant._build_system_prompt("planning")
    assert "planning" in p_plan

    # Fallback
    p_fall = assistant._build_system_prompt("unknown_type")
    assert p_fall == p_gen


def test_build_single_strain_context_minimal(assistant) -> None:
    """Test building strain context with missing metadata."""
    strain_data = {
        "meta": {},  # Empty meta
        "phenotypes": {},
    }

    context = assistant._build_single_strain_context("Minimal Strain", strain_data)
    # Should perform basic formatting even with no data, or return None if really empty logic?
    # Logic:
    # lines = [f"**{strain_name}**:"]
    # ... adds more if exists ...
    # return "\n".join(lines) if len(lines) > 1 else None

    assert context is None


def test_build_single_strain_context_partial(assistant) -> None:
    """Test building strain context with partial metadata."""
    strain_data = {
        "meta": {
            "breeder_notes": "Great strain",
            # No dates, no temps
            "lineage": "A x B",
        },
        "phenotypes": {"Pheno 1": {"notes": "Tall"}},
    }

    context = assistant._build_single_strain_context("Strain A", strain_data)
    assert "**Strain A**:" in context
    assert "Breeder Notes: Great strain" in context
    assert "Lineage: A x B" in context
    assert "Pheno 'Pheno 1': Tall" in context
    # Check missing fields aren't there
    assert "Expected Flowering" not in context
    assert "Ideal Temp" not in context


def test_summarize_plants_no_dates(assistant, mock_deps) -> None:
    """Test summarizing plants that haven't started stages."""
    hass, coordinator, lib = mock_deps

    p1 = create_plant(plant_id="p1", strain="S1", growspace_id=GROWSPACE_ID, stage="veg")
    # p1 has no veg_start or flower_start implicitly (None default)

    summary = assistant._summarize_plants([p1])

    assert summary["count"] == 1
    assert summary["max_veg_days"] == 0
    assert summary["max_flower_days"] == 0


def test_get_strain_analytics_no_harvests(assistant, mock_deps) -> None:
    """Test analytics when strain exists but has no harvest history."""
    hass, coordinator, lib = mock_deps

    # Plant active
    p1 = create_plant(plant_id="p1", strain="S1", growspace_id=GROWSPACE_ID)

    # Library data with no harvests
    lib.get_all.return_value = {
        "S1": {
            "phenotypes": {
                "P1": {"harvests": []}  # Empty harvests
            },
            "meta": {},
        }
    }

    analytics = assistant._get_strain_analytics([p1])

    # S1 should NOT be in analytics because it requires harvests to calculate avg
    assert "S1" not in analytics


def test_get_strain_analytics_missing_strain(assistant, mock_deps) -> None:
    """Test analytics when strain is not in library."""
    hass, coordinator, lib = mock_deps

    p1 = create_plant(plant_id="p1", strain="Unknown Strain", growspace_id=GROWSPACE_ID)
    lib.get_all.return_value = {}

    analytics = assistant._get_strain_analytics([p1])
    assert analytics == {}


@pytest.mark.asyncio
async def test_gather_bayesian_sensor_data_partial(assistant, mock_deps) -> None:
    """Test gathering bayesian data when some sensors are missing."""
    hass, coordinator, lib = mock_deps

    # Mock hass.states.get to return None
    hass.states.get.return_value = None

    data = assistant._gather_bayesian_sensor_data(GROWSPACE_ID)

    assert data["stress"]["active"] is False
    assert data["mold_risk"]["active"] is False
    assert data["light_schedule"]["correct"] is False


def test_build_single_strain_context_full(assistant) -> None:
    """Test building full strain context with all fields."""
    strain_data = {
        "meta": {
            "breeder_notes": "Great strain",
            "flowering_days_min": 60,
            "flowering_days_max": 70,
            "ideal_temp_range": "20-25C",
            "ideal_humidity_range": "40-50%",
            "lineage": "A x B",
        },
        "phenotypes": {"Pheno 1": {"notes": "Tall"}},
    }

    context = assistant._build_single_strain_context("Strain Full", strain_data)

    assert "**Strain Full**:" in context
    assert "Breeder Notes: Great strain" in context
    assert "Expected Flowering: 60-70 days" in context
    assert "Ideal Temp: 20-25C" in context
    assert "Ideal Humidity: 40-50%" in context
    assert "Lineage: A x B" in context
    assert "Pheno 'Pheno 1': Tall" in context


def test_get_strain_specific_context_empty(assistant) -> None:
    """Test getting strain specific context with no plants."""
    context = assistant._get_strain_specific_context([])
    assert context == ""


def test_get_strain_specific_context_integration(assistant, mock_deps) -> None:
    """Test get_strain_specific_context with actual plant data."""
    hass, coordinator, lib = mock_deps

    # Setup plants
    p1 = create_plant(plant_id="p1", strain="Strain A", growspace_id=GROWSPACE_ID)
    p2 = create_plant(
        plant_id="p2", strain="Strain A", growspace_id=GROWSPACE_ID
    )  # Duplicate strain
    p3 = create_plant(plant_id="p3", strain="Strain B", growspace_id=GROWSPACE_ID)

    # Setup library
    lib.get_all.return_value = {
        "Strain A": {"meta": {"breeder_notes": "Note A"}},
        "Strain B": {"meta": {"breeder_notes": "Note B"}},
    }

    context = assistant._get_strain_specific_context([p1, p2, p3])

    assert "**Strain A**" in context
    assert "Note A" in context
    # Should only appear once despite 2 plants
    assert context.count("**Strain A**") == 1

    assert "**Strain B**" in context
    assert "Note B" in context


def test_format_context_data_with_strain_context(assistant, mock_deps) -> None:
    """Test format_context_data including strain guidance."""
    hass, coordinator, lib = mock_deps

    # Setup data
    data = {
        "growspace": {
            "id": GROWSPACE_ID,
            "name": "GS1",
            "size": "3x3",
            "total_plants": 1,
        },
        "environment": {"sensors": {}},
        "analysis": {
            "stress": {"active": False},
            "mold_risk": {"active": False},
            "optimal": {"active": False},
        },
        "plants": {
            "count": 1,
            "strains": ["Strain A"],
            "max_veg_days": 30,
            "max_flower_days": 10,
        },
        "strain_analytics": {},
    }

    # Mock coordinator to return a plant
    coordinator.get_growspace_plants.return_value = [
        create_plant(plant_id="p1", strain="Strain A", growspace_id=GROWSPACE_ID)
    ]

    # Mock library
    lib.get_all.return_value = {"Strain A": {"meta": {"breeder_notes": "Note A"}}}

    formatted = assistant._format_context_data(data)

    assert "STRAIN-SPECIFIC GUIDANCE:" in formatted
    assert "Note A" in formatted
