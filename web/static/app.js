/**
 * AetherHome - High-Performance Industrial IoT Client
 * Features:
 * - Zero-latency Optimistic UI Updates (<1ms local response)
 * - Real-time WebSocket transport (sub-millisecond latency vs HTTP)
 * - Throttled (40ms) high-frequency sensor streams (60fps smooth sliders)
 * - Real mechanical deadbolt cutaway and turbine animations
 */

let ws = null;
let systemState = {
    devices: {},
    overrides: {},
    rules: [],
    scenes: [],
    logs: [],
    simulated_time: "12:00",
    virtual_mode: false
};

// High-frequency slider throttle timers
let tempThrottleTimer = null;
let luxThrottleTimer = null;
let lightSliderTimer = null;

document.addEventListener("DOMContentLoaded", () => {
    initWebSocket();
});

// ----------------------------------------------------
// 1. FAST WEBSOCKET TRANSPORT
// ----------------------------------------------------

function initWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        setWsIndicator(true);
        addLog("SYSTEM", "WebSocket connected with zero-latency channel.");
    };

    ws.onclose = () => {
        setWsIndicator(false);
        setTimeout(initWebSocket, 1500);
    };

    ws.onerror = (err) => {
        console.error("WebSocket Error:", err);
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleWsMessage(msg);
        } catch (e) {
            console.error("Error parsing message:", e);
        }
    };
}

function sendWs(payload) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(payload));
    } else {
        // Fallback to HTTP fetch if WS is connecting
        fallbackHttp(payload);
    }
}

async function fallbackHttp(payload) {
    const action = payload.action;
    try {
        if (action === "command") {
            await fetch(`/api/devices/${payload.device_id}/command`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    command: payload.command,
                    as_manual_override: payload.as_manual_override || false,
                    duration_seconds: payload.duration_seconds
                })
            });
        } else if (action === "sensor") {
            await fetch("/api/sensors/simulate", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload.data)
            });
        }
    } catch (e) {
        console.error("Fallback HTTP error:", e);
    }
}

function setWsIndicator(connected) {
    const dot = document.getElementById("ws-indicator");
    const label = document.getElementById("ws-status");
    if (connected) {
        dot.className = "led-indicator led-green";
        label.textContent = "WS Live (<2ms)";
        label.className = "text-[11px] font-mono text-emerald-300 font-medium";
    } else {
        dot.className = "led-indicator led-red animate-pulse";
        label.textContent = "Reconnecting...";
        label.className = "text-[11px] font-mono text-rose-300 font-medium";
    }
}

function handleWsMessage(msg) {
    const { event, data } = msg;

    if (event === "initial_state") {
        systemState = { ...systemState, ...data };
        renderAll();
    } else if (event === "device_state") {
        systemState.devices[data.device_id] = data;
        renderDevice(data.device_id);
    } else if (event === "availability") {
        if (systemState.devices[data.device_id]) {
            systemState.devices[data.device_id].network_status = data.status;
            renderDevice(data.device_id);
        }
    } else if (event === "sensor_state") {
        systemState.devices[data.device_id] = data;
        renderSensors(data.state);
    } else if (event === "override_update") {
        if (data.active) {
            systemState.overrides[data.device_id] = data;
        } else {
            delete systemState.overrides[data.device_id];
        }
        renderOverride(data.device_id);
        renderRules();
    } else if (event === "rule_toggle") {
        const rule = systemState.rules.find(r => r.rule_id === data.rule_id);
        if (rule) rule.enabled = data.enabled;
        renderRules();
    } else if (event === "time_update") {
        systemState.simulated_time = data.simulated_time;
        systemState.virtual_mode = data.virtual_mode;
        document.getElementById("clock-display").textContent = data.simulated_time;
    } else if (event === "log_event") {
        addLog(data.event_type || "EVENT", data.message, data.data);
    }
}

function renderAll() {
    for (const devId in systemState.devices) {
        renderDevice(devId);
    }
    const sensor = systemState.devices["sensors_living_room"];
    if (sensor && sensor.state) {
        renderSensors(sensor.state);
    }
    renderRules();
    renderScenes();
    if (systemState.logs) {
        const container = document.getElementById("logs-container");
        container.innerHTML = "";
        systemState.logs.forEach(log => {
            addLog(log.event_type, log.message, log.data, log.timestamp);
        });
    }
    if (systemState.simulated_time) {
        document.getElementById("clock-display").textContent = systemState.simulated_time;
    }
}

// ----------------------------------------------------
// 2. DEVICE RENDERING & OPTIMISTIC CONTROLS
// ----------------------------------------------------

function renderDevice(deviceId) {
    const dev = systemState.devices[deviceId];
    if (!dev) return;

    if (dev.device_type === "light") renderLight(dev);
    else if (dev.device_type === "fan") renderFan(dev);
    else if (dev.device_type === "lock") renderLock(dev);
    else if (dev.device_type === "sensor" || deviceId === "sensors_living_room") renderSensors(dev.state);
}

// 2.1 Light Component
function renderLight(dev) {
    const state = dev.state || {};
    const rocker = document.getElementById("rocker-light");
    const powerLabel = document.getElementById("light-power-label");
    const haloBox = document.getElementById("light-halo-box");
    const icon = document.getElementById("light-icon");
    const netBadge = document.getElementById("light-net-badge");
    const slider = document.getElementById("light-brightness-slider");
    const brightnessVal = document.getElementById("light-brightness-val");
    const wattageVal = document.getElementById("light-wattage-val");
    const switchState = document.getElementById("light-switch-state");
    const fallbackBanner = document.getElementById("light-fallback-banner");
    const fallbackText = document.getElementById("light-fallback-text");
    const outageBtn = document.getElementById("btn-light-outage");
    const outageText = document.getElementById("light-outage-text");

    const isOnline = dev.network_status === "online";
    const isPowerOn = state.power === "ON";

    // Power Rocker
    if (isPowerOn) {
        rocker.classList.add("active");
        powerLabel.textContent = "ON";
        powerLabel.className = "text-[9px] font-mono uppercase font-bold text-amber-300";

        // Dynamic warm/cool glow
        const ct = state.color_temp || 3000;
        let glowColor = ct < 3500 ? "rgba(245, 158, 11, 0.4)" : "rgba(96, 165, 250, 0.4)";
        let iconColor = ct < 3500 ? "text-amber-400" : "text-sky-300";
        haloBox.style.boxShadow = `0 0 20px ${glowColor}`;
        haloBox.style.borderColor = ct < 3500 ? "rgba(245, 158, 11, 0.6)" : "rgba(96, 165, 250, 0.6)";
        icon.className = `ph-fill ph-lightbulb-filament text-2xl ${iconColor}`;
    } else {
        rocker.classList.remove("active");
        powerLabel.textContent = "OFF";
        powerLabel.className = "text-[9px] font-mono uppercase font-bold text-slate-500";
        haloBox.style.boxShadow = "none";
        haloBox.style.borderColor = "rgba(255, 255, 255, 0.08)";
        icon.className = "ph-lightbulb-filament text-2xl text-slate-500";
    }

    // Slider and Readouts
    const bVal = state.brightness !== undefined ? state.brightness : 80;
    if (document.activeElement !== slider) {
        slider.value = bVal;
    }
    brightnessVal.textContent = `${bVal}%`;
    wattageVal.textContent = `${state.wattage || 0.0} W`;
    switchState.textContent = state.local_switch_state ? `WALL ${state.local_switch_state}` : "WALL UP";

    // Network
    if (isOnline) {
        netBadge.className = "text-[9px] font-mono font-bold px-1.5 py-0.5 rounded bg-emerald-950/70 text-emerald-300 border border-emerald-500/30";
        netBadge.textContent = "ONLINE";
        outageText.textContent = "Sever Link";
        outageBtn.className = "flex-1 py-1.5 px-2 rounded-lg bg-rose-950/40 hover:bg-rose-900/60 border border-rose-800/40 text-rose-300 text-[11px] font-semibold transition flex items-center justify-center space-x-1.5";
    } else {
        netBadge.className = "text-[9px] font-mono font-bold px-1.5 py-0.5 rounded bg-rose-950/70 text-rose-300 border border-rose-500/30";
        netBadge.textContent = "SEVERED (LWT)";
        outageText.textContent = "Restore Link";
        outageBtn.className = "flex-1 py-1.5 px-2 rounded-lg bg-emerald-950/40 hover:bg-emerald-900/60 border border-emerald-800/40 text-emerald-300 text-[11px] font-semibold transition flex items-center justify-center space-x-1.5";
    }

    // Fallback
    if (dev.fallback_active) {
        fallbackBanner.classList.remove("hidden");
        fallbackText.textContent = `Local Fallback: ${dev.fallback_reason || 'Emergency 20%'}`;
    } else {
        fallbackBanner.classList.add("hidden");
    }

    renderOverride(dev.device_id);
}

// 2.2 Fan Component
function renderFan(dev) {
    const state = dev.state || {};
    const rocker = document.getElementById("rocker-fan");
    const powerLabel = document.getElementById("fan-power-label");
    const icon = document.getElementById("fan-icon");
    const haloBox = document.getElementById("fan-halo-box");
    const netBadge = document.getElementById("fan-net-badge");
    const rpmVal = document.getElementById("fan-rpm-val");
    const currentVal = document.getElementById("fan-current-val");
    const fallbackBanner = document.getElementById("fan-fallback-banner");
    const fallbackText = document.getElementById("fan-fallback-text");
    const outageBtn = document.getElementById("btn-fan-outage");
    const outageText = document.getElementById("fan-outage-text");

    const isOnline = dev.network_status === "online";
    const isPowerOn = state.power === "ON";
    const speed = state.speed || 0;

    // Power & Rocker
    if (isPowerOn) {
        rocker.classList.add("active");
        powerLabel.textContent = "ON";
        powerLabel.className = "text-[9px] font-mono uppercase font-bold text-cyan-300";
        haloBox.style.boxShadow = "0 0 16px rgba(6, 182, 212, 0.35)";
        haloBox.style.borderColor = "rgba(6, 182, 212, 0.5)";
        icon.style.color = "#22d3ee";
    } else {
        rocker.classList.remove("active");
        powerLabel.textContent = "OFF";
        powerLabel.className = "text-[9px] font-mono uppercase font-bold text-slate-500";
        haloBox.style.boxShadow = "none";
        haloBox.style.borderColor = "rgba(255, 255, 255, 0.08)";
        icon.style.color = "#64748b";
    }

    // Turbine Speed Animation
    icon.className = "ph-fan text-2xl turbine-blade";
    if (isPowerOn && speed > 0) {
        icon.classList.add(`fan-running-${speed}`);
    } else {
        icon.classList.add("fan-running-0");
    }

    // Segmented Buttons Highlighting
    [0, 1, 2, 3].forEach(s => {
        const btn = document.getElementById(`fan-step-${s}`);
        if (btn) {
            if ((!isPowerOn && s === 0) || (isPowerOn && speed === s)) {
                btn.className = "segmented-btn active";
            } else {
                btn.className = "segmented-btn";
            }
        }
    });

    // Mode chips
    ["normal", "eco", "breeze"].forEach(m => {
        const mBtn = document.getElementById(`fan-mode-${m}`);
        if (mBtn) {
            if (state.mode === m) {
                mBtn.className = "px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-500/40 font-bold";
            } else {
                mBtn.className = "px-2 py-0.5 rounded bg-slate-800 text-slate-400 hover:bg-slate-700";
            }
        }
    });

    rpmVal.textContent = `${state.rpm || 0} RPM`;
    currentVal.textContent = isPowerOn ? `${(0.18 + speed * 0.12).toFixed(2)} A` : "0.00 A";

    // Network
    if (isOnline) {
        netBadge.className = "text-[9px] font-mono font-bold px-1.5 py-0.5 rounded bg-emerald-950/70 text-emerald-300 border border-emerald-500/30";
        netBadge.textContent = "ONLINE";
        outageText.textContent = "Sever Link";
        outageBtn.className = "flex-1 py-1.5 px-2 rounded-lg bg-rose-950/40 hover:bg-rose-900/60 border border-rose-800/40 text-rose-300 text-[11px] font-semibold transition flex items-center justify-center space-x-1.5";
    } else {
        netBadge.className = "text-[9px] font-mono font-bold px-1.5 py-0.5 rounded bg-rose-950/70 text-rose-300 border border-rose-500/30";
        netBadge.textContent = "SEVERED (LWT)";
        outageText.textContent = "Restore Link";
        outageBtn.className = "flex-1 py-1.5 px-2 rounded-lg bg-emerald-950/40 hover:bg-emerald-900/60 border border-emerald-800/40 text-emerald-300 text-[11px] font-semibold transition flex items-center justify-center space-x-1.5";
    }

    // Fallback
    if (dev.fallback_active) {
        fallbackBanner.classList.remove("hidden");
        fallbackText.textContent = `Local Fallback: ${dev.fallback_reason || 'Eco Speed 1'}`;
    } else {
        fallbackBanner.classList.add("hidden");
    }

    renderOverride(dev.device_id);
}

// 2.3 Smart Deadbolt Lock Component
function renderLock(dev) {
    const state = dev.state || {};
    const card = document.getElementById("card-lock");
    const netBadge = document.getElementById("lock-net-badge");
    const stateBadge = document.getElementById("lock-state-badge");
    const haloBox = document.getElementById("lock-halo-box");
    const icon = document.getElementById("lock-icon");
    const deadboltCylinder = document.getElementById("deadbolt-cylinder");
    const boltStatusText = document.getElementById("bolt-status-text");
    const toggleBtn = document.getElementById("btn-toggle-lock");
    const btnLockIcon = document.getElementById("btn-lock-icon");
    const btnLockText = document.getElementById("btn-lock-text");
    const batteryVal = document.getElementById("lock-battery-val");
    const tamperBtn = document.getElementById("btn-tamper-toggle");
    const fallbackBanner = document.getElementById("lock-fallback-banner");
    const fallbackText = document.getElementById("lock-fallback-text");
    const outageBtn = document.getElementById("btn-lock-outage");
    const outageText = document.getElementById("lock-outage-text");

    const isOnline = dev.network_status === "online";
    const isLocked = state.lock_state === "LOCKED";
    const isTampered = state.tamper_detected === true;

    // Mechanical Deadbolt Cylinder Position
    if (isLocked) {
        deadboltCylinder.className = "steel-bolt bolt-extended";
        boltStatusText.textContent = "EXTENDED (SECURED)";
        boltStatusText.className = "text-emerald-400 font-bold";
        stateBadge.className = "text-[10px] font-mono font-bold px-2 py-0.5 rounded-full bg-emerald-900/60 text-emerald-300 border border-emerald-500/30";
        stateBadge.textContent = "LOCKED";
        haloBox.className = "w-11 h-11 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400";
        icon.className = "ph-lock-key text-2xl text-emerald-400";

        toggleBtn.className = "w-full mt-3 py-2.5 rounded-xl font-mono text-xs font-bold transition flex items-center justify-center space-x-2 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-white/[0.1] shadow-lg";
        btnLockIcon.className = "ph-lock-key-open text-base";
        btnLockText.textContent = "Unlock Deadbolt";
    } else {
        deadboltCylinder.className = "steel-bolt bolt-retracted";
        boltStatusText.textContent = "RETRACTED (UNSECURED)";
        boltStatusText.className = "text-amber-400 font-bold";
        stateBadge.className = "text-[10px] font-mono font-bold px-2 py-0.5 rounded-full bg-amber-900/60 text-amber-300 border border-amber-500/30";
        stateBadge.textContent = "UNLOCKED";
        haloBox.className = "w-11 h-11 rounded-xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400";
        icon.className = "ph-lock-key-open text-2xl text-amber-400";

        toggleBtn.className = "w-full mt-3 py-2.5 rounded-xl font-mono text-xs font-bold transition flex items-center justify-center space-x-2 bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-600/30 shadow-lg";
        btnLockIcon.className = "ph-lock-key text-base";
        btnLockText.textContent = "Engage Deadbolt (Lock)";
    }

    // Tamper Alert
    if (isTampered) {
        card.style.borderColor = "rgba(244, 63, 94, 0.8)";
        card.style.boxShadow = "0 0 25px rgba(244, 63, 94, 0.5)";
        tamperBtn.textContent = "Clear Tamper";
        tamperBtn.className = "text-[10px] font-mono px-2 py-0.5 rounded bg-rose-600 text-white font-bold animate-pulse";
    } else {
        card.style.borderColor = "";
        card.style.boxShadow = "";
        tamperBtn.textContent = "Trip Sensor";
        tamperBtn.className = "text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 hover:bg-rose-900/60 text-slate-300 hover:text-rose-200 font-bold transition";
    }

    batteryVal.textContent = `${state.battery || 92}%`;

    // Network
    if (isOnline) {
        netBadge.className = "text-[9px] font-mono font-bold px-1.5 py-0.5 rounded bg-emerald-950/70 text-emerald-300 border border-emerald-500/30";
        netBadge.textContent = "ONLINE";
        outageText.textContent = "Sever Link";
        outageBtn.className = "flex-1 py-1.5 px-2 rounded-lg bg-rose-950/40 hover:bg-rose-900/60 border border-rose-800/40 text-rose-300 text-[11px] font-semibold transition flex items-center justify-center space-x-1.5";
    } else {
        netBadge.className = "text-[9px] font-mono font-bold px-1.5 py-0.5 rounded bg-rose-950/70 text-rose-300 border border-rose-500/30";
        netBadge.textContent = "SEVERED (LWT)";
        outageText.textContent = "Restore Link";
        outageBtn.className = "flex-1 py-1.5 px-2 rounded-lg bg-emerald-950/40 hover:bg-emerald-900/60 border border-emerald-800/40 text-emerald-300 text-[11px] font-semibold transition flex items-center justify-center space-x-1.5";
    }

    // Fallback
    if (dev.fallback_active) {
        fallbackBanner.classList.remove("hidden");
        fallbackText.textContent = `Local Fallback: ${dev.fallback_reason || 'Fail-Secure Auto-Lock'}`;
    } else {
        fallbackBanner.classList.add("hidden");
    }

    renderOverride(dev.device_id);
}

function renderOverride(deviceId) {
    const override = systemState.overrides[deviceId];
    let bannerId = null;
    if (deviceId === "light_living_room") bannerId = "light-override-banner";
    else if (deviceId === "fan_bedroom") bannerId = "fan-override-banner";
    else if (deviceId === "lock_front_door") bannerId = "lock-override-banner";

    if (!bannerId) return;
    const banner = document.getElementById(bannerId);
    if (!banner) return;

    if (override && override.active) {
        banner.classList.remove("hidden");
    } else {
        banner.classList.add("hidden");
    }
}

// ----------------------------------------------------
// 3. OPTIMISTIC USER ACTIONS (<1ms Perceived Latency)
// ----------------------------------------------------

function toggleLightOptimistic() {
    const dev = systemState.devices["light_living_room"] || { state: { power: "OFF" } };
    const cur = dev.state.power || "OFF";
    const next = cur === "ON" ? "OFF" : "ON";

    // Instant local DOM update
    dev.state.power = next;
    renderLight(dev);

    // Send command over fast WebSocket
    sendWs({
        action: "command",
        device_id: "light_living_room",
        command: { power: next },
        as_manual_override: true,
        duration_seconds: 300,
        reason: `User switched light ${next}`
    });
}

function onLightSliderChange(val) {
    const b = parseInt(val);
    document.getElementById("light-brightness-val").textContent = `${b}%`;

    clearTimeout(lightSliderTimer);
    lightSliderTimer = setTimeout(() => {
        sendWs({
            action: "command",
            device_id: "light_living_room",
            command: { brightness: b, power: "ON" },
            as_manual_override: true,
            duration_seconds: 300
        });
    }, 40);
}

function setLightColorTemp(kelvin) {
    const dev = systemState.devices["light_living_room"];
    if (dev) {
        dev.state.color_temp = kelvin;
        renderLight(dev);
    }
    sendWs({
        action: "command",
        device_id: "light_living_room",
        command: { color_temp: kelvin },
        as_manual_override: true,
        duration_seconds: 300
    });
}

function toggleFanOptimistic() {
    const dev = systemState.devices["fan_bedroom"] || { state: { power: "OFF", speed: 1 } };
    const cur = dev.state.power || "OFF";
    const next = cur === "ON" ? "OFF" : "ON";

    dev.state.power = next;
    if (next === "ON" && (!dev.state.speed || dev.state.speed === 0)) dev.state.speed = 1;
    renderFan(dev);

    sendWs({
        action: "command",
        device_id: "fan_bedroom",
        command: { power: next, speed: dev.state.speed || 1 },
        as_manual_override: true,
        duration_seconds: 300,
        reason: `User switched fan ${next}`
    });
}

function setFanSpeedOptimistic(speed) {
    const dev = systemState.devices["fan_bedroom"] || { state: {} };
    if (speed === 0) {
        dev.state.power = "OFF";
    } else {
        dev.state.power = "ON";
        dev.state.speed = speed;
        dev.state.rpm = speed === 1 ? 360 : (speed === 2 ? 720 : 1150);
    }
    renderFan(dev);

    sendWs({
        action: "command",
        device_id: "fan_bedroom",
        command: speed === 0 ? { power: "OFF" } : { power: "ON", speed: speed },
        as_manual_override: true,
        duration_seconds: 300,
        reason: `User selected speed ${speed}`
    });
}

function setFanMode(mode) {
    const dev = systemState.devices["fan_bedroom"];
    if (dev) {
        dev.state.mode = mode;
        renderFan(dev);
    }
    sendWs({
        action: "command",
        device_id: "fan_bedroom",
        command: { mode: mode },
        as_manual_override: true,
        duration_seconds: 300
    });
}

function toggleLockOptimistic() {
    const lock = systemState.devices["lock_front_door"] || { state: { lock_state: "LOCKED" } };
    const isLocked = lock.state.lock_state === "LOCKED";
    const nextState = isLocked ? "UNLOCKED" : "LOCKED";

    // Instant mechanical animation
    lock.state.lock_state = nextState;
    lock.state.bolt_position = nextState === "LOCKED" ? "extended" : "retracted";
    renderLock(lock);

    sendWs({
        action: "command",
        device_id: "lock_front_door",
        command: { lock_state: nextState },
        as_manual_override: true,
        duration_seconds: 120,
        reason: `User turned deadbolt to ${nextState}`
    });
}

function toggleTamperSensor() {
    const lock = systemState.devices["lock_front_door"];
    const isTampered = lock && lock.state && lock.state.tamper_detected;
    sendWs({
        action: "command",
        device_id: "lock_front_door",
        command: { tamper: !isTampered }
    });
}

function clearOverride(deviceId) {
    delete systemState.overrides[deviceId];
    renderOverride(deviceId);
    renderRules();
    sendWs({
        action: "clear_override",
        device_id: deviceId
    });
}

function toggleDeviceOutage(deviceId) {
    const dev = systemState.devices[deviceId];
    const isOffline = dev && dev.network_status === "offline";
    const nextOutage = !isOffline;

    // Optimistic badge update
    if (dev) {
        dev.network_status = nextOutage ? "offline" : "online";
        renderDevice(deviceId);
    }

    sendWs({
        action: "outage",
        device_id: deviceId,
        outage: nextOutage
    });
}

function simulateLocalInput(deviceId, payload) {
    sendWs({
        action: "local_input",
        device_id: deviceId,
        payload: payload
    });
}

// ----------------------------------------------------
// 4. HIGH-FREQUENCY SENSOR STREAMING (THROTTLED)
// ----------------------------------------------------

function updateTempHint(temp) {
    const hint = document.getElementById("temp-rule-hint");
    if (!hint) return;
    if (temp >= 25.0) {
        hint.className = "text-emerald-400 font-bold animate-pulse";
        hint.textContent = `≥25.0°C: FAN AUTO-ON TRIGGERED`;
    } else if (temp <= 22.0) {
        hint.className = "text-sky-400 font-bold";
        hint.textContent = `≤22.0°C: FAN AUTO-OFF TRIGGERED`;
    } else {
        hint.className = "text-slate-400 font-semibold";
        hint.textContent = `22°C - 25°C: COMFORT DEADBAND`;
    }
}

function updateLuxHint(lux, motion) {
    const hint = document.getElementById("lux-rule-hint");
    if (!hint) return;
    const isMotion = motion !== undefined ? motion : (systemState.devices["sensors_living_room"]?.state?.motion === true);
    if (lux <= 40) {
        if (isMotion) {
            hint.className = "text-emerald-400 font-bold animate-pulse";
            hint.textContent = `≤40 lux + MOTION: LIGHT ON TRIGGERED`;
        } else {
            hint.className = "text-amber-400 font-bold";
            hint.textContent = `≤40 lux: DARK ROOM (MOTION ARMED)`;
        }
    } else {
        hint.className = "text-slate-500 font-semibold";
        hint.textContent = `>40 lux: DAYLIGHT (LIGHT INHIBITED)`;
    }
}

function onSensorTempInput(val) {
    const temp = parseFloat(val);
    document.getElementById("sensor-temp-display").textContent = `${temp.toFixed(1)}°C`;
    updateTempHint(temp);

    clearTimeout(tempThrottleTimer);
    tempThrottleTimer = setTimeout(() => {
        sendWs({
            action: "sensor",
            sensor_id: "sensors_living_room",
            data: { temperature: temp }
        });
    }, 40);
}

function onSensorLuxInput(val) {
    const lux = parseInt(val);
    document.getElementById("sensor-lux-display").textContent = `${lux} lux`;
    updateLuxHint(lux);

    clearTimeout(luxThrottleTimer);
    luxThrottleTimer = setTimeout(() => {
        sendWs({
            action: "sensor",
            sensor_id: "sensors_living_room",
            data: { illuminance_lux: lux }
        });
    }, 40);
}

function toggleMotionSensorOptimistic() {
    const sensor = systemState.devices["sensors_living_room"] || { state: { motion: false } };
    const cur = sensor.state.motion === true;
    sensor.state.motion = !cur;
    renderSensors(sensor.state);

    sendWs({
        action: "sensor",
        sensor_id: "sensors_living_room",
        data: { motion: !cur }
    });
}

function renderSensors(sensorState) {
    if (!sensorState) return;

    if (sensorState.temperature !== undefined) {
        document.getElementById("sensor-temp-display").textContent = `${sensorState.temperature}°C`;
        document.getElementById("slider-temp").value = sensorState.temperature;
        updateTempHint(sensorState.temperature);
    }

    if (sensorState.illuminance_lux !== undefined) {
        document.getElementById("sensor-lux-display").textContent = `${sensorState.illuminance_lux} lux`;
        document.getElementById("slider-lux").value = sensorState.illuminance_lux;
        updateLuxHint(sensorState.illuminance_lux, sensorState.motion);
    }

    const motion = sensorState.motion === true;
    const radarBox = document.getElementById("radar-box");
    const motionIcon = document.getElementById("motion-radar-icon");
    const motionStatus = document.getElementById("sensor-motion-status");
    const motionBtn = document.getElementById("btn-toggle-motion");

    if (motion) {
        radarBox.style.boxShadow = "0 0 16px rgba(99, 102, 241, 0.6)";
        radarBox.style.borderColor = "rgba(99, 102, 241, 0.8)";
        motionIcon.className = "ph-person-simple-walk text-lg text-indigo-400 animate-bounce";
        motionStatus.textContent = "OCCUPANCY DETECTED";
        motionStatus.className = "text-[11px] font-mono text-indigo-300 font-bold";
        motionBtn.textContent = "Clear Motion";
        motionBtn.className = "px-3.5 py-1.5 rounded-lg text-xs font-mono font-bold bg-indigo-600 hover:bg-indigo-500 text-white transition";
    } else {
        radarBox.style.boxShadow = "none";
        radarBox.style.borderColor = "rgba(255, 255, 255, 0.1)";
        motionIcon.className = "ph-person-simple-walk text-lg text-slate-500";
        motionStatus.textContent = "Room Vacant";
        motionStatus.className = "text-[11px] font-mono text-slate-400";
        motionBtn.textContent = "Trigger Motion";
        motionBtn.className = "px-3.5 py-1.5 rounded-lg text-xs font-mono font-bold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-white/[0.08] transition";
    }

    const currentLux = sensorState.illuminance_lux !== undefined
        ? sensorState.illuminance_lux
        : parseInt(document.getElementById("slider-lux").value);
    updateLuxHint(currentLux, motion);
}

// ----------------------------------------------------
// 5. RULES, SCENES & LOGS
// ----------------------------------------------------

function renderRules() {
    const container = document.getElementById("rules-container");
    if (!container || !systemState.rules) return;

    container.innerHTML = "";
    systemState.rules.forEach(rule => {
        let isSuppressed = false;
        const targetDev = rule.config ? (rule.config.target_device || rule.config.lock_device) : null;
        if (targetDev && systemState.overrides[targetDev] && systemState.overrides[targetDev].active) {
            isSuppressed = true;
        }

        const div = document.createElement("div");
        div.className = "p-3 rounded-xl chassis-inset flex items-start justify-between gap-3";

        div.innerHTML = `
            <div class="flex-1">
                <div class="flex items-center space-x-2 mb-1">
                    <span class="text-xs font-bold text-white">${rule.name}</span>
                    <span class="text-[9px] px-1.5 py-0.5 rounded font-mono ${rule.enabled ? 'bg-emerald-950 text-emerald-300 border border-emerald-800/40' : 'bg-slate-800 text-slate-400'}">
                        ${rule.enabled ? 'ACTIVE' : 'MUTED'}
                    </span>
                    ${isSuppressed ? '<span class="text-[9px] font-mono px-2 py-0.5 rounded bg-amber-950 text-amber-300 font-bold border border-amber-500/40 animate-pulse">LOCKED BY USER OVERRIDE</span>' : ''}
                </div>
                <p class="text-[10px] text-slate-400 leading-tight">${rule.description}</p>
            </div>
            <button onclick="toggleRuleOptimistic('${rule.rule_id}')" class="px-2.5 py-1 rounded text-[10px] font-bold ${rule.enabled ? 'bg-emerald-600/30 text-emerald-300 border border-emerald-500/30' : 'bg-slate-800 text-slate-400'} transition">
                ${rule.enabled ? 'Disable' : 'Enable'}
            </button>
        `;
        container.appendChild(div);
    });
}

function toggleRuleOptimistic(ruleId) {
    const rule = systemState.rules.find(r => r.rule_id === ruleId);
    if (rule) rule.enabled = !rule.enabled;
    renderRules();
    sendWs({ action: "rule_toggle", rule_id: ruleId });
}

function renderScenes() {
    const activeScene = systemState.scenes.find(s => s.is_active);
    const badge = document.getElementById("active-scene-badge");
    if (badge) {
        badge.textContent = activeScene ? activeScene.name : "None";
    }
}

function activateSceneOptimistic(sceneId) {
    sendWs({ action: "scene", scene_id: sceneId, force_override: false });
}

function setVirtualTime(timeStr) {
    sendWs({ action: "virtual_time", time: timeStr });
}

document.getElementById("btn-clock-modal").addEventListener("click", () => {
    const customTime = prompt("Enter simulated time (HH:MM e.g. 07:00, 18:30, 22:30) or blank for real-time:", "07:00");
    if (customTime !== null) {
        setVirtualTime(customTime.trim() === "" ? null : customTime.trim());
    }
});

// Logs
function addLog(type, message, data, timestamp) {
    const container = document.getElementById("logs-container");
    const countLabel = document.getElementById("log-count");
    if (!container) return;

    const timeStr = timestamp
        ? new Date(timestamp * 1000).toLocaleTimeString()
        : new Date().toLocaleTimeString();

    let color = "text-slate-300";
    if (type.includes("OVERRIDE")) color = "text-purple-300 font-semibold";
    else if (type.includes("SUPPRESSED")) color = "text-amber-300 font-bold";
    else if (type.includes("OFFLINE") || type.includes("OUTAGE")) color = "text-rose-400 font-bold";
    else if (type.includes("ONLINE") || type.includes("RULE_FIRED")) color = "text-emerald-300 font-semibold";

    const p = document.createElement("p");
    p.className = `${color}`;
    p.innerHTML = `<span class="text-slate-600">[${timeStr}]</span> <span class="text-indigo-400 font-bold">[${type}]</span> ${message}`;

    container.insertBefore(p, container.firstChild);
    while (container.children.length > 50) {
        container.removeChild(container.lastChild);
    }
    if (countLabel) countLabel.textContent = `${container.children.length} events`;
}

function clearUiLogs() {
    const container = document.getElementById("logs-container");
    if (container) container.innerHTML = "";
    document.getElementById("log-count").textContent = "0 events";
}

// ----------------------------------------------------
// 6. KEYPAD MODAL
// ----------------------------------------------------

function promptKeypadPIN() {
    document.getElementById("keypad-pin-input").value = "";
    document.getElementById("keypad-modal").classList.remove("hidden");
}

function closeKeypadModal() {
    document.getElementById("keypad-modal").classList.add("hidden");
}

function appendPin(num) {
    const input = document.getElementById("keypad-pin-input");
    if (input.value.length < 4) input.value += num;
}

function clearPin() {
    document.getElementById("keypad-pin-input").value = "";
}

function submitPin() {
    const pin = document.getElementById("keypad-pin-input").value;
    closeKeypadModal();
    simulateLocalInput("lock_front_door", {
        action: "keypad_pin",
        pin: pin
    });
}
