"""
Simulated Smart Door Lock Device.
Runs as a separate OS process communicating over MQTT.
Features:
- Lock State ('LOCKED', 'UNLOCKED'), Bolt Position ('extended', 'retracted')
- Tamper detection alert
- Battery percentage telemetry
- Local Fallback: FAIL-SECURE Security Policy.
  During network severance, the lock refuses remote commands, initiates an autonomous
  safety auto-lock countdown (securing the deadbolt), and switches to local PIN verification mode.
- Local physical keypad simulation with PIN verification.
"""

import argparse
import logging
import os
import sys
import time

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from devices.base_device import BaseDevice

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [SmartLock] %(message)s")
logger = logging.getLogger("SmartLock")


class SmartLockDevice(BaseDevice):
    def __init__(self, device_id: str = "lock_front_door", name: str = "Front Door Deadbolt", **kwargs):
        super().__init__(device_id, "lock", name, **kwargs)

        if "lock_state" not in self.state:
            self.state = {
                "lock_state": "LOCKED",
                "bolt_position": "extended",
                "tamper_detected": False,
                "battery": 92,
                "local_pin": "1234",
                "last_unlocked_at": 0
            }

        self._auto_lock_pending = False
        self._auto_lock_deadline = 0.0

    def tick(self):
        """Periodic safety tick for auto-lock countdowns and battery simulation."""
        now = time.time()
        # If in outage and unlocked, fail-secure timer triggers lock
        if self._auto_lock_pending and now >= self._auto_lock_deadline:
            logger.warning(f"[{self.device_id}] Fail-Secure Auto-Lock Timer Expired! Engaging physical deadbolt.")
            self.state["lock_state"] = "LOCKED"
            self.state["bolt_position"] = "extended"
            self._auto_lock_pending = False
            self.save_nvram()
            if not self.in_outage:
                self.publish_state()

    def handle_command(self, cmd: dict):
        changed = False
        if "lock_state" in cmd:
            target = cmd["lock_state"]
            if target in ["LOCKED", "UNLOCKED"]:
                self.state["lock_state"] = target
                self.state["bolt_position"] = "extended" if target == "LOCKED" else "retracted"
                if target == "UNLOCKED":
                    self.state["last_unlocked_at"] = time.time()
                changed = True
        
        if "tamper" in cmd:
            self.state["tamper_detected"] = bool(cmd["tamper"])
            changed = True

        if changed:
            self.save_nvram()
            self.publish_state()
            logger.info(f"[{self.device_id}] State updated by remote command: {self.state}")

    def execute_local_fallback(self):
        """
        Local autonomous fallback when broker connection is severed:
        FAIL-SECURE Policy: If unlocked, schedules immediate 5-second auto-lock to secure entry point.
        """
        logger.warning(f"[{self.device_id}] Executing Local Fallback: FAIL_SECURE_ENFORCEMENT")
        if self.state["lock_state"] == "UNLOCKED":
            logger.warning(f"[{self.device_id}] Door is currently UNLOCKED during network drop. Starting 5s fail-secure auto-lock countdown!")
            self._auto_lock_pending = True
            self._auto_lock_deadline = time.time() + 5.0
        else:
            self.state["bolt_position"] = "extended"
        self.save_nvram()

    def handle_local_input(self, input_data: dict):
        """Simulates physical keypad interaction or emergency physical thumbturn."""
        action = input_data.get("action")
        pin = input_data.get("pin")

        if action == "keypad_pin":
            if pin == self.state.get("local_pin", "1234"):
                new_state = "UNLOCKED" if self.state["lock_state"] == "LOCKED" else "LOCKED"
                self.state["lock_state"] = new_state
                self.state["bolt_position"] = "retracted" if new_state == "UNLOCKED" else "extended"
                if new_state == "UNLOCKED":
                    self.state["last_unlocked_at"] = time.time()
                    if self.in_outage:
                        # Even locally unlocked during outage, re-arm fail-secure after 10 seconds
                        self._auto_lock_pending = True
                        self._auto_lock_deadline = time.time() + 10.0
                self.save_nvram()
                self.publish_state()
                logger.info(f"[{self.device_id}] Local Keypad PIN accepted -> Lock is now {self.state['lock_state']}")
            else:
                logger.warning(f"[{self.device_id}] Invalid local keypad PIN attempt!")
        elif action == "manual_thumbturn":
            target = input_data.get("state", "LOCKED")
            self.state["lock_state"] = target
            self.state["bolt_position"] = "extended" if target == "LOCKED" else "retracted"
            self.save_nvram()
            self.publish_state()
            logger.info(f"[{self.device_id}] Physical interior thumbturn turned -> {target}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulated Smart Door Lock Process")
    parser.add_argument("--id", default="lock_front_door", help="Device ID")
    parser.add_argument("--name", default="Front Door Deadbolt", help="Device Name")
    parser.add_argument("--broker", default="127.0.0.1", help="Broker Host")
    parser.add_argument("--port", type=int, default=1883, help="Broker Port")
    args = parser.parse_args()

    device = SmartLockDevice(device_id=args.id, name=args.name, broker_host=args.broker, broker_port=args.port)
    device.start()
