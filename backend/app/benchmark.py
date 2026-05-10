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

SCENARIO_PROFILES: dict[str, dict[str, Any]] = {
    "uniform_random": {
        "label": "Uniform Random",
        "description": "Stationary baseline with independent random drone and hiker placement.",
        "targets_move": False,
    },
    "clustered_drones": {
        "label": "Clustered Drones",
        "description": "Stationary hikers with drones staged near one launch area.",
        "targets_move": False,
    },
    "clustered_targets": {
        "label": "Clustered Hikers",
        "description": "Stationary hikers concentrated in one area.",
        "targets_move": False,
    },
    "edge_targets": {
        "label": "Edge Hikers",
        "description": "Stationary hikers biased near boundaries and corners.",
        "targets_move": False,
    },
    "split_clusters": {
        "label": "Split Clusters",
        "description": "Stationary hikers divided between two separated clusters.",
        "targets_move": False,
    },
    "corridor_route": {
        "label": "Moving Corridor Route",
        "description": "Moving hikers distributed along a diagonal trail with drones staged near one end.",
        "targets_move": True,
    },
    "wandering_hikers": {
        "label": "Wandering Hikers",
        "description": "Moving hikers with bounded deterministic random drift.",
        "targets_move": True,
    },
    "moving_edge_escape": {
        "label": "Moving Edge Escape",
        "description": "Moving hikers start near boundaries and drift along edges.",
        "targets_move": True,
    },
    "diverging_group": {
        "label": "Diverging Group",
        "description": "Moving hikers start clustered, then move in different deterministic directions.",
        "targets_move": True,
    },
}


class AttrDict(dict):
    """Dict with attribute access for simulation/algorithm compatibility."""

    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


def make_run_id() -> str:
    return f"bench-{uuid.uuid4().hex[:12]}"


def total_trials(request: BenchmarkRequest) -> int:
    return len(request.algorithms) * request.iterations


def list_scenario_profiles() -> list[dict[str, Any]]:
    """Return UI-facing scenario profile metadata."""
    return [
        {
            "key": key,
            "label": profile["label"],
            "description": profile["description"],
            "targets_move": profile["targets_move"],
        }
        for key, profile in SCENARIO_PROFILES.items()
    ]


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
                request.scenario_profile,
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
                    scenario_profile=request.scenario_profile,
                    static_targets=not bool(scenario["targets_move"]),
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
    scenario_profile: str = "uniform_random",
    static_targets: bool = True,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Run one algorithm/scenario pair without SITL commands or WS tick broadcasts."""
    algorithm_seed = scenario_seed + ALGORITHM_SEED_OFFSETS.get(algorithm, 909)
    dense_grid = build_dense_coverage_grid(bounds)
    mission = AttrDict({
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
        "_found_target_ids": set[Any](),
        "covered_set": set[Any](),
        "sweep_paths": {},
        "sweep_centroids": {},
        "sweep_phase": {},
        "sweep_reached_radius": None,
        "_suppress_broadcasts": True,
        "_static_targets": static_targets,
        "_move_assigned_sim_drones": True,
        "_rng": random.Random(algorithm_seed),
        "_np_rng": np.random.default_rng(algorithm_seed),
    })
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
        await _update_drones_for_tick(mission, set[str](), waypoints)
        _update_targets_for_tick(mission)
        _update_coverage(mission)
        _track_redundant_coverage(mission, dense_grid, visit_drones_by_cell)
        _track_distance(mission, previous_positions, distance_by_drone)
        _track_coverage_thresholds(mission, threshold_times)

        all_targets_found = await _finalize_mission_progress(mission)
        if all_targets_found:
            mission["status"] = "complete"
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
        "scenario_profile": scenario_profile,
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
    scenario_profile: str = "uniform_random",
) -> dict[str, Any]:
    if scenario_seed is None:
        raise ValueError("scenario_seed is required")
    if scenario_seed < 0:
        raise ValueError("scenario_seed must be non-negative")
    if drone_count < 1 or target_count < 1:
        raise ValueError("drone_count and target_count must be positive")
    if not _is_valid_bounds(bounds):
        raise ValueError("bounds must have positive latitude and longitude ranges")
    if scenario_profile not in SCENARIO_PROFILES:
        raise ValueError(f"Unknown scenario_profile: {scenario_profile}")

    rng = random.Random(scenario_seed)
    targets_move = bool(SCENARIO_PROFILES[scenario_profile]["targets_move"])
    if scenario_profile == "uniform_random":
        drones = _sample_uniform_points(rng, bounds, drone_count)
        targets = _sample_uniform_points(rng, bounds, target_count)
    elif scenario_profile == "clustered_drones":
        drones = _sample_cluster_points(rng, bounds, drone_count, _near_corner(bounds, 0))
        targets = _sample_uniform_points(rng, bounds, target_count)
    elif scenario_profile == "clustered_targets":
        drones = _sample_uniform_points(rng, bounds, drone_count)
        targets = _sample_cluster_points(rng, bounds, target_count, _random_center(rng, bounds))
    elif scenario_profile == "edge_targets":
        drones = _sample_uniform_points(rng, bounds, drone_count)
        targets = _sample_edge_points(rng, bounds, target_count)
    elif scenario_profile == "split_clusters":
        drones = _sample_uniform_points(rng, bounds, drone_count)
        targets = _sample_split_cluster_points(rng, bounds, target_count)
    elif scenario_profile == "corridor_route":
        drones = _sample_cluster_points(rng, bounds, drone_count, _near_corner(bounds, 0))
        targets = _sample_corridor_points(rng, bounds, target_count)
    elif scenario_profile == "wandering_hikers":
        drones = _sample_uniform_points(rng, bounds, drone_count)
        targets = _sample_uniform_points(rng, bounds, target_count)
    elif scenario_profile == "moving_edge_escape":
        drones = _sample_uniform_points(rng, bounds, drone_count)
        targets = _sample_edge_points(rng, bounds, target_count)
    elif scenario_profile == "diverging_group":
        drones = _sample_uniform_points(rng, bounds, drone_count)
        targets = _sample_cluster_points(rng, bounds, target_count, _random_center(rng, bounds))
    return {
        "drones": [
            {
                "id": f"d{i + 1}",
                "lat": point["lat"],
                "lon": point["lon"],
                "status": "idle",
            }
            for i, point in enumerate(drones)
        ],
        "targets": [
            _make_target(i, point, rng, bounds, scenario_profile, targets_move)
            for i, point in enumerate(targets)
        ],
        "targets_move": targets_move,
    }


def _is_valid_bounds(bounds: dict[str, float]) -> bool:
    return bounds["min_lat"] < bounds["max_lat"] and bounds["min_lon"] < bounds["max_lon"]


def _lat_span(bounds: dict[str, float]) -> float:
    return bounds["max_lat"] - bounds["min_lat"]


def _lon_span(bounds: dict[str, float]) -> float:
    return bounds["max_lon"] - bounds["min_lon"]


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _point(lat: float, lon: float, bounds: dict[str, float]) -> dict[str, float]:
    return {
        "lat": _clamp(lat, bounds["min_lat"], bounds["max_lat"]),
        "lon": _clamp(lon, bounds["min_lon"], bounds["max_lon"]),
    }


def _sample_uniform_points(rng: random.Random, bounds: dict[str, float], count: int) -> list[dict[str, float]]:
    return [
        {
            "lat": rng.uniform(bounds["min_lat"], bounds["max_lat"]),
            "lon": rng.uniform(bounds["min_lon"], bounds["max_lon"]),
        }
        for _ in range(count)
    ]


def _random_center(rng: random.Random, bounds: dict[str, float]) -> dict[str, float]:
    return {
        "lat": rng.uniform(
            bounds["min_lat"] + _lat_span(bounds) * 0.25,
            bounds["max_lat"] - _lat_span(bounds) * 0.25,
        ),
        "lon": rng.uniform(
            bounds["min_lon"] + _lon_span(bounds) * 0.25,
            bounds["max_lon"] - _lon_span(bounds) * 0.25,
        ),
    }


def _near_corner(bounds: dict[str, float], corner_index: int) -> dict[str, float]:
    corners = [
        (bounds["min_lat"], bounds["min_lon"]),
        (bounds["min_lat"], bounds["max_lon"]),
        (bounds["max_lat"], bounds["min_lon"]),
        (bounds["max_lat"], bounds["max_lon"]),
    ]
    lat, lon = corners[corner_index % len(corners)]
    inset_lat = _lat_span(bounds) * 0.08
    inset_lon = _lon_span(bounds) * 0.08
    return _point(
        lat + inset_lat if lat == bounds["min_lat"] else lat - inset_lat,
        lon + inset_lon if lon == bounds["min_lon"] else lon - inset_lon,
        bounds,
    )


def _sample_cluster_points(
    rng: random.Random,
    bounds: dict[str, float],
    count: int,
    center: dict[str, float],
) -> list[dict[str, float]]:
    radius_lat = _lat_span(bounds) * 0.08
    radius_lon = _lon_span(bounds) * 0.08
    return [
        _point(
            center["lat"] + rng.uniform(-radius_lat, radius_lat),
            center["lon"] + rng.uniform(-radius_lon, radius_lon),
            bounds,
        )
        for _ in range(count)
    ]


def _sample_split_cluster_points(rng: random.Random, bounds: dict[str, float], count: int) -> list[dict[str, float]]:
    centers = [_near_corner(bounds, 1), _near_corner(bounds, 2)]
    points: list[dict[str, float]] = []
    for i in range(count):
        points.extend(_sample_cluster_points(rng, bounds, 1, centers[i % len(centers)]))
    return points


def _sample_edge_points(rng: random.Random, bounds: dict[str, float], count: int) -> list[dict[str, float]]:
    margin_lat = _lat_span(bounds) * 0.05
    margin_lon = _lon_span(bounds) * 0.05
    points: list[dict[str, float]] = []
    for i in range(count):
        edge = i % 4
        if edge == 0:
            points.append(
                _point(
                    bounds["min_lat"] + rng.uniform(0, margin_lat),
                    rng.uniform(bounds["min_lon"], bounds["max_lon"]),
                    bounds,
                )
            )
        elif edge == 1:
            points.append(
                _point(
                    bounds["max_lat"] - rng.uniform(0, margin_lat),
                    rng.uniform(bounds["min_lon"], bounds["max_lon"]),
                    bounds,
                )
            )
        elif edge == 2:
            points.append(
                _point(
                    rng.uniform(bounds["min_lat"], bounds["max_lat"]),
                    bounds["min_lon"] + rng.uniform(0, margin_lon),
                    bounds,
                )
            )
        else:
            points.append(
                _point(
                    rng.uniform(bounds["min_lat"], bounds["max_lat"]),
                    bounds["max_lon"] - rng.uniform(0, margin_lon),
                    bounds,
                )
            )
    return points


def _sample_corridor_points(rng: random.Random, bounds: dict[str, float], count: int) -> list[dict[str, float]]:
    points: list[dict[str, float]] = []
    for i in range(count):
        progress = (i + 1) / (count + 1)
        jitter_lat = rng.uniform(-_lat_span(bounds) * 0.04, _lat_span(bounds) * 0.04)
        jitter_lon = rng.uniform(-_lon_span(bounds) * 0.04, _lon_span(bounds) * 0.04)
        points.append(
            _point(
                bounds["min_lat"] + _lat_span(bounds) * progress + jitter_lat,
                bounds["min_lon"] + _lon_span(bounds) * progress + jitter_lon,
                bounds,
            )
        )
    return points


def _make_target(
    index: int,
    point: dict[str, float],
    rng: random.Random,
    bounds: dict[str, float],
    scenario_profile: str,
    targets_move: bool,
) -> dict[str, Any]:
    target: dict[str, Any] = {
        "id": f"t{index + 1}",
        "lat": point["lat"],
        "lon": point["lon"],
        "status": "wandering",
        "assigned_drone_id": None,
        "movement": "moving" if targets_move else "stationary",
    }
    if targets_move:
        vx, vy = _target_velocity(index, point, rng, bounds, scenario_profile)
        target["vx"] = vx
        target["vy"] = vy
    return target


def _target_velocity(
    index: int,
    point: dict[str, float],
    rng: random.Random,
    bounds: dict[str, float],
    scenario_profile: str,
) -> tuple[float, float]:
    speed = 0.00025
    if scenario_profile == "corridor_route":
        return speed * 0.85, speed * 0.85
    if scenario_profile == "moving_edge_escape":
        center_lat = bounds["min_lat"] + _lat_span(bounds) / 2
        center_lon = bounds["min_lon"] + _lon_span(bounds) / 2
        vx = speed if point["lat"] < center_lat else -speed
        vy = speed if point["lon"] < center_lon else -speed
        if abs(point["lat"] - bounds["min_lat"]) < abs(point["lat"] - bounds["max_lat"]):
            return abs(vx) * 0.4, vy
        return -abs(vx) * 0.4, vy
    if scenario_profile == "diverging_group":
        angle = (2 * math.pi * index) / 5
        return speed * math.cos(angle), speed * math.sin(angle)
    angle = rng.uniform(0, 2 * math.pi)
    return speed * math.cos(angle), speed * math.sin(angle)


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
