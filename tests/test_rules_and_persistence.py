"""
Test suite for Automation Rules Engine, Manual Override Precedence, and SQLite State Persistence.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from controller.storage import Database
from controller.rules_engine import RulesEngine


def test_rules_and_manual_override_precedence():
    test_db = "data/test_home_automation.db"
    if os.path.exists(test_db):
        os.remove(test_db)

    db = Database(test_db)
    dispatched_commands = []

    def dispatch_cb(device_id, cmd, source):
        dispatched_commands.append((device_id, cmd, source))

    rules_engine = RulesEngine(db, dispatch_cb)

    # Initial device states in memory
    devices = {
        "light_living_room": {
            "device_id": "light_living_room",
            "state": {"power": "OFF", "brightness": 80},
            "network_status": "online"
        },
        "sensors_living_room": {
            "device_id": "sensors_living_room",
            "state": {"motion": False, "illuminance_lux": 20, "temperature": 21.0}
        },
        "fan_bedroom": {
            "device_id": "fan_bedroom",
            "state": {"power": "OFF", "speed": 1}
        },
        "lock_front_door": {
            "device_id": "lock_front_door",
            "state": {"lock_state": "LOCKED", "last_unlocked_at": 0}
        }
    }

    # Save to DB
    for dev_id, dev_data in devices.items():
        db.save_device_state(dev_id, "type", dev_id, dev_data["state"], "online", False)

    # 1. No motion -> Rule should not trigger
    rules_engine.evaluate(devices)
    assert len(dispatched_commands) == 0, "Rule triggered without motion!"

    # 2. Trigger motion in dark room (20 lux <= 40 lux)
    devices["sensors_living_room"]["state"]["motion"] = True
    rules_engine.evaluate(devices)
    assert len(dispatched_commands) == 1
    assert dispatched_commands[0][0] == "light_living_room"
    assert dispatched_commands[0][1]["power"] == "ON"
    print("Test 1: Motion lighting rule triggered successfully.")

    # 3. Apply MANUAL OVERRIDE on Light: User explicitly wants light OFF!
    dispatched_commands.clear()
    db.set_manual_override("light_living_room", {"power": "OFF"}, duration_seconds=60, reason="User wants dark room")
    # Simulate light is currently OFF per user request
    devices["light_living_room"]["state"]["power"] = "OFF"
    db.save_device_state("light_living_room", "light", "Living Room Light", devices["light_living_room"]["state"], "online", False)

    # Trigger motion again -> RULE MUST BE SUPPRESSED BY MANUAL OVERRIDE!
    rules_engine.evaluate(devices)
    assert len(dispatched_commands) == 0, "Rule violated manual override precedence!"
    print("Test 2: Manual override PREVENTED automated rule from turning light on! (Precedence verified)")

    # 4. Clear Manual Override -> Now motion should fire rule again
    db.clear_manual_override("light_living_room")
    rules_engine.evaluate(devices)
    assert len(dispatched_commands) == 1
    assert dispatched_commands[0][0] == "light_living_room"
    assert dispatched_commands[0][1]["power"] == "ON"
    print("Test 3: After clearing manual override, automation resumed.")

    # 5. Climate rule test (temperature > 25°C -> fan on speed 2)
    dispatched_commands.clear()
    devices["sensors_living_room"]["state"]["motion"] = False
    devices["sensors_living_room"]["state"]["temperature"] = 27.5
    rules_engine.evaluate(devices)
    assert len(dispatched_commands) == 1
    assert dispatched_commands[0][0] == "fan_bedroom"
    assert dispatched_commands[0][1]["power"] == "ON"
    assert dispatched_commands[0][1]["speed"] == 2
    print("Test 4: Climate comfort rule triggered fan.")

    # 6. Tamper alarm test
    dispatched_commands.clear()
    devices["lock_front_door"]["state"]["tamper_detected"] = True
    rules_engine.evaluate(devices)
    tamper_targets = [cmd[0] for cmd in dispatched_commands]
    assert "lock_front_door" in tamper_targets
    assert "light_living_room" in tamper_targets
    print("Test 5: Tamper lockdown alarm triggered.")

    # 7. Persistence and Recovery Test
    # Set an override, then re-instantiate Database from disk
    db.set_manual_override("fan_bedroom", {"speed": 3}, duration_seconds=300, reason="User max speed")
    db_reloaded = Database(test_db)
    override = db_reloaded.get_manual_override("fan_bedroom")
    assert override is not None
    assert override["target_state"]["speed"] == 3
    assert override["reason"] == "User max speed"

    states = db_reloaded.get_all_device_states()
    assert "light_living_room" in states
    assert "sensors_living_room" in states
    print("Test 6: SQLite State Persistence & System Recovery verified.")


if __name__ == "__main__":
    test_rules_and_manual_override_precedence()
