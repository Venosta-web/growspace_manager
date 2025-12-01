import sys
import os
from unittest.mock import MagicMock, AsyncMock

# Add mock_ha to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "mock_ha")))
sys.path.insert(0, os.getcwd())

# Mock modules that might be missing or problematic
sys.modules["homeassistant.helpers.entity_platform"] = MagicMock()
sys.modules["homeassistant.helpers.device_registry"] = MagicMock()
sys.modules["homeassistant.helpers.event"] = MagicMock()

import asyncio
from custom_components.growspace_manager.binary_sensor import BayesianEnvironmentSensor
from custom_components.growspace_manager.trend_analyzer import TrendAnalyzer
from custom_components.growspace_manager.notification_manager import NotificationManager

async def verify_refactor():
    print("Verifying BayesianEnvironmentSensor refactoring...")

    # Mock Coordinator and Growspace
    hass = MagicMock()
    coordinator = MagicMock()
    coordinator.hass = hass
    growspace = MagicMock()
    growspace.name = "Test Growspace"
    growspace.notification_target = "notify.mobile_app"
    coordinator.growspaces = {"test_id": growspace}
    coordinator.options = {"ai_settings": {}}

    env_config = {
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": "sensor.hum",
        "vpd_sensor": "sensor.vpd",
    }

    # Instantiate Sensor
    sensor = BayesianEnvironmentSensor(
        coordinator,
        "test_id",
        env_config,
        "stress",
        "Stress",
        "prior_stress",
        "stress_threshold",
    )

    # Verify Managers are initialized
    if isinstance(sensor.trend_analyzer, TrendAnalyzer):
        print("✅ TrendAnalyzer initialized correctly")
    else:
        print("❌ TrendAnalyzer NOT initialized")
        return False

    if isinstance(sensor.notification_manager, NotificationManager):
        print("✅ NotificationManager initialized correctly")
    else:
        print("❌ NotificationManager NOT initialized")
        return False

    # Verify Delegation - Trend Analysis
    sensor.trend_analyzer.async_analyze_sensor_trend = AsyncMock(return_value={"trend": "stable"})
    await sensor._async_analyze_sensor_trend("sensor.test", 60, 25.0)
    if sensor.trend_analyzer.async_analyze_sensor_trend.called:
        print("✅ _async_analyze_sensor_trend delegates to TrendAnalyzer")
    else:
        print("❌ _async_analyze_sensor_trend does NOT delegate")
        return False

    # Verify Delegation - Notification
    sensor.notification_manager.generate_notification_message = MagicMock(return_value="Generated Message")
    sensor.notification_manager.async_send_notification = AsyncMock()
    
    msg = sensor._generate_notification_message("Base Message")
    if sensor.notification_manager.generate_notification_message.called:
        print("✅ _generate_notification_message delegates to NotificationManager")
    else:
        print("❌ _generate_notification_message does NOT delegate")
        return False

    sensor._reasons = [] # Ensure no error in logic
    await sensor._send_notification("Title", "Message")
    if sensor.notification_manager.async_send_notification.called:
        print("✅ _send_notification delegates to NotificationManager")
    else:
        print("❌ _send_notification does NOT delegate")
        return False

    print("Verification complete.")
    return True

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    success = loop.run_until_complete(verify_refactor())
    if not success:
        exit(1)
