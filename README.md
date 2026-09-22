# AetherHome - Industrial IoT Home Automation System & Digital Twin Simulator

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MQTT 3.1.1](https://img.shields.io/badge/MQTT-3.1.1-orange.svg)](http://mqtt.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com)
[![WebSocket](https://img.shields.io/badge/WebSockets-Real--Time-success.svg)](https://websockets.readthedocs.io/)
[![SQLite3](https://img.shields.io/badge/SQLite-State%20Persistence-003B57.svg)](https://www.sqlite.org/)
[![Tests](https://img.shields.io/badge/Tests-100%25%20Passing-brightgreen.svg)]()

> **Academic Submission:** Home Automation System with Simulated IoT Devices  
> **Repository:** [https://github.com/Saad-33/iot-smart-home-simulator](https://github.com/Saad-33/iot-smart-home-simulator)  
> **Author:** Mohammad Saad  
> **Detailed Technical Documentation:** [PROJECT_REPORT.md](PROJECT_REPORT.md)

---

## 1. Executive Summary & System Overview

**AetherHome** is an enterprise-grade, distributed Internet of Things (IoT) smart home simulation platform designed from first principles. Rather than using mock function calls in a single monolithic script, **every simulated device runs as an independent operating system process** communicating strictly over **MQTT 3.1.1** via a custom, asynchronous, pure-Python MQTT broker.

The system features:
- **Decoupled Multi-Process Topology**: Isolated OS processes with independent non-volatile memory (NVRAM).
- **Domain Automation Engine**: Closed-loop rules for motion-activated lighting, ambient daylight harvesting, climate comfort management, and automated security lockdown.
- **Manual Override Precedence**: User interactions strictly supersede automation rules until released or timed out.
- **Network Fault Resilience & Autonomous Local Fallback**: Devices detect broker loss via MQTT Last Will & Testament (LWT) and autonomously enact local safety routines (e.g. Fail-Secure deadbolt auto-lock, emergency glow, offline hardware keypad).
- **Full State Persistence & Recovery**: SQLite database preserves digital twin states, override latches, audit event logs, and schedules across system restarts.
- **Time-of-Day Scene Scheduler & Virtual Clock**: 24-hour cycle scheduler with instant simulation time accelerator and one-click **Away / Perimeter Armed** security lockdown.
- **Industrial Web Dashboard**: Real-time bi-directional WebSocket interface with optimistic UI updates (<1ms perceived latency).

---

## 2. Architecture & Communication Topology

```
+-----------------------------------------------------------------------------------------+
|                                    AetherHome Topology                                  |
+-----------------------------------------------------------------------------------------+
                                             |
                            [ Pure-Python MQTT Broker (:1883) ]
                            (QoS 0/1, Retained, LWT, Wildcards)
                                             |
         +--------------------+--------------+--------------+--------------------+
         |                    |                             |                    |
  [ Smart Light ]      [ Smart Fan ]                 [ Smart Lock ]       [ Multi-Sensor ]
  (PID: OS Process)    (PID: OS Process)             (PID: OS Process)    (PID: OS Process)
   - Dimmable PWM       - 3-Speed Turbine             - Motorized Bolt     - Temp (15-35°C)
   - Spectrum 2700-6000K- RPM Physics Engine          - Fail-Secure Auto   - Motion Radar
   - Emergency Glow 20% - Eco Fallback (Speed 1)      - Offline Keypad PIN - Lux (5-400 lux)
   - Wall Switch Sim    - Pull-Chain Sim              - Tamper Detector    - Cyclic Telemetry
         |                    |                             |                    |
         +--------------------+--------------+--------------+--------------------+
                                             |
                         [ Central Controller Daemon (FastAPI) ]
                         (controller.py / rules_engine.py / storage.py)
                                             |
                 +---------------------------+---------------------------+
                 |                           |                           |
         [ Rules Engine ]          [ Manual Overrides ]         [ Scene Scheduler ]
       - Motion Lighting         - Strictly Beats Rules       - 24h Virtual Clock
       - Daylight Harvesting     - Configurable TTL           - Morning / Day / Evening
       - Climate Comfort Fan     - Instant Re-evaluation      - Night / Away Lockdown
       - Auto-Lock (20s)         - WebSocket Broadcast        - Force Override Precedence
       - Tamper Alarm
                 |                           |                           |
                 +---------------------------+---------------------------+
                                             |
                           [ SQLite Database: data/home_automation.db ]
                           (States, Overrides, Rules, Scenes, Audit Logs)
                                             |
                            [ High-Performance Web Dashboard ]
                            (FastAPI & WebSockets @ http://127.0.0.1:8000)
```

---

## 3. Core Features & Academic Grading Rubric Alignment

### 3.1 Dedicated Process Device Models (IoT Architecture)
- **Living Room Dimmable Light (`devices/device_light.py`)**:
  - Continuous brightness control ($1\% - 100\%$) and Correlated Color Temperature ($2700\text{K} - 6000\text{K}$).
  - Live real-time electrical load calculation ($P_{\text{load}} = 0.5\text{W} + 9.5\text{W} \times \frac{\text{brightness}}{100}$).
  - Physical 3-way toggle wall-switch simulation with non-volatile edge detection.
- **Bedroom 3-Speed Ceiling Fan (`devices/device_fan.py`)**:
  - Mechanical turbine simulation with realistic angular velocity: Speed 1 ($360\text{ RPM}$), Speed 2 ($720\text{ RPM}$), Speed 3 ($1150\text{ RPM}$).
  - Modes: Normal, Eco, and Breeze.
  - Physical pull-chain toggle simulator.
- **Front Door Deadbolt Lock (`devices/device_lock.py`)**:
  - Motorized mechanical deadbolt model with `extended` (LOCKED) and `retracted` (UNLOCKED) states.
  - Autonomous Fail-Secure policy and integrated Tamper trip sensor.
  - Offline local hardware keypad supporting 4-digit PIN access (`1234`).
- **Environmental Multi-Sensor (`devices/device_sensors.py`)**:
  - Multi-parameter ambient sensing: Temperature ($15^\circ\text{C} - 35^\circ\text{C}$), Humidity ($20\% - 90\%$), Ambient Illuminance ($5 - 400\text{ lux}$), and PIR Occupancy radar.

---

### 3.2 MQTT 3.1.1 Communication APIs
The communication layer adheres strictly to standard MQTT topic taxonomy:

| Topic Pattern | QoS | Retained | Description |
| :--- | :---: | :---: | :--- |
| `home/devices/{id}/availability` | 1 | Yes | Heartbeat & connection status (`online` / `offline`) managed via MQTT Last Will and Testament (LWT). |
| `home/devices/{id}/state` | 1 | Yes | Complete JSON device state payload broadcast on every state change. |
| `home/devices/{id}/set` | 1 | No | Command actuation payloads dispatched by the controller or dashboard. |
| `home/devices/{id}/simulate_outage` | 1 | No | Administrative fault injection to sever/restore device network connectivity. |
| `home/devices/{id}/local_input` | 1 | No | Hardware physical input simulation (wall switches, pull chains, keypad PINs). |
| `home/sensors/environment/state` | 1 | Yes | Periodic telemetry feed broadcast from simulated sensor nodes. |

---

### 3.3 Domain Automation Rules Engine
The controller evaluates incoming telemetry using clean closed-loop control algorithms:

1. **Night Motion Lighting**:
   $$\text{Trigger: } \text{Occupancy} = \text{True} \land \text{Illuminance} \le 40\text{ lux} \implies \text{Turn Light ON (60\% brightness, 2800K warm)}$$
2. **Ambient Daylight Harvesting (Auto-Off)**:
   $$\text{Trigger: } \text{Illuminance} \ge 120\text{ lux} \land \text{Light} = \text{ON} \implies \text{Turn Light OFF (energy conservation)}$$
3. **Climate Comfort Fan**:
   $$\text{Trigger: } \text{Temperature} \ge 25.0^\circ\text{C} \implies \text{Turn Fan ON (Speed 2)}$$
   $$\text{Trigger: } \text{Temperature} \le 22.0^\circ\text{C} \implies \text{Turn Fan OFF}$$
4. **Auto-Lock Security**:
   $$\text{Trigger: } \text{Door} = \text{UNLOCKED} \land (\text{Current Time} - \text{Unlocked At}) \ge 20\text{s} \implies \text{Drive Deadbolt to LOCKED}$$
   *(Includes live 1-second auto-lock countdown timer on the dashboard card).*
5. **Security Tamper Lockdown**:
   $$\text{Trigger: } \text{Tamper Sensor} = \text{Tripped} \implies \text{Force Deadbolt LOCKED} \land \text{Turn Light ON to 100\% Strobe (6500K Cool)}$$

---

### 3.4 Manual Override Precedence Guarantee
- Whenever a user intervenes—via dashboard toggles, brightness sliders, physical switch, or REST API—a **manual override** is registered with an optional Time-To-Live (TTL).
- While an override is active, all contradictory automation rules are strictly **suppressed** and logged to the audit trail as `SCENE_SUPPRESSED` / `OVERRIDE_ACTIVE`.
- Releasing the override immediately re-evaluates the rules engine and restores automation.

---

### 3.5 Network Outage Resilience & Domain-Specific Fallback
When a device's network link is severed (via physical disconnection or simulated fault injection):
- **Deadbolt Smart Lock (Fail-Secure Policy)**:
  Rejects all remote commands. If currently `UNLOCKED`, it autonomously initiates a 5-second emergency countdown, after which the local actuator drives the deadbolt to `LOCKED`. The local 4-digit PIN keypad (`1234`) operates entirely offline.
- **Smart Light (Emergency Safety Illumination)**:
  Transitions automatically to an autonomous $20\%$ emergency safety glow so occupants are never stranded in total darkness. The local wall switch remains fully functional.
- **Smart Fan (Eco Safety Mode)**:
  Drops to Speed 1 (Eco Mode, 360 RPM) to conserve power and prevent overheating during gateway loss.

---

### 3.6 Time-of-Day Scene Scheduler & Away Mode
- **Scheduled Presets**:
  - `Morning Sunrise (07:00)`: Light 50% warm, Fan OFF, Door LOCKED.
  - `Day / Work Mode (09:00)`: Light OFF, Fan ON (Speed 1 Eco), Door LOCKED.
  - `Evening Relaxation (18:30)`: Light 80% warm, Fan ON (Speed 2), Door LOCKED.
  - `Night / Sleep (22:30)`: Light OFF, Fan ON (Speed 1), Door LOCKED.
  - `Away / Perimeter Armed`: Unconditionally clears all user overrides, turns light OFF, turns fan OFF (0 RPM), drives deadbolt to LOCKED, and arms perimeter security.
- **Virtual Simulation Clock**:
  Fast-forward time or set arbitrary virtual times (`07:00`, `09:00`, `18:30`, `22:30`) via the dashboard to verify 24-hour scheduled transitions immediately.

---

## 4. Quick Start & Execution Guide

### Prerequisites
- **Python 3.10+** (Tested on Windows, macOS, Linux)
- Standard library modules + `paho-mqtt`, `fastapi`, `uvicorn`, `websockets`

### 1. Installation & Environment Setup
```powershell
# Clone repository
git clone https://github.com/Saad-33/iot-smart-home-simulator.git
cd "iot-smart-home-simulator"

# Create & activate virtual environment (Windows)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# (Linux / macOS)
# python3 -m venv .venv
# source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Launch Entire System (One Command)
```powershell
python launcher.py
```
*`launcher.py` supervises and starts:*
1. Pure-Python AsyncIO MQTT 3.1.1 Broker (`:1883`)
2. Smart Light OS Process
3. Smart Fan OS Process
4. Smart Deadbolt OS Process
5. Environment Multi-Sensor OS Process
6. Central Controller Daemon & FastAPI WebSocket Dashboard (`:8000`)

Open your browser and navigate to:
```
http://127.0.0.1:8000
```

---

## 5. Demonstration & Evaluation Instructions (For Examiners)

To evaluate each required capability quickly in the web interface:

| Demonstration Objective | Action on Web Dashboard | Expected Observable Result |
| :--- | :--- | :--- |
| **1. Auto-Lock Security** | Click **"Unlock Deadbolt"** on the Front Door Deadbolt card. | Status shows `RETRACTED (AUTO-LOCK IN 20s)`. A live countdown ticks down from 20s to 0s, after which the deadbolt extends to `LOCKED` automatically. |
| **2. Daylight Harvesting** | Turn the Light ON, then drag the **Ambient Illuminance slider to $\ge 120\text{ lux}$**. | The rule fires and automatically turns the light **OFF** to conserve energy. |
| **3. Night Motion Lighting** | Drag Illuminance to $\le 40\text{ lux}$, then click **"Trigger Motion"**. | The room occupancy turns blue and the light automatically turns **ON** (warm 60%). |
| **4. Climate Comfort Fan** | Drag Ambient Temperature to **$\ge 25.0^\circ\text{C}$**. | Ceiling fan automatically spins up to Speed 2 ($720\text{ RPM}$). |
| **5. Manual Override Precedence** | Manually turn the Light OFF using the rocker switch. Then trigger motion in the dark. | The banner `OVERRIDE BEATS RULES` appears. The light strictly remains OFF. |
| **6. Away / Perimeter Armed** | Turn on the light and fan, then click the red **"AWAY / PERIMETER ARMED"** button. | Light turns OFF, fan stops (0 RPM), deadbolt locks, and all overrides are released immediately. |
| **7. Network Outage & Fallback** | Click **"Sever Link"** on the Smart Deadbolt card. | Link badge turns to `SEVERED (LWT)`. If unlocked, a 5s countdown engages and enforces fail-secure lock. Click **"Keypad (1234)"** to unlock offline. |
| **8. State Persistence** | Set fan to speed 3. Terminate the system (`Ctrl+C`), and re-run `python launcher.py`. | Fan state, speed 3, and all database records are restored from SQLite automatically. |

---

## 6. Automated Verification & Test Suite

The repository includes a comprehensive 4-tier automated test suite covering unit, integration, and end-to-end verification.

```powershell
# Tier 1: MQTT Broker Pub/Sub, QoS 1, Retained Messages, and LWT
python tests/test_mqtt_broker.py

# Tier 2: Device Models, Fallback Logic, and NVRAM Emulation
python tests/test_devices.py

# Tier 3: Rules Engine, Manual Override Precedence & SQLite Persistence
python tests/test_rules_and_persistence.py

# Tier 4: Full Multi-Process End-to-End System Integration Suite
python tests/test_e2e_integration.py
```

### Automated Test Output Sample:
```
--- [E2E TEST] Starting Pure Python MQTT Broker ---
--- [E2E TEST] Starting Device Models ---
--- [E2E TEST] Starting Home Controller ---
[OK] Step 1: All device models connected to MQTT broker and registered online.
[OK] Step 2: Automation rule fired and turned Smart Light ON.
[OK] Step 3: Manual override strictly suppressed automation rule. Light stayed OFF.
[OK] Step 4: After clearing manual override, automation resumed.
[OK] Step 5: Network outage simulated; Lock entered Fail-Secure fallback and locked deadbolt.
[OK] Step 6: Network restored; Lock reconciled state.
[OK] Step 7: Night scene activated across all devices.
[OK] Step 8: Controller restarted and recovered all states and overrides from SQLite.

=======================================================
   [SUCCESS] ALL END-TO-END INTEGRATION TESTS PASSED!  
=======================================================
```

---

## 7. Codebase Structure

```
.
├── broker.py                          # Zero-dependency AsyncIO MQTT 3.1.1 broker
├── launcher.py                        # Master multi-process supervisor
├── requirements.txt                   # Project dependencies
├── PROJECT_REPORT.md                  # In-depth architectural & technical specification
├── README.md                          # Main project overview & user guide
│
├── devices/                           # Autonomous Device OS Processes
│   ├── base_device.py                 # Abstract base class: MQTT client, NVRAM, LWT
│   ├── device_light.py                # Smart Dimmable Light process
│   ├── device_fan.py                  # 3-speed ceiling fan process (RPM physics)
│   ├── device_lock.py                 # Fail-Secure motorized deadbolt process
│   └── device_sensors.py              # Environment multi-sensor process
│
├── controller/                        # Central Controller Daemon
│   ├── controller.py                  # Central coordinator & MQTT listener
│   ├── rules_engine.py                # Automation rules & override precedence evaluator
│   ├── scheduler.py                   # 24h scene scheduler & virtual simulation clock
│   └── storage.py                     # SQLite relational persistence layer
│
├── web/                               # Web Dashboard & APIs
│   ├── app.py                         # FastAPI REST application & WebSocket server
│   └── static/
│       ├── index.html                 # Dashboard markup & interactive controls
│       ├── style.css                  # Custom styling, animations & deadbolt cutaway
│       └── app.js                     # Zero-latency WebSocket client & optimistic UI
│
└── tests/                             # Comprehensive Automated Test Suites
    ├── test_mqtt_broker.py            # Broker protocol conformance tests
    ├── test_devices.py                # Device autonomy & fallback tests
    ├── test_rules_and_persistence.py  # Automation logic & override tests
    └── test_e2e_integration.py        # End-to-end integration test suite
```

---

## 8. Licensing & Author

- **Author:** Mohammad Saad
- **Coursework:** Internet of Things (IoT) & Smart Systems Architecture
- **License:** Open Source (MIT License)
