from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict
import uuid

from app.models import MissionCreate, MissionStart

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

@app.post("/missions/{mission_id}/start")
def start_mission(mission_id: str, start_data: Optional[MissionStart] = None):
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
            
    return mission

@app.post("/missions/{mission_id}/stop")
def stop_mission(mission_id: str):
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
    
    return mission