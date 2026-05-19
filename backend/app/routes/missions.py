"""Mission lifecycle routes for create, start, dispatch, stop, and delete flows."""

import asyncio
import logging
import random
import uuid
from typing import List, Optional
import numpy as np

from fastapi import APIRouter, HTTPException

from app.dispatch import run_direct_dispatch, run_dispatch_script
from app.models import (
    ApplyProbabilityRegionRequest,
    ConfirmSearchAreaRequest,
    DispatchTargetsRequest,
    MissionCreate,
    MissionStart,
    Mission,
    PreviewProbabilityRegionRequest,
)
from app.algorithms.base import build_dense_coverage_grid
from app.probability_grid import (
    REGION_LABEL_CODES,
    build_probability_grid,
    create_operator_label_grid,
    create_searchable_mask,
    rectangle_bounds_to_grid_mask,
)
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
from app.algorithms.grid import build_search_grid
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


@router.post("/missions/{mission_id}/confirm-search-area")
def confirm_search_area(mission_id: str, request: ConfirmSearchAreaRequest):
    """Confirm mission bounds and initialize search-grid/probability-grid state."""
    if mission_id not in mission_db:
        raise HTTPException(status_code=404, detail="Mission not found")

    mission = mission_db[mission_id]
    mission.bounds = request.bounds.model_dump()
    mission.grid, mission.grid_shape = build_search_grid(
        mission.bounds,
        target_cell_size_m=100.0,
    )

    rows, cols = mission.grid_shape
    mission.operator_label_grid = create_operator_label_grid(rows, cols)
    mission.searchable_mask = create_searchable_mask(rows, cols)

    probability_grid_2d, searchable_mask = build_probability_grid(
        grid_shape=mission.grid_shape,
        operator_label_grid=mission.operator_label_grid,
        searchable_mask=mission.searchable_mask,
        smoothing_iterations=mission.probability_grid_config.get("smoothing_passes", 1),
    )

    mission.searchable_mask = searchable_mask
    mission.probability_grid = probability_grid_2d.ravel()
    mission.search_area_confirmed = True
    mission.probability_grid_confirmed = False

    return mission.to_dict()


@router.post("/missions/{mission_id}/probability-grid/preview-region")
def preview_probability_region(mission_id: str, request: PreviewProbabilityRegionRequest):
    """Preview which discrete probability-grid cells a drawn rectangle would affect."""
    if mission_id not in mission_db:
        raise HTTPException(status_code=404, detail="Mission not found")

    mission = mission_db[mission_id]
    if not mission.search_area_confirmed or mission.grid is None or mission.grid_shape is None:
        raise HTTPException(status_code=400, detail="Search area must be confirmed before previewing regions")

    mask = rectangle_bounds_to_grid_mask(
        search_grid=mission.grid,
        grid_shape=mission.grid_shape,
        rect_bounds=request.rect_bounds.model_dump(),
    )
    rows, cols = np.where(mask)
    cells = [[int(row), int(col)] for row, col in zip(rows.tolist(), cols.tolist())]
    return {
        "cells": cells,
        "count": len(cells),
    }


@router.post("/missions/{mission_id}/probability-grid/apply-region")
def apply_probability_region(mission_id: str, request: ApplyProbabilityRegionRequest):
    """Apply an operator-selected label to the cells covered by a drawn rectangle."""
    if mission_id not in mission_db:
        raise HTTPException(status_code=404, detail="Mission not found")

    mission = mission_db[mission_id]
    if not mission.search_area_confirmed or mission.grid is None or mission.grid_shape is None:
        raise HTTPException(status_code=400, detail="Search area must be confirmed before applying regions")
    if mission.operator_label_grid is None:
        raise HTTPException(status_code=400, detail="Operator label grid is not initialized")

    mask = rectangle_bounds_to_grid_mask(
        search_grid=mission.grid,
        grid_shape=mission.grid_shape,
        rect_bounds=request.rect_bounds.model_dump(),
    )
    label_code = REGION_LABEL_CODES[request.label]
    mission.operator_label_grid = np.asarray(mission.operator_label_grid, dtype=np.uint8).copy()
    mission.operator_label_grid[mask] = label_code

    probability_grid_2d, searchable_mask = build_probability_grid(
        grid_shape=tuple(mission.grid_shape),
        operator_label_grid=mission.operator_label_grid,
        searchable_mask=None,
        smoothing_iterations=mission.probability_grid_config.get("smoothing_passes", 1),
    )
    mission.searchable_mask = searchable_mask
    mission.probability_grid = probability_grid_2d.ravel()
    mission.probability_grid_confirmed = False

    rows, cols = np.where(mask)
    cells = [[int(row), int(col)] for row, col in zip(rows.tolist(), cols.tolist())]
    return {
        "operator_label_grid": mission.operator_label_grid.tolist(),
        "probability_grid": mission.probability_grid.tolist(),
        "cells": cells,
        "count": len(cells),
    }


@router.post("/missions/{mission_id}/probability-grid/confirm")
def confirm_probability_grid(mission_id: str):
    """Finalize the current operator labels into the mission's probability grid."""
    if mission_id not in mission_db:
        raise HTTPException(status_code=404, detail="Mission not found")

    mission = mission_db[mission_id]
    if not mission.search_area_confirmed or mission.grid_shape is None:
        raise HTTPException(status_code=400, detail="Search area must be confirmed before confirming probability grid")
    if mission.operator_label_grid is None:
        raise HTTPException(status_code=400, detail="Operator label grid is not initialized")

    probability_grid_2d, searchable_mask = build_probability_grid(
        grid_shape=mission.grid_shape,
        operator_label_grid=mission.operator_label_grid,
        searchable_mask=mission.searchable_mask,
        smoothing_iterations=mission.probability_grid_config.get("smoothing_passes", 1),
    )
    if not np.any(searchable_mask):
        raise HTTPException(status_code=400, detail="Probability grid confirmation failed: no searchable cells remain")

    mission.searchable_mask = searchable_mask
    mission.probability_grid = probability_grid_2d.ravel()
    mission.probability_grid_confirmed = True
    return mission.to_dict()


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

    missing_setup_steps: list[str] = []
    if not mission.search_area_confirmed:
        missing_setup_steps.append("search area must be confirmed")
    if mission.grid is None:
        missing_setup_steps.append("search grid is not initialized")
    if mission.probability_grid is None:
        missing_setup_steps.append("probability grid is not initialized")
    if not mission.probability_grid_confirmed:
        missing_setup_steps.append("probability grid must be confirmed")
    if missing_setup_steps:
        raise HTTPException(
            status_code=400,
            detail=f"Mission setup incomplete: {', '.join(missing_setup_steps)}",
        )

    mission.status = "searching"
    mission.elapsed_seconds = 0

    if start_data:
        if start_data.drones is not None:
            mission.drones = [d.model_dump() for d in start_data.drones]
        if start_data.algorithm is not None:
            mission.algorithm = start_data.algorithm
        if start_data.hikers is not None:
            mission.hikers = [h.model_dump() for h in start_data.hikers]

    bounds = mission.bounds
    startup_note = await _ensure_sitl_running_for_mission(mission)

    targets = []
    if mission.hikers:
        for hiker in mission.hikers:
            targets.append(
                {
                    "id": hiker["id"],
                    "lat": hiker["lat"],
                    "lon": hiker["lon"],
                    "status": "found" if hiker.get("found") else "wandering",
                    "assigned_drone_id": None,
                    "movement": hiker.get("movement", "moving"),
                }
            )
    else:
        for _ in range(random.randint(2, 3)):
            targets.append(
                {
                    "id": f"tgt-{uuid.uuid4().hex[:8]}",
                    "lat": random.uniform(bounds["min_lat"], bounds["max_lat"]),
                    "lon": random.uniform(bounds["min_lon"], bounds["max_lon"]),
                    "status": "wandering",
                    "assigned_drone_id": None,
                    "movement": "moving",
                }
            )
    mission.targets = targets
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


@router.post("/missions/{mission_id}/stop")
async def stop_mission(mission_id: str):
    """Stop a mission and broadcast that it is no longer running."""
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
        raise HTTPException(status_code=400, detail="Mission must be 'search_complete' to initiate recall")

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
