"""
Master Process Launcher and Orchestrator for Home Automation System.
Spawns each component as an independent OS process:
1. MQTT Broker (broker.py)
2. Smart Light Device (devices/device_light.py)
3. Smart Fan Device (devices/device_fan.py)
4. Smart Door Lock Device (devices/device_lock.py)
5. Environment Sensors (devices/device_sensors.py)
6. Central Controller & Web Dashboard (web/app.py via uvicorn)

Manages process lifecycle, monitors health, and performs graceful shutdown.
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from typing import Dict, List, Tuple

PROCESS_DEFS = [
    ("MQTT Broker", [sys.executable, "broker.py"]),
    ("Smart Light", [sys.executable, "devices/device_light.py"]),
    ("Smart Fan", [sys.executable, "devices/device_fan.py"]),
    ("Smart Lock", [sys.executable, "devices/device_lock.py"]),
    ("Environment Sensors", [sys.executable, "devices/device_sensors.py"]),
    ("Controller & Web Hub", [sys.executable, "-m", "uvicorn", "web.app:app", "--host", "127.0.0.1", "--port", "8000"])
]


class ProcessLauncher:
    def __init__(self):
        self.running_processes: List[Tuple[str, subprocess.Popen]] = []
        self._stopping = False

    def start_all(self):
        print("\n=======================================================")
        print("   AetherHome IoT Controller - Starting Ecosystem      ")
        print("=======================================================\n")

        base_dir = os.path.dirname(os.path.abspath(__file__))

        for name, cmd in PROCESS_DEFS:
            print(f"[*] Spawning process: {name} ...")
            # Broker needs a short moment to bind port before devices connect
            proc = subprocess.Popen(
                cmd,
                cwd=base_dir,
                env=os.environ.copy()
            )
            self.running_processes.append((name, proc))
            if name == "MQTT Broker":
                time.sleep(1.0)  # wait for broker socket to open
            else:
                time.sleep(0.3)

        print("\n[OK] All 6 independent processes are running:")
        for name, proc in self.running_processes:
            print(f"    - {name:<22} (PID: {proc.pid})")

        print("\n[WEB] Web Dashboard running at: http://127.0.0.1:8000")
        print("[INFO] Press Ctrl+C at any time to gracefully terminate all processes.\n")

    def monitor(self):
        try:
            while not self._stopping:
                for name, proc in self.running_processes:
                    ret = proc.poll()
                    if ret is not None and not self._stopping:
                        print(f"\n[!] WARNING: Process '{name}' (PID {proc.pid}) exited with code {ret}!")
                time.sleep(2.0)
        except KeyboardInterrupt:
            print("\n[!] Shutdown signal received. Stopping all processes...")
            self.stop_all()

    def stop_all(self):
        self._stopping = True
        for name, proc in reversed(self.running_processes):
            if proc.poll() is None:
                print(f"[*] Terminating {name} (PID {proc.pid})...")
                try:
                    proc.terminate()
                    proc.wait(timeout=2.0)
                except Exception:
                    proc.kill()
        print("[OK] All processes terminated cleanly.")


if __name__ == "__main__":
    launcher = ProcessLauncher()

    def handle_sig(sig, frame):
        launcher.stop_all()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    launcher.start_all()
    launcher.monitor()
