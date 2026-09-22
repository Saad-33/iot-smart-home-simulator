"""
Central Home Automation Controller Daemon.
Coordinates MQTT communication, state persistence, rules engine,
manual overrides, scene scheduling, and network outage handling.
"""

import json
import logging
import os
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional
import paho.mqtt.client as mqtt

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from controller.storage import Database
from controller.rules_engine import RulesEngine
from controller.scheduler import SceneScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [Controller] %(message)s")
logger = logging.getLogger("Controller")


class HomeController:
    def __init__(
        self,
        broker_host: str = "127.0.0.1",
        broker_port: int = 1883,
        db_path: str = "data/home_automation.db"
    ):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.db = Database(db_path)

        # In-memory mirror of digital twin states
        self.devices: Dict[str, Dict[str, Any]] = self.db.get_all_device_states()
        logger.info(f"Restored {len(self.devices)} device states from database.")

        # Subsystems
        self.rules_engine = RulesEngine(self.db, self.dispatch_command)
        self.scheduler = SceneScheduler(
            self.db,
            self.dispatch_command,
            clear_override_cb=self.clear_manual_override,
            scene_notify_cb=lambda s_id, s_data: self.notify_listeners("scene_update", {"scene_id": s_id, "name": s_data.get("name", s_id)})
        )

        # Listeners for real-time WebSockets
        self._update_listeners: List[Callable[[Dict[str, Any]], None]] = []

        # MQTT Client
        self.mqtt_client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="home_controller_daemon"
        )
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message
        self.mqtt_client.on_disconnect = self._on_disconnect

        self.running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._wake_event = threading.Event()

    def add_update_listener(self, listener: Callable[[Dict[str, Any]], None]):
        self._update_listeners.append(listener)

    def notify_listeners(self, event_type: str, data: Any):
        payload = {"event": event_type, "data": data, "timestamp": time.time()}
        for cb in self._update_listeners:
            try:
                cb(payload)
            except Exception as e:
                logger.debug(f"Error calling listener: {e}")

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            logger.info("Controller connected to MQTT Broker.")
            # Subscribe to all device states, availability, and sensor telemetry
            client.subscribe("home/devices/+/state", qos=1)
            client.subscribe("home/devices/+/availability", qos=1)
            client.subscribe("home/sensors/+/state", qos=1)
            client.subscribe("home/controller/command", qos=1)
            self.db.log_event("CONTROLLER_ONLINE", "Controller", "Controller connected to MQTT Broker")
        else:
            logger.error(f"Controller failed to connect to broker, rc={rc}")

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None):
        logger.warning(f"Controller disconnected from MQTT Broker (reason {reason_code})")

    def _on_message(self, client, userdata, message):
        topic = message.topic
        payload_str = message.payload.decode("utf-8", errors="ignore")
        try:
            data = json.loads(payload_str) if payload_str else {}
        except Exception:
            data = {}

        parts = topic.split("/")
        if len(parts) >= 4 and parts[1] == "devices":
            device_id = parts[2]
            msg_type = parts[3]

            if msg_type == "state":
                self._handle_device_state(device_id, data)
            elif msg_type == "availability":
                self._handle_device_availability(device_id, data)

        elif len(parts) >= 4 and parts[1] == "sensors":
            sensor_id = parts[2]
            if parts[3] == "state":
                self._handle_sensor_state(sensor_id, data)

    def _handle_device_state(self, device_id: str, data: Dict[str, Any]):
        state = data.get("state", {})
        dev_type = data.get("device_type", "unknown")
        name = data.get("name", device_id)
        fallback_active = data.get("fallback_active", False)
        fallback_reason = data.get("fallback_reason")
        net_status = data.get("network_status", "online")

        # Update in-memory twin
        if device_id not in self.devices:
            self.devices[device_id] = {}

        self.devices[device_id].update({
            "device_id": device_id,
            "device_type": dev_type,
            "name": name,
            "state": state,
            "network_status": net_status,
            "fallback_active": fallback_active,
            "fallback_reason": fallback_reason,
            "updated_at": time.time()
        })

        # Persist to SQLite
        self.db.save_device_state(
            device_id, dev_type, name, state, net_status, fallback_active, fallback_reason
        )

        # Notify UI
        if dev_type == "sensor":
            self.notify_listeners("sensor_state", self.devices[device_id])
        else:
            self.notify_listeners("device_state", self.devices[device_id])

        # Evaluate automation rules
        self.rules_engine.evaluate(self.devices)

    def _handle_device_availability(self, device_id: str, data: Dict[str, Any]):
        status = data.get("status", "unknown")
        logger.info(f"Availability update for '{device_id}': {status}")

        if device_id in self.devices:
            self.devices[device_id]["network_status"] = status
            self.db.save_device_state(
                device_id,
                self.devices[device_id].get("device_type", "unknown"),
                self.devices[device_id].get("name", device_id),
                self.devices[device_id].get("state", {}),
                status,
                self.devices[device_id].get("fallback_active", False),
                self.devices[device_id].get("fallback_reason")
            )

        if status == "offline":
            self.db.log_event("DEVICE_OFFLINE", "Availability", f"Device '{device_id}' went offline (LWT trigger)", data)
        else:
            self.db.log_event("DEVICE_ONLINE", "Availability", f"Device '{device_id}' connected online", data)

        self.notify_listeners("availability", {"device_id": device_id, "status": status})

    def _handle_sensor_state(self, sensor_id: str, data: Dict[str, Any]):
        state = data.get("state", data)
        if sensor_id not in self.devices:
            self.devices[sensor_id] = {
                "device_id": sensor_id,
                "device_type": "sensor",
                "name": data.get("name", sensor_id),
                "state": state,
                "network_status": "online",
                "fallback_active": False,
                "updated_at": time.time()
            }
        else:
            self.devices[sensor_id]["state"] = state
            self.devices[sensor_id]["updated_at"] = time.time()

        self.db.save_device_state(
            sensor_id, "sensor", self.devices[sensor_id]["name"],
            state, "online", False
        )

        self.notify_listeners("sensor_state", self.devices[sensor_id])
        self.rules_engine.evaluate(self.devices)

    def dispatch_command(self, device_id: str, command: Dict[str, Any], source: str = "controller"):
        """Sends MQTT command to device."""
        if not self.mqtt_client.is_connected():
            logger.warning(f"Cannot dispatch command; MQTT broker not connected: {command}")
            return

        topic = f"home/devices/{device_id}/set"
        payload = json.dumps(command)
        self.mqtt_client.publish(topic, payload, qos=1)
        logger.info(f"Dispatched command to '{device_id}' from {source}: {payload}")
        self.db.log_event("COMMAND_SENT", source, f"Command sent to {device_id}", {"device_id": device_id, "command": command})

    def set_manual_override(
        self,
        device_id: str,
        target_state: Dict[str, Any],
        duration_seconds: Optional[int] = None,
        reason: str = "Manual User Action"
    ):
        """
        Engages manual override, ensuring automation rules cannot override user choice.
        Sends command to device and persists override to SQLite.
        """
        self.db.set_manual_override(device_id, target_state, duration_seconds, reason)
        self.db.log_event("MANUAL_OVERRIDE_SET", "User", f"Manual override set on '{device_id}'", {
            "device_id": device_id, "target_state": target_state, "duration": duration_seconds, "reason": reason
        })
        # Send command to device
        self.dispatch_command(device_id, target_state, source="manual_override")
        self.notify_listeners("override_update", self.db.get_manual_override(device_id))

    def clear_manual_override(self, device_id: str):
        """Clears manual override and immediately re-evaluates automation rules."""
        self.db.clear_manual_override(device_id)
        self.db.log_event("MANUAL_OVERRIDE_CLEARED", "User", f"Manual override cleared on '{device_id}'", {"device_id": device_id})
        self.notify_listeners("override_update", {"device_id": device_id, "active": False})
        # Re-evaluate rules right away so automation can resume
        self.rules_engine.evaluate(self.devices)

    def simulate_outage(self, device_id: str, outage: bool = True):
        """Sends simulated network outage command to device and updates flag file."""
        flag_path = f"data/outage_{device_id}.flag"
        os.makedirs("data", exist_ok=True)
        if outage:
            try:
                with open(flag_path, "w") as f:
                    f.write("1")
            except Exception as e:
                logger.debug(f"Error writing flag: {e}")
        else:
            if os.path.exists(flag_path):
                try:
                    os.remove(flag_path)
                except Exception as e:
                    logger.debug(f"Error removing flag: {e}")

        # Also publish over MQTT if still connected
        topic = f"home/devices/{device_id}/simulate_outage"
        self.mqtt_client.publish(topic, json.dumps({"outage": outage}), qos=1)
        action_name = "Triggered Outage" if outage else "Restored Network"
        logger.info(f"{action_name} on device '{device_id}'")
        self.db.log_event("OUTAGE_SIMULATION", "Simulator", f"{action_name} on {device_id}", {"device_id": device_id, "outage": outage})

    def simulate_sensor_input(self, sensor_id: str, values: Dict[str, Any]):
        """Injects simulated environment sensor values (temp, motion, lux)."""
        if sensor_id not in self.devices:
            self.devices[sensor_id] = {
                "device_id": sensor_id,
                "device_type": "sensor",
                "name": "Environment Multi-Sensor",
                "state": {},
                "network_status": "online",
                "fallback_active": False,
                "updated_at": time.time()
            }
        self.devices[sensor_id]["state"].update(values)
        self.devices[sensor_id]["updated_at"] = time.time()

        # Persist and notify UI immediately
        self.db.save_device_state(
            sensor_id, "sensor", self.devices[sensor_id].get("name", "Environment Multi-Sensor"),
            self.devices[sensor_id]["state"], "online", False
        )
        self.notify_listeners("sensor_state", self.devices[sensor_id])
        self.rules_engine.evaluate(self.devices)

        # Publish MQTT to synchronize background sensor process
        topic = f"home/devices/{sensor_id}/set"
        self.mqtt_client.publish(topic, json.dumps(values), qos=1)
        self.db.log_event("SENSOR_INJECTED", "Simulator", f"Simulated sensor input on {sensor_id}", values)
        self._wake_event.set()

    def start(self):
        self.running = True
        logger.info("Starting Home Controller Daemon...")
        self.mqtt_client.connect(self.broker_host, self.broker_port, keepalive=60)
        self.mqtt_client.loop_start()

        self._worker_thread = threading.Thread(target=self._loop, daemon=True)
        self._worker_thread.start()

    def _loop(self):
        while self.running:
            try:
                # 1. Periodic rules engine evaluation (for timers like auto-lock)
                self.rules_engine.evaluate(self.devices)

                # 2. Scene scheduler tick
                self.scheduler.tick()

                # 3. Clean up expired manual overrides
                all_overrides = self.db.get_all_manual_overrides()
                # If an override expired, db.get_manual_override clears it and returns None
                for dev_id in list(self.devices.keys()):
                    self.db.get_manual_override(dev_id)

                self._wake_event.wait(timeout=0.1)
                self._wake_event.clear()
            except Exception as e:
                logger.error(f"Controller loop error: {e}")
                time.sleep(0.1)

    def stop(self):
        self.running = False
        self._wake_event.set()
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        logger.info("Home Controller Daemon stopped.")
