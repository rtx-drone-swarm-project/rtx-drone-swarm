from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional, Dict, List, Tuple
from pathlib import Path
import uuid
import asyncio, json
import math
import numpy as np
import os
import sys
import threading
import time

from app.models import MissionCreate, MissionStart, DispatchTargetsRequest
from pymavlink import mavutil
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

# TODO: Until Redis Container is ready, use this in-memory DB
missions_db: Dict[str, dict] = {}

SWARM_COMMAND_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "swarm_command.py"
DEFAULT_DISPATCH_HOST = "127.0.0.1"
DEFAULT_DISPATCH_TIMEOUT_SECONDS = 15.0
DEFAULT_DISPATCH_ALT = 30.0
START_SITL_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "start_sitl_swarm.sh"
AUTO_START_SITL_ON_MISSION_START = os.environ.get("AUTO_START_SITL_ON_MISSION_START", "0") == "1"
DEFAULT_SITL_HOME_ALT = float(os.environ.get("SITL_HOME_ALT", "0"))
DEFAULT_SITL_HOST = os.environ.get("SITL_HOST", "127.0.0.1")
DEFAULT_SITL_BASE_PORT = int(os.environ.get("SITL_BASE_PORT", "14550"))
DEFAULT_SITL_PORT_STEP = int(os.environ.get("SITL_PORT_STEP", "10"))
DEFAULT_SITL_COUNT = int(os.environ.get("SITL_COUNT", "15"))
DEFAULT_SITL_POLL_INTERVAL_SECONDS = float(os.environ.get("SITL_POLL_INTERVAL_SECONDS", "0.2"))


class SITLTelemetryBridge:
    def __init__(
        self,
        host: str = DEFAULT_SITL_HOST,
        base_port: int = DEFAULT_SITL_BASE_PORT,
        port_step: int = DEFAULT_SITL_PORT_STEP,
        count: int = DEFAULT_SITL_COUNT,
        poll_interval_seconds: float = DEFAULT_SITL_POLL_INTERVAL_SECONDS,
    ):
        self.host = host
        self.base_port = base_port
        self.port_step = port_step
        self.count = count
        self.poll_interval_seconds = poll_interval_seconds
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._connections: Dict[int, object] = {}
        self._states_by_sysid: Dict[int, dict] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="sitl-telemetry-bridge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def get_states_by_sysid(self) -> Dict[int, dict]:
        with self._lock:
            return {sysid: dict(state) for sysid, state in self._states_by_sysid.items()}

    def _run(self) -> None:
        while not self._stop_event.is_set():
            for index in range(self.count):
                if self._stop_event.is_set():
                    break
                if index not in self._connections:
                    self._try_connect(index)

            for index, conn in list(self._connections.items()):
                try:
                    while True:
                        msg = conn.recv_match(blocking=False)
                        if msg is None:
                            break
                        self._handle_message(msg)
                except Exception:
                    self._connections.pop(index, None)

            self._stop_event.wait(self.poll_interval_seconds)

    def _try_connect(self, index: int) -> None:
        port = self.base_port + index * self.port_step
        address = self._connection_address(port)
        try:
            conn = mavutil.mavlink_connection(address, source_system=255)
            conn.wait_heartbeat(timeout=0.5)
            self._connections[index] = conn
        except Exception:
            return

    def _connection_address(self, port: int) -> str:
        if self.host in ("127.0.0.1", "localhost", "0.0.0.0"):
            return f"udpin:0.0.0.0:{port}"
        return f"udp:{self.host}:{port}"

    def _handle_message(self, msg: object) -> None:
        message_type = msg.get_type()
        sysid = int(msg.get_srcSystem())
        if sysid <= 0:
            return

        with self._lock:
            state = self._states_by_sysid.setdefault(
                sysid,
                {
                    "sysid": sysid,
                    "armed": False,
                    "mode": "UNKNOWN",
                    "lat": None,
                    "lon": None,
                    "alt": None,
                    "heading": None,
                    "groundspeed": None,
                    "battery_remaining": None,
                    "has_position": False,
                    "last_seen": time.time(),
                },
            )
            state["last_seen"] = time.time()

            if message_type == "HEARTBEAT":
                state["armed"] = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                mode_name = "UNKNOWN"
                mode_mapping = mavutil.mode_string_v10(msg)
                if isinstance(mode_mapping, str) and mode_mapping:
                    mode_name = mode_mapping
                state["mode"] = mode_name
            elif message_type == "VFR_HUD":
                state["groundspeed"] = float(msg.groundspeed)
                state["alt"] = float(msg.alt)
                heading = getattr(msg, "heading", None)
                if heading not in (None, 65535):
                    state["heading"] = float(heading)
            elif message_type == "GLOBAL_POSITION_INT":
                state["lat"] = msg.lat / 1e7
                state["lon"] = msg.lon / 1e7
                state["alt"] = msg.relative_alt / 1000.0
                heading = getattr(msg, "hdg", None)
                if heading not in (None, 65535):
                    state["heading"] = heading / 100.0
                state["has_position"] = True
            elif message_type == "SYS_STATUS":
                battery_remaining = getattr(msg, "battery_remaining", None)
                if battery_remaining not in (None, -1):
                    state["battery_remaining"] = int(battery_remaining)


sitl_bridge = SITLTelemetryBridge()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    sitl_bridge.start()
    try:
        yield
    finally:
        sitl_bridge.stop()


app = FastAPI(lifespan=lifespan)

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


def _coerce_sysid(value: object) -> Optional[int]:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _dispatch_failure_row(drone_id: Optional[str], sysid: Optional[int], message: str) -> dict:
    return {
        "drone_id": drone_id,
        "sysid": sysid,
        "success": False,
        "message": message,
    }


def _extract_result_payload(stdout_text: str) -> Optional[List[dict]]:
    if not stdout_text:
        return None

    candidates = [stdout_text.strip()]
    candidates.extend(line.strip() for line in stdout_text.splitlines() if line.strip())
    for candidate in reversed(candidates):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return parsed
    return None


def _normalize_script_results(raw_results: object, expected_assignments: List[dict]) -> List[dict]:
    candidate_rows: List[dict] = []
    if isinstance(raw_results, list):
        candidate_rows = [row for row in raw_results if isinstance(row, dict)]

    normalized: List[dict] = []
    consumed_indexes = set()

    for expected in expected_assignments:
        expected_sysid = _coerce_sysid(expected.get("sysid"))
        expected_drone_id = expected.get("drone_id")

        matched_index = None
        for idx, row in enumerate(candidate_rows):
            if idx in consumed_indexes:
                continue
            row_sysid = _coerce_sysid(row.get("sysid"))
            row_drone_id = row.get("drone_id")
            if expected_sysid is not None and row_sysid == expected_sysid:
                matched_index = idx
                break
            if expected_drone_id is not None and row_drone_id == expected_drone_id:
                matched_index = idx
                break

        if matched_index is None:
            normalized.append(
                _dispatch_failure_row(
                    expected_drone_id,
                    expected_sysid,
                    "No dispatch result returned by script.",
                )
            )
            continue

        consumed_indexes.add(matched_index)
        row = candidate_rows[matched_index]
        normalized.append(
            {
                "drone_id": row.get("drone_id", expected_drone_id),
                "sysid": _coerce_sysid(row.get("sysid")) or expected_sysid,
                "success": bool(row.get("success")),
                "message": str(row.get("message", "")),
            }
        )

    return normalized


def _mission_drone_to_sysid_map(mission: dict) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    for index, drone in enumerate(mission.get("drones", []), start=1):
        drone_id = drone.get("id")
        if drone_id is None:
            continue
        sysid = _coerce_sysid(drone.get("sysid")) or index
        drone["sysid"] = sysid
        mapping[str(drone_id)] = sysid
    return mapping


def _sync_mission_drones_with_sitl(mission: dict) -> set[str]:
    live_states = sitl_bridge.get_states_by_sysid()
    live_drone_ids = set()

    for index, drone in enumerate(mission.get("drones", []), start=1):
        sysid = _coerce_sysid(drone.get("sysid")) or index
        drone["sysid"] = sysid
        live_state = live_states.get(sysid)
        if not live_state or not live_state.get("has_position"):
            drone["telemetry_source"] = "simulated"
            continue

        lat = live_state.get("lat")
        lon = live_state.get("lon")
        alt = live_state.get("alt")

        if lat is not None and lon is not None:
            drone["lat"] = float(lat)
            drone["lon"] = float(lon)
        if alt is not None:
            drone["alt"] = float(alt)

        drone["groundspeed"] = live_state.get("groundspeed")
        drone["heading"] = live_state.get("heading")
        drone["battery_remaining"] = live_state.get("battery_remaining")
        drone["armed"] = live_state.get("armed")
        drone["mode"] = live_state.get("mode")
        drone["telemetry_source"] = "sitl"
        live_drone_ids.add(str(drone.get("id")))

    return live_drone_ids


def _build_start_dispatch_assignments(mission: dict) -> List[dict]:
    assignments = []
    for index, drone in enumerate(mission.get("drones", []), start=1):
        target_lat = drone.get("target_lat")
        target_lon = drone.get("target_lon")
        if target_lat is None or target_lon is None:
            continue

        drone_id = drone.get("id")
        assignments.append(
            {
                "drone_id": str(drone_id) if drone_id is not None else None,
                "sysid": _coerce_sysid(drone.get("sysid")) or index,
                "lat": float(target_lat),
                "lon": float(target_lon),
                "alt": float(drone.get("alt") if drone.get("alt") is not None else DEFAULT_DISPATCH_ALT),
            }
        )

    return assignments


def _mission_bounds_center(bounds: dict) -> Tuple[float, float]:
    return (
        (float(bounds["min_lat"]) + float(bounds["max_lat"])) / 2.0,
        (float(bounds["min_lon"]) + float(bounds["max_lon"])) / 2.0,
    )


def _generate_coverage_points(bounds: dict, drone_count: int) -> List[Tuple[float, float]]:
    if drone_count <= 0:
        return []

    grid_side = max(2, math.ceil(math.sqrt(drone_count)))
    grid_points = build_search_grid(bounds, n=grid_side)
    if len(grid_points) <= drone_count:
        return [(float(lat), float(lon)) for lat, lon in grid_points]

    selected_indexes = np.linspace(0, len(grid_points) - 1, num=drone_count, dtype=int)
    return [(float(grid_points[idx][0]), float(grid_points[idx][1])) for idx in selected_indexes]


def _assign_start_area_targets(mission: dict) -> List[dict]:
    drones = mission.get("drones", [])
    points = _generate_coverage_points(mission["bounds"], len(drones))
    assignments: List[dict] = []

    for index, (drone, point) in enumerate(zip(drones, points), start=1):
        lat, lon = point
        drone["target_lat"] = lat
        drone["target_lon"] = lon
        if drone.get("lat") is None or drone.get("telemetry_source") != "sitl":
            drone["lat"] = lat
            drone["lon"] = lon

        assignments.append(
            {
                "drone_id": str(drone.get("id")) if drone.get("id") is not None else None,
                "sysid": _coerce_sysid(drone.get("sysid")) or index,
                "lat": lat,
                "lon": lon,
                "alt": float(drone.get("alt") if drone.get("alt") is not None else DEFAULT_DISPATCH_ALT),
            }
        )

    return assignments


async def _ensure_sitl_running_for_mission(mission: dict) -> Optional[str]:
    if not AUTO_START_SITL_ON_MISSION_START:
        return None
    if sitl_bridge.get_states_by_sysid():
        return None
    if not START_SITL_SCRIPT.exists():
        return f"SITL start script not found: {START_SITL_SCRIPT}"

    bounds = mission["bounds"]
    center_lat, center_lon = _mission_bounds_center(bounds)
    home = f"{center_lat:.7f},{center_lon:.7f},{DEFAULT_SITL_HOME_ALT:.1f},0"
    env = os.environ.copy()
    env["SITL_HOME"] = home
    env["SITL_OUT_HOST"] = DEFAULT_SITL_HOST
    env["SITL_BASE_PORT"] = str(DEFAULT_SITL_BASE_PORT)
    env["SITL_PORT_STEP"] = str(DEFAULT_SITL_PORT_STEP)

    try:
        await asyncio.create_subprocess_exec(
            str(START_SITL_SCRIPT),
            str(max(len(mission.get("drones", [])), 1)),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
        )
    except Exception as exc:
        return f"Failed to auto-start SITL: {exc}"

    return f"Starting SITL near mission center {center_lat:.5f}, {center_lon:.5f}"


def _prepare_dispatch_assignments(
    request: DispatchTargetsRequest,
    mission: dict,
) -> Tuple[List[dict], List[dict]]:
    mission_sysid_map = _mission_drone_to_sysid_map(mission)
    valid_assignments: List[dict] = []
    preflight_failures: List[dict] = []

    for item in request.assignments:
        resolved_sysid = item.sysid
        if resolved_sysid is None and item.drone_id is not None:
            resolved_sysid = mission_sysid_map.get(str(item.drone_id))

        sysid = _coerce_sysid(resolved_sysid)
        if sysid is None:
            preflight_failures.append(
                _dispatch_failure_row(
                    item.drone_id,
                    None,
                    "Cannot resolve sysid; provide sysid or a mission drone_id.",
                )
            )
            continue

        valid_assignments.append(
            {
                "drone_id": item.drone_id,
                "sysid": sysid,
                "lat": float(item.lat),
                "lon": float(item.lon),
                "alt": float(item.alt if item.alt is not None else DEFAULT_DISPATCH_ALT),
            }
        )

    return valid_assignments, preflight_failures


async def run_dispatch_script(
    assignments: List[dict],
    host: str = DEFAULT_DISPATCH_HOST,
    timeout_seconds: float = DEFAULT_DISPATCH_TIMEOUT_SECONDS,
    count: Optional[int] = None,
) -> List[dict]:
    if not assignments:
        return []

    if not SWARM_COMMAND_SCRIPT.exists():
        return [
            _dispatch_failure_row(
                item.get("drone_id"),
                _coerce_sysid(item.get("sysid")),
                f"Dispatch script not found: {SWARM_COMMAND_SCRIPT}",
            )
            for item in assignments
        ]

    timeout_seconds = max(1.0, float(timeout_seconds))
    inferred_count = max((_coerce_sysid(item.get("sysid")) or 0 for item in assignments), default=0)
    selected_count = count if count is not None and count > 0 else max(inferred_count, len(assignments))
    command = [
        sys.executable,
        str(SWARM_COMMAND_SCRIPT),
        "dispatch-targets",
        "--host",
        host,
        "--count",
        str(selected_count),
        "--assignments-json",
        json.dumps(assignments),
    ]

    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        if process and process.returncode is None:
            process.kill()
            await process.communicate()
        return [
            _dispatch_failure_row(
                item.get("drone_id"),
                _coerce_sysid(item.get("sysid")),
                f"Dispatch timeout after {timeout_seconds:.1f}s",
            )
            for item in assignments
        ]
    except Exception as exc:
        return [
            _dispatch_failure_row(
                item.get("drone_id"),
                _coerce_sysid(item.get("sysid")),
                f"Dispatch execution error: {exc}",
            )
            for item in assignments
        ]

    stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
    parsed_results = _extract_result_payload(stdout_text)

    if process.returncode != 0:
        reason = f"Dispatch script exited with code {process.returncode}"
        if stderr_text:
            reason = f"{reason}: {stderr_text}"
        if parsed_results is None:
            return [
                _dispatch_failure_row(
                    item.get("drone_id"),
                    _coerce_sysid(item.get("sysid")),
                    reason,
                )
                for item in assignments
            ]
        normalized = _normalize_script_results(parsed_results, assignments)
        for row in normalized:
            if not row["success"] and not row["message"]:
                row["message"] = reason
        return normalized

    if parsed_results is None:
        reason = "Dispatch script did not return JSON results"
        if stderr_text:
            reason = f"{reason}: {stderr_text}"
        return [
            _dispatch_failure_row(
                item.get("drone_id"),
                _coerce_sysid(item.get("sysid")),
                reason,
            )
            for item in assignments
        ]

    return _normalize_script_results(parsed_results, assignments)

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
    Background mission loop.

    When live SITL telemetry is available, drone positions are updated from
    MAVLink. Otherwise, the loop falls back to in-memory movement so the rest
    of the mission lifecycle still works in local UI-only demos.
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
        live_drone_ids = _sync_mission_drones_with_sitl(mission)
        
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
        
        # Start of main simulation logic for this tick:
        # Compute Voronoi centroids for all unassigned drones (once per tick).
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
                    
        # End of main simulation logic for this tick.

        # 1. Drone and Target logic
        for drone in mission["drones"]:
            has_live_telemetry = str(drone.get("id")) in live_drone_ids
            target_id = drone.get("assigned_target_id")
            if target_id and "targets" in mission:
                target = find_target(target_id)
                if target:
                    if drone["id"] == target.get("finder_drone_id") and target.get("status") == "confirming":
                        # Finder holds position at the target while confirmation drone arrives.
                        if not has_live_telemetry:
                            drone["lat"] = target["lat"]
                            drone["lon"] = target["lon"]
                        drone["role"] = "finder"
                        continue

                    d_lat = target["lat"] - drone["lat"]
                    d_lon = target["lon"] - drone["lon"]
                    dist = math.hypot(d_lat, d_lon)
                    if dist > TARGET_STOP_RADIUS and not has_live_telemetry:
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
                            if not has_live_telemetry:
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
                                if not has_live_telemetry:
                                    drone["lat"] = target["lat"]
                                    drone["lon"] = target["lon"]
                else:
                    drone["assigned_target_id"] = None
                    drone["role"] = None
            else:
                if drone.get("role") not in ["finder", "confirmer"]:
                    drone["role"] = None
                centroid = centroid_map.get(drone["id"])
                if centroid is not None and not has_live_telemetry:
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
                elif not has_live_telemetry:
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
    startup_note = await _ensure_sitl_running_for_mission(mission)
    if startup_note:
        mission["sitl_startup_note"] = startup_note

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

    dispatch_assignments = _build_start_dispatch_assignments(mission)
    if not dispatch_assignments:
        dispatch_assignments = _assign_start_area_targets(mission)
    dispatch_results = []
    if dispatch_assignments:
        dispatch_results = await run_dispatch_script(
            assignments=dispatch_assignments,
            host=DEFAULT_DISPATCH_HOST,
            timeout_seconds=DEFAULT_DISPATCH_TIMEOUT_SECONDS,
        )
    mission["dispatch_results"] = dispatch_results
            
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


@app.get("/sitl/status")
def sitl_status():
    states = sorted(sitl_bridge.get_states_by_sysid().values(), key=lambda row: row["sysid"])
    return {
        "host": sitl_bridge.host,
        "base_port": sitl_bridge.base_port,
        "port_step": sitl_bridge.port_step,
        "configured_count": sitl_bridge.count,
        "connected_count": len(states),
        "drones": states,
    }


@app.post("/missions/{mission_id}/dispatch-targets")
async def dispatch_targets(mission_id: str, dispatch_data: DispatchTargetsRequest):
    if mission_id not in missions_db:
        raise HTTPException(status_code=404, detail="Mission not found")

    mission = missions_db[mission_id]
    valid_assignments, preflight_failures = _prepare_dispatch_assignments(dispatch_data, mission)

    script_results = []
    if valid_assignments:
        script_results = await run_dispatch_script(
            assignments=valid_assignments,
            host=dispatch_data.host or DEFAULT_DISPATCH_HOST,
            timeout_seconds=dispatch_data.timeout_seconds or DEFAULT_DISPATCH_TIMEOUT_SECONDS,
            count=dispatch_data.count,
        )

    dispatch_results = preflight_failures + script_results
    mission["dispatch_results"] = dispatch_results
    return {
        "mission_id": mission_id,
        "dispatch_results": dispatch_results,
    }

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
