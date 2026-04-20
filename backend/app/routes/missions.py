"""Mission lifecycle routes for create, start, dispatch, stop, and delete flows."""

import asyncio
import logging
import random
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException

from app.dispatch import run_direct_dispatch, run_dispatch_script
from app.models import DispatchTargetsRequest, MissionCreate, MissionStart
from app.missions import (
    _assign_start_area_targets,
    _build_start_dispatch_assignments,
    _coerce_sysid,
    _dispatch_failure_row,
    _ensure_sitl_running_for_mission,
    _prepare_dispatch_assignments,
    missions_db,
)
from app.settings import DEFAULT_DISPATCH_HOST, DEFAULT_DISPATCH_TIMEOUT_SECONDS
from app.simulation import simulation_loop
#from app.voronoi import build_search_grid <---------------------------------------------------------------------------------------------
from app.algorithms.base import build_search_grid
from app.ws import manager


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/missions")
def create_mission(mission_data: MissionCreate):
    """Create an in-memory mission record from validated request data."""
    mission_id = str(uuid.uuid4())
    mission = {
        "id": mission_id,
        "name": mission_data.name,
        "status": "idle",
        "progress": 0.0,
        "elapsed_seconds": 0,
        "algorithm": getattr(mission_data, "algorithm", "voronoi"),
        "bounds": mission_data.bounds.model_dump(),
        "drones": [d.model_dump() for d in mission_data.drones],
        "hikers": [m.model_dump() for m in mission_data.hikers] if mission_data.hikers else [],
    }
    missions_db[mission_id] = mission
    return mission


@router.get("/missions/{mission_id}")
def get_mission(mission_id: str):
    """Return one stored mission or raise ``404`` if the id is unknown."""
    if mission_id not in missions_db:
        raise HTTPException(status_code=404, detail="Mission not found")
    return missions_db[mission_id]


async def _background_dispatch(mission: dict, mission_id: str, assignments: List[dict]) -> None:
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
    mission["dispatch_results"] = results
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
            "status": mission.get("status", "running"),
            "phase": mission.get("phase"),
            "dispatch_results": results,
        }
    )


@router.post("/missions/{mission_id}/start")
async def start_mission(mission_id: str, start_data: Optional[MissionStart] = None):
    """Start a mission, seed targets and coverage points, then launch simulation tasks."""
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

    bounds = mission["bounds"]
    startup_note = await _ensure_sitl_running_for_mission(mission)
    if startup_note:
        mission["sitl_startup_note"] = startup_note

    mission["grid"] = build_search_grid(bounds, n=15).tolist()

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
    mission["targets"] = targets

    dispatch_assignments = _build_start_dispatch_assignments(mission)
    if not dispatch_assignments:
        dispatch_assignments = _assign_start_area_targets(mission)

    logger.info(
        "start_mission %s: %d dispatch assignments, %d drones",
        mission_id,
        len(dispatch_assignments),
        len(mission.get("drones", [])),
    )

    await manager.broadcast(
        {
            "type": "mission_status",
            "mission_id": mission_id,
            "status": "running",
            "phase": mission.get("phase"),
            "progress": mission["progress"],
            "targets": targets,
        }
    )

    asyncio.create_task(simulation_loop(mission_id))

    if dispatch_assignments:
        asyncio.create_task(_background_dispatch(mission, mission_id, dispatch_assignments))

    return mission


@router.post("/missions/{mission_id}/dispatch-targets")
async def dispatch_targets(mission_id: str, dispatch_data: DispatchTargetsRequest):
    """Dispatch one or more mission drones to explicit coordinates via the helper script."""
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


@router.post("/missions/{mission_id}/stop")
async def stop_mission(mission_id: str):
    """Stop a mission and broadcast that it is no longer running."""
    if mission_id not in missions_db:
        raise HTTPException(status_code=404, detail="Mission not found")

    mission = missions_db[mission_id]
    if mission["status"] not in ["running", "idle"]:
        raise HTTPException(status_code=400, detail="Mission is already stopped or complete")

    mission["status"] = "stopped"
    mission["progress"] = 0.0

    await manager.broadcast(
        {
            "type": "mission_status",
            "mission_id": mission_id,
            "status": "stopped",
            "phase": mission.get("phase"),
            "progress": mission["progress"],
        }
    )
    await manager.broadcast({"type": "telemetry", "drones": []})

    return mission


@router.delete("/missions/{mission_id}")
async def delete_mission(mission_id: str):
    """Delete a mission record and broadcast that it is gone."""
    if mission_id not in missions_db:
        raise HTTPException(status_code=404, detail="Mission not found")
    mission = missions_db.pop(mission_id)
    if mission.get("status") == "running":
        mission["status"] = "stopped"
    await manager.broadcast(
        {
            "type": "mission_status",
            "mission_id": mission_id,
            "status": "deleted",
            "phase": mission.get("phase"),
            "progress": 0.0,
        }
    )
    return {"ok": True, "mission_id": mission_id}

@router.post("/missions/{mission_id}/recall")
async def recall_mission(mission_id: str):
    """Recall a mission and broadcast that recall has been initiated."""
    if mission_id not in missions_db:
        raise HTTPException(status_code=404, detail="Mission not found")

    mission = missions_db[mission_id]
    # Prevent invalid transitions
    if mission.get("phase") != "post_search":
        raise HTTPException(status_code=400, detail="Mission is not running")

    # If already recalling, do nothing
    if mission.get("phase") == "recall":
        return {"message": "Recall already in progress"}

    # Transition to recall phase
    mission["phase"] = "recall"
    mission["recall_sent"] = False

    await manager.broadcast(
        {
            "type": "mission_status",
            "mission_id": mission_id,
            "status": "recall",
            "phase": mission.get("phase"),
            "progress": mission["progress"],
        }
    )

    return mission
