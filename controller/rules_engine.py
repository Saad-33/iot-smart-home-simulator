"""
Rules Engine for Home Automation Controller.
Evaluates environment sensor and timer conditions against automation rules.
CRITICAL DESIGN PRINCIPLE: Manual Override Precedence.
If a device has an active manual override, rule actions targeting that device
are strictly suppressed, logged, and will NOT overwrite the user's manual setting.
"""

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from controller.storage import Database

logger = logging.getLogger("RulesEngine")


class RulesEngine:
    def __init__(self, db: Database, dispatch_command_cb: Callable[[str, Dict[str, Any], str], None]):
        """
        :param db: SQLite Database instance
        :param dispatch_command_cb: Callback function (device_id, command_dict, trigger_source)
        """
        self.db = db
        self.dispatch_command = dispatch_command_cb
        self._last_motion_time: float = 0.0

    def evaluate(self, current_devices: Dict[str, Dict[str, Any]]):
        """
        Evaluates all enabled automation rules against the current device states.
        Respects manual override hierarchy.
        """
        self._current_devices = current_devices
        rules = self.db.get_rules()
        now = time.time()

        for rule in rules:
            if not rule.get("enabled", False):
                continue

            rule_id = rule["rule_id"]
            trigger_type = rule["trigger_type"]
            config = rule.get("config", {})

            try:
                if trigger_type == "sensor_motion":
                    self._eval_motion_rule(rule_id, config, current_devices, now)
                elif trigger_type == "sensor_temp":
                    self._eval_climate_rule(rule_id, config, current_devices, now)
                elif trigger_type == "timer_lock":
                    self._eval_auto_lock_rule(rule_id, config, current_devices, now)
                elif trigger_type == "security_tamper":
                    self._eval_tamper_rule(rule_id, config, current_devices, now)
            except Exception as e:
                logger.error(f"Error evaluating rule '{rule_id}': {e}")

    def _eval_motion_rule(
        self, rule_id: str, config: Dict[str, Any], devices: Dict[str, Dict[str, Any]], now: float
    ):
        sensor_id = config.get("sensor_id", "sensors_living_room")
        target_device = config.get("target_device", "light_living_room")
        lux_threshold = config.get("lux_threshold", 40)
        daylight_threshold = config.get("daylight_threshold", 120)
        action = config.get("action", {"power": "ON", "brightness": 60})

        sensor = devices.get(sensor_id, {}).get("state", {})
        motion = sensor.get("motion", False)
        lux = sensor.get("illuminance_lux", 100)

        # Do not interfere if tamper security alarm is active
        if devices.get("lock_front_door", {}).get("state", {}).get("tamper_detected", False):
            return

        # 1. Trigger ON only if motion is detected and room is dark
        if motion and lux <= lux_threshold:
            self._execute_rule_action(rule_id, target_device, action, f"Motion detected in dark room ({lux} lux <= {lux_threshold} lux)")
        # 2. Ambient Daylight Inhibit / Harvesting: Turn OFF when daylight is bright
        elif lux >= daylight_threshold:
            self._execute_rule_action(rule_id, target_device, {"power": "OFF"}, f"Daylight bright ({lux} lux >= {daylight_threshold} lux) -> Auto-Off")

    def _eval_climate_rule(
        self, rule_id: str, config: Dict[str, Any], devices: Dict[str, Dict[str, Any]], now: float
    ):
        sensor_id = config.get("sensor_id", "sensors_living_room")
        target_device = config.get("target_device", "fan_bedroom")
        temp_threshold = config.get("temp_threshold", 25.0)
        action = config.get("action", {"power": "ON", "speed": 2})

        sensor = devices.get(sensor_id, {}).get("state", {})
        temp = sensor.get("temperature", 20.0)

        if temp >= temp_threshold:
            self._execute_rule_action(rule_id, target_device, action, f"Temperature {temp}°C >= {temp_threshold}°C (Cooling Activated)")
        elif temp <= 22.0:
            # When temperature drops back down below 22°C, auto-turn fan OFF if it was in cooling mode (speed 2)
            current_fan = devices.get(target_device, {}).get("state", {})
            if current_fan.get("power") == "ON" and current_fan.get("speed") == action.get("speed", 2):
                self._execute_rule_action(rule_id, target_device, {"power": "OFF"}, f"Temperature {temp}°C cooled below 22.0°C (Auto-Off)")

    def _eval_auto_lock_rule(
        self, rule_id: str, config: Dict[str, Any], devices: Dict[str, Dict[str, Any]], now: float
    ):
        target_device = config.get("target_device", "lock_front_door")
        duration = config.get("unlock_duration_seconds", 20)
        action = config.get("action", {"lock_state": "LOCKED"})

        lock = devices.get(target_device, {}).get("state", {})
        lock_state = lock.get("lock_state", "LOCKED")
        last_unlocked = lock.get("last_unlocked_at", 0)

        if lock_state == "UNLOCKED":
            # If unlocked but no timestamp was recorded, initialize timestamp to now so it locks in 20s
            if not last_unlocked or last_unlocked <= 0:
                last_unlocked = now
                lock["last_unlocked_at"] = now

            elapsed = now - last_unlocked
            if elapsed >= duration:
                # Clear manual override so the lock returns to secured state
                self.db.clear_manual_override(target_device)
                self._execute_rule_action(
                    rule_id, target_device, action,
                    f"Door unlocked for {int(elapsed)}s (threshold: {duration}s)",
                    bypass_override=True
                )

    def _eval_tamper_rule(
        self, rule_id: str, config: Dict[str, Any], devices: Dict[str, Dict[str, Any]], now: float
    ):
        lock_id = config.get("lock_device", "lock_front_door")
        light_id = config.get("light_device", "light_living_room")
        action_light = config.get("action_light", {"power": "ON", "brightness": 100})
        action_lock = config.get("action_lock", {"lock_state": "LOCKED"})

        lock = devices.get(lock_id, {}).get("state", {})
        is_tampered = bool(lock.get("tamper_detected", False))
        if is_tampered:
            if not getattr(self, "_tamper_active", False):
                self._tamper_active = True
                self._execute_rule_action(rule_id, lock_id, action_lock, "Tamper sensor tripped! Immediate lock down", bypass_override=True)
                self._execute_rule_action(rule_id, light_id, action_light, "Tamper alarm strobe lighting", bypass_override=True)
        else:
            self._tamper_active = False

    def _execute_rule_action(
        self, rule_id: str, device_id: str, action: Dict[str, Any], reason: str, bypass_override: bool = False
    ):
        """
        Executes action only if Manual Override is NOT active (unless emergency bypass).
        """
        override = self.db.get_manual_override(device_id)

        if override and not bypass_override:
            # Check if override still active
            expires_str = f"until {time.strftime('%H:%M:%S', time.localtime(override['expires_at']))}" if override.get("expires_at") else "indefinite"
            msg = f"Rule '{rule_id}' SUPPRESSED for '{device_id}' by active manual override ({expires_str})."
            logger.info(msg)
            self.db.log_event("RULE_SUPPRESSED", "RulesEngine", msg, {"rule_id": rule_id, "device_id": device_id, "override": override})
            return

        # Check if device is already in target state to prevent spamming MQTT (unless emergency bypass)
        if not bypass_override:
            current_state = {}
            if hasattr(self, "_current_devices") and self._current_devices:
                current_state = self._current_devices.get(device_id, {}).get("state", {})
            if not current_state:
                current_state = self.db.get_all_device_states().get(device_id, {}).get("state", {})
            already_matched = all(current_state.get(k) == v for k, v in action.items())
            if already_matched:
                return

        now = time.time()
        self.db.update_rule_last_triggered(rule_id, now)
        msg = f"Rule '{rule_id}' fired on '{device_id}': {reason}"
        logger.info(msg)
        self.db.log_event("RULE_FIRED", "RulesEngine", msg, {"rule_id": rule_id, "device_id": device_id, "action": action})

        # Send command through controller
        self.dispatch_command(device_id, action, f"rule:{rule_id}")
