"""Unit tests for the VACO hybrid coverage algorithm."""

from __future__ import annotations

import asyncio
import math
import random

import numpy as np

from app.algorithms.base import build_dense_coverage_grid
from app.algorithms.stigmergy_engine import GridConfig, InMemoryPheromoneGrid
from app.algorithms.vaco import VoronoiACOHybridCoverage
from app.benchmark import AttrDict, run_headless_trial


_BOUNDS = {"min_lat": 0.0, "max_lat": 0.04, "min_lon": 0.0, "max_lon": 0.04}


def _make_drone(drone_id: str, lat: float, lon: float) -> dict:
    return {"id": drone_id, "lat": lat, "lon": lon, "status": "idle"}


def _make_mission(drones: list[dict], seed: int = 42) -> AttrDict:
    dense_grid = build_dense_coverage_grid(_BOUNDS)
    return AttrDict({
        "id": "test-vaco",
        "status": "running",
        "algorithm": "vaco",
        "bounds": _BOUNDS,
        "elapsed_seconds": 0,
        "drones": drones,
        "targets": [],
        "_dense_coverage_grid": dense_grid,
        "_dense_grid_size": len(dense_grid),
        "_dense_covered_count": 0,
        "covered_set": set(),
        "_suppress_broadcasts": True,
        "_rng": random.Random(seed),
        "_np_rng": np.random.default_rng(seed),
    })


def _advance_ticks(algo: VoronoiACOHybridCoverage, mission: AttrDict, n: int) -> None:
    for _ in range(n):
        mission["elapsed_seconds"] += 1
        waypoints = algo.get_target_waypoints(mission, mission["drones"])
        for drone in mission["drones"]:
            wp = waypoints.get(str(drone["id"]))
            if wp is None:
                continue
            drone["lat"] = wp[0]
            drone["lon"] = wp[1]


def test_vaco_mission_start_moves_drones():
    drones = [
        _make_drone("d1", 0.005, 0.005),
        _make_drone("d2", 0.015, 0.015),
        _make_drone("d3", 0.025, 0.025),
        _make_drone("d4", 0.035, 0.035),
    ]
    initial = {d["id"]: (d["lat"], d["lon"]) for d in drones}
    mission = _make_mission(drones, seed=1)
    algo = VoronoiACOHybridCoverage()
    algo.initialize(mission)
    _advance_ticks(algo, mission, n=20)

    any_moved = any(
        math.hypot(d["lat"] - initial[d["id"]][0], d["lon"] - initial[d["id"]][1]) > 1e-9
        for d in mission["drones"]
    )
    assert any_moved, "No drone moved after 20 VACO ticks"


def test_vaco_partition_covers_all_drones():
    drones = [
        _make_drone("d1", 0.003, 0.003),
        _make_drone("d2", 0.003, 0.037),
        _make_drone("d3", 0.037, 0.003),
        _make_drone("d4", 0.037, 0.037),
    ]
    mission = _make_mission(drones, seed=99)
    algo = VoronoiACOHybridCoverage()
    algo.initialize(mission)
    _advance_ticks(algo, mission, n=1)

    territories = mission._rtx_territories
    assert set(territories.keys()) == {d["id"] for d in drones}
    for drone in drones:
        territory = territories.get(drone["id"])
        assert territory is not None
        assert isinstance(territory, np.ndarray)
        assert len(territory) > 0


def test_vaco_deterministic_under_seed():
    kwargs = dict(
        run_id="det-test-vaco",
        algorithm="vaco",
        iteration=1,
        scenario_seed=2026,
        bounds=_BOUNDS,
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

    assert result_a["coverage_pct"] == result_b["coverage_pct"]
    assert result_a["targets_found"] == result_b["targets_found"]
    assert result_a["total_distance_traveled_m"] == result_b["total_distance_traveled_m"]


def test_vaco_pheromone_evaporates():
    cfg = GridConfig(
        lat_min=0.0,
        lat_max=1.0,
        lon_min=0.0,
        lon_max=1.0,
        rows=10,
        cols=10,
        evaporation_rate=0.97,
        deposit_strength=1.0,
    )
    grid = InMemoryPheromoneGrid(cfg)
    grid.deposit(0.5, 0.5)
    initial = grid.get_value(0.5, 0.5)
    for _ in range(10):
        grid.tick()
    decayed = grid.get_value(0.5, 0.5)

    assert initial == 1.0
    assert decayed < initial
