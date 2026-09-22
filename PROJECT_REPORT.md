# Comprehensive Technical Project Report: AetherHome IoT Smart Home Simulator

**Project Title:** Home Automation System with Simulated IoT Devices  
**Repository:** [https://github.com/Saad-33/iot-smart-home-simulator](https://github.com/Saad-33/iot-smart-home-simulator)  
**Author:** Mohammad Saad  
**System Architecture:** Multi-Process Micro-services over MQTT 3.1.1 with SQLite State Persistence and Real-time WebSocket Dashboard  

---

## 1. Executive Summary

The **AetherHome IoT Smart Home Simulator** is a full-stack, distributed Internet of Things (IoT) home automation platform built from fundamental principles. The primary design goal is to deliver an end-to-end simulation of a real-world residential smart home ecosystem without requiring physical microcontroller hardware. 

Each device—a **Dimmable Light**, a **3-Speed Ceiling Fan**, a **Motorized Deadbolt Lock**, and an **Environmental Multi-Sensor**—is modeled as an isolated operating system process. The devices communicate exclusively over standard **MQTT 3.1.1** topics through a zero-dependency, pure-Python asynchronous MQTT broker. A central controller applies closed-loop automation rules, manages manual override precedence, orchestrates time-of-day scenes, and logs system telemetry into an embedded SQLite database. In the event of network disruption, each device exhibits domain-specific autonomous local fallback behavior (e.g. the deadbolt autonomously executes a Fail-Secure auto-lock). A high-performance web dashboard built with FastAPI, WebSockets, and Tailwind CSS provides real-time monitoring and interactive control.

---

## 2. System Architecture & Process Topology

Unlike monolithic simulation scripts where devices are merely internal function calls, AetherHome strictly decouples every hardware device into an isolated operating system process with its own event loop, non-volatile RAM (NVRAM), and network socket.

`
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
   - Power & Dimming    - 3 Speeds + Modes            - Motorized Bolt     - Temp (15-35°C)
   - Wattage Telemetry  - RPM Physics Simulator       - Fail-Secure Auto   - Motion Occupancy
   - 20% Emergency Glow - Eco Fallback (Speed 1)      - Offline Keypad PIN - Lux (5-400 lux)
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
       - Climate Comfort Fan     - Configurable Expiry        - Morning/Work/Evening
       - Auto-Lock (20s)         - Instant Re-evaluation      - Night/Away Presets
       - Tamper Alarm
                 |                           |                           |
                 +---------------------------+---------------------------+
                                             |
                              [ SQLite Database: home_automation.db ]
                              (States, Overrides, Rules, Scenes, Logs)
                                             |
                              [ WebSocket Broadcast Layer (:8000) ]
                                             |
                              [ Industrial Glassmorphic Web UI ]
`

### Component Roles
1. **MQTT Broker (roker.py)**: A pure-Python AsyncIO MQTT 3.1.1 server. Implements topic prefix matching, wildcard routing (+ and #), Last Will and Testament (LWT), QoS 0 and 1 message delivery, and disk-persisted retained message tables.
2. **Device Models (devices/*.py)**: Independent client processes running standard Paho-MQTT connections. Each maintains a local NVRAM JSON file in data/nvram_*.json to mirror hardware EEPROM.
3. **Home Controller (controller/controller.py)**: Subscribes to device telemetry, enforces business logic and safety rules, tracks overrides, and coordinates scene activation.
4. **Master Launcher (launcher.py)**: An orchestrator that manages process lifecycles, health monitoring, and graceful multi-process termination.

---

## 3. Communication API & MQTT Topic Matrix

All inter-process communication adheres strictly to a standardized MQTT topic hierarchy:

| Topic Pattern | Type | QoS | Description |
| :--- | :--- | :---: | :--- |
| home/devices/{id}/availability | Status | 1 (Retained) | Node connection state (online / offline). Published on connect and configured as the broker Last Will and Testament (LWT). |
| home/devices/{id}/state | Telemetry | 1 (Retained) | Complete device digital twin state (power, speed, lock status, wattage, RPM, battery, NVRAM timestamps). |
| home/devices/{id}/set | Command | 1 | Dispatched by the Controller or Dashboard to instruct a device to adopt target settings. |
| home/devices/{id}/simulate_outage | Fault Injection | 1 | Commands the device to sever its TCP socket and execute local disconnected fallback routines. |
| home/devices/{id}/local_input | Hardware Event | 1 | Simulates physical user interactions directly at the device (e.g. wall switch toggle, PIN entry on door keypad). |

---

## 4. Intelligent Rules Engine & Automation Logic

The Rules Engine (controller/rules_engine.py) operates as a closed-loop controller that evaluates environmental sensor data against configurable thresholds.

`
       [ Ambient Lux <= 40 & Occupancy Detected ] ──────> Turn Light ON (60% Warm Glow)
       [ Ambient Lux >= 120 (Bright Daylight)    ] ──────> Turn Light OFF (Daylight Harvesting)
       
       [ Temperature >= 25.0°C                   ] ──────> Turn Fan ON (Speed 2 Cooling)
       [ Temperature <= 22.0°C                   ] ──────> Turn Fan OFF (Eco Comfort Restored)
       
       [ Deadbolt Unlocked for > 20 seconds      ] ──────> Motorized Auto-Lock (Security Timeout)
       [ Deadbolt Tamper Sensor Tripped          ] ──────> Force Lock + Flash Floodlights (Tamper Alarm)
`

### Key Engineering Principles
* **Deadband Hysteresis**: Prevents rapid cycling. Lighting has a 40–120 lux deadband; climate control has a 22–25°C deadband.
* **Manual Override Precedence**: If a user explicitly toggles a switch or adjusts a slider on the dashboard, a timed **Manual Override** is attached in SQLite. While active, the Rules Engine is strictly suppressed for that device.
* **Mutual Exclusion & Alarm Priority**: If the security tamper alarm is active, environmental vacancy rules are inhibited so safety floodlighting is never extinguished prematurely.

---

## 5. Hardware Device Models & State Machines

### 5.1 Smart Dimmable Light (device_light.py)
- **State Properties**: power (ON/OFF), rightness (0–100%), color_temp (2000K–6500K), wattage (dynamic telemetry).
- **Physical Physics Simulation**: Simulates dynamic wattage draw using a calibrated linear formula:
  \text{Wattage} = 1.5\text{W} + \left(\frac{\text{Brightness}}{100} \times 10.5\text{W}\right)
- **Emergency Outage Fallback**: If the network connection drops, the light engages local autonomous fallback, establishing a 20% warm emergency glow so residents are not left in darkness.

### 5.2 Bedroom Ceiling Fan (device_fan.py)
- **State Properties**: power, speed (0, 1, 2, 3), mode (
ormal, eco, reeze), pm.
- **Aerodynamic Simulation**: Dynamically models blade rotation physics:
  - Speed 0: 0 RPM
  - Speed 1: 360 RPM
  - Speed 2: 780 RPM
  - Speed 3: 1150 RPM
- **Eco Outage Fallback**: If the broker connection is lost, the fan enters autonomous Eco Speed 1 to maintain ventilation while minimizing battery/power draw.

### 5.3 Front Door Smart Deadbolt (device_lock.py)
- **Dual Physical State**:
  - lock_state: Logical state (LOCKED vs UNLOCKED).
  - olt_position: Physical position (extended into door frame vs etracted into chassis).
- **Fail-Secure Autonomous Fallback**: If network connectivity is severed while the door is unlocked, an onboard embedded timer initiates a **5-second countdown**. Upon expiry, the local motor drives the deadbolt into the LOCKED position (**Fail-Secure**).
- **Local Offline Keypad**: The device accepts local hardware PIN inputs (local_input). Entering PIN 1234 verifies the hash directly on the simulated device microcontroller and retracts the deadbolt, guaranteeing access even during total network failure.
- **Tamper Intrusion Detection**: An accelerometer sensor flags forced-entry attempts, triggering immediate physical lockdown and alerting the central controller.

### 5.4 Environment Multi-Sensor Studio (device_sensors.py)
- Periodically samples and broadcasts ambient living conditions:
  - **Temperature**: 15.0°C to 35.0°C
  - **Occupancy Motion Radar**: Boolean (True / False)
  - **Illuminance**: 5 lux (Night) to 400 lux (Full Daylight)

---

## 6. Fault Tolerance, Outage Resilience & State Persistence

| Failure Scenario | System Reaction | Recovery Mechanism |
| :--- | :--- | :--- |
| **MQTT Broker Drops** | Devices enter local fallback mode within keepalive window. | Devices auto-reconnect; Controller reconciles states from SQLite. |
| **Simulated Network Outage** | LWT immediately publishes offline; Deadbolt initiates 5s Fail-Secure auto-lock; Light activates 20% glow. | Toggling link restoration re-establishes MQTT session, republishes state, and clears fallback flags. |
| **Controller Crash / Power Loss** | Device models continue operating independently using local NVRAM (data/nvram_*.json). | On restart, Controller reads data/home_automation.db and reconstitutes digital twin state and active overrides. |

---

## 7. Time-of-Day Scene Orchestration

The system includes a **Virtual Simulation Clock** with configurable time acceleration to test 24-hour routine cycles:

| Scene ID | Name | Time | Configured Preset |
| :--- | :--- | :---: | :--- |
| morning | Morning Sunrise | 07:00 | Light 50% Warm (3000K), Fan OFF, Deadbolt LOCKED |
| day | Day / Work Mode | 09:00 | Light OFF, Fan Eco Speed 1, Deadbolt LOCKED |
| evening | Evening Relaxation | 18:30 | Light 80% Ambient (3500K), Fan Speed 2, Deadbolt LOCKED |
| 
ight | Night / Sleep | 22:30 | Light OFF, Fan Speed 1 (Gentle Breeze), Deadbolt LOCKED |
| way | Away / Armed | Manual | Light OFF, Fan OFF, Deadbolt LOCKED, Sensors Armed |

---

## 8. Verification & Automated Test Results

The codebase includes an exhaustive test suite verifying all 8 core milestones:

`powershell
.\.venv\Scripts\python.exe tests/test_e2e_integration.py
`

### Test Execution Matrix
* **Step 1: Multi-Process MQTT Connectivity** $\rightarrow$ [PASS] All 4 device processes connect and register online via LWT.
* **Step 2: Automated Motion Lighting Rule** $\rightarrow$ [PASS] Light engages when motion is injected in a dark environment.
* **Step 3: Manual Override Precedence** $\rightarrow$ [PASS] Manual command strictly suppresses automation rules.
* **Step 4: Override Clearance & Automation Resumption** $\rightarrow$ [PASS] Automation resumes once override expires or is cleared.
* **Step 5: Network Outage & Fail-Secure Deadbolt Fallback** $\rightarrow$ [PASS] 5-second countdown locks deadbolt on link severance.
* **Step 6: Network Link Reconnection & State Reconciliation** $\rightarrow$ [PASS] MQTT session re-establishes and clears fallback banners.
* **Step 7: Time-of-Day Scene Scheduler Activation** $\rightarrow$ [PASS] Night scene broadcasts and sets target states across all nodes.
* **Step 8: Controller Restart & SQLite Persistence Recovery** $\rightarrow$ [PASS] Full controller restart cleanly recovers states, overrides, and rules from SQLite.

---

## 9. Conclusion

The AetherHome project successfully proves that a distributed, robust, and resilient IoT smart home infrastructure can be modeled in pure software. By adhering to real-world industrial IoT standards—separate OS process boundaries, RFC-compliant MQTT 3.1.1 messaging, Last Will and Testament status tracking, non-volatile state persistence, and autonomous local fallback policies—the simulator achieves high architectural fidelity and complete fault tolerance.
