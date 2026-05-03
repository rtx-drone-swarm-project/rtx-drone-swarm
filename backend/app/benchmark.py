"""Headless benchmark runner for comparing search algorithms on paired scenarios."""

from __future__ import annotations

import asyncio
import math
import random
import uuid
from typing import Any

import numpy as np

from app.algorithms import get_algorithm
from app.algorithms.base import DETECTION_RADIUS, build_dense_coverage_grid, build_search_grid
from app.benchmark_db import aggregate_trials, finish_run, insert_trial
from app.models import BenchmarkRequest
from app.simulation import (
    _finalize_mission_progress,
    _update_coverage,
    _update_drones_for_tick,
    _update_targets_for_tick,
)
from app.ws import manager


# Algorithms with internal randomness get deterministic, distinct local RNG
# streams for each paired scenario. Unknown future algorithms still get a stable
# default offset, but adding a named offset makes report/debug output clearer.
ALGORITHM_SEED_OFFSETS = {
    "voronoi": 101,
    "voronoi_aco": 151,
    "apf": 202,
    "sweep": 303,
}


def make_run_id() -> str:
    return f"bench-{uuid.uuid4().hex[:12]}"


def total_trials(request: BenchmarkRequest) -> int:
    return len(request.algorithms) * request.iterations


async def run_benchmark_job(run_id: str, request: BenchmarkRequest) -> dict[str, Any]:
    """Run all requested algorithms on shared per-iteration scenarios."""
    trials: list[dict[str, Any]] = []
    completed = 0
    total = total_trials(request)
    base_seed = request.seed if request.seed is not None else random.SystemRandom().randint(1, 2_147_483_647)

    try:
        for iteration in range(request.iterations):
            scenario_seed = base_seed + iteration
            scenario = _build_scenario(
                request.bounds.model_dump(),
                request.drone_count,
                request.target_count,
                scenario_seed,
            )
            for algorithm in request.algorithms:
                trial = await run_headless_trial(
                    run_id=run_id,
                    algorithm=algorithm,
                    iteration=iteration + 1,
                    scenario_seed=scenario_seed,
                    bounds=request.bounds.model_dump(),
                    drone_starts=scenario["drones"],
                    target_starts=scenario["targets"],
                    timeout_seconds=request.timeout_seconds,
                )
                await asyncio.to_thread(insert_trial, trial)
                trials.append(trial)
                completed += 1
                await manager.broadcast(
                    {
                        "type": "benchmark_progress",
                        "run_id": run_id,
                        "completed": completed,
                        "total": total,
                        "status": "running",
                    }
                )

        summary = aggregate_trials(trials)
        await asyncio.to_thread(finish_run, run_id, "complete", summary=summary)
        await manager.broadcast(
            {
                "type": "benchmark_progress",
                "run_id": run_id,
                "completed": completed,
                "total": total,
                "status": "complete",
            }
        )
        return summary
    except asyncio.CancelledError:
        summary = aggregate_trials(trials)
        await asyncio.to_thread(
            finish_run, run_id, "cancelled", summary=summary, error="Stopped by user"
        )
        await manager.broadcast(
            {
                "type": "benchmark_progress",
                "run_id": run_id,
                "completed": completed,
                "total": total,
                "status": "cancelled",
            }
        )
        return summary
    except Exception as exc:
        await asyncio.to_thread(finish_run, run_id, "failed", summary=aggregate_trials(trials), error=str(exc))
        await manager.broadcast(
            {
                "type": "benchmark_progress",
                "run_id": run_id,
                "completed": completed,
                "total": total,
                "status": "failed",
                "error": str(exc),
            }
        )
        raise


async def run_headless_trial(
    *,
    run_id: str,
    algorithm: str,
    iteration: int,
    scenario_seed: int,
    bounds: dict[str, float],
    drone_starts: list[dict[str, Any]],
    target_starts: list[dict[str, Any]],
    timeout_seconds: int,
) -> dict[str, Any]:
    """Run one algorithm/scenario pair without SITL commands or WS tick broadcasts."""
    algorithm_seed = scenario_seed + ALGORITHM_SEED_OFFSETS.get(algorithm, 909)
    dense_grid = build_dense_coverage_grid(bounds)
    mission = {
        "id": f"{run_id}-{algorithm}-{iteration}",
        "name": "Headless Benchmark Trial",
        "status": "running",
        "progress": 0.0,
        "elapsed_seconds": 0,
        "algorithm": algorithm,
        "bounds": bounds,
        "grid": build_search_grid(bounds, n=15).tolist(),
        "drones": [dict[str, Any](drone) for drone in drone_starts],
        "targets": [dict[str, Any](target) for target in target_starts],
        "_dense_coverage_grid": dense_grid,
        "_dense_grid_size": len(dense_grid),
        "_found_target_ids": [],
        "_suppress_broadcasts": True,
        "_static_targets": True,
        "_move_assigned_sim_drones": True,
        "_rng": random.Random(algorithm_seed),
        "_np_rng": np.random.default_rng(algorithm_seed),
    }
    strategy = get_algorithm(algorithm)
    strategy.initialize(mission)

    distance_by_drone = {str(drone["id"]): 0.0 for drone in mission["drones"]}
    visit_drones_by_cell: dict[int, set[str]] = {}
    threshold_times: dict[int, int | None] = {50: None, 80: None, 95: None}

    for _ in range(timeout_seconds):
        if mission["status"] != "running":
            break

        mission["elapsed_seconds"] += 1
        free_drones = [
            drone
            for drone in mission["drones"]
            if not drone.get("assigned_target_id") and drone.get("role") not in ["finder", "confirmer"]
        ]

        waypoints = await asyncio.to_thread(strategy.get_target_waypoints, mission, free_drones)

        previous_positions = {
            str(drone["id"]): (float(drone["lat"]), float(drone["lon"]))
            for drone in mission["drones"]
        }
        await _update_drones_for_tick(mission, set(), waypoints, bounds)
        _update_targets_for_tick(mission, bounds)
        _update_coverage(mission)
        _track_redundant_coverage(mission, dense_grid, visit_drones_by_cell)
        _track_distance(mission, previous_positions, distance_by_drone)
        _track_coverage_thresholds(mission, threshold_times)

        all_targets_found = await _finalize_mission_progress(mission)
        if all_targets_found:
            break

    elapsed = int(mission.get("elapsed_seconds", 0))
    grid_size = int(mission.get("_dense_grid_size") or len(dense_grid))
    covered_count = int(mission.get("_dense_covered_count", 0))
    coverage_pct = round(100.0 * covered_count / grid_size, 3) if grid_size else 0.0
    found_times = [
        float(target["found_at"])
        for target in mission.get("targets", [])
        if target.get("status") == "found" and "found_at" in target
    ]
    targets_found = len(found_times)
    total_distance = round(sum(distance_by_drone.values()), 3)
    drone_count = len(mission["drones"])
    redundant_cells = sum(1 for drone_ids in visit_drones_by_cell.values() if len(drone_ids) > 1)
    trial_status = "timeout" if mission.get("status") == "running" else mission.get("status", "unknown")

    return {
        "run_id": run_id,
        "algorithm": algorithm,
        "iteration": iteration,
        "scenario_seed": scenario_seed,
        "bounds_json": bounds,
        "drone_count": drone_count,
        "target_count": len(mission.get("targets", [])),
        "timeout_seconds": timeout_seconds,
        "elapsed_seconds": elapsed,
        "first_find_seconds": min(found_times) if found_times else None,
        "avg_find_seconds": round(sum(found_times) / len(found_times), 3) if found_times else None,
        "last_find_seconds": max(found_times) if found_times else None,
        "completion_elapsed_seconds": mission.get("completion_elapsed_seconds"),
        "coverage_pct": coverage_pct,
        "miss_pct": round(max(0.0, 100.0 - coverage_pct), 3),
        "redundant_coverage_pct": round(100.0 * redundant_cells / grid_size, 3) if grid_size else 0.0,
        "coverage_per_drone_second": round(coverage_pct / max(drone_count * elapsed, 1), 6),
        "hiker_find_rate": round(targets_found / max(elapsed, 1), 6),
        "total_distance_traveled_m": total_distance,
        "avg_distance_per_drone_m": round(total_distance / max(drone_count, 1), 3),
        "max_distance_single_drone_m": round(max(distance_by_drone.values(), default=0.0), 3),
        "time_to_50_coverage": threshold_times[50],
        "time_to_80_coverage": threshold_times[80],
        "time_to_95_coverage": threshold_times[95],
        "targets_total": len(mission.get("targets", [])),
        "targets_found": targets_found,
        "status": trial_status,
    }


def _build_scenario(
    bounds: dict[str, float],
    drone_count: int,
    target_count: int,
    scenario_seed: int,
) -> dict[str, list[dict[str, Any]]]:
    rng = random.Random(scenario_seed)
    return {
        "drones": [
            {
                "id": f"d{i + 1}",
                "lat": rng.uniform(bounds["min_lat"], bounds["max_lat"]),
                "lon": rng.uniform(bounds["min_lon"], bounds["max_lon"]),
                "status": "idle",
            }
            for i in range(drone_count)
        ],
        "targets": [
            {
                "id": f"t{i + 1}",
                "lat": rng.uniform(bounds["min_lat"], bounds["max_lat"]),
                "lon": rng.uniform(bounds["min_lon"], bounds["max_lon"]),
                "status": "wandering",
                "assigned_drone_id": None,
            }
            for i in range(target_count)
        ],
    }


def _track_distance(
    mission: dict,
    previous_positions: dict[str, tuple[float, float]],
    distance_by_drone: dict[str, float],
) -> None:
    for drone in mission["drones"]:
        drone_id = str(drone["id"])
        previous = previous_positions.get(drone_id)
        if previous is None:
            continue
        distance_by_drone[drone_id] += _degrees_to_meters(
            previous[0],
            previous[1],
            float(drone["lat"]),
            float(drone["lon"]),
        )


def _track_redundant_coverage(
    mission: dict,
    dense_grid: np.ndarray,
    visit_drones_by_cell: dict[int, set[str]],
) -> None:
    for drone in mission.get("drones", []):
        dlat = float(drone.get("lat", 0.0))
        dlon = float(drone.get("lon", 0.0))
        lat_mask = np.abs(dense_grid[:, 0] - dlat) <= DETECTION_RADIUS
        lon_mask = np.abs(dense_grid[:, 1] - dlon) <= DETECTION_RADIUS
        candidates = np.where(lat_mask & lon_mask)[0]
        if len(candidates) == 0:
            continue
        sub = dense_grid[candidates]
        within = candidates[
            np.hypot(sub[:, 0] - dlat, sub[:, 1] - dlon) <= DETECTION_RADIUS
        ]
        for cell_idx in within:
            visit_drones_by_cell.setdefault(int(cell_idx), set()).add(str(drone["id"]))


def _track_coverage_thresholds(mission: dict, threshold_times: dict[int, int | None]) -> None:
    grid_size = int(mission.get("_dense_grid_size") or 0)
    if not grid_size:
        return
    coverage_pct = 100.0 * int(mission.get("_dense_covered_count", 0)) / grid_size
    for threshold in threshold_times:
        if threshold_times[threshold] is None and coverage_pct >= threshold:
            threshold_times[threshold] = int(mission.get("elapsed_seconds", 0))


def _degrees_to_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    mid_lat = math.radians((lat1 + lat2) / 2.0)
    dlat_m = (lat2 - lat1) * 110_574.0
    dlon_m = (lon2 - lon1) * 111_320.0 * math.cos(mid_lat)
    return math.hypot(dlat_m, dlon_m)
