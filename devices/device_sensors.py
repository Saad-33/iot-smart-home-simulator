"""
Simulated Environmental Sensors Process.
Runs as a separate OS process communicating over MQTT.
Publishes telemetry:
- Temperature (°C)
- Humidity (% RH)
- Motion Occupancy (true/false)
- Ambient Light (lux)
Provides control topic to allow dashboard and test scripts to simulate environmental events.
"""

import argparse
import json
import logging
import os
import sys
import time

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from devices.base_device import BaseDevice

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [Sensors] %(message)s")
logger = logging.getLogger("Sensors")


class EnvironmentSensors(BaseDevice):
    def __init__(self, device_id: str = "sensors_living_room", name: str = "Living Room Multi-Sensor", **kwargs):
        super().__init__(device_id, "sensor", name, **kwargs)

        if "temperature" not in self.state:
            self.state = {
                "temperature": 22.5,
                "humidity": 45,
                "motion": False,
                "illuminance_lux": 150
            }

    def handle_command(self, cmd: dict):
        changed = False
        if "temperature" in cmd:
            self.state["temperature"] = round(float(cmd["temperature"]), 1)
            changed = True
        if "humidity" in cmd:
            self.state["humidity"] = int(cmd["humidity"])
            changed = True
        if "motion" in cmd:
            self.state["motion"] = bool(cmd["motion"])
            changed = True
        if "illuminance_lux" in cmd:
            self.state["illuminance_lux"] = int(cmd["illuminance_lux"])
            changed = True

        if changed:
            self.save_nvram()
            self.publish_state()
            logger.info(f"[{self.device_id}] Sensor values simulated: {self.state}")

    def execute_local_fallback(self):
        logger.warning(f"[{self.device_id}] Environmental sensors running in disconnected buffer mode.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulated Environment Sensors Process")
    parser.add_argument("--id", default="sensors_living_room", help="Device ID")
    parser.add_argument("--name", default="Living Room Multi-Sensor", help="Device Name")
    parser.add_argument("--broker", default="127.0.0.1", help="Broker Host")
    parser.add_argument("--port", type=int, default=1883, help="Broker Port")
    args = parser.parse_args()

    device = EnvironmentSensors(device_id=args.id, name=args.name, broker_host=args.broker, broker_port=args.port)
    device.start()
