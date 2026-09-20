# AetherHome - IoT Smart Home Controller & Simulated Devices

A comprehensive, production-grade Home Automation System built from first principles covering **IoT Architecture**, **Communication APIs**, and the **Home Automation Domain**.

Every device is modeled as an independent software process communicating over **MQTT 3.1.1** to a local broker. The system features a central rules engine with **Manual Override Precedence**, **Simulated Network Outage Resilience** with domain-driven **Local Fallback behaviors**, persistent state recovery via **SQLite**, a **Time-of-Day Scene Scheduler**, and a real-time **Web Dashboard**.

---

## Architecture Overview

```
+-----------------------------------------------------------------------------------+
|                               AetherHome Architecture                             |
+-----------------------------------------------------------------------------------+
                                          |
                         [ MQTT Broker (:1883) - broker.py ]
                         (Retained Messages, LWT, QoS 0/1)
                                          |
     +-------------------+----------------+-------------------+-------------------+
     |                   |                                    |                   |
[ Smart Light ]     [ Smart Fan ]                      [ Smart Lock ]     [ Multi-Sensor ]
(device_light.py)   (device_fan.py)                    (device_lock.py)   (device_sensors.py)
 - Power & Dimming   - 3 Speeds, Eco/Breeze Modes       - Motorized Bolt   - Temp (deg C)
 - Wattage Telemetry - RPM Simulation                   - Fail-Secure      - Motion Occupancy
 - Emergency Mode    - Eco Fallback Speed               - Local PIN Keypad - Ambient Lux
     |                   |                                    |                   |
     +-------------------+----------------+-------------------+-------------------+
                                          |
                         [ Central Controller - controller.py ]
                                          |
               +--------------------------+--------------------------+
               |                          |                          |
       [ Rules Engine ]          [ Manual Overrides ]       [ Scene Scheduler ]
     - Night Motion Lighting   - Strictly Beats Rules     - Morning / Day / Evening
     - Climate Comfort Fan     - Expiry Timers / Indef.   - Night / Away
     - Auto-Lock Deadbolt      - Fast Re-evaluation       - Virtual Simulation Clock
     - Tamper Security Alarm
               |                          |                          |
               +--------------------------+--------------------------+
                                          |
                        [ SQLite DB: home_automation.db ]
                   (States, Overrides, Rules, Scenes, Audit Logs)
                                          |
                          [ FastAPI & WebSocket Server ]
                                  (web/app.py)
                                          |
                       [ Modern Glassmorphic Web Dashboard ]
                                (http://localhost:8000)
```

---

## Key Capabilities

### 1. Separate Process Architecture over MQTT
- Every device model runs as an isolated OS process communicating strictly over MQTT 3.1.1:
  - `broker.py`: Zero-dependency, RFC-compliant pure-Python `asyncio` MQTT 3.1.1 broker.
  - `devices/device_light.py`: Smart dimmable light process.
  - `devices/device_fan.py`: 3-speed ceiling fan process.
  - `devices/device_lock.py`: Motorized deadbolt smart lock process.
  - `devices/device_sensors.py`: Ambient environment multi-sensor process.

### 2. MQTT Topic Schema & Communication APIs
| Topic Filter | Type | Description |
| :--- | :--- | :--- |
| `home/devices/{id}/availability` | Retained (QoS 1) | Online / Offline status managed via MQTT Last Will and Testament (LWT). |
| `home/devices/{id}/state` | Retained (QoS 1) | Current device state payload (power, speed, lock status, fallback active, wattage). |
| `home/devices/{id}/set` | Command (QoS 1) | Action payloads dispatched by the controller or dashboard. |
| `home/devices/{id}/simulate_outage` | Control (QoS 1) | Injects network link failure to test local autonomy. |
| `home/devices/{id}/local_input` | Hardware Input | Simulates local physical switch toggles, fan dials, or keypad PIN entry. |
| `home/sensors/environment/state` | Retained (QoS 1) | Telemetry stream for temperature, humidity, motion occupancy, and illuminance. |

### 3. Manual Override Precedence
- When a user explicitly interacts with a device (via web dashboard or physical simulation), an **active manual override** is recorded in SQLite with an optional expiration countdown.
- **Precedence Guarantee**: The Rules Engine evaluates all incoming triggers, but if a device has an active manual override, automated rule actions are strictly suppressed and flagged in the audit log.
- Clearing the override immediately resumes automated rule evaluation.

### 4. Simulated Network Outage & Domain-Specific Local Fallback
Each device handles loss of connectivity autonomously:
- **Smart Door Lock (Fail-Secure Access Control Policy)**:
  - When connection is severed, remote commands are rejected.
  - If currently `UNLOCKED`, an autonomous 5-second countdown triggers to drive the physical deadbolt to `LOCKED`, securing premises.
  - Physical keypad PIN entry (`1234`) remains functional offline.
- **Smart Light (Emergency Safety Illumination)**:
  - Automatically transitions to an autonomous emergency glow (20% warm 2700K) so occupants are never left in pitch darkness.
  - Preserves physical wall switch functionality offline.
- **Smart Fan (Eco Safety Mode)**:
  - Automatically switches to Eco Mode at Speed 1 (360 RPM) to prevent motor stall and conserve power during home gateway failure.

### 5. State Persistence & System Recovery
- All device states, active manual overrides, scene schedules, rules configurations, and audit events are continuously synchronized to SQLite (`data/home_automation.db`) and retained MQTT topics.
- When the controller or devices are restarted, they immediately recover their operational states, active overrides, and schedules.

### 6. Time-of-Day Scene Scheduler (Stretch Feature)
- Preset Scenes:
  - **Morning Sunrise (07:00)**: Light ON (50% warm), Fan OFF, Lock LOCKED.
  - **Day / Work Mode (09:00)**: Light OFF, Fan ON (Speed 1 Eco), Lock LOCKED.
  - **Evening Relaxation (18:30)**: Light ON (80% warm), Fan ON (Speed 2), Lock LOCKED.
  - **Night / Sleep (22:30)**: Light OFF, Fan ON (Speed 1), Lock LOCKED.
  - **Away / Security Armed**: Light OFF, Fan OFF, Lock LOCKED, Security Armed.
- **Virtual Simulation Clock**: Includes controls to fast-forward through a 24-hour cycle or set virtual times (e.g. `07:00`, `18:30`, `22:30`) to test schedule triggers instantly.

### 7. Real-Time Web Dashboard
- Served via FastAPI on `http://localhost:8000`.
- Live bi-directional WebSockets (`/ws`).
- Interactive controls: brightness sliders, speed buttons, motorized deadbolt toggle, tamper sensor trigger, sensor simulation sliders, rule toggles, outage simulator, and live audit event log.

---

## Quick Start Guide

### 1. Activate Environment
```powershell
.\.venv\Scripts\Activate.ps1
```

### 2. Launch All Separate Processes
To start the MQTT broker, all 4 simulated device processes, and the central controller web hub simultaneously:
```powershell
python launcher.py
```

Open your browser and navigate to:
```
http://127.0.0.1:8000
```

### 3. Run Automated Tests
```powershell
# 1. MQTT Broker Pub/Sub & Retained Messages Test
python tests/test_mqtt_broker.py

# 2. Device Models, Fallback Logic & NVRAM Test
python tests/test_devices.py

# 3. Rules Engine, Manual Override Precedence & Persistence Test
python tests/test_rules_and_persistence.py

# 4. Comprehensive End-to-End System Integration Test
python tests/test_e2e_integration.py
```

---

## Directory Structure

```
.
├── broker.py                      # Pure-Python AsyncIO MQTT 3.1.1 Broker
├── launcher.py                    # Master multi-process launcher & supervisor
├── requirements.txt               # Frozen dependencies
│
├── devices/
│   ├── base_device.py             # Base IoT model with LWT, NVRAM & outage handling
│   ├── device_light.py            # Smart Dimmable Light process
│   ├── device_fan.py              # Smart Ceiling Fan process
│   ├── device_lock.py             # Smart Deadbolt Lock process (Fail-Secure)
│   └── device_sensors.py          # Environment Multi-Sensor process
│
├── controller/
│   ├── controller.py              # Central Controller daemon
│   ├── rules_engine.py            # Rules engine with Manual Override precedence
│   ├── scheduler.py               # Scene & Time-of-Day scheduler
│   └── storage.py                 # SQLite persistence layer
│
├── web/
│   ├── app.py                     # FastAPI REST API & WebSocket server
│   └── static/
│       ├── index.html             # Dashboard UI
│       ├── style.css              # Custom animations & glassmorphism
│       └── app.js                 # WebSocket client & real-time controls
│
├── data/                          # SQLite database & NVRAM state files
│   ├── home_automation.db
│   └── nvram_*.json
│
└── tests/
    ├── test_mqtt_broker.py
    ├── test_devices.py
    ├── test_rules_and_persistence.py
    └── test_e2e_integration.py
```
