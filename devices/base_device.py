"""
Base class for simulated IoT devices.
Handles MQTT communication, LWT availability, NVRAM state persistence,
heartbeat telemetry, and simulated network outages with local fallback execution.
"""

import json
import logging
import os
import time
import threading
from typing import Any, Dict, Optional
import paho.mqtt.client as mqtt

logger = logging.getLogger("BaseDevice")

class BaseDevice:
    def __init__(
        self,
        device_id: str,
        device_type: str,
        name: str,
        broker_host: str = "127.0.0.1",
        broker_port: int = 1883,
        storage_dir: str = "data"
    ):
        self.device_id = device_id
        self.device_type = device_type
        self.name = name
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.storage_path = os.path.join(storage_dir, f"nvram_{device_id}.json")
        self.outage_flag_path = os.path.join(storage_dir, f"outage_{device_id}.flag")
        if os.path.exists(self.outage_flag_path):
            try:
                os.remove(self.outage_flag_path)
            except Exception:
                pass
        
        self.state: Dict[str, Any] = {}
        self.fallback_active: bool = False
        self.fallback_reason: Optional[str] = None
        self.in_outage: bool = False
        self.running: bool = False

        # Load NVRAM state if available
        self.load_nvram()

        # Setup MQTT client
        self.client: Optional[mqtt.Client] = None
        self._init_mqtt()

    def _init_mqtt(self):
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"device_{self.device_id}"
        )
        
        # Last Will and Testament (LWT)
        lwt_payload = json.dumps({
            "status": "offline",
            "device_id": self.device_id,
            "timestamp": time.time(),
            "reason": "connection_lost"
        })
        self.client.will_set(
            topic=f"home/devices/{self.device_id}/availability",
            payload=lwt_payload,
            qos=1,
            retain=True
        )

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    def load_nvram(self):
        """Loads state from local simulated hardware NVRAM flash memory."""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.state.update(data.get("state", {}))
                    self.fallback_active = data.get("fallback_active", False)
                    self.fallback_reason = data.get("fallback_reason", None)
                    logger.info(f"[{self.device_id}] Recovered state from NVRAM: {self.state}")
            except Exception as e:
                logger.warning(f"[{self.device_id}] Failed to load NVRAM: {e}")

    def save_nvram(self):
        """Persists state to local simulated hardware NVRAM flash memory."""
        try:
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            payload = {
                "device_id": self.device_id,
                "device_type": self.device_type,
                "state": self.state,
                "fallback_active": self.fallback_active,
                "fallback_reason": self.fallback_reason,
                "updated_at": time.time()
            }
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            logger.warning(f"[{self.device_id}] Failed to save NVRAM: {e}")

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            logger.info(f"[{self.device_id}] Connected to MQTT Broker successfully.")
            # Clear any stale fallback status from previous session if no outage flag
            if not os.path.exists(self.outage_flag_path):
                self.in_outage = False
                self.fallback_active = False
                self.fallback_reason = None
                self.save_nvram()

            # Publish online availability
            avail_payload = json.dumps({
                "status": "online",
                "device_id": self.device_id,
                "name": self.name,
                "type": self.device_type,
                "timestamp": time.time()
            })
            client.publish(f"home/devices/{self.device_id}/availability", avail_payload, qos=1, retain=True)

            # Subscriptions
            client.subscribe(f"home/devices/{self.device_id}/set", qos=1)
            client.subscribe(f"home/devices/{self.device_id}/simulate_outage", qos=1)
            client.subscribe(f"home/devices/{self.device_id}/local_input", qos=1)

            # Publish initial state
            self.publish_state()
        else:
            logger.error(f"[{self.device_id}] Failed to connect to MQTT broker, rc={rc}")

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None):
        logger.warning(f"[{self.device_id}] Disconnected from MQTT broker (reason: {reason_code})")
        if not self.in_outage and self.running:
            # Unintentional disconnect -> trigger local fallback
            self.trigger_local_fallback("MQTT connection dropped unexpectedly")

    def _on_message(self, client, userdata, message):
        topic = message.topic
        payload_str = message.payload.decode("utf-8", errors="ignore")
        logger.debug(f"[{self.device_id}] Received message on {topic}: {payload_str}")

        try:
            data = json.loads(payload_str) if payload_str else {}
        except Exception:
            data = {"raw": payload_str}

        if topic == f"home/devices/{self.device_id}/set":
            if not self.in_outage:
                self.handle_command(data)
            else:
                logger.warning(f"[{self.device_id}] Ignored remote command during network outage: {data}")

        elif topic == f"home/devices/{self.device_id}/simulate_outage":
            enable_outage = data.get("outage", True)
            if enable_outage:
                self.simulate_network_outage()
            else:
                self.restore_network()

        elif topic == f"home/devices/{self.device_id}/local_input":
            # Local physical user interface (e.g. wall switch pressed, lock keypad PIN typed)
            self.handle_local_input(data)

    def publish_state(self):
        """Publishes current device state over MQTT to home/devices/{id}/state."""
        if not self.client or not self.client.is_connected() or self.in_outage:
            return

        payload = {
            "device_id": self.device_id,
            "device_type": self.device_type,
            "name": self.name,
            "state": self.state,
            "fallback_active": self.fallback_active,
            "fallback_reason": self.fallback_reason,
            "network_status": "offline" if self.in_outage else "online",
            "timestamp": time.time()
        }
        self.client.publish(
            f"home/devices/{self.device_id}/state",
            json.dumps(payload),
            qos=1,
            retain=True
        )

    def simulate_network_outage(self):
        """Simulates complete network isolation / gateway disconnect."""
        if self.in_outage:
            return
        logger.warning(f"[{self.device_id}] !!! SIMULATING NETWORK OUTAGE - Severing MQTT connection !!!")
        self.in_outage = True
        if self.client:
            # Abruptly stop network loop without clean MQTT DISCONNECT packet
            # This makes the broker trigger LWT!
            try:
                self.client.loop_stop()
                if self.client.is_connected():
                    self.client._sock.close()
            except Exception as e:
                logger.debug(f"[{self.device_id}] Socket close: {e}")
        
        # Execute local fallback behavior
        self.trigger_local_fallback("Simulated network outage")

    def restore_network(self):
        """Restores network connectivity and reconciles state with MQTT broker."""
        if not self.in_outage:
            return
        logger.info(f"[{self.device_id}] +++ Restoring network connectivity +++")
        self.in_outage = False
        self.fallback_active = False
        self.fallback_reason = None
        self.save_nvram()

        # Re-initialize client to connect cleanly
        self._init_mqtt()
        try:
            self.client.connect(self.broker_host, self.broker_port, keepalive=60)
            self.client.loop_start()
        except Exception as e:
            logger.error(f"[{self.device_id}] Error reconnecting: {e}")

    def trigger_local_fallback(self, reason: str):
        """Invoked when connection is lost. Subclasses implement device-specific safe states."""
        self.fallback_active = True
        self.fallback_reason = reason
        self.execute_local_fallback()
        self.save_nvram()

    def execute_local_fallback(self):
        """Override in subclasses to provide domain-specific autonomous behavior."""
        pass

    def handle_command(self, command: Dict[str, Any]):
        """Override in subclasses to handle incoming MQTT commands."""
        pass

    def handle_local_input(self, input_data: Dict[str, Any]):
        """Override in subclasses to handle physical switches/keypad."""
        pass

    def check_outage_flag(self):
        """Monitors simulated physical link status via flag file."""
        flag_exists = os.path.exists(self.outage_flag_path)
        if flag_exists and not self.in_outage:
            self.simulate_network_outage()
        elif not flag_exists and self.in_outage:
            self.restore_network()

    def start(self):
        self.running = True
        logger.info(f"Starting {self.name} ({self.device_id})...")
        try:
            self.client.connect(self.broker_host, self.broker_port, keepalive=60)
            self.client.loop_start()
        except Exception as e:
            logger.warning(f"[{self.device_id}] Initial connection failed: {e}. Will retry...")
            # Still run fallback if network initially unavailable
            self.trigger_local_fallback("Initial broker connection unavailable")

        # Background maintenance/heartbeat thread
        while self.running:
            try:
                self.check_outage_flag()
                self.tick()
                time.sleep(0.05)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"[{self.device_id}] Loop error: {e}")

    def tick(self):
        """Periodic device cycle (override for timers, auto-lock countdowns, telemetry)."""
        pass

    def stop(self):
        self.running = False
        if self.client:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass
        self.save_nvram()
        logger.info(f"[{self.device_id}] Stopped.")
