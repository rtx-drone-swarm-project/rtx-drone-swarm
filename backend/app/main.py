from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict, List
import uuid
import asyncio, json
import math

from app.models import MissionCreate, MissionStart

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        dead = []
        for conn in self.active_connections:
            try:
                await conn.send_text(json.dumps(message))
            except:
                dead.append(conn)
        for conn in dead:
            self.disconnect(conn)

manager = ConnectionManager()
app = FastAPI()

# Allow the Vite dev server (and Docker-exposed frontend) to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # Docker / production frontend
        "http://localhost:5174",   # Vite dev server (npm run dev)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# TODO: Until Redis Container is ready, use this in-memory DB
missions_db: Dict[str, dict] = {}

# --- Endpoints ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/missions")
def create_mission(mission_data: MissionCreate):
    mission_id = str(uuid.uuid4())

    mission = {
        "id": mission_id,
        "name": mission_data.name,
        "status": "idle",
        "progress": 0.0,
        "bounds": mission_data.bounds.model_dump(),
        "drones": [d.model_dump() for d in mission_data.drones],
        "hikers": [m.model_dump() for m in mission_data.hikers] if mission_data.hikers else []
    }
    missions_db[mission_id] = mission
    return mission

# Physics/Sim Constants
JITTER_DEG = 0.0001

async def simulation_loop(mission_id: str):
    """
    Background task that acts as a simple progress bar filler and adds jitter
    to the drones so they appear 'active'.
    
    TODO: Delete this loop once real SITL telemetry is connected via the
    POST /telemetry endpoint (see bottom of file).
    """
    if mission_id not in missions_db:
        return
        
    mission = missions_db[mission_id]
    import random
    
    while mission["status"] == "running":
        # 1. Jitter drone positions slightly to simulate activity
        for drone in mission["drones"]:
            drone["lat"] += random.uniform(-JITTER_DEG, JITTER_DEG)
            drone["lon"] += random.uniform(-JITTER_DEG, JITTER_DEG)

        # 2. Update Progress (mocked simple progression 1% per tick)
        if mission["progress"] < 100.0:
            mission["progress"] = min(100.0, mission["progress"] + 1.0)

        # 3. Broadcast Telemetry and Progress
        await manager.broadcast({
            "type": "telemetry",
            "drones": mission["drones"]
        })
        
        await manager.broadcast({
            "type": "mission_progress",
            "progress": mission["progress"]
        })

        # 4. Wait for next tick
        await asyncio.sleep(1.0)


@app.post("/missions/{mission_id}/start")
async def start_mission(mission_id: str, start_data: Optional[MissionStart] = None):
    if mission_id not in missions_db:
        raise HTTPException(status_code=404, detail="Mission not found")
        
    mission = missions_db[mission_id]
    
    if mission["status"] != "idle":
        raise HTTPException(status_code=400, detail="Only 'idle' missions can be started")
        
    mission["status"] = "running"
    
    if start_data:
        if start_data.drones is not None:
            mission["drones"] = [d.model_dump() for d in start_data.drones]
        if start_data.algorithm is not None:
            mission["algorithm"] = start_data.algorithm
            
    # Broadcast status change
    await manager.broadcast({
        "type": "mission_status",
        "mission_id": mission_id,
        "status": "running",
        "progress": mission["progress"]
    })
    
    # Spawn the background simulation loop
    asyncio.create_task(simulation_loop(mission_id))
            
    return mission

@app.post("/missions/{mission_id}/stop")
async def stop_mission(mission_id: str):
    if mission_id not in missions_db:
        raise HTTPException(status_code=404, detail="Mission not found")
        
    mission = missions_db[mission_id]
    
    # Optional logic: If we want to allow stopping even if "idle", adjust this. 
    # Usually "stopped" means interrupting a "running" mission.
    # We will just transition anything to stopped if it's running.
    if mission["status"] not in ["running", "idle"]:
        raise HTTPException(status_code=400, detail="Mission is already stopped or complete")
        
    # Standard dictates transitioning: running -> stopped
    mission["status"] = "stopped"
    
    # Broadcast stopped status
    await manager.broadcast({
        "type": "mission_status",
        "mission_id": mission_id,
        "status": "stopped",
        "progress": mission["progress"]
    })
    
    return mission