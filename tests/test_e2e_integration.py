"""
End-to-End System Integration Test for Home Automation System.
Verifies:
1. Device models communicating with MQTT broker as separate instances.
2. Central Controller applying rules to sensor feeds.
3. Manual Override precedence strictly beating automation rules.
4. Network Outage simulation and Fail-Secure local fallback on the smart lock.
5. Scene activation (Night / Sleep scene).
6. SQLite state recovery across controller restarts.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import threading
import time
from broker import MQTTBroker
from devices.device_light import SmartLightDevice
from devices.device_fan import SmartFanDevice
from devices.device_lock import SmartLockDevice
from devices.device_sensors import EnvironmentSensors
from controller.controller import HomeController

TEST_PORT = 18884
TEST_DB = "data/e2e_test_automation.db"


def run_e2e_test():
    print("\n--- [E2E TEST] Starting Pure Python MQTT Broker ---")
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    if os.path.exists("data/e2e_retained.json"):
        os.remove("data/e2e_retained.json")

    broker = MQTTBroker(host="127.0.0.1", port=TEST_PORT, storage_path="data/e2e_retained.json")
    loop = asyncio.new_event_loop()
    broker_thread = threading.Thread(target=lambda: loop.run_until_complete(broker.start()), daemon=True)
    broker_thread.start()
    time.sleep(0.5)

    print("--- [E2E TEST] Starting Device Models ---")
    light = SmartLightDevice(device_id="light_living_room", name="Living Room Light", broker_port=TEST_PORT)
    fan = SmartFanDevice(device_id="fan_bedroom", name="Bedroom Fan", broker_port=TEST_PORT)
    lock = SmartLockDevice(device_id="lock_front_door", name="Front Door Deadbolt", broker_port=TEST_PORT)
    sensors = EnvironmentSensors(device_id="sensors_living_room", name="Living Room Sensors", broker_port=TEST_PORT)

    for dev in [light, fan, lock, sensors]:
        t = threading.Thread(target=dev.start, daemon=True)
        t.start()
    time.sleep(0.8)
    lock.handle_command({"tamper": False})

    print("--- [E2E TEST] Starting Home Controller ---")
    controller = HomeController(broker_port=TEST_PORT, db_path=TEST_DB)
    controller.start()
    time.sleep(1.0)

    # 1. Verify all devices registered and online
    assert "light_living_room" in controller.devices, "Light device not registered!"
    assert "fan_bedroom" in controller.devices, "Fan device not registered!"
    assert "lock_front_door" in controller.devices, "Lock device not registered!"
    assert controller.devices["light_living_room"]["network_status"] == "online"
    print("[OK] Step 1: All device models connected to MQTT broker and registered online.")

    # 2. Test Automated Rule: Night Motion Lighting
    print("--- [E2E TEST] Testing Rule: Night Motion Lighting ---")
    # Set sensor to dark room (20 lux) and motion active
    sensors.handle_command({"motion": True, "illuminance_lux": 20})
    time.sleep(1.0)
    # Controller rules engine should have turned light ON
    assert light.state["power"] == "ON", "Automated motion lighting rule failed to turn light ON!"
    print("[OK] Step 2: Automation rule fired and turned Smart Light ON.")

    # 3. Test Manual Override Precedence: User turns light OFF
    print("--- [E2E TEST] Testing Manual Override Precedence ---")
    controller.set_manual_override("light_living_room", {"power": "OFF"}, duration_seconds=60, reason="User manual toggle")
    time.sleep(0.8)
    assert light.state["power"] == "OFF", "Manual override failed to set light OFF!"

    # Trigger motion again -> RULE MUST BE BLOCKED!
    sensors.handle_command({"motion": True, "illuminance_lux": 10})
    time.sleep(1.0)
    assert light.state["power"] == "OFF", "CRITICAL ERROR: Automated rule violated manual override precedence!"
    print("[OK] Step 3: Manual override strictly suppressed automation rule. Light stayed OFF.")

    # 4. Clear Manual Override -> Rule should be able to resume
    controller.clear_manual_override("light_living_room")
    time.sleep(1.0)
    assert light.state["power"] == "ON", "After clearing override, automation failed to resume!"
    print("[OK] Step 4: After clearing manual override, automation resumed.")

    # 5. Test Network Outage & Local Fail-Secure Fallback on Smart Lock
    print("--- [E2E TEST] Testing Network Outage & Fail-Secure Fallback on Lock ---")
    # Unlock door remotely
    controller.dispatch_command("lock_front_door", {"lock_state": "UNLOCKED"})
    time.sleep(0.5)
    assert lock.state["lock_state"] == "UNLOCKED"

    # Simulate network outage on lock
    controller.simulate_outage("lock_front_door", outage=True)
    time.sleep(0.5)
    assert lock.fallback_active is True, "Lock failed to enter fallback mode during outage!"

    # Fail-Secure auto-lock timer
    lock._auto_lock_deadline = time.time() - 1.0  # Fast-forward auto-lock safety countdown
    lock.tick()
    assert lock.state["lock_state"] == "LOCKED", "Lock failed to execute Fail-Secure auto-lock!"
    assert lock.state["bolt_position"] == "extended"
    print("[OK] Step 5: Network outage simulated; Lock entered Fail-Secure fallback and locked deadbolt.")

    # Restore network on lock
    controller.simulate_outage("lock_front_door", outage=False)
    time.sleep(1.0)
    assert lock.fallback_active is False
    print("[OK] Step 6: Network restored; Lock reconciled state.")

    # 6. Test Scene Activation: Night Scene
    print("--- [E2E TEST] Testing Scene Scheduling: Night / Sleep ---")
    # Vacate room and normalize temperature so automation rules do not overwrite night scene
    sensors.handle_command({"motion": False, "temperature": 21.0})
    time.sleep(0.5)
    controller.scheduler.activate_scene("night", force_override=True)
    time.sleep(1.0)
    assert light.state["power"] == "OFF", "Night scene failed to turn off light!"
    assert fan.state["power"] == "ON" and fan.state["speed"] == 1, "Night scene failed to set fan to speed 1!"
    assert lock.state["lock_state"] == "LOCKED", "Night scene failed to lock deadbolt!"
    print("[OK] Step 7: Night scene activated across all devices.")

    # 7. Test SQLite Persistence & Restart Recovery
    print("--- [E2E TEST] Testing Controller Restart & State Recovery ---")
    # Set an override on fan before shutdown
    controller.set_manual_override("fan_bedroom", {"speed": 3}, duration_seconds=180, reason="User wants max cooling")
    controller.stop()
    time.sleep(0.5)

    # Spawn new controller instance using same SQLite DB
    controller_restarted = HomeController(broker_port=TEST_PORT, db_path=TEST_DB)
    controller_restarted.start()
    time.sleep(1.0)

    # Verify state was restored
    recovered_override = controller_restarted.db.get_manual_override("fan_bedroom")
    assert recovered_override is not None, "Manual override not recovered across restart!"
    assert recovered_override["target_state"]["speed"] == 3
    assert "light_living_room" in controller_restarted.devices
    print("[OK] Step 8: Controller restarted and recovered all states and overrides from SQLite.")

    controller_restarted.stop()
    for dev in [light, fan, lock, sensors]:
        dev.stop()

    print("\n=======================================================")
    print("   [SUCCESS] ALL END-TO-END INTEGRATION TESTS PASSED!  ")
    print("=======================================================\n")


if __name__ == "__main__":
    run_e2e_test()
