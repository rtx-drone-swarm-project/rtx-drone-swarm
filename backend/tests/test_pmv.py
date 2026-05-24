from __future__ import annotations

import asyncio
import math
import random

import numpy as np

from app.algorithms.base import DETECTION_RADIUS, build_dense_coverage_grid
from app.algorithms.pmv import (
    DIFFUSE_SIGMA_DEG,
    PMVSearchAlgorithm,
    _diffuse_probability,
    _moving_profile_sigma,
    build_pmv_heatmap_payload,
)
from app.algorithms.priors import (
    BOUNDARY_BAND_DEG,
    CORRIDOR_HALFWIDTH_DEG,
    build_prior,
    normalize_probability,
)
from app.benchmark import AttrDict, SCENARIO_PROFILES, run_headless_trial


_BOUNDS = {"min_lat": 0.0, "max_lat": 0.04, "min_lon": 0.0, "max_lon": 0.04}


def _make_mission(
    drones: list[dict],
    *,
    bounds: dict | None = None,
    scenario_profile: str = "uniform_random",
    seed: int = 42,
) -> AttrDict:
    bounds = bounds or _BOUNDS
    dense_grid = build_dense_coverage_grid(bounds)
    return AttrDict({
        "id": "test-pmv",
        "status": "running",
        "elapsed_seconds": 0,
        "algorithm": "pmv",
        "bounds": bounds,
        "grid": dense_grid.tolist(),
        "drones": drones,
        "targets": [],
        "scenario_profile": scenario_profile,
        "_dense_coverage_grid": dense_grid,
        "_dense_grid_size": len(dense_grid),
        "_dense_covered_count": 0,
        "covered_set": set(),
        "_suppress_broadcasts": True,
        "_rng": random.Random(seed),
        "_np_rng": np.random.default_rng(seed),
    })


def _line_distances(
    grid: np.ndarray,
    start: tuple[float, float],
    end: tuple[float, float],
) -> np.ndarray:
    start_np = np.asarray(start, dtype=float)
    end_np = np.asarray(end, dtype=float)
    segment = end_np - start_np
    t = np.clip(((grid - start_np) @ segment) / float(np.dot(segment, segment)), 0.0, 1.0)
    projection = start_np + t[:, np.newaxis] * segment
    return np.linalg.norm(grid - projection, axis=1)


def test_pmv_priors_are_normalized_for_all_scenario_profiles():
    grid = build_dense_coverage_grid(_BOUNDS)

    for profile in SCENARIO_PROFILES:
        prior = build_prior(_BOUNDS, grid, profile)
        assert prior.shape == (len(grid),)
        assert np.isclose(float(prior.sum()), 1.0, atol=1e-6), profile
        assert np.all(prior >= 0), profile


def test_pmv_priors_have_expected_mass_location():
    grid = build_dense_coverage_grid(_BOUNDS)

    edge_prior = build_prior(_BOUNDS, grid, "edge_targets")
    edge_distance = np.minimum.reduce(
        [
            grid[:, 0] - _BOUNDS["min_lat"],
            _BOUNDS["max_lat"] - grid[:, 0],
            grid[:, 1] - _BOUNDS["min_lon"],
            _BOUNDS["max_lon"] - grid[:, 1],
        ]
    )
    edge_mask = edge_distance <= BOUNDARY_BAND_DEG
    assert float(edge_prior[edge_mask].sum()) > 0.5

    corridor_prior = build_prior(_BOUNDS, grid, "corridor_route")
    corridor_mask = _line_distances(
        grid,
        (_BOUNDS["min_lat"], _BOUNDS["min_lon"]),
        (_BOUNDS["max_lat"], _BOUNDS["max_lon"]),
    ) <= CORRIDOR_HALFWIDTH_DEG
    assert float(corridor_prior[corridor_mask].sum()) > 0.5


def test_wandering_hikers_prior_is_uniform_without_explicit_clues():
    grid = build_dense_coverage_grid(_BOUNDS)

    prior = build_prior(_BOUNDS, grid, "wandering_hikers")

    assert np.allclose(prior, np.ones(len(grid), dtype=float) / len(grid))


def test_probability_normalization_sanitizes_invalid_weights():
    normalized = normalize_probability(np.array([np.nan, np.inf, -1.0, 0.0, 2.0]))

    assert np.allclose(normalized, np.array([0.0, 0.0, 0.0, 0.0, 1.0]))


def test_pmv_posterior_decays_after_scan():
    drones = [{"id": "d1", "lat": 0.02, "lon": 0.02, "status": "idle"}]
    mission = _make_mission(drones)
    algo = PMVSearchAlgorithm()
    algo.initialize(mission)

    grid = mission["pmv_grid"]
    before = mission["pmv_P"].copy()
    scanned = np.hypot(grid[:, 0] - 0.02, grid[:, 1] - 0.02) <= DETECTION_RADIUS

    mission["elapsed_seconds"] = 1
    algo.get_target_waypoints(mission, mission["drones"])

    after = mission["pmv_P"]
    assert float(after[scanned].sum()) < float(before[scanned].sum())
    assert np.isclose(float(after.sum()), 1.0, atol=1e-6)


def test_moving_profile_sigma_scales_with_bounds():
    small = {"min_lat": 0.0, "max_lat": 0.02, "min_lon": 0.0, "max_lon": 0.02}
    large = {"min_lat": 0.0, "max_lat": 0.10, "min_lon": 0.0, "max_lon": 0.10}

    # Tiny bounds may fall to the floor; the floor itself must be respected.
    assert _moving_profile_sigma("wandering_hikers", small) >= DIFFUSE_SIGMA_DEG
    # On a 10 km-equivalent extent the moving sigma should grow well past the
    # detection-radius floor; otherwise PMV cannot keep up with translating
    # hikers and corridor_route collapses to 0% success.
    assert _moving_profile_sigma("wandering_hikers", large) > DIFFUSE_SIGMA_DEG * 2
    # corridor_route uses a stronger fraction because the corridor extends
    # along the full diagonal of the bounds.
    assert _moving_profile_sigma("corridor_route", large) > _moving_profile_sigma(
        "wandering_hikers", large
    )


def test_pmv_corridor_diffusion_spreads_further_at_large_bounds():
    """At 12 km-equivalent bounds the moving-profile diffusion must spread mass
    well past one detection radius in a single step; otherwise PMV cannot
    track a hiker translating along a long corridor."""
    bounds = {"min_lat": 0.0, "max_lat": 0.108, "min_lon": 0.0, "max_lon": 0.108}
    grid = build_dense_coverage_grid(bounds)
    posterior = np.full(len(grid), 1e-9, dtype=float)
    hot_idx = int(np.argmin(np.hypot(grid[:, 0] - 0.05, grid[:, 1] - 0.05)))
    posterior[hot_idx] = 1.0
    posterior /= posterior.sum()

    sigma = _moving_profile_sigma("corridor_route", bounds)
    diffused = _diffuse_probability(posterior, grid, bounds, sigma)

    hot_pt = grid[hot_idx]
    nearby_radius = DETECTION_RADIUS * 5
    distances = np.hypot(grid[:, 0] - hot_pt[0], grid[:, 1] - hot_pt[1])
    far_mask = distances > nearby_radius
    # Without a bounds-aware sigma the probability barely leaves the seed cell;
    # with the new fraction-of-diagonal sigma it must reach noticeably further.
    assert float(diffused[far_mask].sum()) > 0.2


def test_pmv_diffusion_spreads_mass():
    grid = build_dense_coverage_grid(_BOUNDS)
    posterior = np.full(len(grid), 1e-9, dtype=float)
    hot_idx = int(np.argmin(np.hypot(grid[:, 0] - 0.02, grid[:, 1] - 0.02)))
    posterior[hot_idx] = 1.0
    posterior /= posterior.sum()

    diffused = _diffuse_probability(posterior, grid, _BOUNDS, DETECTION_RADIUS)

    assert float(diffused.max()) < float(posterior.max())
    assert float(np.var(diffused)) < float(np.var(posterior))
    assert np.isclose(float(diffused.sum()), 1.0, atol=1e-6)


def test_pmv_waypoint_selects_highest_score_cell():
    drones = [{"id": "d1", "lat": 0.002, "lon": 0.002, "status": "idle"}]
    mission = _make_mission(drones)
    algo = PMVSearchAlgorithm()
    algo.initialize(mission)

    grid = mission["pmv_grid"]
    hot_idx = int(np.argmin(np.hypot(grid[:, 0] - 0.018, grid[:, 1] - 0.018)))
    posterior = np.full(len(grid), 1e-9, dtype=float)
    posterior[hot_idx] = 1.0
    posterior /= posterior.sum()
    mission["pmv_P"] = posterior

    waypoints = algo.get_target_waypoints(mission, mission["drones"])

    assert waypoints["d1"] == (float(grid[hot_idx, 0]), float(grid[hot_idx, 1]))


def test_pmv_global_hotspot_can_pull_drone_beyond_fixed_partition():
    drones = [{"id": "d1", "lat": 0.002, "lon": 0.002, "status": "idle"}]
    mission = _make_mission(drones)
    algo = PMVSearchAlgorithm()
    algo.initialize(mission)

    grid = mission["pmv_grid"]
    local_indices = np.where((grid[:, 0] <= 0.006) & (grid[:, 1] <= 0.006))[0]
    hot_idx = int(np.argmin(np.hypot(grid[:, 0] - 0.04, grid[:, 1] - 0.04)))
    assert hot_idx not in set(local_indices.tolist())

    posterior = np.full(len(grid), 1e-9, dtype=float)
    posterior[local_indices] = 0.01
    posterior[hot_idx] = 1.0
    posterior /= posterior.sum()
    mission["pmv_drone_cells"] = {"d1": local_indices}
    mission["pmv_P"] = posterior

    waypoints = algo.get_target_waypoints(mission, mission["drones"])

    assert waypoints["d1"] == (float(grid[hot_idx, 0]), float(grid[hot_idx, 1]))


def test_pmv_uniform_probability_stays_inside_partition():
    drones = [{"id": "d1", "lat": 0.002, "lon": 0.002, "status": "idle"}]
    mission = _make_mission(drones)
    algo = PMVSearchAlgorithm()
    algo.initialize(mission)

    grid = mission["pmv_grid"]
    local_indices = np.where((grid[:, 0] <= 0.006) & (grid[:, 1] <= 0.006))[0]
    mission["pmv_drone_cells"] = {"d1": local_indices}
    mission["pmv_P"] = np.ones(len(grid), dtype=float) / len(grid)

    waypoints = algo.get_target_waypoints(mission, mission["drones"])

    assert waypoints["d1"] in {
        (float(grid[idx, 0]), float(grid[idx, 1]))
        for idx in local_indices
    }


def test_pmv_heatmap_payload_is_row_major_and_aligned_to_bounds():
    mission = _make_mission([{"id": "d1", "lat": 0.0, "lon": 0.0, "status": "idle"}])
    mission["pmv_grid"] = np.array(
        [
            [0.0, 0.0],
            [0.0, 1.0],
            [1.0, 0.0],
            [1.0, 1.0],
        ],
        dtype=float,
    )
    mission["pmv_P"] = np.array([0.1, 0.2, 0.3, 0.4], dtype=float)
    mission["bounds"] = {"min_lat": 0.0, "max_lat": 1.0, "min_lon": 0.0, "max_lon": 1.0}

    payload = build_pmv_heatmap_payload(mission, mission_id="m1", rows=2, cols=2)

    assert payload is not None
    assert payload["type"] == "pmv_heatmap"
    assert payload["mission_id"] == "m1"
    assert payload["rows"] == 2
    assert payload["cols"] == 2
    assert payload["bounds"] == mission["bounds"]
    assert payload["values"] == [0.1, 0.2, 0.3, 0.4]
    assert payload["max_value"] == 0.4
    assert payload["total_probability"] == 1.0


def test_pmv_heatmap_payload_normalizes_probability_and_ignores_targets():
    drones = [{"id": "d1", "lat": 0.02, "lon": 0.02, "status": "idle"}]
    mission = _make_mission(drones)
    algo = PMVSearchAlgorithm()
    algo.initialize(mission)
    mission["pmv_P"] = mission["pmv_P"] * 5.0

    mission["targets"] = [{"id": "hidden", "lat": 0.0, "lon": 0.0}]
    payload_a = build_pmv_heatmap_payload(mission, mission_id="m1", rows=20, cols=20)
    mission["targets"] = [{"id": "hidden", "lat": 0.04, "lon": 0.04}]
    payload_b = build_pmv_heatmap_payload(mission, mission_id="m1", rows=20, cols=20)

    assert payload_a is not None
    assert len(payload_a["values"]) == 400
    assert np.isclose(payload_a["total_probability"], 1.0, atol=1e-9)
    assert payload_a == payload_b


def test_pmv_deterministic_under_seed():
    kwargs = dict(
        run_id="pmv-det-test",
        algorithm="pmv",
        iteration=1,
        scenario_seed=2024,
        bounds={"min_lat": 0.0, "max_lat": 0.02, "min_lon": 0.0, "max_lon": 0.02},
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
        timeout_seconds=20,
    )

    result_a = asyncio.run(run_headless_trial(**kwargs))
    result_b = asyncio.run(run_headless_trial(**kwargs))

    assert result_a["coverage_pct"] == result_b["coverage_pct"]
    assert result_a["targets_found"] == result_b["targets_found"]
    assert math.isclose(
        result_a["total_distance_traveled_m"],
        result_b["total_distance_traveled_m"],
    )
