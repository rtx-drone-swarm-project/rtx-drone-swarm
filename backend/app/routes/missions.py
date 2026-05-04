"""Mission lifecycle routes for create, start, dispatch, pause, and delete flows."""

import asyncio
import logging
import random
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException

from app.dispatch import run_direct_dispatch, run_dispatch_script
from app.models import DispatchTargetsRequest, MissionCreate, MissionStart, Mission
from app.algorithms.base import build_dense_coverage_grid
from app.missions import (
    _assign_start_area_targets,
    _build_start_dispatch_assignments,
    _coerce_sysid,
    _dispatch_failure_row,
    _ensure_sitl_running_for_mission,
    _prepare_dispatch_assignments,
    _sync_mission_drones_with_sitl,
    mission_db,
)
from app.settings import DEFAULT_DISPATCH_HOST, DEFAULT_DISPATCH_TIMEOUT_SECONDS
from app.simulation import simulation_loop
from app.algorithms.base import build_search_grid
from app.ws import manager


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/missions")
def create_mission(mission_data: MissionCreate):
    """Create an in-memory mission record from validated request data."""
    mission_id = str(uuid.uuid4())
    mission = Mission(mission_id, mission_data)
    mission_db[mission_id] = mission
    return mission.to_dict()


@router.get("/missions/{mission_id}")
def get_mission(mission_id: str):
    """Return one stored mission or raise ``404`` if the id is unknown."""
    if mission_id not in mission_db:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission_db[mission_id].to_dict()


async def _background_dispatch(mission: Mission, mission_id: str, assignments: List[dict]) -> None:
    """Run startup dispatch in the background and broadcast normalized results."""
    logger.info("_background_dispatch: dispatching %d drones for mission %s", len(assignments), mission_id)
    try:
        results = await run_direct_dispatch(assignments)
    except Exception as exc:
        logger.exception("Background dispatch failed for mission %s", mission_id)
        results = [
            _dispatch_failure_row(
                assignment.get("drone_id"),
                _coerce_sysid(assignment.get("sysid")),
                f"Background dispatch error: {exc}",
            )
            for assignment in assignments
        ]
        
    success_count = sum(1 for row in results if row.get("success"))
    logger.info(
        "_background_dispatch mission %s: %d/%d drones dispatched successfully",
        mission_id,
        success_count,
        len(results),
    )
    for row in results:
        if not row.get("success"):
            logger.warning("  dispatch fail sysid=%s: %s", row.get("sysid"), row.get("message"))
    await manager.broadcast(
        {
            "type": "mission_status",
            "mission_id": mission_id,
            "status": mission.status,
            "dispatch_results": results,
        }
    )


@router.post("/missions/{mission_id}/start")
async def start_mission(mission_id: str, start_data: Optional[MissionStart] = None):
    """Start a mission, seed targets and coverage points, then launch simulation tasks."""
    if mission_id not in mission_db:
        raise HTTPException(status_code=404, detail="Mission not found")

    mission = mission_db[mission_id]
    if mission.status != "idle":
        raise HTTPException(status_code=400, detail="Only 'idle' missions can be started")

    mission.status = "searching"
    mission.elapsed_seconds = 0

    if start_data:
        if start_data.drones is not None:
            mission.drones = [d.model_dump() for d in start_data.drones]
        if start_data.algorithm is not None:
            mission.algorithm = start_data.algorithm

    bounds = mission.bounds
    startup_note = await _ensure_sitl_running_for_mission(mission)

    targets = []
    for _ in range(random.randint(2, 3)):
        targets.append(
            {
                "id": f"tgt-{uuid.uuid4().hex[:8]}",
                "lat": random.uniform(bounds["min_lat"], bounds["max_lat"]),
                "lon": random.uniform(bounds["min_lon"], bounds["max_lon"]),
                "status": "wandering",
                "assigned_drone_id": None,
            }
        )
    mission.targets = targets
    mission.grid = build_search_grid(bounds, n=15)
    mission._dense_coverage_grid = build_dense_coverage_grid(bounds)
    mission._dense_grid_size = len(mission._dense_coverage_grid)

    dispatch_assignments = _build_start_dispatch_assignments(mission)
    if not dispatch_assignments:
        dispatch_assignments = _assign_start_area_targets(mission)

    logger.info(
        "start_mission %s: %d dispatch assignments, %d drones",
        mission_id,
        len(dispatch_assignments),
        len(getattr(mission, "drones", [])),
    )

    await manager.broadcast(
        {
            "type": "mission_status",
            "mission_id": mission_id,
            "status": mission.status,
            "progress": mission.progress,
            "targets": targets,
        }
    )

    asyncio.create_task(simulation_loop(mission_id))

    if dispatch_assignments:
        asyncio.create_task(_background_dispatch(mission, mission_id, dispatch_assignments))

    return mission.to_dict()


@router.post("/missions/{mission_id}/dispatch-targets")
async def dispatch_targets(mission_id: str, dispatch_data: DispatchTargetsRequest):
    """Dispatch one or more mission drones to explicit coordinates via the helper script."""
    if mission_id not in mission_db:
        raise HTTPException(status_code=404, detail="Mission not found")

    mission = mission_db[mission_id]
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
    return {
        "mission_id": mission_id,
        "dispatch_results": dispatch_results,
    }


@router.post("/missions/{mission_id}/pause")
async def pause_mission(mission_id: str):
    """Pause a mission and broadcast that it is no longer running."""
    if mission_id not in mission_db:
        raise HTTPException(status_code=404, detail="Mission not found")

    mission = mission_db[mission_id]
    if mission.status in ["idle", "search_complete", "paused", "mission_complete"]:
        raise HTTPException(status_code=400, detail="Drones are not in motion")

    _sync_mission_drones_with_sitl(mission)
    mission.status = "paused"

    await manager.broadcast(
        {
            "type": "mission_status",
            "mission_id": mission_id,
            "status": mission.status,
            "progress": mission.progress,
        }
    )
    await manager.broadcast({"type": "telemetry", "drones": mission.drones})

    return mission.to_dict()


@router.get("/missions/{mission_id}/metrics")
def get_mission_metrics(mission_id: str):
    """Return algorithm performance metrics for a completed or in-progress mission."""
    if mission_id not in mission_db:
        raise HTTPException(status_code=404, detail="Mission not found")
    mission = mission_db[mission_id]
    targets = mission.targets
    found_targets = [t for t in targets if t.get("status") == "found"]
    found_times = [t["found_at"] for t in found_targets if "found_at" in t]

    # Use dense coverage if available (accurate); fall back to sparse for old missions.
    sparse_grid_size = len(mission.grid) if mission.grid is not None else 0
    grid_size = getattr(mission, "_dense_grid_size", 0) or sparse_grid_size
    covered_count = mission._dense_covered_count
    coverage_pct = round(100.0 * covered_count / grid_size, 1) if grid_size else 0.0
    elapsed = mission.elapsed_seconds
    coverage_rate = round(coverage_pct / elapsed, 3) if elapsed > 0 else 0.0

    return {
        "algorithm": mission.algorithm,
        "status": mission.status,
        "elapsed_seconds": elapsed,
        "completion_elapsed_seconds": mission.completion_elapsed_seconds,
        "targets_total": len(targets),
        "targets_found": len(found_targets),
        "found_at_seconds": found_times,
        "first_find_seconds": min(found_times) if found_times else None,
        "last_find_seconds": max(found_times) if found_times else None,
        "avg_find_seconds": round(sum(found_times) / len(found_times), 1) if found_times else None,
        "coverage_pct": coverage_pct,
        "coverage_rate_per_sec": coverage_rate,
    }


@router.delete("/missions/{mission_id}")
async def delete_mission(mission_id: str):
    """Delete a mission record and broadcast that it is gone."""
    if mission_id not in mission_db:
        raise HTTPException(status_code=404, detail="Mission not found")
    mission = mission_db.pop(mission_id)
    mission.status = "idle"

    await manager.broadcast(
        {
            "type": "mission_status",
            "mission_id": mission_id,
            "status": mission.status,
            "progress": 0.0,
        }
    )

    return {"ok": True, "mission_id": mission_id}

@router.post("/missions/{mission_id}/recall")
async def recall_mission(mission_id: str):
    """Recall a mission and broadcast that recall has been initiated."""
    if mission_id not in mission_db:
        raise HTTPException(status_code=404, detail="Mission not found")

    mission = mission_db[mission_id]
    # Prevent invalid transitions
    if mission.status != "search_complete":
        raise HTTPException(status_code=400, detail="Mission is not running")

    # If already recalling, do nothing
    if mission.status == "recalling":
        return {"message": "Recall already in progress"}

    mission.status = "recalling"

    await manager.broadcast(
        {
            "type": "mission_status",
            "mission_id": mission_id,
            "status": mission.status,
            "progress": mission.progress,
        }
    )

    return mission.to_dict()
