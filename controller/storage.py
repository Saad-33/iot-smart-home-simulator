"""
Persistent SQLite storage for Home Automation System.
Stores:
- Device states
- Manual overrides (with expiry timestamps)
- Automation rules configuration
- Scene schedules and definitions
- Audit logs and event telemetry
"""

import json
import logging
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Storage")


class Database:
    def __init__(self, db_path: str = "data/home_automation.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. Device states
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS device_states (
                    device_id TEXT PRIMARY KEY,
                    device_type TEXT,
                    name TEXT,
                    state_json TEXT,
                    network_status TEXT DEFAULT 'offline',
                    fallback_active INTEGER DEFAULT 0,
                    fallback_reason TEXT,
                    updated_at REAL
                )
            """)

            # 2. Manual overrides
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS manual_overrides (
                    device_id TEXT PRIMARY KEY,
                    active INTEGER DEFAULT 0,
                    target_state_json TEXT,
                    expires_at REAL,
                    reason TEXT,
                    updated_at REAL
                )
            """)

            # 3. Automation rules
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS automation_rules (
                    rule_id TEXT PRIMARY KEY,
                    name TEXT,
                    description TEXT,
                    enabled INTEGER DEFAULT 1,
                    trigger_type TEXT,
                    config_json TEXT,
                    last_triggered_at REAL DEFAULT 0
                )
            """)

            # 4. Scenes and Schedules
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scenes (
                    scene_id TEXT PRIMARY KEY,
                    name TEXT,
                    actions_json TEXT,
                    scheduled_time TEXT,
                    is_active INTEGER DEFAULT 0,
                    updated_at REAL
                )
            """)

            # 5. Audit log
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    event_type TEXT,
                    source TEXT,
                    message TEXT,
                    data_json TEXT
                )
            """)

            conn.commit()
        self._seed_defaults()

    def _seed_defaults(self):
        """Seed default rules and scenes if empty."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Seed rules
            cursor.execute("SELECT COUNT(*) FROM automation_rules")
            if cursor.fetchone()[0] == 0:
                default_rules = [
                    (
                        "night_motion_lighting",
                        "Night Motion Lighting",
                        "Turn on Living Room Light to 60% warm when motion is detected and illuminance < 40 lux (or Night scene)",
                        1,
                        "sensor_motion",
                        json.dumps({
                            "sensor_id": "sensors_living_room",
                            "target_device": "light_living_room",
                            "lux_threshold": 40,
                            "action": {"power": "ON", "brightness": 60, "color_temp": 2800}
                        }),
                        0.0
                    ),
                    (
                        "climate_comfort_fan",
                        "Climate Comfort Fan",
                        "Turn on Bedroom Fan (Speed 2) when temperature exceeds 25.0°C and room is occupied",
                        1,
                        "sensor_temp",
                        json.dumps({
                            "sensor_id": "sensors_living_room",
                            "target_device": "fan_bedroom",
                            "temp_threshold": 25.0,
                            "action": {"power": "ON", "speed": 2, "mode": "normal"}
                        }),
                        0.0
                    ),
                    (
                        "auto_lock_security",
                        "Auto-Lock Security",
                        "Automatically lock Front Door Deadbolt after being unlocked for more than 20 seconds",
                        1,
                        "timer_lock",
                        json.dumps({
                            "target_device": "lock_front_door",
                            "unlock_duration_seconds": 20,
                            "action": {"lock_state": "LOCKED"}
                        }),
                        0.0
                    ),
                    (
                        "tamper_alarm",
                        "Security Tamper Lockdown",
                        "Trigger alarm light illumination and lock all doors immediately if tamper sensor is tripped",
                        1,
                        "security_tamper",
                        json.dumps({
                            "lock_device": "lock_front_door",
                            "light_device": "light_living_room",
                            "action_light": {"power": "ON", "brightness": 100, "color_temp": 6500},
                            "action_lock": {"lock_state": "LOCKED"}
                        }),
                        0.0
                    )
                ]
                cursor.executemany(
                    "INSERT INTO automation_rules VALUES (?, ?, ?, ?, ?, ?, ?)",
                    default_rules
                )

            # Seed scenes
            cursor.execute("SELECT COUNT(*) FROM scenes")
            if cursor.fetchone()[0] == 0:
                now = time.time()
                default_scenes = [
                    (
                        "morning",
                        "Morning Sunrise",
                        json.dumps({
                            "light_living_room": {"power": "ON", "brightness": 50, "color_temp": 3000},
                            "fan_bedroom": {"power": "OFF"},
                            "lock_front_door": {"lock_state": "LOCKED"}
                        }),
                        "07:00",
                        0,
                        now
                    ),
                    (
                        "day",
                        "Day / Work Mode",
                        json.dumps({
                            "light_living_room": {"power": "OFF"},
                            "fan_bedroom": {"power": "ON", "speed": 1, "mode": "eco"},
                            "lock_front_door": {"lock_state": "LOCKED"}
                        }),
                        "09:00",
                        0,
                        now
                    ),
                    (
                        "evening",
                        "Evening Relaxation",
                        json.dumps({
                            "light_living_room": {"power": "ON", "brightness": 80, "color_temp": 3500},
                            "fan_bedroom": {"power": "ON", "speed": 2, "mode": "normal"},
                            "lock_front_door": {"lock_state": "LOCKED"}
                        }),
                        "18:30",
                        0,
                        now
                    ),
                    (
                        "night",
                        "Night / Sleep",
                        json.dumps({
                            "light_living_room": {"power": "OFF"},
                            "fan_bedroom": {"power": "ON", "speed": 1, "mode": "normal"},
                            "lock_front_door": {"lock_state": "LOCKED"}
                        }),
                        "22:30",
                        0,
                        now
                    ),
                    (
                        "away",
                        "Away / Security Armed",
                        json.dumps({
                            "light_living_room": {"power": "OFF"},
                            "fan_bedroom": {"power": "OFF"},
                            "lock_front_door": {"lock_state": "LOCKED"}
                        }),
                        None,
                        0,
                        now
                    )
                ]
                cursor.executemany("INSERT INTO scenes VALUES (?, ?, ?, ?, ?, ?)", default_scenes)

            conn.commit()

    # --- Device State Persistence ---
    def save_device_state(
        self,
        device_id: str,
        device_type: str,
        name: str,
        state: Dict[str, Any],
        network_status: str,
        fallback_active: bool,
        fallback_reason: Optional[str] = None
    ):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO device_states (device_id, device_type, name, state_json, network_status, fallback_active, fallback_reason, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    device_type = excluded.device_type,
                    name = excluded.name,
                    state_json = excluded.state_json,
                    network_status = excluded.network_status,
                    fallback_active = excluded.fallback_active,
                    fallback_reason = excluded.fallback_reason,
                    updated_at = excluded.updated_at
            """, (
                device_id, device_type, name, json.dumps(state),
                network_status, 1 if fallback_active else 0, fallback_reason, time.time()
            ))
            conn.commit()

    def get_all_device_states(self) -> Dict[str, Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM device_states")
            rows = cursor.fetchall()
            result = {}
            for r in rows:
                result[r["device_id"]] = {
                    "device_id": r["device_id"],
                    "device_type": r["device_type"],
                    "name": r["name"],
                    "state": json.loads(r["state_json"]) if r["state_json"] else {},
                    "network_status": r["network_status"],
                    "fallback_active": bool(r["fallback_active"]),
                    "fallback_reason": r["fallback_reason"],
                    "updated_at": r["updated_at"]
                }
            return result

    # --- Manual Override Persistence ---
    def set_manual_override(
        self,
        device_id: str,
        target_state: Dict[str, Any],
        duration_seconds: Optional[int] = None,
        reason: str = "User manual command"
    ):
        now = time.time()
        expires_at = (now + duration_seconds) if duration_seconds else None
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO manual_overrides (device_id, active, target_state_json, expires_at, reason, updated_at)
                VALUES (?, 1, ?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    active = 1,
                    target_state_json = excluded.target_state_json,
                    expires_at = excluded.expires_at,
                    reason = excluded.reason,
                    updated_at = excluded.updated_at
            """, (device_id, json.dumps(target_state), expires_at, reason, now))
            conn.commit()

    def clear_manual_override(self, device_id: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE manual_overrides SET active = 0, updated_at = ? WHERE device_id = ?
            """, (time.time(), device_id))
            conn.commit()

    def get_manual_override(self, device_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM manual_overrides WHERE device_id = ?", (device_id,))
            r = cursor.fetchone()
            if not r or not r["active"]:
                return None
            
            # Check if expired
            if r["expires_at"] and time.time() > r["expires_at"]:
                self.clear_manual_override(device_id)
                return None

            return {
                "device_id": r["device_id"],
                "active": bool(r["active"]),
                "target_state": json.loads(r["target_state_json"]) if r["target_state_json"] else {},
                "expires_at": r["expires_at"],
                "reason": r["reason"],
                "updated_at": r["updated_at"]
            }

    def get_all_manual_overrides(self) -> Dict[str, Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM manual_overrides WHERE active = 1")
            rows = cursor.fetchall()
            result = {}
            now = time.time()
            for r in rows:
                if r["expires_at"] and now > r["expires_at"]:
                    continue
                result[r["device_id"]] = {
                    "device_id": r["device_id"],
                    "active": True,
                    "target_state": json.loads(r["target_state_json"]) if r["target_state_json"] else {},
                    "expires_at": r["expires_at"],
                    "reason": r["reason"],
                    "updated_at": r["updated_at"]
                }
            return result

    # --- Rules Persistence ---
    def get_rules(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM automation_rules")
            rows = cursor.fetchall()
            return [{
                "rule_id": r["rule_id"],
                "name": r["name"],
                "description": r["description"],
                "enabled": bool(r["enabled"]),
                "trigger_type": r["trigger_type"],
                "config": json.loads(r["config_json"]) if r["config_json"] else {},
                "last_triggered_at": r["last_triggered_at"]
            } for r in rows]

    def set_rule_enabled(self, rule_id: str, enabled: bool):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE automation_rules SET enabled = ? WHERE rule_id = ?", (1 if enabled else 0, rule_id))
            conn.commit()

    def update_rule_last_triggered(self, rule_id: str, timestamp: float):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE automation_rules SET last_triggered_at = ? WHERE rule_id = ?", (timestamp, rule_id))
            conn.commit()

    # --- Scenes Persistence ---
    def get_scenes(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM scenes")
            rows = cursor.fetchall()
            return [{
                "scene_id": r["scene_id"],
                "name": r["name"],
                "actions": json.loads(r["actions_json"]) if r["actions_json"] else {},
                "scheduled_time": r["scheduled_time"],
                "is_active": bool(r["is_active"]),
                "updated_at": r["updated_at"]
            } for r in rows]

    def set_active_scene(self, scene_id: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE scenes SET is_active = 0")
            cursor.execute("UPDATE scenes SET is_active = 1, updated_at = ? WHERE scene_id = ?", (time.time(), scene_id))
            conn.commit()

    def update_scene_schedule(self, scene_id: str, scheduled_time: Optional[str]):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE scenes SET scheduled_time = ?, updated_at = ? WHERE scene_id = ?", (scheduled_time, time.time(), scene_id))
            conn.commit()

    # --- Audit Log ---
    def log_event(self, event_type: str, source: str, message: str, data: Optional[Dict[str, Any]] = None):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO audit_logs (timestamp, event_type, source, message, data_json)
                VALUES (?, ?, ?, ?, ?)
            """, (time.time(), event_type, source, message, json.dumps(data) if data else None))
            conn.commit()

    def get_recent_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [{
                "id": r["id"],
                "timestamp": r["timestamp"],
                "event_type": r["event_type"],
                "source": r["source"],
                "message": r["message"],
                "data": json.loads(r["data_json"]) if r["data_json"] else None
            } for r in rows]
