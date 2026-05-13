"""Unit tests for the PSO (Voronoi-constrained) search algorithm.

Test coverage
-------------
test_pso_mission_start_moves_drones   — starting a mission with pso and advancing
                                        20 ticks moves at least one drone.
test_pso_no_collapse                  — 4 drones, 60 ticks: min pairwise distance
                                        never drops below NICHING_RADIUS_DEG for
                                        more than 10 consecutive ticks.
test_pso_velocity_capped              — 60 ticks: |v| <= MAX_SPEED_DEG + epsilon
                                        every tick for every drone.
test_pso_deterministic_under_seed     — two run_headless_trial calls with the same
                                        scenario_seed produce identical coverage_pct
                                        and total_distance_traveled_m.
test_pso_phase_transition             — injecting a detected target mid-run causes
                                        Phase-2 fitness to activate and gbest to
                                        shift toward the injected detection.
"""

from __future__ import annotations

import asyncio
import math
import random

import numpy as np
import pytest

from app.algorithms.base import build_dense_coverage_grid, DETECTION_RADIUS
from app.algorithms.pso import PSOSearchAlgorithm, MAX_SPEED_DEG, NICHING_RADIUS_DEG
from app.benchmark import AttrDict, run_headless_trial


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

_BOUNDS = {"min_lat": 0.0, "max_lat": 0.04, "min_lon": 0.0, "max_lon": 0.04}


def _make_mission(
    drones: list[dict],
    targets: list[dict] | None = None,
    bounds: dict | None = None,
    seed: int = 42,
) -> AttrDict:
    """Minimal benchmark-style AttrDict mission for unit tests."""
    bounds = bounds or _BOUNDS
    dense_grid = build_dense_coverage_grid(bounds)
    return AttrDict({
        "id": "test-pso",
        "status": "running",
        "algorithm": "pso",
        "bounds": bounds,
        "drones": drones,
        "targets": targets or [],
        "_dense_coverage_grid": dense_grid,
        "_dense_grid_size": len(dense_grid),
        "_dense_covered_count": 0,
        "covered_set": set(),
        "_suppress_broadcasts": True,
        "_rng": random.Random(seed),
        "_np_rng": np.random.default_rng(seed),
    })


def _make_drone(drone_id: str, lat: float, lon: float) -> dict:
    return {"id": drone_id, "lat": lat, "lon": lon, "status": "idle"}


def _advance_ticks(algo: PSOSearchAlgorithm, mission: AttrDict, n: int) -> None:
    """Run `n` synchronous get_target_waypoints ticks and apply waypoints."""
    for _ in range(n):
        waypoints = algo.get_target_waypoints(mission, mission["drones"])
        for drone in mission["drones"]:
            wp = waypoints.get(str(drone["id"]))
            if wp is not None:
                drone["lat"] = wp[0]
                drone["lon"] = wp[1]
        # Update covered_set counter so fitness can vary between ticks
        mission["_dense_covered_count"] = len(mission["covered_set"])


# ---------------------------------------------------------------------------
# Test 1 — moving drones
# ---------------------------------------------------------------------------

def test_pso_mission_start_moves_drones():
    """After 20 ticks, at least one drone must have moved from its initial position."""
    drones = [
        _make_drone("d1", 0.005, 0.005),
        _make_drone("d2", 0.015, 0.015),
        _make_drone("d3", 0.025, 0.025),
    ]
    initial = {d["id"]: (d["lat"], d["lon"]) for d in drones}
    mission = _make_mission(drones, seed=1)
    algo = PSOSearchAlgorithm()
    algo.initialize(mission)
    _advance_ticks(algo, mission, n=20)

    any_moved = any(
        math.hypot(d["lat"] - initial[d["id"]][0], d["lon"] - initial[d["id"]][1]) > 1e-9
        for d in mission["drones"]
    )
    assert any_moved, "No drone moved after 20 PSO ticks"


# ---------------------------------------------------------------------------
# Test 2 — no swarm collapse
# ---------------------------------------------------------------------------

def test_pso_no_collapse():
    """Niching + Voronoi clipping: min pairwise dist must NOT stay below
    NICHING_RADIUS_DEG for more than 10 consecutive ticks."""
    # Spread 4 drones across the area
    drones = [
        _make_drone("d1", 0.003, 0.003),
        _make_drone("d2", 0.003, 0.037),
        _make_drone("d3", 0.037, 0.003),
        _make_drone("d4", 0.037, 0.037),
    ]
    mission = _make_mission(drones, seed=99)
    algo = PSOSearchAlgorithm()
    algo.initialize(mission)

    consecutive_collapsed_ticks = 0
    max_consecutive_collapsed = 0

    for _ in range(60):
        waypoints = algo.get_target_waypoints(mission, mission["drones"])
        for drone in mission["drones"]:
            wp = waypoints.get(str(drone["id"]))
            if wp is not None:
                drone["lat"] = wp[0]
                drone["lon"] = wp[1]

        positions = [(float(d["lat"]), float(d["lon"])) for d in mission["drones"]]
        min_dist = float("inf")
        for i in range(len(positions)):
            for j in range(i + 1, len(positions)):
                dist = math.hypot(
                    positions[i][0] - positions[j][0],
                    positions[i][1] - positions[j][1],
                )
                min_dist = min(min_dist, dist)

        if min_dist < NICHING_RADIUS_DEG:
            consecutive_collapsed_ticks += 1
        else:
            consecutive_collapsed_ticks = 0

        max_consecutive_collapsed = max(max_consecutive_collapsed, consecutive_collapsed_ticks)

    assert max_consecutive_collapsed <= 10, (
        f"Swarm collapsed (min pairwise dist < NICHING_RADIUS) for "
        f"{max_consecutive_collapsed} consecutive ticks (limit: 10)"
    )


# ---------------------------------------------------------------------------
# Test 3 — velocity cap
# ---------------------------------------------------------------------------

def test_pso_velocity_capped():
    """Every stored velocity vector must have magnitude <= MAX_SPEED_DEG + ε."""
    drones = [
        _make_drone("d1", 0.005, 0.005),
        _make_drone("d2", 0.035, 0.035),
        _make_drone("d3", 0.005, 0.035),
        _make_drone("d4", 0.035, 0.005),
    ]
    mission = _make_mission(drones, seed=7)
    algo = PSOSearchAlgorithm()
    algo.initialize(mission)

    eps = 1e-9
    for tick in range(60):
        algo.get_target_waypoints(mission, mission["drones"])
        for drone in mission["drones"]:
            v = mission["pso_velocities"].get(str(drone["id"]))
            if v is not None:
                speed = float(np.linalg.norm(v))
                assert speed <= MAX_SPEED_DEG + eps, (
                    f"Drone {drone['id']} velocity {speed:.8f} > MAX_SPEED_DEG "
                    f"{MAX_SPEED_DEG} at tick {tick}"
                )


# ---------------------------------------------------------------------------
# Test 4 — determinism under seed
# ---------------------------------------------------------------------------

def test_pso_deterministic_under_seed():
    """Two run_headless_trial calls with the same scenario_seed must produce
    identical coverage_pct and total_distance_traveled_m."""
    bounds = {"min_lat": 0.0, "max_lat": 0.04, "min_lon": 0.0, "max_lon": 0.04}
    kwargs = dict(
        run_id="det-test",
        algorithm="pso",
        iteration=1,
        scenario_seed=2024,
        bounds=bounds,
        drone_starts=[
            {"id": "d1", "lat": 0.01, "lon": 0.01, "status": "idle"},
            {"id": "d2", "lat": 0.03, "lon": 0.03, "status": "idle"},
        ],
        target_starts=[
            {
                "id": "t1",
                "lat": 0.02,
                "lon": 0.02,
                "status": "wandering",
                "assigned_drone_id": None,
            }
        ],
        timeout_seconds=30,
    )
    result_a = asyncio.run(run_headless_trial(**kwargs))
    result_b = asyncio.run(run_headless_trial(**kwargs))

    assert result_a["coverage_pct"] == result_b["coverage_pct"], (
        f"coverage_pct not deterministic: {result_a['coverage_pct']} vs {result_b['coverage_pct']}"
    )
    assert result_a["total_distance_traveled_m"] == result_b["total_distance_traveled_m"], (
        "total_distance_traveled_m not deterministic"
    )


# ---------------------------------------------------------------------------
# Test 5 — Phase 2 transition
# ---------------------------------------------------------------------------

def test_pso_phase_transition():
    """Injecting a detected target triggers Phase-2 fitness and shifts gbest
    toward the injected detection location."""
    # Place drones away from the injection point
    drones = [
        _make_drone("d1", 0.005, 0.005),
        _make_drone("d2", 0.010, 0.010),
        _make_drone("d3", 0.020, 0.020),
    ]
    mission = _make_mission(drones, seed=55)
    algo = PSOSearchAlgorithm()
    algo.initialize(mission)

    # Run Phase 1 for 10 ticks — no detections, gbest is coverage-driven
    _advance_ticks(algo, mission, n=10)
    gbest_before = mission["pso_gbest"].copy()

    # Inject a detected target in the far corner
    detection_lat, detection_lon = 0.038, 0.038
    mission["targets"] = [
        {
            "id": "t_injected",
            "lat": detection_lat,
            "lon": detection_lon,
            "status": "detected",
            "assigned_drone_id": None,
        }
    ]
    # Ensure Phase-2 fitness is active by checking _fitness directly
    fit_phase2 = algo._fitness(mission, 0.038, 0.038)
    fit_phase1_away = algo._fitness(mission, 0.001, 0.001)
    # In Phase 2 the fitness near the detection must be higher (attractor adds 1/dist)
    assert fit_phase2 > fit_phase1_away, (
        f"Phase-2 fitness near detection ({fit_phase2:.4f}) should exceed "
        f"far-away fitness ({fit_phase1_away:.4f})"
    )

    # Run Phase 2 for 20 more ticks
    _advance_ticks(algo, mission, n=20)
    gbest_after = mission["pso_gbest"].copy()

    # gbest should have shifted closer to the detection
    dist_before = math.hypot(
        gbest_before[0] - detection_lat, gbest_before[1] - detection_lon
    )
    dist_after = math.hypot(
        gbest_after[0] - detection_lat, gbest_after[1] - detection_lon
    )
    assert dist_after < dist_before, (
        f"gbest did not shift toward detection: "
        f"dist_before={dist_before:.5f} dist_after={dist_after:.5f}"
    )
