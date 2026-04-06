import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.sitl import telemetry_drones_from_sitl_bridge
from app.ws import manager


router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        drones = telemetry_drones_from_sitl_bridge()
        if drones:
            await websocket.send_text(json.dumps({"type": "telemetry", "drones": drones}))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
