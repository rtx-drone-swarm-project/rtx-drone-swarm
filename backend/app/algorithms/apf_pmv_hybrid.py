"""APF-PMV Hybrid search algorithm.

Phase 1 — APF (Artificial Potential Fields)
    Drones repel each other and the boundary walls, spreading explosively
    across the search area from the co-located launch point.  No memory,
    no partitioning — just fast broad coverage.  This phase dominates
    early time-to-first-detection.

Phase 2 — PMV (Probability-Map Voronoi)
    Once the APF phase ends, the posterior is initialised from the cells
    already scanned by APF (which are down-weighted via the Bayesian
    downdate), giving PMV a non-uniform starting map rather than a flat
    prior.  PMV then finishes the mission systematically.

Transition triggers (OR logic, with a mandatory time floor)
-----------------------------------------------------------
The switch fires when ALL of the following are true:

    elapsed >= APF_MIN_SECONDS          # floor: APF has had time to spread

AND at least ONE of:

    first_detection_occurred            # posterior now has real signal
    coverage_rate < COVERAGE_RATE_FLOOR # APF is retracing, not exploring
    elapsed >= APF_MAX_SECONDS          # hard ceiling regardless

Rationale
---------
* The floor prevents switching before the swarm has spread — PMV on a
  near-uniform posterior from 5 seconds of scanning is barely better
  than random.
* Coverage-rate drop is the theoretically cleanest trigger: it detects
  the moment APF's equilibrium is reached and new-area discovery stalls.
* First-detection triggers an early switch when evidence is available,
  since PMV's posterior exploitation is most valuable precisely when
  the map has a non-trivial peak to chase.
* The ceiling guarantees transition even on hard scenarios where APF
  never achieves a detection or a clean coverage-rate drop.
"""

from __future__ import annotations

import logging
import math
import random
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
# Transition thresholds
# --------------------------------------------------------------------------

# APF must run for at least this many seconds before any switch is allowed.
# Chosen to cover the initial spread phase (~2-3 drone equilibrium cycles).
APF_MIN_SECONDS = 90

# Hard ceiling: switch to PMV unconditionally after this many seconds.
APF_MAX_SECONDS = 180

# If new-cell discovery rate (fraction of total grid per second) drops below
# this, APF has hit equilibrium and is retracing ground.
COVERAGE_RATE_FLOOR = 0.0008  # ~0.08% of grid per second

# How many seconds between coverage-rate samples.
COVERAGE_RATE_WINDOW = 10

# --------------------------------------------------------------------------
# APF constants — copied from apf.py
# --------------------------------------------------------------------------
APF_REPULSION_DRONE = 0.0002
APF_REPULSION_WALL  = 0.0005
APF_STEP_SIZE       = 0.001

# --------------------------------------------------------------------------
# PMV constants — copied from pmv.py
# --------------------------------------------------------------------------
DETECTION_PROB                  = 0.9
DIFFUSE_INTERVAL_S              = 10
DIFFUSE_SIGMA_DEG               = DETECTION_RADIUS
DIFFUSE_SIGMA_FRACTION          = 0.04
DIFFUSE_SIGMA_FRACTION_CORRIDOR = 0.08
LAMBDA_DEG                      = 5 * DETECTION_RADIUS
TRAVEL_WEIGHT_FLOOR             = 0.18
GLOBAL_HOTSPOT_RATIO            = 1.15
GLOBAL_HOTSPOT_BOOST            = 1.35
GLOBAL_HOTSPOT_PEAK_FRACTION    = 0.65
EPS                             = 1e-12
_SEED_LLOYD_ITERS               = 8
_MOVING_PROFILES = {
    "corridor_route",
    "wandering_hikers",
    "moving_edge_escape",
    "diverging_group",
}


# --------------------------------------------------------------------------
# Mission dict helpers
# --------------------------------------------------------------------------

def _getm(mission, key: str, default=None):
    if isinstance(mission, dict):
        return mission.get(key, default)
    return getattr(mission, key, default)


def _setm(mission, key: str, value) -> None:
    if isinstance(mission, dict):
        mission[key] = value
    else:
        setattr(mission, key, value)


# --------------------------------------------------------------------------
# PMV pure helpers — copied verbatim from pmv.py
# --------------------------------------------------------------------------

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
    return np.apply_along_axis(
        lambda row: np.convolve(row, kernel, mode="valid"), axis, padded
    )


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

    lat_index = {v: i for i, v in enumerate(unique_lats.tolist())}
    lon_index = {v: i for i, v in enumerate(unique_lons.tolist())}
    lat_ids = np.array([lat_index[round(float(v), 12)] for v in grid[:, 0]], dtype=int)
    lon_ids = np.array([lon_index[round(float(v), 12)] for v in grid[:, 1]], dtype=int)

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
# Hybrid algorithm
# --------------------------------------------------------------------------

class APFPMVHybrid(BaseSearchAlgorithm):
    """APF explosive spread → PMV systematic posterior search.

    Phase 1 (APF): drones repel each other and the walls, spreading fast
    across the search area.  The posterior is updated silently in the
    background during this phase so that when the switch fires, PMV
    inherits a meaningful non-uniform map rather than a flat prior.

    Phase 2 (PMV): full PMV logic including Voronoi partitioning, global
    hotspot detection, adaptive travel weights, and diffusion for moving
    targets.

    The current phase is stored in ``mission["_hybrid_phase"]`` as either
    ``"apf"`` or ``"pmv"`` so external tools can inspect it.
    """

    algorithm_key  = "apf_pmv"
    display_name   = "APF → PMV Hybrid"
    description    = (
        "APF explosive spread for fast first detection, then PMV posterior "
        "search for systematic completion."
    )
    display_order  = 40

    # ------------------------------------------------------------------
    # initialize
    # ------------------------------------------------------------------

    def initialize(self, mission) -> None:
        """Set up APF phase state and silently build the PMV grid/posterior."""
        elapsed = int(_getm(mission, "elapsed_seconds", 0) or 0)

        _setm(mission, "_hybrid_phase",              "apf")
        _setm(mission, "_hybrid_apf_start_t",        elapsed)
        _setm(mission, "_hybrid_last_coverage_t",    elapsed)
        _setm(mission, "_hybrid_last_coverage_frac", 0.0)
        _setm(mission, "_hybrid_transition_logged",  False)

        # Build the PMV grid and posterior now so APF scans can down-weight
        # cells in the background.  The posterior starts from the scenario
        # prior (uniform for uniform_random) and is updated every tick even
        # while APF is flying, so it's non-trivial by the time PMV takes over.
        self._pmv_initialize(mission)

        logger.info("apf_pmv | initialized — starting APF phase")

    # ------------------------------------------------------------------
    # get_target_waypoints — phase dispatcher
    # ------------------------------------------------------------------

    def get_target_waypoints(
        self, mission, free_drones: List[dict]
    ) -> Dict[str, Tuple[float, float]]:
        if not free_drones:
            return {}

        # Re-initialize if state is missing (e.g. after a drone set change).
        if _getm(mission, "_hybrid_phase") is None:
            self.initialize(mission)

        # Always update the PMV posterior from this tick's scans, even during
        # APF phase — this is what gives PMV a warm start when it takes over.
        self._pmv_update_posterior_inplace(mission)

        # Check transition conditions.
        if _getm(mission, "_hybrid_phase") == "apf":
            if self._should_transition(mission, free_drones):
                self._transition_to_pmv(mission, free_drones)

        if _getm(mission, "_hybrid_phase") == "apf":
            return self._apf_waypoints(mission, free_drones)
        else:
            return self._pmv_waypoints(mission, free_drones)

    # ------------------------------------------------------------------
    # Transition logic
    # ------------------------------------------------------------------

    def _should_transition(self, mission, free_drones: list[dict]) -> bool:
        elapsed   = int(_getm(mission, "elapsed_seconds", 0) or 0)
        apf_start = int(_getm(mission, "_hybrid_apf_start_t", elapsed) or elapsed)
        apf_time  = elapsed - apf_start

        # Mandatory floor — never switch before APF has spread.
        if apf_time < APF_MIN_SECONDS:
            return False

        # Hard ceiling — always switch after max time.
        if apf_time >= APF_MAX_SECONDS:
            return True

        # First detection — any target confirmed or in confirmation.
        targets = _getm(mission, "targets", [])
        first_detection = any(
            t.get("status") in ("detected", "confirming", "found")
            for t in targets
        )
        if first_detection:
            return True

        # Coverage rate drop — APF has hit equilibrium and is retracing.
        if self._coverage_rate_low(mission):
            return True

        return False

    def _coverage_rate_low(self, mission) -> bool:
        """Return True if new-cell discovery rate has dropped below the floor."""
        elapsed      = int(_getm(mission, "elapsed_seconds", 0) or 0)
        last_t       = int(_getm(mission, "_hybrid_last_coverage_t",    elapsed) or elapsed)
        last_frac    = float(_getm(mission, "_hybrid_last_coverage_frac", 0.0) or 0.0)
        window       = elapsed - last_t

        if window < COVERAGE_RATE_WINDOW:
            return False

        grid      = _getm(mission, "pmv_grid")
        posterior = _getm(mission, "pmv_P")
        if grid is None or posterior is None:
            return False

        grid      = np.asarray(grid,      dtype=float)
        posterior = np.asarray(posterior, dtype=float)

        # Cells whose posterior has been down-weighted are "scanned".
        # We use 1/n as the uniform baseline — scanned cells fall well below it.
        n            = len(posterior)
        uniform_val  = 1.0 / max(n, 1)
        scanned_frac = float((posterior < uniform_val * 0.5).sum()) / max(n, 1)

        rate = (scanned_frac - last_frac) / max(window, 1)

        # Update sample for next call.
        _setm(mission, "_hybrid_last_coverage_t",    elapsed)
        _setm(mission, "_hybrid_last_coverage_frac", scanned_frac)

        return rate < COVERAGE_RATE_FLOOR

    def _transition_to_pmv(self, mission, free_drones: list[dict]) -> None:
        """Flip phase flag and (re)assign Voronoi partitions from current positions."""
        elapsed = int(_getm(mission, "elapsed_seconds", 0) or 0)
        _setm(mission, "_hybrid_phase", "pmv")

        # Re-run partition assignment using current drone positions so that
        # each drone gets the zone closest to where it already is, minimising
        # the initial transit after the handoff.
        self._pmv_repartition(mission, free_drones)

        if not _getm(mission, "_hybrid_transition_logged", False):
            logger.info(
                "apf_pmv | transition to PMV at t=%ds — phase 2 starting",
                elapsed,
            )
            _setm(mission, "_hybrid_transition_logged", True)

    # ------------------------------------------------------------------
    # APF phase
    # ------------------------------------------------------------------

    def _apf_waypoints(
        self, mission, free_drones: List[dict]
    ) -> Dict[str, Tuple[float, float]]:
        """Identical to PotentialFieldsCoverage.get_target_waypoints."""
        waypoint_map: Dict[str, Tuple[float, float]] = {}
        bounds = _getm(mission, "bounds", {})
        rng    = _getm(mission, "_rng", None) or random

        for i, drone in enumerate(free_drones):
            dlat = float(drone.get("lat", 0.0))
            dlon = float(drone.get("lon", 0.0))

            force_lat = 0.0
            force_lon = 0.0

            # 1. Drone-drone repulsion.
            for j, other in enumerate(free_drones):
                if i == j:
                    continue
                olat = float(other.get("lat", 0.0))
                olon = float(other.get("lon", 0.0))
                dist = math.hypot(dlat - olat, dlon - olon)
                if 0.0001 < dist < 0.02:
                    mag = APF_REPULSION_DRONE / (dist ** 2)
                    force_lat += mag * (dlat - olat) / dist
                    force_lon += mag * (dlon - olon) / dist

            # 2. Wall repulsion.
            dist_north = max(0.0001, bounds["max_lat"] - dlat)
            dist_south = max(0.0001, dlat - bounds["min_lat"])
            dist_east  = max(0.0001, bounds["max_lon"] - dlon)
            dist_west  = max(0.0001, dlon - bounds["min_lon"])

            force_lat -= APF_REPULSION_WALL / (dist_north ** 2)
            force_lat += APF_REPULSION_WALL / (dist_south ** 2)
            force_lon -= APF_REPULSION_WALL / (dist_east  ** 2)
            force_lon += APF_REPULSION_WALL / (dist_west  ** 2)

            # 3. Random jitter to break symmetry.
            force_lat += rng.uniform(-0.0001, 0.0001)
            force_lon += rng.uniform(-0.0001, 0.0001)

            # 4. Normalise and step.
            force_mag = math.hypot(force_lat, force_lon)
            if force_mag > 0:
                step_lat = (force_lat / force_mag) * APF_STEP_SIZE
                step_lon = (force_lon / force_mag) * APF_STEP_SIZE
            else:
                step_lat = step_lon = 0.0

            target_lat = max(bounds["min_lat"], min(bounds["max_lat"], dlat + step_lat))
            target_lon = max(bounds["min_lon"], min(bounds["max_lon"], dlon + step_lon))

            waypoint_map[drone["id"]] = (float(target_lat), float(target_lon))

        return waypoint_map

    # ------------------------------------------------------------------
    # PMV phase — thin wrappers around the PMV helpers below
    # ------------------------------------------------------------------

    def _pmv_waypoints(
        self, mission, free_drones: List[dict]
    ) -> Dict[str, Tuple[float, float]]:
        """Full PMV get_target_waypoints logic, operating on pmv_ state keys."""
        # Re-partition if a drone reappears after confirming a target.
        drone_cells = _getm(mission, "pmv_drone_cells", {})
        if any(str(d["id"]) not in drone_cells for d in free_drones):
            self._pmv_repartition(mission, free_drones)

        grid      = _getm(mission, "pmv_grid")
        posterior = _getm(mission, "pmv_P")
        drone_cells = _getm(mission, "pmv_drone_cells", {})
        centroids   = _getm(mission, "pmv_cell_centroids", {})
        if grid is None or posterior is None or not drone_cells:
            return {}

        grid      = np.asarray(grid,      dtype=float)
        posterior = np.asarray(posterior, dtype=float)

        global_hot_indices = self._global_hot_indices(posterior, len(free_drones))

        waypoints: Dict[str, Tuple[float, float]] = {}
        planned_points: list[tuple[float, float]] = []

        for drone in free_drones:
            drone_id     = str(drone["id"])
            cell_indices = np.asarray(drone_cells.get(drone_id, []), dtype=int)
            if len(cell_indices) == 0:
                continue

            cell_mass = float(posterior[cell_indices].sum())
            candidate_indices = self._candidate_indices(
                posterior, cell_indices, global_hot_indices
            )
            if len(candidate_indices) == 0:
                continue

            if cell_mass <= EPS and len(global_hot_indices) == 0:
                centroid = centroids.get(drone_id)
                if centroid is not None:
                    waypoints[drone["id"]] = (float(centroid[0]), float(centroid[1]))
                    planned_points.append((float(centroid[0]), float(centroid[1])))
                continue

            candidate_points = grid[candidate_indices]
            pos = np.array(
                [float(drone.get("lat", 0.0)), float(drone.get("lon", 0.0))],
                dtype=float,
            )
            travel_weight    = self._travel_weights(
                candidate_points, pos, _getm(mission, "bounds", {})
            )
            overlap_weight   = self._overlap_weights(candidate_points, planned_points)
            in_home_cell     = np.isin(candidate_indices, cell_indices)
            assist_boost     = np.where(in_home_cell, 1.0, GLOBAL_HOTSPOT_BOOST)
            probability_weight = (
                posterior[candidate_indices]
                / max(float(posterior.max(initial=0.0)), EPS)
            )

            scores = probability_weight * overlap_weight * travel_weight * assist_boost
            if float(scores.max(initial=0.0)) <= EPS:
                scores = probability_weight * travel_weight * assist_boost

            best_idx   = int(np.argmax(scores))
            best_point = candidate_points[best_idx]
            waypoint   = (float(best_point[0]), float(best_point[1]))
            waypoints[drone["id"]] = waypoint
            planned_points.append(waypoint)

        _setm(mission, "pmv_P", posterior)
        return waypoints

    # ------------------------------------------------------------------
    # PMV initialisation / repartition helpers
    # ------------------------------------------------------------------

    def _pmv_initialize(self, mission) -> None:
        """Build the PMV grid and prior — called once at mission start."""
        drones = _getm(mission, "drones", [])
        bounds = _getm(mission, "bounds", {})
        if not bounds:
            return

        dense_grid = _getm(mission, "_dense_coverage_grid")
        if dense_grid is None:
            dense_grid = build_dense_coverage_grid(bounds)
        else:
            dense_grid = np.asarray(dense_grid, dtype=float)

        profile         = str(_getm(mission, "scenario_profile", "uniform_random") or "uniform_random")
        scenario_params = _getm(mission, "scenario_params", None)
        posterior       = build_prior(bounds, dense_grid, profile, scenario_params)

        _setm(mission, "pmv_grid",           dense_grid)
        _setm(mission, "pmv_P",              posterior)
        _setm(mission, "pmv_profile",        profile)
        _setm(mission, "pmv_last_diffuse_t", int(_getm(mission, "elapsed_seconds", 0) or 0))

        # Partition using current drone positions if available; empty dicts
        # are fine here — _pmv_repartition fills them at transition time.
        if drones:
            self._pmv_repartition(mission, drones)
        else:
            _setm(mission, "pmv_drone_cells",    {})
            _setm(mission, "pmv_cell_centroids", {})

    def _pmv_repartition(self, mission, drones: list[dict]) -> None:
        """Assign Voronoi partitions from current drone positions."""
        bounds     = _getm(mission, "bounds", {})
        dense_grid = _getm(mission, "pmv_grid")
        if not bounds or dense_grid is None:
            return

        dense_grid = np.asarray(dense_grid, dtype=float)
        k          = len(drones)
        if k == 0:
            return

        seeds = _partition_seeds(
            bounds, k,
            lloyd_iters=_SEED_LLOYD_ITERS,
            dense_grid=dense_grid,
        )
        labels = _voronoi_assign(dense_grid, seeds)

        drone_positions = np.array(
            [[float(d.get("lat", 0.0)), float(d.get("lon", 0.0))] for d in drones],
            dtype=float,
        )
        drone_to_seed = _match_drones_to_seeds(drone_positions, seeds)

        drone_cells:    dict[str, np.ndarray]          = {}
        drone_centroids: dict[str, tuple[float, float]] = {}
        for drone, seed_idx in zip(drones, drone_to_seed):
            drone_id     = str(drone["id"])
            cell_indices = np.where(labels == seed_idx)[0]
            drone_cells[drone_id] = cell_indices
            if len(cell_indices) > 0:
                centroid = dense_grid[cell_indices].mean(axis=0)
            else:
                centroid = seeds[seed_idx]
            drone_centroids[drone_id] = (float(centroid[0]), float(centroid[1]))

        _setm(mission, "pmv_drone_cells",    drone_cells)
        _setm(mission, "pmv_cell_centroids", drone_centroids)

    def _pmv_update_posterior_inplace(self, mission) -> None:
        """Bayesian downdate + diffusion — updates pmv_P in the mission dict.

        Called every tick regardless of phase so the posterior is warm when
        PMV takes over.
        """
        grid      = _getm(mission, "pmv_grid")
        posterior = _getm(mission, "pmv_P")
        if grid is None or posterior is None:
            return

        grid      = np.asarray(grid,      dtype=float)
        posterior = np.asarray(posterior, dtype=float).copy()

        scanned = _scanned_indices(grid, _getm(mission, "drones", []))
        if len(scanned) > 0:
            posterior[scanned] *= (1.0 - DETECTION_PROB)
            posterior = normalize_probability(posterior)

        profile      = str(_getm(mission, "pmv_profile",
                                 _getm(mission, "scenario_profile", "uniform_random")))
        elapsed      = int(_getm(mission, "elapsed_seconds", 0) or 0)
        last_diffuse = int(_getm(mission, "pmv_last_diffuse_t", elapsed) or elapsed)

        if profile in _MOVING_PROFILES and elapsed - last_diffuse >= DIFFUSE_INTERVAL_S:
            bounds   = _getm(mission, "bounds", {})
            sigma    = _moving_profile_sigma(profile, bounds)
            posterior = _diffuse_probability(posterior, grid, bounds, sigma)
            _setm(mission, "pmv_last_diffuse_t", elapsed)

        _setm(mission, "pmv_P", normalize_probability(posterior))

    # ------------------------------------------------------------------
    # PMV scoring helpers — identical to PMVSearchAlgorithm
    # ------------------------------------------------------------------

    def _overlap_weights(
        self,
        candidate_points: np.ndarray,
        planned_points: list[tuple[float, float]],
    ) -> np.ndarray:
        if not planned_points:
            return np.ones(len(candidate_points), dtype=float)
        planned   = np.asarray(planned_points, dtype=float)
        distances = np.linalg.norm(candidate_points[:, np.newaxis] - planned, axis=2)
        return 1.0 - (distances <= DETECTION_RADIUS).any(axis=1).astype(float)

    def _global_hot_indices(
        self, posterior: np.ndarray, free_drone_count: int
    ) -> np.ndarray:
        if len(posterior) == 0:
            return np.array([], dtype=int)
        peak   = float(posterior.max(initial=0.0))
        median = float(np.median(posterior))
        if peak <= EPS or peak <= median * GLOBAL_HOTSPOT_RATIO:
            return np.array([], dtype=int)
        percentile_threshold = float(np.percentile(posterior, 90))
        threshold   = max(peak * GLOBAL_HOTSPOT_PEAK_FRACTION, percentile_threshold)
        hot_indices = np.where(posterior >= threshold)[0]
        min_count   = min(len(posterior), max(free_drone_count * 6, 12))
        if len(hot_indices) < min_count:
            hot_indices = np.argpartition(posterior, -min_count)[-min_count:]
        return np.asarray(sorted(set(int(i) for i in hot_indices)), dtype=int)

    def _candidate_indices(
        self,
        posterior: np.ndarray,
        cell_indices: np.ndarray,
        global_hot_indices: np.ndarray,
    ) -> np.ndarray:
        if len(global_hot_indices) == 0:
            return cell_indices
        local_peak  = float(posterior[cell_indices].max(initial=0.0)) if len(cell_indices) else 0.0
        global_peak = float(posterior[global_hot_indices].max(initial=0.0))
        if local_peak > EPS and global_peak < local_peak * GLOBAL_HOTSPOT_RATIO:
            return cell_indices
        combined = np.concatenate([cell_indices, global_hot_indices])
        return np.asarray(sorted(set(int(i) for i in combined)), dtype=int)

    def _travel_weights(
        self,
        candidate_points: np.ndarray,
        drone_position: np.ndarray,
        bounds: dict,
    ) -> np.ndarray:
        travel_cost     = np.linalg.norm(candidate_points - drone_position, axis=1)
        lat_span        = float(bounds.get("max_lat", 0.0) - bounds.get("min_lat", 0.0))
        lon_span        = float(bounds.get("max_lon", 0.0) - bounds.get("min_lon", 0.0))
        adaptive_lambda = max(LAMBDA_DEG, math.hypot(lat_span, lon_span) * 0.35)
        return TRAVEL_WEIGHT_FLOOR + (1.0 - TRAVEL_WEIGHT_FLOOR) * np.exp(
            -travel_cost / max(adaptive_lambda, EPS)
        )