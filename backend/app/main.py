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
        bounds = mission["bounds"]
        SPEED = 0.001
        DETECTION_RADIUS = 0.005
        TARGET_STOP_RADIUS = 0.0001
        
        def bounce(entity, vx, vy):
            if entity["lat"] < bounds["min_lat"]:
                entity["lat"] = bounds["min_lat"]
                entity["vx"] = abs(vx)
            elif entity["lat"] > bounds["max_lat"]:
                entity["lat"] = bounds["max_lat"]
                entity["vx"] = -abs(vx)
            if entity["lon"] < bounds["min_lon"]:
                entity["lon"] = bounds["min_lon"]
                entity["vy"] = abs(vy)
            elif entity["lon"] > bounds["max_lon"]:
                entity["lon"] = bounds["max_lon"]
                entity["vy"] = -abs(vy)
        
        # 1. Drone and Target logic
        for drone in mission["drones"]:
            target_id = drone.get("assigned_target_id")
            if target_id and "targets" in mission:
                # Move towards target
                target = next((t for t in mission["targets"] if t["id"] == target_id), None)
                if target:
                    d_lat = target["lat"] - drone["lat"]
                    d_lon = target["lon"] - drone["lon"]
                    dist = math.hypot(d_lat, d_lon)
                    if dist > TARGET_STOP_RADIUS:
                        drone["lat"] += (d_lat / dist) * SPEED
                        drone["lon"] += (d_lon / dist) * SPEED
                        # Jitter
                        drone["lat"] += random.uniform(-JITTER_DEG/2, JITTER_DEG/2)
                        drone["lon"] += random.uniform(-JITTER_DEG/2, JITTER_DEG/2)
                    else:
                        target["status"] = "found"
                        # they stay here
                else:
                    drone["assigned_target_id"] = None
            else:
                if "vx" not in drone:
                    angle = random.uniform(0, 2 * math.pi)
                    drone["vx"] = SPEED * math.cos(angle)
                    drone["vy"] = SPEED * math.sin(angle)
                drone["lat"] += drone["vx"]
                drone["lon"] += drone["vy"]
                bounce(drone, drone["vx"], drone["vy"])
                
        if "targets" in mission:
            for target in mission["targets"]:
                if target.get("status", "wandering") == "wandering":
                    if "vx" not in target:
                        angle = random.uniform(0, 2 * math.pi)
                        target["vx"] = (SPEED/2) * math.cos(angle)
                        target["vy"] = (SPEED/2) * math.sin(angle)
                    target["lat"] += target["vx"]
                    target["lon"] += target["vy"]
                    bounce(target, target["vx"], target["vy"])
                    
                    nearest_drone = None
                    min_dist = float('inf')
                    for drone in mission["drones"]:
                        dist = math.hypot(drone["lat"] - target["lat"], drone["lon"] - target["lon"])
                        if dist < min_dist:
                            min_dist = dist
                            nearest_drone = drone
                            
                    if min_dist < DETECTION_RADIUS and nearest_drone and not nearest_drone.get("assigned_target_id"):
                        target["status"] = "detected"
                        target["assigned_drone_id"] = nearest_drone["id"]
                        nearest_drone["assigned_target_id"] = target["id"]

        # 2. Update Progress
        if mission["progress"] < 100.0:
            mission["progress"] += 0.75
        if mission["progress"] >= 100.0:
            mission["progress"] = 100.0

        # 3. Broadcast Telemetry and Progress
        await manager.broadcast({
            "type": "telemetry",
            "drones": mission["drones"]
        })
        
        await manager.broadcast({
            "type": "mission_progress",
            "progress": mission["progress"]
        })
        
        # Also broadcast targets to update their positions
        if "targets" in mission:
            await manager.broadcast({
                "type": "mission_status",
                "mission_id": mission_id,
                "status": "running",
                "progress": mission["progress"],
                "targets": mission["targets"]
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
            
    # TODO: algorithm marker selection, for now it's randomly generated
    import random
    
    bounds = mission["bounds"]
    num_targets = random.randint(2, 3) # Randomly choose 2 or 3 targets as requested
    targets = []
    
    for i in range(num_targets):
        # We don't assign to a specific drone anymore since there are fewer targets than drones
        t_lat = random.uniform(bounds["min_lat"], bounds["max_lat"])
        t_lon = random.uniform(bounds["min_lon"], bounds["max_lon"])
        
        targets.append({
            "id": f"tgt-{uuid.uuid4().hex[:8]}",
            "lat": t_lat,
            "lon": t_lon,
            "status": "wandering",
            "assigned_drone_id": None
        })
        
    mission["targets"] = targets
            
    # Broadcast status change
    await manager.broadcast({
        "type": "mission_status",
        "mission_id": mission_id,
        "status": "running",
        "progress": mission["progress"],
        "targets": targets
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
    mission["progress"] = 0.0
    
    # Broadcast stopped status
    await manager.broadcast({
        "type": "mission_status",
        "mission_id": mission_id,
        "status": "stopped",
        "progress": mission["progress"]
    })
    
    return mission