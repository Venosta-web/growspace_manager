"""Tests for the CropSteeringHistoryAnalyzer helper."""

from collections.abc import Sequence
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun import freeze_time
import pytest

from custom_components.growspace_manager.crop_steering_history import (
    CropSteeringHistoryAnalyzer,
    get_recorder_instance,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationStrategy,
)
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util


@pytest.fixture
def mock_hass():
    """Mock Home Assistant instance."""
    return MagicMock(spec=HomeAssistant)


@pytest.fixture
def analyzer(mock_hass):
    """Fixture for CropSteeringHistoryAnalyzer."""
    return CropSteeringHistoryAnalyzer(mock_hass)


def create_mock_history(
    by_entity: dict[str, Sequence[tuple[datetime, float | str]]],
) -> dict[str, list[State]]:
    """Create a mock get_significant_states-style history dict."""
    history: dict[str, list[State]] = {}
    for entity_id, states in by_entity.items():
        history[entity_id] = [
            State(entity_id, str(value), last_updated=dt) for dt, value in states
        ]
    return history


def test_get_recorder_instance_returns_recorder_for_hass(mock_hass) -> None:
    """get_recorder_instance should defer to the recorder helper's get_instance."""
    with patch("homeassistant.helpers.recorder.get_instance") as mock_get_instance:
        mock_get_instance.return_value = "recorder"

        assert get_recorder_instance(mock_hass) == "recorder"
        mock_get_instance.assert_called_once_with(mock_hass)


@patch(
    "custom_components.growspace_manager.crop_steering_history.get_recorder_instance"
)
@pytest.mark.asyncio
@freeze_time("2026-06-07 10:00:00")
async def test_async_get_history_anchor_prefers_detected_lights_on_time(
    mock_get_recorder, analyzer, mock_hass
) -> None:
    """The lights-on anchor should prefer detected_lights_on_time over lights_on_time."""
    mock_recorder_instance = MagicMock()
    mock_get_recorder.return_value = mock_recorder_instance
    mock_recorder_instance.async_add_executor_job = AsyncMock(return_value={})

    growspace = Growspace(
        id="tent1",
        name="Tent 1",
        environment_config=EnvironmentConfig(),
        irrigation_strategy=IrrigationStrategy(
            lights_on_time="06:00:00",
            detected_lights_on_time="07:00:00",
        ),
    )

    result = await analyzer.async_get_history(growspace)

    assert result["lights_on"] == "2026-06-07T07:00:00+00:00"


@patch(
    "custom_components.growspace_manager.crop_steering_history.get_recorder_instance"
)
@pytest.mark.asyncio
@freeze_time("2026-06-07 10:00:00")
async def test_async_get_history_parses_lights_on_time_without_seconds(
    mock_get_recorder, analyzer, mock_hass
) -> None:
    """A lights-on time given as HH:MM (no seconds) should still be parsed."""
    mock_recorder_instance = MagicMock()
    mock_get_recorder.return_value = mock_recorder_instance
    mock_recorder_instance.async_add_executor_job = AsyncMock(return_value={})

    growspace = Growspace(
        id="tent1",
        name="Tent 1",
        environment_config=EnvironmentConfig(),
        irrigation_strategy=IrrigationStrategy(lights_on_time="06:30"),
    )

    result = await analyzer.async_get_history(growspace)

    assert result["lights_on"] == "2026-06-07T06:30:00+00:00"


@patch(
    "custom_components.growspace_manager.crop_steering_history.get_recorder_instance"
)
@pytest.mark.asyncio
@freeze_time("2026-06-07 06:12:00")
async def test_async_get_history_buckets_soil_moisture_as_simple_mean(
    mock_get_recorder, analyzer, mock_hass
) -> None:
    """Soil moisture readings should be bucketed anchor-relative and averaged."""
    mock_recorder_instance = MagicMock()
    mock_get_recorder.return_value = mock_recorder_instance

    history = create_mock_history(
        {
            "sensor.soil1": [
                (datetime(2026, 6, 7, 4, 1, tzinfo=dt_util.UTC), 10.0),
                (datetime(2026, 6, 7, 4, 3, tzinfo=dt_util.UTC), 20.0),
            ]
        }
    )
    mock_recorder_instance.async_add_executor_job = AsyncMock(return_value=history)

    growspace = Growspace(
        id="tent1",
        name="Tent 1",
        environment_config=EnvironmentConfig(soil_moisture_sensor="sensor.soil1"),
        irrigation_strategy=IrrigationStrategy(lights_on_time="06:00:00"),
    )

    result = await analyzer.async_get_history(growspace)

    assert result["soil_moisture"][0] == {
        "timestamp": "2026-06-07T04:00:00+00:00",
        "value": 15.0,
    }


@patch(
    "custom_components.growspace_manager.crop_steering_history.get_recorder_instance"
)
@pytest.mark.asyncio
@freeze_time("2026-06-07 06:12:00")
async def test_async_get_history_averages_pore_ec_across_sensors_skipping_missing(
    mock_get_recorder, analyzer, mock_hass
) -> None:
    """Pore EC buckets average across sensors; a sensor missing a bucket is skipped."""
    mock_recorder_instance = MagicMock()
    mock_get_recorder.return_value = mock_recorder_instance

    history = create_mock_history(
        {
            "sensor.pore1": [(datetime(2026, 6, 7, 4, 1, tzinfo=dt_util.UTC), 2.0)],
            "sensor.pore2": [
                (datetime(2026, 6, 7, 4, 2, tzinfo=dt_util.UTC), 4.0),
                (datetime(2026, 6, 7, 4, 8, tzinfo=dt_util.UTC), 8.0),
            ],
        }
    )
    mock_recorder_instance.async_add_executor_job = AsyncMock(return_value=history)

    growspace = Growspace(
        id="tent1",
        name="Tent 1",
        environment_config=EnvironmentConfig(
            pore_ec_sensors=["sensor.pore1", "sensor.pore2"]
        ),
        irrigation_strategy=IrrigationStrategy(lights_on_time="06:00:00"),
    )

    result = await analyzer.async_get_history(growspace)

    # Bucket 0 [04:00, 04:05): pore1 -> mean 2.0, pore2 -> mean 4.0, average -> 3.0
    assert result["pore_ec"][0] == {
        "timestamp": "2026-06-07T04:00:00+00:00",
        "value": 3.0,
    }
    # Bucket 1 [04:05, 04:10): pore1 has no reading, only pore2 -> 8.0
    assert result["pore_ec"][1] == {
        "timestamp": "2026-06-07T04:05:00+00:00",
        "value": 8.0,
    }


@patch(
    "custom_components.growspace_manager.crop_steering_history.get_recorder_instance"
)
@pytest.mark.asyncio
@freeze_time("2026-06-07 06:12:00")
async def test_async_get_history_includes_bulk_ec_when_sensors_configured(
    mock_get_recorder, analyzer, mock_hass
) -> None:
    """The bulk_ec key should appear when bulk_ec_sensors are configured."""
    mock_recorder_instance = MagicMock()
    mock_get_recorder.return_value = mock_recorder_instance

    history = create_mock_history(
        {
            "sensor.bulk1": [(datetime(2026, 6, 7, 4, 1, tzinfo=dt_util.UTC), 1.5)],
        }
    )
    mock_recorder_instance.async_add_executor_job = AsyncMock(return_value=history)

    growspace = Growspace(
        id="tent1",
        name="Tent 1",
        environment_config=EnvironmentConfig(bulk_ec_sensors=["sensor.bulk1"]),
        irrigation_strategy=IrrigationStrategy(lights_on_time="06:00:00"),
    )

    result = await analyzer.async_get_history(growspace)

    assert result["bulk_ec"][0] == {
        "timestamp": "2026-06-07T04:00:00+00:00",
        "value": 1.5,
    }


@patch(
    "custom_components.growspace_manager.crop_steering_history.get_recorder_instance"
)
@pytest.mark.asyncio
@freeze_time("2026-06-07 06:12:00")
async def test_async_get_history_clips_buckets_at_now_and_omits_unconfigured_keys(
    mock_get_recorder, analyzer, mock_hass
) -> None:
    """No buckets are fabricated past "now"; pore_ec/bulk_ec are absent when unconfigured."""
    mock_recorder_instance = MagicMock()
    mock_get_recorder.return_value = mock_recorder_instance
    mock_recorder_instance.async_add_executor_job = AsyncMock(return_value={})

    growspace = Growspace(
        id="tent1",
        name="Tent 1",
        environment_config=EnvironmentConfig(soil_moisture_sensor="sensor.soil1"),
        irrigation_strategy=IrrigationStrategy(lights_on_time="06:00:00"),
    )

    result = await analyzer.async_get_history(growspace)

    # Window is [04:00, 06:12) -> last bucket starts at 06:10 (partial, 2 minutes)
    assert result["soil_moisture"][-1]["timestamp"] == "2026-06-07T06:10:00+00:00"
    assert len(result["soil_moisture"]) == 27
    assert "pore_ec" not in result
    assert "bulk_ec" not in result


@patch(
    "custom_components.growspace_manager.crop_steering_history.get_recorder_instance"
)
@pytest.mark.asyncio
@freeze_time("2026-06-07 06:12:00")
async def test_async_get_history_ignores_non_numeric_readings_in_bucket_average(
    mock_get_recorder, analyzer, mock_hass
) -> None:
    """Unknown, unavailable, empty, and non-numeric readings are excluded from buckets."""
    mock_recorder_instance = MagicMock()
    mock_get_recorder.return_value = mock_recorder_instance

    history = create_mock_history(
        {
            "sensor.soil1": [
                (datetime(2026, 6, 7, 4, 1, tzinfo=dt_util.UTC), STATE_UNKNOWN),
                (datetime(2026, 6, 7, 4, 2, tzinfo=dt_util.UTC), STATE_UNAVAILABLE),
                (datetime(2026, 6, 7, 4, 3, tzinfo=dt_util.UTC), ""),
                (datetime(2026, 6, 7, 4, 4, tzinfo=dt_util.UTC), "not_a_number"),
                (datetime(2026, 6, 7, 4, 4, 30, tzinfo=dt_util.UTC), "12.5"),
            ]
        }
    )
    mock_recorder_instance.async_add_executor_job = AsyncMock(return_value=history)

    growspace = Growspace(
        id="tent1",
        name="Tent 1",
        environment_config=EnvironmentConfig(soil_moisture_sensor="sensor.soil1"),
        irrigation_strategy=IrrigationStrategy(lights_on_time="06:00:00"),
    )

    result = await analyzer.async_get_history(growspace)

    assert result["soil_moisture"][0] == {
        "timestamp": "2026-06-07T04:00:00+00:00",
        "value": 12.5,
    }
