from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict, List
import uuid
import asyncio, json
import math

import numpy as np

from app.models import MissionCreate, MissionStart
from app.voronoi import build_search_grid, lloyd_step

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
        "elapsed_seconds": 0,
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
    mission.setdefault("_found_target_ids", [])
    mission.setdefault("elapsed_seconds", 0)
    import random

    async def emit_target_found(target: dict, drone_id: Optional[str] = None):
        found_ids = mission.setdefault("_found_target_ids", [])
        if target["id"] in found_ids:
            return
        found_ids.append(target["id"])
        await manager.broadcast({
            "type": "target_found",
            "target_id": target["id"],
            "drone_id": drone_id,
            "lat": target["lat"],
            "lon": target["lon"],
            "found_at": mission.get("elapsed_seconds", 0),
        })
    
    while mission["status"] == "running":
        mission["elapsed_seconds"] = mission.get("elapsed_seconds", 0) + 1
        bounds = mission["bounds"]
        SPEED = 0.001
        DETECTION_RADIUS = 0.012
        TARGET_STOP_RADIUS = 0.0005
        
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

        def find_target(target_id):
            return next((t for t in mission.get("targets", []) if t["id"] == target_id), None)

        def find_drone(drone_id):
            return next((d for d in mission["drones"] if d["id"] == drone_id), None)

        def assign_confirmation_drone(target, finder_drone):
            finder_pos_lat = finder_drone["lat"]
            finder_pos_lon = finder_drone["lon"]
            candidates = [
                d
                for d in mission["drones"]
                if d["id"] != finder_drone["id"] and not d.get("assigned_target_id")
            ]
            if not candidates:
                return None
            confirmer = min(
                candidates,
                key=lambda d: math.hypot(d["lat"] - finder_pos_lat, d["lon"] - finder_pos_lon),
            )
            confirmer["assigned_target_id"] = target["id"]
            confirmer["role"] = "confirmer"
            target["confirming_drone_id"] = confirmer["id"]
            target["status"] = "confirming"
            return confirmer
        
        # 1. Compute Voronoi centroids for all unassigned drones (once per tick).
        # Only drones without an assigned target participate in coverage.
        centroid_map: dict = {}
        if "grid" in mission:
            free_drones = [
                d for d in mission["drones"]
                if not d.get("assigned_target_id") and d.get("role") not in ["finder", "confirmer"]
            ]
            if free_drones:
                grid_np = np.array(mission["grid"])
                positions = np.array([[d["lat"], d["lon"]] for d in free_drones])
                new_centroids, _ = lloyd_step(grid_np, positions)
                for d, c in zip(free_drones, new_centroids):
                    centroid_map[d["id"]] = c  # [lat, lon]

        # 1. Drone and Target logic
        for drone in mission["drones"]:
            target_id = drone.get("assigned_target_id")
            if target_id and "targets" in mission:
                target = find_target(target_id)
                if target:
                    if drone["id"] == target.get("finder_drone_id") and target.get("status") == "confirming":
                        # Finder holds position at the target while confirmation drone arrives.
                        drone["lat"] = target["lat"]
                        drone["lon"] = target["lon"]
                        drone["role"] = "finder"
                        continue

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
                        if target.get("status") in ["detected", "wandering"]:
                            # First drone arrived and found target; now request confirmation from nearest free drone.
                            target["status"] = "confirming"
                            target["finder_drone_id"] = drone["id"]
                            drone["role"] = "finder"
                            drone["lat"] = target["lat"]
                            drone["lon"] = target["lon"]
                            assign_confirmation_drone(target, drone)
                            if not target.get("confirming_drone_id"):
                                target["status"] = "found"
                                drone["assigned_target_id"] = None
                                drone["role"] = None
                                await emit_target_found(target, drone["id"])
                        elif target.get("status") == "confirming":
                            if drone["id"] == target.get("confirming_drone_id"):
                                # Confirmation drone has arrived.
                                target["status"] = "found"
                                finder = find_drone(target.get("finder_drone_id"))
                                if finder:
                                    finder["assigned_target_id"] = None
                                    finder["role"] = None
                                drone["assigned_target_id"] = None
                                drone["role"] = None
                                await emit_target_found(target, drone["id"])
                            elif drone["id"] == target.get("finder_drone_id"):
                                drone["lat"] = target["lat"]
                                drone["lon"] = target["lon"]
                else:
                    drone["assigned_target_id"] = None
                    drone["role"] = None
            else:
                if drone.get("role") not in ["finder", "confirmer"]:
                    drone["role"] = None
                centroid = centroid_map.get(drone["id"])
                if centroid is not None:
                    # Move toward Voronoi centroid for this drone's coverage cell.
                    d_lat = centroid[0] - drone["lat"]
                    d_lon = centroid[1] - drone["lon"]
                    dist = math.hypot(d_lat, d_lon)
                    if dist > TARGET_STOP_RADIUS:
                        drone["lat"] += (d_lat / dist) * SPEED
                        drone["lon"] += (d_lon / dist) * SPEED
                        drone["lat"] += random.uniform(-JITTER_DEG / 2, JITTER_DEG / 2)
                        drone["lon"] += random.uniform(-JITTER_DEG / 2, JITTER_DEG / 2)
                    bounce(drone, d_lat, d_lon)
                else:
                    # Fallback: random walk (used while grid is not yet available).
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
                        nearest_drone["role"] = None

        # Check if all targets have been found
        all_targets_found = False
        if "targets" in mission and mission["targets"]:
            all_targets_found = all(t.get("status") == "found" for t in mission["targets"])
            if all_targets_found:
                mission["status"] = "complete"
                mission["progress"] = 100.0

        # 2. Update Progress (only while running)
        if mission.get("status") == "running" and mission["progress"] < 100.0:
            mission["progress"] += 0.75
        if mission["progress"] >= 100.0:
            mission["progress"] = 100.0
            if mission.get("status") == "running":
                if "targets" in mission:
                    for target in mission["targets"]:
                        if target.get("status") == "found":
                            continue
                        target["status"] = "found"
                        assigned_drone_id = (
                            target.get("confirming_drone_id")
                            or target.get("finder_drone_id")
                            or target.get("assigned_drone_id")
                        )
                        for drone_id_key in ("confirming_drone_id", "finder_drone_id", "assigned_drone_id"):
                            drone_id = target.get(drone_id_key)
                            if not drone_id:
                                continue
                            drone = find_drone(drone_id)
                            if drone:
                                drone["assigned_target_id"] = None
                                drone["role"] = None
                        await emit_target_found(target, assigned_drone_id)
                mission["status"] = "complete"
                all_targets_found = True

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
                "status": mission.get("status", "running"),
                "progress": mission["progress"],
                "targets": mission["targets"]
            })

        if all_targets_found:
            break

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
    mission["elapsed_seconds"] = 0
    mission["_found_target_ids"] = []
    
    if start_data:
        if start_data.drones is not None:
            mission["drones"] = [d.model_dump() for d in start_data.drones]
        if start_data.algorithm is not None:
            mission["algorithm"] = start_data.algorithm
            
    # TODO: algorithm marker selection, for now it's randomly generated
    import random
    
    bounds = mission["bounds"]

    # Build the Voronoi search grid once and store it on the mission.
    # simulation_loop reads this each tick to run lloyd_step.
    mission["grid"] = build_search_grid(bounds, n=15).tolist()

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
