"""Mission-state helpers shared by routes, dispatch, and simulation."""

import asyncio
import json
import math
import os
from typing import Dict, List, Optional, Tuple

import numpy as np

from app.settings import (
    AUTO_START_SITL_ON_MISSION_START,
    DEFAULT_DISPATCH_ALT,
    DEFAULT_SITL_BASE_PORT,
    DEFAULT_SITL_HOME_ALT,
    DEFAULT_SITL_HOST,
    DEFAULT_SITL_PORT_STEP,
    LAUNCH_SITL_SCRIPT,
)
from app.voronoi import build_search_grid
from app.models import MissionCreate


mission_db: Dict[str, dict] = {}

class Mission:
    id: str
    name: str
    status: "idle" or "searching" or "search_complete" or "recalling" or "paused" or "mission_complete"
    progress: float
    elapsed_seconds: int
    algorithm: str
    bounds: dict[str, float]
    drones: list[dict]
    hikers: list[dict]
    targets: list[dict]
    algorithm: str

    def __init__(self, mission_id: str, mission_data: MissionCreate):
        self.id = mission_id
        self.name = mission_data.name
        self.status = "idle"
        self.progress = 0.0
        self.elapsed_seconds = 0
        self.algorithm = getattr(mission_data, "algorithm", "voronoi")
        self.bounds = mission_data.bounds.model_dump()
        self.drones = [d.model_dump() for d in mission_data.drones]
        self.hikers = [m.model_dump() for m in mission_data.hikers] if mission_data.hikers else []
        self.targets = []
        self.algorithm = getattr(mission_data, "algorithm", "voronoi")


def _coerce_sysid(value: object) -> Optional[int]:
    """Convert a candidate system id into a positive integer or None."""
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _dispatch_failure_row(drone_id: Optional[str], sysid: Optional[int], message: str) -> dict:
    """Build a normalized dispatch failure payload."""
    return {
        "drone_id": drone_id,
        "sysid": sysid,
        "success": False,
        "message": message,
    }


def _extract_result_payload(stdout_text: str) -> Optional[List[dict]]:
    """Extract the last JSON list payload from a helper script's stdout text."""
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
    """Match raw script rows back to requested assignments and normalize the shape."""
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


def _mission_drone_to_sysid_map(mission: Mission) -> Dict[str, int]:
    """Infer or persist a mission's drone-id to MAVLink sysid mapping."""
    mapping: Dict[str, int] = {}
    for index, drone in enumerate(getattr(mission, "drones", []), start=1):
        drone_id = drone.get("id")
        if drone_id is None:
            continue
        sysid = _coerce_sysid(drone.get("sysid")) or index
        drone["sysid"] = sysid
        mapping[str(drone_id)] = sysid
    return mapping


def _sync_mission_drones_with_sitl(mission: Mission) -> set[str]:
    """Overlay live SITL telemetry onto mission drones and return live drone ids."""
    from app.sitl import sitl_bridge

    live_states = sitl_bridge.get_states_by_sysid()
    live_drone_ids = set()

    for index, drone in enumerate(getattr(mission, "drones", []), start=1):
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


def _build_start_dispatch_assignments(mission: Mission) -> List[dict]:
    """Create startup dispatch commands from any pre-assigned drone target coordinates."""
    assignments = []
    for index, drone in enumerate(getattr(mission, "drones", []), start=1):
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
                "alt": DEFAULT_DISPATCH_ALT,
            }
        )

    return assignments


def _mission_bounds_center(bounds: dict) -> Tuple[float, float]:
    """Return the geographic midpoint of mission bounds."""
    return (
        (float(bounds["min_lat"]) + float(bounds["max_lat"])) / 2.0,
        (float(bounds["min_lon"]) + float(bounds["max_lon"])) / 2.0,
    )


def _generate_coverage_points(bounds: dict, drone_count: int) -> List[Tuple[float, float]]:
    """Generate evenly distributed coverage points inside mission bounds."""
    if drone_count <= 0:
        return []

    grid_side = max(2, math.ceil(math.sqrt(drone_count)))
    grid_points = build_search_grid(bounds, n=grid_side)
    if len(grid_points) <= drone_count:
        return [(float(lat), float(lon)) for lat, lon in grid_points]

    selected_indexes = np.linspace(0, len(grid_points) - 1, num=drone_count, dtype=int)
    return [(float(grid_points[idx][0]), float(grid_points[idx][1])) for idx in selected_indexes]


def _assign_start_area_targets(mission: Mission) -> List[dict]:
    """Assign each mission drone an initial coverage point and matching dispatch row."""
    drones = getattr(mission, "drones", [])
    points = _generate_coverage_points(mission.bounds, len(drones))
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
                "alt": DEFAULT_DISPATCH_ALT,
            }
        )

    return assignments


async def _ensure_sitl_running_for_mission(mission: Mission) -> Optional[str]:
    """Optionally auto-start SITL near the mission center when no bridge data exists."""
    from app.sitl import sitl_bridge

    if not AUTO_START_SITL_ON_MISSION_START:
        return None
    if sitl_bridge.get_states_by_sysid():
        return None
    if not LAUNCH_SITL_SCRIPT.exists():
        return f"SITL launch script not found: {LAUNCH_SITL_SCRIPT}"

    bounds = mission.bounds
    center_lat, center_lon = _mission_bounds_center(bounds)
    home = f"{center_lat:.7f},{center_lon:.7f},{DEFAULT_SITL_HOME_ALT:.1f},0"
    env = os.environ.copy()
    env["SITL_HOME"] = home
    env["SITL_OUT_HOST"] = DEFAULT_SITL_HOST
    env["SITL_BASE_PORT"] = str(DEFAULT_SITL_BASE_PORT)
    env["SITL_PORT_STEP"] = str(DEFAULT_SITL_PORT_STEP)

    try:
        await asyncio.create_subprocess_exec(
            str(LAUNCH_SITL_SCRIPT),
            str(max(len(getattr(mission, "drones", [])), 1)),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
        )
    except Exception as exc:
        return f"Failed to auto-start SITL: {exc}"

    return f"Starting SITL near mission center {center_lat:.5f}, {center_lon:.5f}"


def _prepare_dispatch_assignments(request, mission: Mission) -> Tuple[List[dict], List[dict]]:
    """Resolve request assignments into valid dispatch rows plus preflight failures."""
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
