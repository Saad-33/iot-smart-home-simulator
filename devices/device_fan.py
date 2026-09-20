"""
Simulated Smart Fan Device.
Runs as a separate OS process communicating over MQTT.
Features:
- Power, Speeds (1, 2, 3), Modes ('normal', 'eco', 'breeze')
- Simulated dynamic RPM telemetry
- Local Fallback: Eco Safety Speed (Speed 1, Eco mode) during network outages to prevent motor stalls and conserve energy
- Physical speed toggle simulation via local input.
"""

import argparse
import logging
import os
import sys

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from devices.base_device import BaseDevice

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [SmartFan] %(message)s")
logger = logging.getLogger("SmartFan")


class SmartFanDevice(BaseDevice):
    def __init__(self, device_id: str = "fan_bedroom", name: str = "Bedroom Ceiling Fan", **kwargs):
        super().__init__(device_id, "fan", name, **kwargs)

        if "power" not in self.state:
            self.state = {
                "power": "OFF",
                "speed": 1,
                "mode": "normal",
                "rpm": 0
            }
        self.update_rpm()

    def update_rpm(self):
        if self.state.get("power") == "ON":
            speed = self.state.get("speed", 1)
            rpm_map = {1: 360, 2: 720, 3: 1150}
            self.state["rpm"] = rpm_map.get(speed, 360)
        else:
            self.state["rpm"] = 0

    def handle_command(self, cmd: dict):
        changed = False
        if "power" in cmd and cmd["power"] in ["ON", "OFF"]:
            self.state["power"] = cmd["power"]
            changed = True
        if "speed" in cmd:
            val = max(1, min(3, int(cmd["speed"])))
            self.state["speed"] = val
            if self.state["power"] == "OFF":
                self.state["power"] = "ON"
            changed = True
        if "mode" in cmd and cmd["mode"] in ["normal", "eco", "breeze"]:
            self.state["mode"] = cmd["mode"]
            changed = True

        if changed:
            self.update_rpm()
            self.save_nvram()
            self.publish_state()
            logger.info(f"[{self.device_id}] State updated by remote command: {self.state}")

    def execute_local_fallback(self):
        """
        Local autonomous fallback when broker connection is lost:
        Switches to ECO mode at speed 1 to preserve steady air circulation safely.
        """
        logger.warning(f"[{self.device_id}] Executing Local Fallback: ECO_SAFETY_CIRCULATION (Speed 1, Eco)")
        if self.state["power"] == "ON":
            self.state["speed"] = 1
            self.state["mode"] = "eco"
        self.update_rpm()
        self.save_nvram()

    def handle_local_input(self, input_data: dict):
        """Simulates physical pull-chain / dial on the fan."""
        action = input_data.get("action")
        if action == "cycle_speed":
            if self.state["power"] == "OFF":
                self.state["power"] = "ON"
                self.state["speed"] = 1
            elif self.state["speed"] < 3:
                self.state["speed"] += 1
            else:
                self.state["power"] = "OFF"
                self.state["speed"] = 1
            self.update_rpm()
            self.save_nvram()
            self.publish_state()
            logger.info(f"[{self.device_id}] Local dial cycled -> Power: {self.state['power']}, Speed: {self.state['speed']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulated Smart Fan Process")
    parser.add_argument("--id", default="fan_bedroom", help="Device ID")
    parser.add_argument("--name", default="Bedroom Ceiling Fan", help="Device Name")
    parser.add_argument("--broker", default="127.0.0.1", help="Broker Host")
    parser.add_argument("--port", type=int, default=1883, help="Broker Port")
    args = parser.parse_args()

    device = SmartFanDevice(device_id=args.id, name=args.name, broker_host=args.broker, broker_port=args.port)
    device.start()
