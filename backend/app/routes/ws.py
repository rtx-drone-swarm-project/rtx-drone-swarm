"""WebSocket route for streaming telemetry to browser clients."""

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

# Import sitl_bridge directly!
from app.sitl import sitl_bridge
from app.ws import manager


router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Accept a telemetry socket and push the latest idle SITL snapshot on connect."""
    await manager.connect(websocket)
    try:
        # Get the states directly from the bridge and convert the dict to a list
        states_dict = sitl_bridge.get_states_by_sysid()
        if states_dict:
            drones_list = list(states_dict.values())
            await websocket.send_text(json.dumps({"type": "telemetry", "drones": drones_list}))
            
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)