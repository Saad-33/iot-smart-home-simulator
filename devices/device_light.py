"""
Simulated Smart Dimmable Light Device.
Runs as a separate OS process communicating over MQTT.
Features:
- Power, Brightness (0-100), Color Temperature (2700-6500K)
- Dynamic Wattage calculation
- Local Fallback: Failsafe Emergency Glow (20% warm) if disconnected, or maintains local physical switch state.
- Physical switch toggle simulation via local input.
"""

import argparse
import logging
import os
import sys

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from devices.base_device import BaseDevice

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [SmartLight] %(message)s")
logger = logging.getLogger("SmartLight")


class SmartLightDevice(BaseDevice):
    def __init__(self, device_id: str = "light_living_room", name: str = "Living Room Ceiling Light", **kwargs):
        super().__init__(device_id, "light", name, **kwargs)

        # Default state if not in NVRAM
        if "power" not in self.state:
            self.state = {
                "power": "OFF",
                "brightness": 80,
                "color_temp": 3000,
                "wattage": 0.0,
                "local_switch_state": "UP"
            }
        self.update_wattage()

    def update_wattage(self):
        """Calculates power consumption based on brightness and power state."""
        if self.state.get("power") == "ON":
            brightness = self.state.get("brightness", 80)
            # Max 12.0 Watts at 100% brightness
            self.state["wattage"] = round(1.5 + (brightness / 100.0) * 10.5, 1)
        else:
            self.state["wattage"] = 0.0

    def handle_command(self, cmd: dict):
        changed = False
        if "power" in cmd and cmd["power"] in ["ON", "OFF"]:
            self.state["power"] = cmd["power"]
            changed = True
        if "brightness" in cmd:
            val = max(0, min(100, int(cmd["brightness"])))
            self.state["brightness"] = val
            if val > 0 and self.state["power"] == "OFF":
                self.state["power"] = "ON"
            changed = True
        if "color_temp" in cmd:
            val = max(2000, min(6500, int(cmd["color_temp"])))
            self.state["color_temp"] = val
            changed = True

        if changed:
            self.update_wattage()
            self.save_nvram()
            self.publish_state()
            logger.info(f"[{self.device_id}] State updated by remote command: {self.state}")

    def execute_local_fallback(self):
        """
        Local autonomous fallback when broker connection is severed:
        Activates emergency safety mode (ensures at least 20% illumination so occupants aren't left in the dark).
        """
        logger.warning(f"[{self.device_id}] Executing Local Fallback: EMERGENCY_SAFETY_LIGHTING (20% warm)")
        self.state["power"] = "ON"
        self.state["brightness"] = 20
        self.state["color_temp"] = 2700
        self.update_wattage()
        self.save_nvram()

    def handle_local_input(self, input_data: dict):
        """Simulates physical wall switch toggle."""
        action = input_data.get("action")
        if action == "toggle_switch" or "power" in input_data:
            new_power = "OFF" if self.state["power"] == "ON" else "ON"
            self.state["power"] = input_data.get("power", new_power)
            self.update_wattage()
            self.save_nvram()
            self.publish_state()
            logger.info(f"[{self.device_id}] Physical switch toggled locally -> Power is now {self.state['power']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulated Smart Light Process")
    parser.add_argument("--id", default="light_living_room", help="Device ID")
    parser.add_argument("--name", default="Living Room Light", help="Device Name")
    parser.add_argument("--broker", default="127.0.0.1", help="Broker Host")
    parser.add_argument("--port", type=int, default=1883, help="Broker Port")
    args = parser.parse_args()

    device = SmartLightDevice(device_id=args.id, name=args.name, broker_host=args.broker, broker_port=args.port)
    device.start()
