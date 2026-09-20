"""
FastAPI Web Application and WebSocket Server for Home Automation System.
Provides REST APIs and real-time WebSocket telemetry for the Web Dashboard.
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from controller.controller import HomeController

logger = logging.getLogger("WebApp")

app = FastAPI(title="Smart Home Controller API", version="1.0.0")

# Mount static files
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Shared controller instance
controller: Optional[HomeController] = None
connected_websockets: List[WebSocket] = []
main_loop: Optional[asyncio.AbstractEventLoop] = None


class CommandRequest(BaseModel):
    command: Dict[str, Any]
    as_manual_override: bool = False
    duration_seconds: Optional[int] = None
    reason: Optional[str] = "Dashboard User Action"


class OverrideRequest(BaseModel):
    target_state: Dict[str, Any]
    duration_seconds: Optional[int] = None
    reason: Optional[str] = "Manual User Action"


class OutageRequest(BaseModel):
    outage: bool


class LocalInputRequest(BaseModel):
    action: str
    pin: Optional[str] = None
    power: Optional[str] = None
    state: Optional[str] = None


class SensorSimulateRequest(BaseModel):
    sensor_id: str = "sensors_living_room"
    temperature: Optional[float] = None
    humidity: Optional[int] = None
    motion: Optional[bool] = None
    illuminance_lux: Optional[int] = None


class SceneActivateRequest(BaseModel):
    force_override: bool = False


class VirtualTimeRequest(BaseModel):
    time: Optional[str] = None  # e.g. "07:00", "18:30" or null to reset


@app.on_event("startup")
async def startup_event():
    global controller, main_loop
    main_loop = asyncio.get_running_loop()
    controller = HomeController()
    controller.start()

    # Register controller listener to broadcast over WebSockets
    def on_controller_update(event_payload: Dict[str, Any]):
        if main_loop and main_loop.is_running():
            asyncio.run_coroutine_threadsafe(broadcast_ws(event_payload), main_loop)

    controller.add_update_listener(on_controller_update)
    logger.info("FastAPI Server & Home Controller started.")


@app.on_event("shutdown")
async def shutdown_event():
    global controller
    if controller:
        controller.stop()


async def broadcast_ws(message: Dict[str, Any]):
    dead_sockets = []
    text = json.dumps(message)
    for ws in connected_websockets:
        try:
            await ws.send_text(text)
        except Exception:
            dead_sockets.append(ws)
    for dead in dead_sockets:
        if dead in connected_websockets:
            connected_websockets.remove(dead)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_websockets.append(websocket)
    try:
        # Send initial full state bundle
        initial_bundle = {
            "event": "initial_state",
            "data": {
                "devices": controller.devices if controller else {},
                "overrides": controller.db.get_all_manual_overrides() if controller else {},
                "rules": controller.db.get_rules() if controller else [],
                "scenes": controller.db.get_scenes() if controller else [],
                "logs": controller.db.get_recent_logs(20) if controller else [],
                "simulated_time": controller.scheduler.get_current_simulated_time_str() if controller else "12:00",
                "virtual_mode": controller.scheduler.virtual_mode if controller else False
            }
        }
        await websocket.send_text(json.dumps(initial_bundle))

        while True:
            text = await websocket.receive_text()
            try:
                msg = json.loads(text)
                action = msg.get("action")
                if action == "command" and controller:
                    if msg.get("as_manual_override"):
                        controller.set_manual_override(msg["device_id"], msg["command"], msg.get("duration_seconds", 300), msg.get("reason", "WebSocket Override"))
                    else:
                        controller.dispatch_command(msg["device_id"], msg["command"], source="websocket")
                elif action == "override" and controller:
                    controller.set_manual_override(msg["device_id"], msg["target_state"], msg.get("duration_seconds"), msg.get("reason", "WebSocket"))
                elif action == "clear_override" and controller:
                    controller.clear_manual_override(msg["device_id"])
                elif action == "sensor" and controller:
                    sensor_id = msg.get("sensor_id", "sensors_living_room")
                    controller.simulate_sensor_input(sensor_id, msg["data"])
                elif action == "outage" and controller:
                    controller.simulate_outage(msg["device_id"], msg.get("outage", True))
                elif action == "outage_all" and controller:
                    for dev_id in controller.devices.keys():
                        if dev_id.startswith("light") or dev_id.startswith("fan") or dev_id.startswith("lock"):
                            controller.simulate_outage(dev_id, msg.get("outage", True))
                elif action == "scene" and controller:
                    controller.scheduler.activate_scene(msg["scene_id"], force_override=msg.get("force_override", False))
                elif action == "virtual_time" and controller:
                    controller.scheduler.set_virtual_time(msg.get("time"))
                    c_time = controller.scheduler.get_current_simulated_time_str()
                    controller.notify_listeners("time_update", {
                        "simulated_time": c_time,
                        "virtual_mode": controller.scheduler.virtual_mode
                    })
                elif action == "rule_toggle" and controller:
                    rules = {r["rule_id"]: r for r in controller.db.get_rules()}
                    r_id = msg["rule_id"]
                    if r_id in rules:
                        n_st = not rules[r_id]["enabled"]
                        controller.db.set_rule_enabled(r_id, n_st)
                        controller.notify_listeners("rule_toggle", {"rule_id": r_id, "enabled": n_st})
                elif action == "local_input" and controller:
                    t_topic = f"home/devices/{msg['device_id']}/local_input"
                    controller.mqtt_client.publish(t_topic, json.dumps(msg["payload"]), qos=1)
            except Exception as e:
                logger.error(f"WebSocket client command error: {e}")
    except WebSocketDisconnect:
        if websocket in connected_websockets:
            connected_websockets.remove(websocket)


@app.get("/")
async def root():
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/api/state")
async def get_full_state():
    return {
        "devices": controller.devices,
        "overrides": controller.db.get_all_manual_overrides(),
        "rules": controller.db.get_rules(),
        "scenes": controller.db.get_scenes(),
        "simulated_time": controller.scheduler.get_current_simulated_time_str(),
        "virtual_mode": controller.scheduler.virtual_mode
    }


@app.get("/api/devices")
async def get_devices():
    return controller.devices


@app.post("/api/devices/{device_id}/command")
async def send_device_command(device_id: str, req: CommandRequest):
    if req.as_manual_override:
        controller.set_manual_override(device_id, req.command, req.duration_seconds, req.reason or "Dashboard Override")
    else:
        controller.dispatch_command(device_id, req.command, source="web_dashboard")
    return {"status": "dispatched", "device_id": device_id, "command": req.command}


@app.post("/api/devices/{device_id}/override")
async def set_device_override(device_id: str, req: OverrideRequest):
    controller.set_manual_override(device_id, req.target_state, req.duration_seconds, req.reason or "Dashboard Override")
    return {"status": "override_set", "device_id": device_id}


@app.delete("/api/devices/{device_id}/override")
async def clear_device_override(device_id: str):
    controller.clear_manual_override(device_id)
    return {"status": "override_cleared", "device_id": device_id}


@app.post("/api/devices/{device_id}/outage")
async def toggle_device_outage(device_id: str, req: OutageRequest):
    controller.simulate_outage(device_id, req.outage)
    return {"status": "outage_toggled", "device_id": device_id, "outage": req.outage}


@app.post("/api/outage/all")
async def toggle_global_outage(req: OutageRequest):
    for dev_id in controller.devices.keys():
        if dev_id.startswith("light") or dev_id.startswith("fan") or dev_id.startswith("lock"):
            controller.simulate_outage(dev_id, req.outage)
    return {"status": "global_outage_toggled", "outage": req.outage}


@app.post("/api/devices/{device_id}/local_input")
async def send_device_local_input(device_id: str, req: LocalInputRequest):
    topic = f"home/devices/{device_id}/local_input"
    payload = req.dict(exclude_none=True)
    controller.mqtt_client.publish(topic, json.dumps(payload), qos=1)
    controller.db.log_event("LOCAL_INPUT_SIMULATED", "Simulator", f"Physical input on {device_id}", payload)
    return {"status": "local_input_sent", "device_id": device_id}


@app.get("/api/rules")
async def get_rules():
    return controller.db.get_rules()


@app.post("/api/rules/{rule_id}/toggle")
async def toggle_rule(rule_id: str):
    rules = {r["rule_id"]: r for r in controller.db.get_rules()}
    if rule_id not in rules:
        raise HTTPException(status_code=404, detail="Rule not found")
    new_state = not rules[rule_id]["enabled"]
    controller.db.set_rule_enabled(rule_id, new_state)
    controller.notify_listeners("rule_toggle", {"rule_id": rule_id, "enabled": new_state})
    return {"rule_id": rule_id, "enabled": new_state}


@app.get("/api/scenes")
async def get_scenes():
    return controller.db.get_scenes()


@app.post("/api/scenes/{scene_id}/activate")
async def activate_scene(scene_id: str, req: SceneActivateRequest):
    success = controller.scheduler.activate_scene(scene_id, force_override=req.force_override)
    if not success:
        raise HTTPException(status_code=404, detail="Scene not found")
    return {"status": "activated", "scene_id": scene_id, "force": req.force_override}


@app.post("/api/scheduler/time")
async def set_scheduler_time(req: VirtualTimeRequest):
    controller.scheduler.set_virtual_time(req.time)
    current_time = controller.scheduler.get_current_simulated_time_str()
    controller.notify_listeners("time_update", {
        "simulated_time": current_time,
        "virtual_mode": controller.scheduler.virtual_mode
    })
    return {"status": "updated", "simulated_time": current_time, "virtual_mode": controller.scheduler.virtual_mode}


@app.post("/api/sensors/simulate")
async def simulate_sensor(req: SensorSimulateRequest):
    data = req.dict(exclude_none=True)
    sensor_id = data.pop("sensor_id", "sensors_living_room")
    controller.simulate_sensor_input(sensor_id, data)
    return {"status": "sensor_simulated", "data": data}


@app.get("/api/logs")
async def get_logs(limit: int = 50):
    return controller.db.get_recent_logs(limit)
