from __future__ import annotations

import asyncio
import math
import random

import numpy as np

from app.algorithms.base import DETECTION_RADIUS, build_dense_coverage_grid
from app.algorithms.infotaxis import InfotaxisSearch
from app.benchmark import AttrDict, run_headless_trial


_BOUNDS = {"min_lat": 0.0, "max_lat": 0.02, "min_lon": 0.0, "max_lon": 0.02}


def _make_mission(
    drones: list[dict],
    *,
    bounds: dict | None = None,
    seed: int = 42,
) -> AttrDict:
    bounds = bounds or _BOUNDS
    dense_grid = build_dense_coverage_grid(bounds)
    return AttrDict({
        "id": "test-infotaxis",
        "status": "running",
        "elapsed_seconds": 0,
        "algorithm": "infotaxis",
        "bounds": bounds,
        "grid": dense_grid.tolist(),
        "drones": drones,
        "targets": [],
        "scenario_profile": "uniform_random",
        "_dense_coverage_grid": dense_grid,
        "_dense_grid_size": len(dense_grid),
        "_dense_covered_count": 0,
        "covered_set": set(),
        "_suppress_broadcasts": True,
        "_rng": random.Random(seed),
        "_np_rng": np.random.default_rng(seed),
    })


def _posterior_with_entropy_frontier(
    grid: np.ndarray,
    center: tuple[float, float],
) -> np.ndarray:
    posterior = np.full(len(grid), 1e-9, dtype=float)
    hot_idx = int(np.argmin(np.hypot(grid[:, 0] - center[0], grid[:, 1] - center[1])))
    posterior[hot_idx] = 0.5
    far_mask = np.hypot(grid[:, 0] - center[0], grid[:, 1] - center[1]) > DETECTION_RADIUS * 3
    posterior[far_mask] += 0.5 / float(far_mask.sum())
    posterior /= posterior.sum()
    return posterior


def test_infotaxis_initializes_attrdict_mission():
    mission = _make_mission([{"id": "d1", "lat": 0.01, "lon": 0.01, "status": "idle"}])
    algo = InfotaxisSearch()

    algo.initialize(mission)

    assert mission["itx_grid"].shape == (mission["_dense_grid_size"], 2)
    assert np.isclose(float(mission["itx_P"].sum()), 1.0, atol=1e-6)
    assert set(mission["itx_drone_cells"].keys()) == {"d1"}


def test_infotaxis_posterior_decays_after_scan():
    drones = [{"id": "d1", "lat": 0.01, "lon": 0.01, "status": "idle"}]
    mission = _make_mission(drones)
    algo = InfotaxisSearch()
    algo.initialize(mission)

    grid = mission["itx_grid"]
    before = mission["itx_P"].copy()
    scanned = np.hypot(grid[:, 0] - 0.01, grid[:, 1] - 0.01) <= DETECTION_RADIUS

    mission["elapsed_seconds"] = 1
    algo.get_target_waypoints(mission, mission["drones"])

    after = mission["itx_P"]
    assert float(after[scanned].sum()) < float(before[scanned].sum())
    assert np.isclose(float(after.sum()), 1.0, atol=1e-6)


def test_infotaxis_waypoint_changes_when_posterior_mass_shifts():
    drones = [{"id": "d1", "lat": 0.01, "lon": 0.01, "status": "idle"}]
    mission = _make_mission(drones)
    algo = InfotaxisSearch()
    algo.initialize(mission)
    grid = mission["itx_grid"]

    southwest = (0.004, 0.004)
    northeast = (0.016, 0.016)

    mission["itx_P"] = _posterior_with_entropy_frontier(grid, southwest)
    waypoint_sw = algo.get_target_waypoints(mission, mission["drones"])["d1"]

    mission["itx_P"] = _posterior_with_entropy_frontier(grid, northeast)
    waypoint_ne = algo.get_target_waypoints(mission, mission["drones"])["d1"]

    assert waypoint_sw != waypoint_ne
    assert math.hypot(waypoint_sw[0] - southwest[0], waypoint_sw[1] - southwest[1]) <= DETECTION_RADIUS
    assert math.hypot(waypoint_ne[0] - northeast[0], waypoint_ne[1] - northeast[1]) <= DETECTION_RADIUS


def test_infotaxis_deterministic_under_seed():
    kwargs = dict(
        run_id="infotaxis-det-test",
        algorithm="infotaxis",
        iteration=1,
        scenario_seed=2024,
        bounds=_BOUNDS,
        drone_starts=[
            {"id": "d1", "lat": 0.002, "lon": 0.002, "status": "idle"},
            {"id": "d2", "lat": 0.018, "lon": 0.018, "status": "idle"},
        ],
        target_starts=[
            {
                "id": "t1",
                "lat": 0.015,
                "lon": 0.015,
                "status": "wandering",
                "assigned_drone_id": None,
                "movement": "stationary",
            }
        ],
        scenario_profile="edge_targets",
        timeout_seconds=10,
    )

    result_a = asyncio.run(run_headless_trial(**kwargs))
    result_b = asyncio.run(run_headless_trial(**kwargs))

    assert result_a["coverage_pct"] == result_b["coverage_pct"]
    assert result_a["targets_found"] == result_b["targets_found"]
    assert math.isclose(
        result_a["total_distance_traveled_m"],
        result_b["total_distance_traveled_m"],
    )
