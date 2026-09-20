"""
Test suite for IoT device models, local fallback behavior, and NVRAM persistence.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from devices.device_light import SmartLightDevice
from devices.device_fan import SmartFanDevice
from devices.device_lock import SmartLockDevice


def test_device_light_logic():
    # Clean test nvram
    nvram_file = "data/nvram_test_light.json"
    if os.path.exists(nvram_file):
        os.remove(nvram_file)

    light = SmartLightDevice(device_id="test_light", name="Test Light")
    assert light.state["power"] == "OFF"
    assert light.state["wattage"] == 0.0

    # Command ON with 50% brightness
    light.handle_command({"power": "ON", "brightness": 50})
    assert light.state["power"] == "ON"
    assert light.state["brightness"] == 50
    assert light.state["wattage"] > 5.0

    # Test Local Fallback (Emergency Safety Lighting)
    light.trigger_local_fallback("Simulated outage")
    assert light.fallback_active is True
    assert light.state["power"] == "ON"
    assert light.state["brightness"] == 20  # Emergency mode

    # Test NVRAM persistence
    light2 = SmartLightDevice(device_id="test_light", name="Test Light")
    assert light2.state["brightness"] == 20
    assert light2.fallback_active is True
    print("Device Light logic and fallback PASSED!")


def test_device_fan_logic():
    nvram_file = "data/nvram_test_fan.json"
    if os.path.exists(nvram_file):
        os.remove(nvram_file)

    fan = SmartFanDevice(device_id="test_fan", name="Test Fan")
    fan.handle_command({"power": "ON", "speed": 3})
    assert fan.state["speed"] == 3
    assert fan.state["rpm"] == 1150

    # Test Local Fallback
    fan.trigger_local_fallback("Simulated outage")
    assert fan.fallback_active is True
    assert fan.state["speed"] == 1
    assert fan.state["mode"] == "eco"
    assert fan.state["rpm"] == 360
    print("Device Fan logic and fallback PASSED!")


def test_device_lock_logic():
    nvram_file = "data/nvram_test_lock.json"
    if os.path.exists(nvram_file):
        os.remove(nvram_file)

    lock = SmartLockDevice(device_id="test_lock", name="Test Lock")
    assert lock.state["lock_state"] == "LOCKED"
    assert lock.state["bolt_position"] == "extended"

    # Unlock via command
    lock.handle_command({"lock_state": "UNLOCKED"})
    assert lock.state["lock_state"] == "UNLOCKED"
    assert lock.state["bolt_position"] == "retracted"

    # Trigger Fail-Secure Local Fallback
    lock.trigger_local_fallback("Simulated outage")
    assert lock.fallback_active is True
    assert lock._auto_lock_pending is True

    # Fast forward time to trigger auto-lock safety countdown
    lock._auto_lock_deadline = time.time() - 1.0
    lock.tick()
    assert lock.state["lock_state"] == "LOCKED"
    assert lock.state["bolt_position"] == "extended"
    print("Device Lock Fail-Secure Fallback PASSED!")


if __name__ == "__main__":
    test_device_light_logic()
    test_device_fan_logic()
    test_device_lock_logic()
