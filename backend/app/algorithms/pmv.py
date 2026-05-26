"""Probability-Map Voronoi (PMV) search.

PMV keeps the same fixed, balanced Voronoi partitioning style as ``sweep`` but
uses a Bayesian posterior over the dense coverage grid to choose each drone's
next information-gain waypoint.
"""

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

DETECTION_PROB = 0.9
DIFFUSE_INTERVAL_S = 10
# Baseline diffusion sigma (used as a floor at small bounds).
DIFFUSE_SIGMA_DEG = DETECTION_RADIUS
# At large bounds the fixed sigma is too small relative to how far a moving
# hiker travels per diffusion step, so PMV's posterior cannot keep up. Scale
# sigma with the bounds diagonal for moving profiles. corridor_route ramps into
# the stronger factor only as bounds grow; using it at 6 km over-diffuses the
# corridor prior and can erase the small-map full-success advantage.
DIFFUSE_SIGMA_FRACTION = 0.04
DIFFUSE_SIGMA_FRACTION_CORRIDOR = 0.08
CORRIDOR_SIGMA_RAMP_START_SPAN_DEG = 0.06
CORRIDOR_SIGMA_RAMP_FULL_SPAN_DEG = 0.108
LAMBDA_DEG = 5 * DETECTION_RADIUS
TRAVEL_WEIGHT_FLOOR = 0.18
GLOBAL_HOTSPOT_RATIO = 1.05
GLOBAL_HOTSPOT_BOOST = 1.35
GLOBAL_HOTSPOT_PEAK_FRACTION = 0.55
EPS = 1e-12
# Depletion thresholds: when a drone's cell mass drops below these
# fractions of the average cell mass, it progressively expands search.
DEPLETION_GLOBAL_THRESHOLD = 0.3
DEPLETION_BLEND_THRESHOLD = 0.7
# Travel-weight multiplier for exhausted drones so they can reach far cells.
EXHAUSTED_LAMBDA_MULTIPLIER = 3.0
_SEED_LLOYD_ITERS = 8
_MOVING_PROFILES = {
    "corridor_route",
    "wandering_hikers",
    "moving_edge_escape",
    "diverging_group",
}
DEFAULT_HEATMAP_ROWS = 20
DEFAULT_HEATMAP_COLS = 20


def _getm(mission, key: str, default=None):
    if isinstance(mission, dict):
        return mission.get(key, default)
    return getattr(mission, key, default)


def _setm(mission, key: str, value) -> None:
    if isinstance(mission, dict):
        mission[key] = value
    else:
        setattr(mission, key, value)


def build_pmv_heatmap_payload(
    mission,
    *,
    mission_id: str | None = None,
    rows: int = DEFAULT_HEATMAP_ROWS,
    cols: int = DEFAULT_HEATMAP_COLS,
) -> dict | None:
    """Return a bounded, coarse heatmap sampled from PMV posterior state."""
    bounds = _getm(mission, "bounds", {})
    grid = _getm(mission, "pmv_grid")
    posterior = _getm(mission, "pmv_P")
    if not bounds or grid is None or posterior is None or rows <= 0 or cols <= 0:
        return None

    min_lat = float(bounds["min_lat"])
    max_lat = float(bounds["max_lat"])
    min_lon = float(bounds["min_lon"])
    max_lon = float(bounds["max_lon"])
    lat_span = max(max_lat - min_lat, EPS)
    lon_span = max(max_lon - min_lon, EPS)

    grid_np = np.asarray(grid, dtype=float)
    posterior_np = normalize_probability(np.asarray(posterior, dtype=float))
    if len(grid_np) == 0 or len(grid_np) != len(posterior_np):
        return None

    heatmap = np.zeros((rows, cols), dtype=float)
    lat_bins = np.floor(((grid_np[:, 0] - min_lat) / lat_span) * rows).astype(int)
    lon_bins = np.floor(((grid_np[:, 1] - min_lon) / lon_span) * cols).astype(int)
    lat_bins = np.clip(lat_bins, 0, rows - 1)
    lon_bins = np.clip(lon_bins, 0, cols - 1)

    for row_idx, col_idx, value in zip(lat_bins, lon_bins, posterior_np):
        heatmap[int(row_idx), int(col_idx)] += float(value)

    values = [round(float(value), 12) for value in heatmap.reshape(rows * cols)]
    total_probability = float(sum(values))
    return {
        "type": "pmv_heatmap",
        "mission_id": mission_id or str(_getm(mission, "id", "")),
        "algorithm": "pmv",
        "rows": rows,
        "cols": cols,
        "bounds": {
            "min_lat": min_lat,
            "max_lat": max_lat,
            "min_lon": min_lon,
            "max_lon": max_lon,
        },
        "values": values,
        "max_value": round(max(values, default=0.0), 12),
        "total_probability": round(total_probability, 12),
    }


class PMVSearchAlgorithm(BaseSearchAlgorithm):
    """Bayesian probability map over fixed Voronoi partitions."""

    algorithm_key = "pmv"
    display_name = "PMV (Probability Map Voronoi)"
    description = "Bayesian probability map over Voronoi partitions with information-gain waypoints."
    display_order = 50

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
        drone_centroids: dict[str, tuple[float, float]] = {}
        for drone, seed_idx in zip(drones, drone_to_seed):
            drone_id = str(drone["id"])
            cell_indices = np.where(labels == seed_idx)[0]
            drone_cells[drone_id] = cell_indices
            if len(cell_indices) > 0:
                centroid = dense_grid[cell_indices].mean(axis=0)
            else:
                centroid = seeds[seed_idx]
            drone_centroids[drone_id] = (float(centroid[0]), float(centroid[1]))

        profile = str(_getm(mission, "scenario_profile", "uniform_random") or "uniform_random")
        scenario_params = _getm(mission, "scenario_params", None)
        # This is the Bayesian "belief map": one probability per dense-grid
        # point, shaped by profile-level SAR clues and normalized to sum to 1.
        posterior = build_prior(bounds, dense_grid, profile, scenario_params)

        _setm(mission, "pmv_grid", dense_grid)
        _setm(mission, "pmv_P", posterior)
        _setm(mission, "pmv_drone_cells", drone_cells)
        _setm(mission, "pmv_cell_centroids", drone_centroids)
        _setm(mission, "pmv_last_diffuse_t", int(_getm(mission, "elapsed_seconds", 0) or 0))
        _setm(mission, "pmv_profile", profile)

        logger.info(
            "pmv | initialized %d cells across %d drones for profile=%s",
            len(dense_grid),
            k,
            profile,
        )

    def get_target_waypoints(
        self, mission, free_drones: List[dict]
    ) -> Dict[str, Tuple[float, float]]:
        if not free_drones:
            return {}

        if self._needs_initialize(mission, free_drones):
            self.initialize(mission)

        grid = _getm(mission, "pmv_grid")
        posterior = _getm(mission, "pmv_P")
        drone_cells = _getm(mission, "pmv_drone_cells", {})
        centroids = _getm(mission, "pmv_cell_centroids", {})
        if grid is None or posterior is None or not drone_cells:
            return {}

        grid = np.asarray(grid, dtype=float)
        posterior = np.asarray(posterior, dtype=float)
        posterior = self._update_posterior(mission, grid, posterior)
        global_hot_indices = self._global_hot_indices(posterior, len(free_drones))

        waypoints: Dict[str, Tuple[float, float]] = {}
        planned_points: list[tuple[float, float]] = []

        # Pre-compute grid-wide average probability per cell for depletion
        # comparison.  A drone is "depleted" when its cells' average
        # probability density is well below the grid-wide average, meaning
        # those cells have been scanned and belief redistributed elsewhere.
        grid_avg_prob = float(posterior.mean()) if len(posterior) > 0 else 0.0

        for drone in free_drones:
            drone_id = str(drone["id"])
            cell_indices = np.asarray(drone_cells.get(drone_id, []), dtype=int)
            if len(cell_indices) == 0:
                continue

            cell_avg_prob = float(posterior[cell_indices].mean())
            depletion_ratio = cell_avg_prob / max(grid_avg_prob, EPS)

            # Exhaustion-aware candidate selection: as a drone's local
            # partition depletes, smoothly expand its search area from
            # local-only → blended → full grid.
            candidate_indices = self._candidate_indices(
                posterior,
                cell_indices,
                global_hot_indices,
                depletion_ratio,
            )
            if len(candidate_indices) == 0:
                continue

            candidate_points = grid[candidate_indices]
            pos = np.array([float(drone.get("lat", 0.0)), float(drone.get("lon", 0.0))])
            travel_weight = self._travel_weights(
                candidate_points, pos, _getm(mission, "bounds", {}),
                exhausted=(depletion_ratio < DEPLETION_GLOBAL_THRESHOLD),
            )
            overlap_weight = self._overlap_weights(candidate_points, planned_points)
            in_home_cell = np.isin(candidate_indices, cell_indices)
            assist_boost = np.where(in_home_cell, 1.0, GLOBAL_HOTSPOT_BOOST)
            probability_weight = posterior[candidate_indices] / max(float(posterior.max(initial=0.0)), EPS)
            # Information-gain score: partitions are the default, but a clearly
            # hotter global PMV region can pull nearby or under-used drones out
            # of their fixed cell. The travel floor prevents large maps from
            # making edge probability mathematically unreachable.
            scores = probability_weight * overlap_weight * travel_weight * assist_boost

            if float(scores.max(initial=0.0)) <= EPS:
                scores = probability_weight * travel_weight * assist_boost
            best_idx = int(np.argmax(scores))
            best_point = candidate_points[best_idx]
            waypoint = (float(best_point[0]), float(best_point[1]))
            waypoints[drone["id"]] = waypoint
            planned_points.append(waypoint)

        _setm(mission, "pmv_P", posterior)
        return waypoints

    def _needs_initialize(self, mission, free_drones: list[dict]) -> bool:
        if _getm(mission, "pmv_P") is None or _getm(mission, "pmv_grid") is None:
            return True
        drone_cells = _getm(mission, "pmv_drone_cells", {})
        return any(str(drone["id"]) not in drone_cells for drone in free_drones)

    def _update_posterior(
        self,
        mission,
        grid: np.ndarray,
        posterior: np.ndarray,
    ) -> np.ndarray:
        updated = posterior.copy()
        scanned = _scanned_indices(grid, _getm(mission, "drones", []))
        if len(scanned) > 0:
            # A scanned cell is not impossible, just much less likely after a
            # failed detection; renormalization redistributes belief elsewhere.
            updated[scanned] *= (1.0 - DETECTION_PROB)
            updated = normalize_probability(updated)

        profile = str(_getm(mission, "pmv_profile", _getm(mission, "scenario_profile", "uniform_random")))
        elapsed = int(_getm(mission, "elapsed_seconds", 0) or 0)
        last_diffuse = int(_getm(mission, "pmv_last_diffuse_t", elapsed) or 0)
        if profile in _MOVING_PROFILES and elapsed - last_diffuse >= DIFFUSE_INTERVAL_S:
            bounds = _getm(mission, "bounds", {})
            # Moving-target profiles use a simple random-walk transition model:
            # blur the posterior a little so probability can leak to neighbors.
            sigma = _moving_profile_sigma(profile, bounds)
            updated = _diffuse_probability(updated, grid, bounds, sigma)
            _setm(mission, "pmv_last_diffuse_t", elapsed)

        return normalize_probability(updated)

    def _overlap_weights(
        self,
        candidate_points: np.ndarray,
        planned_points: list[tuple[float, float]],
    ) -> np.ndarray:
        if not planned_points:
            return np.ones(len(candidate_points), dtype=float)
        planned = np.asarray(planned_points, dtype=float)
        distances = np.linalg.norm(candidate_points[:, np.newaxis] - planned, axis=2)
        sensor_overlap = (distances <= DETECTION_RADIUS).any(axis=1).astype(float)
        return 1.0 - sensor_overlap

    def _global_hot_indices(self, posterior: np.ndarray, free_drone_count: int) -> np.ndarray:
        if len(posterior) == 0:
            return np.array([], dtype=int)
        peak = float(posterior.max(initial=0.0))
        median = float(np.median(posterior))
        if peak <= EPS:
            return np.array([], dtype=int)

        # Always provide a minimum set of global candidates so that
        # exhausted drones have somewhere useful to go.  The old gate
        # (peak <= median * 1.15) blocked this when the posterior was
        # nearly uniform after heavy scanning, leaving drones stranded.
        min_count = min(len(posterior), max(free_drone_count * 8, 16))

        if peak <= median * GLOBAL_HOTSPOT_RATIO:
            # Posterior is nearly flat — return the top-N cells by value
            # so exhausted drones can still find the best remaining areas.
            hot_indices = np.argpartition(posterior, -min_count)[-min_count:]
            return np.asarray(sorted(set(int(idx) for idx in hot_indices)), dtype=int)

        percentile_threshold = float(np.percentile(posterior, 85))
        threshold = max(peak * GLOBAL_HOTSPOT_PEAK_FRACTION, percentile_threshold)
        hot_indices = np.where(posterior >= threshold)[0]

        if len(hot_indices) < min_count:
            hot_indices = np.argpartition(posterior, -min_count)[-min_count:]
        return np.asarray(sorted(set(int(idx) for idx in hot_indices)), dtype=int)

    def _candidate_indices(
        self,
        posterior: np.ndarray,
        cell_indices: np.ndarray,
        global_hot_indices: np.ndarray,
        depletion_ratio: float = 1.0,
    ) -> np.ndarray:
        # Fully depleted partition: search the entire grid.
        if depletion_ratio < DEPLETION_GLOBAL_THRESHOLD:
            # Drone's cell is nearly empty — give it the full grid so it
            # can assist any remaining hotspot anywhere in the search area.
            return np.arange(len(posterior))

        # Partially depleted: blend local cell with global hotspots.
        if depletion_ratio < DEPLETION_BLEND_THRESHOLD:
            if len(global_hot_indices) > 0:
                combined = np.concatenate([cell_indices, global_hot_indices])
                return np.asarray(sorted(set(int(idx) for idx in combined)), dtype=int)
            return cell_indices

        # Healthy partition: use original gating logic.
        if len(global_hot_indices) == 0:
            return cell_indices

        local_peak = float(posterior[cell_indices].max(initial=0.0)) if len(cell_indices) else 0.0
        global_peak = float(posterior[global_hot_indices].max(initial=0.0))
        if local_peak > EPS and global_peak < local_peak * GLOBAL_HOTSPOT_RATIO:
            return cell_indices

        combined = np.concatenate([cell_indices, global_hot_indices])
        return np.asarray(sorted(set(int(idx) for idx in combined)), dtype=int)

    def _travel_weights(
        self,
        candidate_points: np.ndarray,
        drone_position: np.ndarray,
        bounds: dict,
        *,
        exhausted: bool = False,
    ) -> np.ndarray:
        travel_cost = np.linalg.norm(candidate_points - drone_position, axis=1)
        lat_span = float(bounds.get("max_lat", 0.0) - bounds.get("min_lat", 0.0))
        lon_span = float(bounds.get("max_lon", 0.0) - bounds.get("min_lon", 0.0))
        adaptive_lambda = max(LAMBDA_DEG, math.hypot(lat_span, lon_span) * 0.35)
        # Exhausted drones get a much wider travel radius so they can
        # actually reach distant hotspots instead of being trapped by
        # the exponential distance penalty near their empty partition.
        if exhausted:
            adaptive_lambda *= EXHAUSTED_LAMBDA_MULTIPLIER
        return TRAVEL_WEIGHT_FLOOR + (1.0 - TRAVEL_WEIGHT_FLOOR) * np.exp(
            -travel_cost / max(adaptive_lambda, EPS)
        )


def _moving_profile_sigma(profile: str, bounds: dict[str, float]) -> float:
    """Bounds-aware diffusion sigma for moving-target profiles.

    Fixed sigma works at 6 km bounds but is too small at 10–12 km, where a
    hiker translates further per diffusion interval than the kernel can spread.
    Scaling with the bounds diagonal keeps PMV's transition model proportional
    to how far a target can plausibly move between updates.
    """
    lat_span = float(bounds.get("max_lat", 0.0) - bounds.get("min_lat", 0.0))
    lon_span = float(bounds.get("max_lon", 0.0) - bounds.get("min_lon", 0.0))
    diag = math.hypot(lat_span, lon_span)
    if profile != "corridor_route":
        return max(DIFFUSE_SIGMA_DEG, diag * DIFFUSE_SIGMA_FRACTION)

    max_span = max(lat_span, lon_span)
    if max_span <= CORRIDOR_SIGMA_RAMP_START_SPAN_DEG:
        return DIFFUSE_SIGMA_DEG

    ramp_width = CORRIDOR_SIGMA_RAMP_FULL_SPAN_DEG - CORRIDOR_SIGMA_RAMP_START_SPAN_DEG
    ramp = min(
        1.0,
        max(0.0, (max_span - CORRIDOR_SIGMA_RAMP_START_SPAN_DEG) / ramp_width),
    )
    fraction = DIFFUSE_SIGMA_FRACTION_CORRIDOR * ramp
    return max(DIFFUSE_SIGMA_DEG, diag * fraction)


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


def _diffuse_probability(
    posterior: np.ndarray,
    grid: np.ndarray,
    bounds: dict[str, float],
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
