"""
Scene Manager and Time-of-Day Scheduler.
Manages scenes:
- Morning Sunrise (07:00)
- Day / Work (09:00)
- Evening Relaxation (18:30)
- Night / Sleep (22:30)
- Away / Security Armed
Provides a Virtual Simulation Clock so users and automated tests can fast-forward time
and test 24-hour cycle schedules immediately.
"""

import datetime
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional
from controller.storage import Database

logger = logging.getLogger("Scheduler")


class SceneScheduler:
    def __init__(
        self,
        db: Database,
        dispatch_command_cb: Callable[[str, Dict[str, Any], str], None],
        clear_override_cb: Optional[Callable[[str], None]] = None,
        scene_notify_cb: Optional[Callable[[str, Dict[str, Any]], None]] = None
    ):
        self.db = db
        self.dispatch_command = dispatch_command_cb
        self.clear_override_cb = clear_override_cb
        self.scene_notify_cb = scene_notify_cb

        # Simulation clock support
        self.virtual_mode: bool = False
        self.virtual_time: Optional[datetime.time] = None
        self._last_evaluated_minute: Optional[str] = None

    def set_virtual_time(self, time_str: Optional[str]):
        """Set virtual time like '07:00' or None to resume real-time clock."""
        if time_str:
            parts = [int(p) for p in time_str.split(":")]
            self.virtual_time = datetime.time(parts[0], parts[1])
            self.virtual_mode = True
            logger.info(f"Virtual simulation clock set to {time_str}")
        else:
            self.virtual_mode = False
            self.virtual_time = None
            logger.info("Virtual simulation clock disabled; restored real-time clock.")

    def get_current_simulated_time_str(self) -> str:
        if self.virtual_mode and self.virtual_time:
            return self.virtual_time.strftime("%H:%M")
        return datetime.datetime.now().strftime("%H:%M")

    def activate_scene(self, scene_id: str, force_override: bool = False):
        """
        Activates a specific scene immediately.
        :param scene_id: ID of scene (e.g. 'morning', 'night', 'away')
        :param force_override: If True, bypasses device manual overrides.
        """
        scenes = {s["scene_id"]: s for s in self.db.get_scenes()}
        if scene_id not in scenes:
            logger.error(f"Scene '{scene_id}' not found.")
            return False

        scene = scenes[scene_id]
        actions = scene.get("actions", {})
        self.db.set_active_scene(scene_id)
        msg = f"Activating Scene: '{scene['name']}' ({scene_id})"
        logger.info(msg)
        self.db.log_event("SCENE_ACTIVATED", "Scheduler", msg, {"scene_id": scene_id, "actions": actions})

        if self.scene_notify_cb:
            try:
                self.scene_notify_cb(scene_id, scene)
            except Exception as e:
                logger.debug(f"Error in scene_notify_cb: {e}")

        # Away scene ALWAYS forces override so security arming is absolute
        if scene_id == "away":
            force_override = True

        for device_id, cmd in actions.items():
            # Respect manual override unless forced
            override = self.db.get_manual_override(device_id)
            if override:
                if force_override:
                    if self.clear_override_cb:
                        self.clear_override_cb(device_id)
                    else:
                        self.db.clear_manual_override(device_id)
                else:
                    suppress_msg = f"Scene '{scene_id}' action on '{device_id}' suppressed by manual override."
                    logger.info(suppress_msg)
                    self.db.log_event("SCENE_SUPPRESSED", "Scheduler", suppress_msg, {"device_id": device_id, "scene_id": scene_id})
                    continue

            self.dispatch_command(device_id, cmd, f"scene:{scene_id}")

        return True

    def tick(self):
        """Checks scheduled times every cycle."""
        current_hm = self.get_current_simulated_time_str()
        if current_hm == self._last_evaluated_minute:
            return
        self._last_evaluated_minute = current_hm

        scenes = self.db.get_scenes()
        for s in scenes:
            sched = s.get("scheduled_time")
            if sched and sched == current_hm:
                logger.info(f"Scheduled time reached ({current_hm}) for scene '{s['name']}'")
                self.activate_scene(s["scene_id"], force_override=False)
