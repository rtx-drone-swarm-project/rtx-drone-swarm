"""Infotaxis search algorithm for drone swarm SAR.

Infotaxis scores by expected information gain
(binary entropy of local detection probability).

Built off current PMV implementation"""

from __future__ import annotations

import logging
import math
from typing import Dict, List, Tuple

import numpy as np

from app.algorithms.base import BaseSearchAlgorithm, DETECTION_RADIUS, build_dense_coverage_grid
from app.algorithms.boustrophedon import (
    _match_drones_to_seeds,
    _partition_seeds,
    _voronoi_assign,
)
from app.algorithms.priors import build_prior, normalize_probability


logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Constants — identical to pmv.py so results are directly comparable
# --------------------------------------------------------------------------
DETECTION_PROB                  = 0.9
DIFFUSE_INTERVAL_S              = 10
DIFFUSE_SIGMA_DEG               = DETECTION_RADIUS
DIFFUSE_SIGMA_FRACTION          = 0.04
DIFFUSE_SIGMA_FRACTION_CORRIDOR = 0.08
LAMBDA_DEG                      = 5 * DETECTION_RADIUS
TRAVEL_WEIGHT_FLOOR             = 0.18
EPS                             = 1e-12
_SEED_LLOYD_ITERS               = 8
_MOVING_PROFILES = {
    "corridor_route",
    "wandering_hikers",
    "moving_edge_escape",
    "diverging_group",
}


def _getm(mission, key: str, default=None):
    if isinstance(mission, dict):
        return mission.get(key, default)
    return getattr(mission, key, default)


def _setm(mission, key: str, value) -> None:
    if isinstance(mission, dict):
        mission[key] = value
    else:
        setattr(mission, key, value)


def _scanned_indices(grid: np.ndarray, drones: list[dict]) -> np.ndarray:
    scanned: set[int] = set()
    for drone in drones:
        if drone.get("lat") is None or drone.get("lon") is None:
            continue
        dlat = float(drone["lat"])
        dlon = float(drone["lon"])
        lat_mask = np.abs(grid[:, 0] - dlat) <= DETECTION_RADIUS
        lon_mask = np.abs(grid[:, 1] - dlon) <= DETECTION_RADIUS
        candidates = np.where(lat_mask & lon_mask)[0]
        if len(candidates) == 0:
            continue
        sub = grid[candidates]
        within = candidates[
            np.hypot(sub[:, 0] - dlat, sub[:, 1] - dlon) <= DETECTION_RADIUS
        ]
        scanned.update(int(i) for i in within)
    return np.array(sorted(scanned), dtype=int)


def _moving_profile_sigma(profile: str, bounds: dict) -> float:
    """Bounds-aware diffusion sigma — identical to pmv.py."""
    lat_span = float(bounds.get("max_lat", 0.0) - bounds.get("min_lat", 0.0))
    lon_span = float(bounds.get("max_lon", 0.0) - bounds.get("min_lon", 0.0))
    diag = math.hypot(lat_span, lon_span)
    fraction = (
        DIFFUSE_SIGMA_FRACTION_CORRIDOR
        if profile == "corridor_route"
        else DIFFUSE_SIGMA_FRACTION
    )
    return max(DIFFUSE_SIGMA_DEG, diag * fraction)


def _axis_step(axis_values: np.ndarray, fallback_span: float) -> float:
    if len(axis_values) >= 2:
        diffs = np.diff(axis_values)
        diffs = diffs[diffs > 0]
        if len(diffs) > 0:
            return float(np.median(diffs))
    return max(float(fallback_span), DETECTION_RADIUS)


def _gaussian_kernel(sigma_cells: float) -> np.ndarray:
    radius = max(1, int(math.ceil(3 * sigma_cells)))
    offsets = np.arange(-radius, radius + 1, dtype=float)
    kernel = np.exp(-0.5 * (offsets / max(sigma_cells, EPS)) ** 2)
    return kernel / float(kernel.sum())


def _convolve_axis(matrix: np.ndarray, kernel: np.ndarray, axis: int) -> np.ndarray:
    pad = len(kernel) // 2
    padded = np.pad(
        matrix,
        [(pad, pad), (0, 0)] if axis == 0 else [(0, 0), (pad, pad)],
        mode="edge",
    )
    return np.apply_along_axis(lambda row: np.convolve(row, kernel, mode="valid"), axis, padded)


def _diffuse_probability(
    posterior: np.ndarray,
    grid: np.ndarray,
    bounds: dict,
    sigma_deg: float,
) -> np.ndarray:
    if len(posterior) <= 1:
        return normalize_probability(posterior)

    unique_lats = np.unique(np.round(grid[:, 0], 12))
    unique_lons = np.unique(np.round(grid[:, 1], 12))
    if len(unique_lats) * len(unique_lons) != len(posterior):
        return normalize_probability(posterior)

    lat_index = {value: idx for idx, value in enumerate(unique_lats.tolist())}
    lon_index = {value: idx for idx, value in enumerate(unique_lons.tolist())}
    lat_ids = np.array([lat_index[round(float(lat), 12)] for lat in grid[:, 0]], dtype=int)
    lon_ids = np.array([lon_index[round(float(lon), 12)] for lon in grid[:, 1]], dtype=int)

    matrix = np.zeros((len(unique_lats), len(unique_lons)), dtype=float)
    matrix[lat_ids, lon_ids] = posterior

    lat_step = _axis_step(unique_lats, bounds.get("max_lat", 0.0) - bounds.get("min_lat", 0.0))
    lon_step = _axis_step(unique_lons, bounds.get("max_lon", 0.0) - bounds.get("min_lon", 0.0))
    lat_kernel = _gaussian_kernel(max(sigma_deg / max(lat_step, EPS), EPS))
    lon_kernel = _gaussian_kernel(max(sigma_deg / max(lon_step, EPS), EPS))

    diffused = _convolve_axis(matrix, lat_kernel, axis=0)
    diffused = _convolve_axis(diffused, lon_kernel, axis=1)

    flat = diffused[lat_ids, lon_ids]
    return normalize_probability(flat)


# --------------------------------------------------------------------------
# Infotaxis scoring
# --------------------------------------------------------------------------

def _infotaxis_weights(
    posterior: np.ndarray,
    candidate_indices: np.ndarray,
    grid: np.ndarray,
) -> np.ndarray:
    """Expected information gain for each candidate cell — fully vectorised.

    For each candidate point c, p_detect is the total posterior mass inside
    the detection footprint centred on c.  The expected entropy reduction from
    visiting c is approximated by the binary entropy H(p_detect):

        H(p) = -p·log(p) - (1-p)·log(1-p)

    This peaks at p=0.5 (maximum uncertainty — most to learn) and falls
    toward zero at p≈0 (already ruled out) and p≈1 (already obvious).

    The result drives drones toward the *exploration frontier*: the boundary
    between well-swept and unsearched regions, rather than straight to the
    posterior peak as PMV does.

    Complexity: O(n²) memory for the pairwise distance matrix, but no Python
    loop — the entire computation is in numpy, which is typically 50-100x
    faster than the equivalent loop for partition sizes seen in practice.
    """
    pts = grid[candidate_indices]           # (n, 2)
    p_local = posterior[candidate_indices]  # (n,)

    # Pairwise distances between all candidate points: (n, n)
    diff  = pts[:, np.newaxis, :] - pts[np.newaxis, :, :]  # (n, n, 2)
    dists = np.hypot(diff[:, :, 0], diff[:, :, 1])         # (n, n)

    # in_window[i, j] = True if candidate j is within detection radius of i
    in_window = dists <= DETECTION_RADIUS                   # (n, n) bool

    # local_mass[i] = sum of posterior over all candidates in footprint of i
    local_mass = (p_local[np.newaxis, :] * in_window).sum(axis=1)  # (n,)

    # Binary entropy H(p) — vectorised, safe at boundaries
    p = np.clip(local_mass, EPS, 1.0 - EPS)
    return -p * np.log(p) - (1.0 - p) * np.log(1.0 - p)


# --------------------------------------------------------------------------
# Algorithm class
# --------------------------------------------------------------------------

class InfotaxisSearch(BaseSearchAlgorithm):
    """Infotaxis UAV swarm search.

    Identical to PMVSearchAlgorithm except waypoint scoring uses expected
    information gain (binary entropy of local detection probability) instead
    of raw posterior probability mass.

    Scoring comparison
    ------------------
    PMV:       score = probability_weight * overlap_weight * travel_weight
    Infotaxis: score = info_gain          * overlap_weight * travel_weight

    Where info_gain = H(p_detect) = binary entropy of the posterior mass
    inside the detection radius at each candidate cell.
    """

    algorithm_key  = "infotaxis"
    display_name   = "Infotaxis"
    description    = (
        "Expected information gain waypoint selection over a Bayesian posterior. "
        "Drives drones toward the uncertainty frontier rather than the probability peak."
    )
    display_order  = 60

    # ------------------------------------------------------------------
    # initialize — identical to PMVSearchAlgorithm
    # ------------------------------------------------------------------

    def initialize(self, mission) -> None:
        drones = _getm(mission, "drones", [])
        bounds = _getm(mission, "bounds", {})
        if not drones or not bounds:
            return

        dense_grid = _getm(mission, "_dense_coverage_grid")
        if dense_grid is None:
            dense_grid = build_dense_coverage_grid(bounds)
        else:
            dense_grid = np.asarray(dense_grid, dtype=float)

        k = len(drones)
        seeds = _partition_seeds(
            bounds,
            k,
            lloyd_iters=_SEED_LLOYD_ITERS,
            dense_grid=dense_grid,
        )
        labels = _voronoi_assign(dense_grid, seeds)
        drone_positions = np.array(
            [[float(d.get("lat", 0.0)), float(d.get("lon", 0.0))] for d in drones],
            dtype=float,
        )
        drone_to_seed = _match_drones_to_seeds(drone_positions, seeds)

        drone_cells: dict[str, np.ndarray] = {}
        for drone, seed_idx in zip(drones, drone_to_seed):
            drone_id = str(drone["id"])
            cell_indices = np.where(labels == seed_idx)[0]
            drone_cells[drone_id] = cell_indices

        profile = str(_getm(mission, "scenario_profile", "uniform_random") or "uniform_random")
        scenario_params = _getm(mission, "scenario_params", None)
        posterior = build_prior(bounds, dense_grid, profile, scenario_params)

        _setm(mission, "itx_grid",           dense_grid)
        _setm(mission, "itx_P",              posterior)
        _setm(mission, "itx_drone_cells",    drone_cells)
        _setm(mission, "itx_last_diffuse_t", int(_getm(mission, "elapsed_seconds", 0) or 0))
        _setm(mission, "itx_profile",        profile)

        logger.info(
            "infotaxis | initialized %d cells across %d drones for profile=%s",
            len(dense_grid), k, profile,
        )

    # ------------------------------------------------------------------
    # get_target_waypoints
    # ------------------------------------------------------------------

    def get_target_waypoints(
        self, mission, free_drones: List[dict]
    ) -> Dict[str, Tuple[float, float]]:
        if not free_drones:
            return {}

        if self._needs_initialize(mission, free_drones):
            self.initialize(mission)

        grid        = _getm(mission, "itx_grid")
        posterior   = _getm(mission, "itx_P")
        drone_cells = _getm(mission, "itx_drone_cells", {})
        if grid is None or posterior is None or not drone_cells:
            return {}

        grid      = np.asarray(grid,      dtype=float)
        posterior = np.asarray(posterior, dtype=float)
        posterior = self._update_posterior(mission, grid, posterior)

        # All cells with any remaining posterior mass — used as the
        # cross-partition candidate set for depleted drones.
        live_indices = np.where(posterior > EPS * 100)[0]

        waypoints: Dict[str, Tuple[float, float]] = {}
        planned_points: list[tuple[float, float]] = []

        for drone in free_drones:
            drone_id     = str(drone["id"])
            cell_indices = np.asarray(drone_cells.get(drone_id, []), dtype=int)
            if len(cell_indices) == 0:
                continue

            # If the drone's partition is depleted, roam the full live grid.
            # This prevents freezing and lets the drone contribute to wherever
            # the information frontier currently is — across partition boundaries.
            cell_mass = float(posterior[cell_indices].sum())
            if cell_mass <= EPS:
                candidate_indices = live_indices
            else:
                candidate_indices = cell_indices

            if len(candidate_indices) == 0:
                continue

            candidate_points = grid[candidate_indices]
            pos = np.array(
                [float(drone.get("lat", 0.0)), float(drone.get("lon", 0.0))],
                dtype=float,
            )

            travel_weight  = self._travel_weights(
                candidate_points, pos, _getm(mission, "bounds", {})
            )
            overlap_weight = self._overlap_weights(candidate_points, planned_points)
            info_gain      = _infotaxis_weights(posterior, candidate_indices, grid)

            scores = info_gain * overlap_weight * travel_weight

            # If overlap avoidance zeroes everything out, relax it.
            if float(scores.max(initial=0.0)) <= EPS:
                scores = info_gain * travel_weight

            best_idx   = int(np.argmax(scores))
            best_point = candidate_points[best_idx]
            waypoint   = (float(best_point[0]), float(best_point[1]))
            waypoints[drone["id"]] = waypoint
            planned_points.append(waypoint)

        _setm(mission, "itx_P", posterior)
        return waypoints


    def _needs_initialize(self, mission, free_drones: list[dict]) -> bool:
        if _getm(mission, "itx_P") is None or _getm(mission, "itx_grid") is None:
            return True
        drone_cells = _getm(mission, "itx_drone_cells", {})
        return any(str(d["id"]) not in drone_cells for d in free_drones)

    def _update_posterior(
        self,
        mission,
        grid: np.ndarray,
        posterior: np.ndarray,
    ) -> np.ndarray:
        updated = posterior.copy()
        scanned = _scanned_indices(grid, _getm(mission, "drones", []))
        if len(scanned) > 0:
            updated[scanned] *= (1.0 - DETECTION_PROB)
            updated = normalize_probability(updated)

        profile = str(
            _getm(mission, "itx_profile",
                  _getm(mission, "scenario_profile", "uniform_random"))
        )
        elapsed      = int(_getm(mission, "elapsed_seconds", 0) or 0)
        last_diffuse = int(_getm(mission, "itx_last_diffuse_t", elapsed) or 0)

        if profile in _MOVING_PROFILES and elapsed - last_diffuse >= DIFFUSE_INTERVAL_S:
            bounds  = _getm(mission, "bounds", {})
            sigma   = _moving_profile_sigma(profile, bounds)
            updated = _diffuse_probability(updated, grid, bounds, sigma)
            _setm(mission, "itx_last_diffuse_t", elapsed)

        return normalize_probability(updated)

    def _overlap_weights(
        self,
        candidate_points: np.ndarray,
        planned_points: list[tuple[float, float]],
    ) -> np.ndarray:
        if not planned_points:
            return np.ones(len(candidate_points), dtype=float)
        planned  = np.asarray(planned_points, dtype=float)
        distances = np.linalg.norm(candidate_points[:, np.newaxis] - planned, axis=2)
        sensor_overlap = (distances <= DETECTION_RADIUS).any(axis=1).astype(float)
        return 1.0 - sensor_overlap

    def _travel_weights(
        self,
        candidate_points: np.ndarray,
        drone_position: np.ndarray,
        bounds: dict,
    ) -> np.ndarray:
        travel_cost = np.linalg.norm(candidate_points - drone_position, axis=1)
        lat_span = float(bounds.get("max_lat", 0.0) - bounds.get("min_lat", 0.0))
        lon_span = float(bounds.get("max_lon", 0.0) - bounds.get("min_lon", 0.0))
        adaptive_lambda = max(LAMBDA_DEG, math.hypot(lat_span, lon_span) * 0.35)
        return TRAVEL_WEIGHT_FLOOR + (1.0 - TRAVEL_WEIGHT_FLOOR) * np.exp(
            -travel_cost / max(adaptive_lambda, EPS)
        )