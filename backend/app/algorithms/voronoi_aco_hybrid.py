import logging
import math
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np
from app.algorithms.stigmergy_engine import GridConfig, InMemoryPheromoneGrid

log = logging.getLogger(__name__)

# NOTE: BOOTSTRAP_SPREAD_DEG and BOOTSTRAP_TIMEOUT_TICKS have been removed.
# These constants were dead — vaco.py never imported them and defines its own
# authoritative values as class-level attributes on VoronoiACOHybridCoverage.

class PlannerPhase(Enum):
    LLOYD = "lloyd"
    ACO = "aco"

@dataclass
class PlannerConfig:
    """Consolidates geometry and mission settings."""
    detection_radius_m: float = 30.0
    # coverage_threshold removed: the authoritative value is
    # VoronoiACOHybridCoverage.REPARTITION_COVERAGE_THRESHOLD = 0.75 in vaco.py.
    # Keeping it here at a different value (0.85) was a source of confusion.
    row_band_deg: float = field(init=False)
    min_wp_dist_deg: float = field(init=False)

    def __post_init__(self):
        # 1m ≈ 0.00001 degrees.
        # FIX: Row spacing reduced from 1.8× to 1.2× radius to guarantee
        # overlap between adjacent sweep rows and eliminate missed strips.
        # At 30m radius: 0.00036° ≈ 36m spacing (6m overlap per side).
        self.row_band_deg = (self.detection_radius_m * 1.2) * 0.00001

        # FIX: min waypoint distance reduced from 0.8× to 0.5× radius so
        # the thinning step keeps enough points to cover the territory densely.
        self.min_wp_dist_deg = (self.detection_radius_m * 0.5) * 0.00001


@dataclass
class DroneState:
    id: str
    lat: float
    lon: float
    territory: Optional[np.ndarray] = None


class NavigationController:
    """
    Handles high-efficiency boustrophedon sweeps aligned to
    the territory's longest axis to minimize battery-draining turns.
    """
    WAYPOINT_THRESHOLD_M = 12.0
    SPEED_MS = 8.0
    TIMEOUT_FACTOR = 1.5
    TIMEOUT_MIN_S = 15.0
    TIMEOUT_MAX_S = 90.0

    def __init__(self, drone_id: str, pcfg: PlannerConfig, territory: np.ndarray):
        self.drone_id = drone_id
        self.cfg = pcfg
        self._territory_hash = 0
        self._sweep_index = 0
        self._current_waypoint = None
        self._wp_set_time = 0.0
        self.set_territory(territory)

    def set_territory(self, territory: np.ndarray):
        new_hash = hash(territory.tobytes())
        if new_hash == self._territory_hash:
            return

        self._territory_hash = new_hash
        self._sweep_order = self._compute_rotated_sweep(territory)
        self._sweep_index = 0
        self._current_waypoint = None

    def _compute_rotated_sweep(self, territory: np.ndarray) -> np.ndarray:
        """Finds the longest axis via PCA and aligns sweep rows to it."""
        if len(territory) < 3:
            return territory

        # 1. PCA for Longest Axis
        centered = territory - np.mean(territory, axis=0)
        cov = np.cov(centered.T)
        _, eigenvectors = np.linalg.eigh(cov)
        angle = math.atan2(eigenvectors[1, 1], eigenvectors[0, 1])

        # 2. Rotation Matrix
        cos_a, sin_a = math.cos(-angle), math.sin(-angle)
        rot = np.array([[cos_a, -sin_a], [sin_a, cos_a]])
        inv_rot = np.array([[cos_a, sin_a], [-sin_a, cos_a]])

        # 3. Aligned Boustrophedon
        rotated_pts = territory @ rot.T
        lat_min = rotated_pts[:, 0].min()
        row_idx = ((rotated_pts[:, 0] - lat_min) / self.cfg.row_band_deg).astype(int)

        ordered = []
        for r in sorted(set(row_idx)):
            row_pts = rotated_pts[row_idx == r]
            row_pts = row_pts[np.argsort(row_pts[:, 1])]
            if r % 2 == 1:
                row_pts = row_pts[::-1]
            ordered.append(row_pts)

        # 4. Thin and Rotate Back
        all_pts = np.vstack(ordered) @ inv_rot.T
        thinned = [all_pts[0]]
        for pt in all_pts[1:]:
            if np.linalg.norm(pt - thinned[-1]) >= self.cfg.min_wp_dist_deg:
                thinned.append(pt)

        return np.array(thinned)

    def get_waypoint(self, current_lat: float, current_lon: float, mission_time_s: float) -> Tuple[float, float]:
        if self._current_waypoint is not None:
            dist = self._haversine_m(current_lat, current_lon, *self._current_waypoint)
            elapsed = mission_time_s - self._wp_set_time
            timeout = min(max(dist / self.SPEED_MS * self.TIMEOUT_FACTOR, self.TIMEOUT_MIN_S), self.TIMEOUT_MAX_S)

            if dist > self.WAYPOINT_THRESHOLD_M and elapsed < timeout:
                return self._current_waypoint

        # Advance sweep
        wp = self._sweep_order[self._sweep_index % len(self._sweep_order)]
        self._sweep_index += 1
        self._current_waypoint = (float(wp[0]), float(wp[1]))
        self._wp_set_time = mission_time_s
        return self._current_waypoint

    @staticmethod
    def _haversine_m(lat1, lon1, lat2, lon2):
        R = 6371000
        dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
        a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class VoronoiACOPlanner:
    """Manages the Lloyd partitioning and swarm state."""
    def __init__(self, **kwargs):
        self.bounds = kwargs.get("bounds")
        self.pcfg = kwargs.get("planner_config")
        self._repart_lock = threading.Lock()
        self._repart_pending = False
        self.phase = PlannerPhase.LLOYD

        # FIX: Grid resolution increased. grid_n is derived from search area
        # in vaco.py._compute_scale_params. Falls back to 100 (was 50) so each
        # drone gets ~667 cells (was ~167) at 15 drones — 4× denser coverage map.
        phero_n = kwargs.get("grid_n", 100)
        cfg = GridConfig(
            lat_min=self.bounds["min_lat"],
            lat_max=self.bounds["max_lat"],
            lon_min=self.bounds["min_lon"],
            lon_max=self.bounds["max_lon"],
            rows=phero_n,
            cols=phero_n,
        )
        self.pheromone_grid = InMemoryPheromoneGrid(cfg)

    def transition_to_aco(self):
        self.phase = PlannerPhase.ACO

    def _territory_coverage(self, drone: DroneState) -> float:
        """
        Returns % of territory points that have pheromone deposits.
        Uses the PheromoneGrid associated with the planner.
        """
        if drone.territory is None or len(drone.territory) == 0:
            return 1.0  # Empty is technically 'done'

        visited = 0
        for pt in drone.territory:
            if self.pheromone_grid.get_value(pt[0], pt[1]) > 0.01:
                visited += 1

        return visited / len(drone.territory)

    def _run_lloyd(self, states: List[DroneState], grid_n: int = 100):
        """
        Executes the spatial partitioning.
        Updates each DroneState.territory in-place.

        grid_n controls the resolution of the discrete search grid. It is
        computed in vaco.py._compute_scale_params so that each drone always
        receives ~240 cells regardless of area size or swarm count.

        FIX: Default raised from 60 → 100 to match the higher pheromone grid
        resolution and give each drone a denser territory (~667 cells at k=15).
        """
        k = len(states)
        lats = np.linspace(self.bounds["min_lat"], self.bounds["max_lat"], grid_n)
        lons = np.linspace(self.bounds["min_lon"], self.bounds["max_lon"], grid_n)
        ll, lo = np.meshgrid(lats, lons)
        grid_points = np.column_stack([ll.ravel(), lo.ravel()])

        # Get current drone positions as initial centroids
        centroids = np.array([[s.lat, s.lon] for s in states])

        # Perform balanced assignment
        assignment, counts = _balanced_lloyd_assignment(centroids, grid_points, k)

        # Commit territories back to drone objects
        for i, state in enumerate(states):
            mask = (assignment == i)
            if mask.sum() > 0:
                state.territory = grid_points[mask]
            else:
                log.warning(f"Drone {state.id} received 0 Voronoi cells!")


def _jitter_collinear_centroids(
    drones: List[dict], bounds: dict, inset: float = 0.002
) -> List[Tuple[float, float]]:
    """
    If drones are too close or on a line, spread them into a grid
    so Lloyd doesn't collapse on the first tick.

    inset is expressed in degrees and is derived from the actual search area
    in vaco.py._compute_scale_params (5% of the larger span). The default
    0.002° (~222m) is preserved for callers that don't pass a scale.
    """
    k = len(drones)
    cols = math.ceil(math.sqrt(k))
    rows = math.ceil(k / cols)

    lat_span = bounds["max_lat"] - bounds["min_lat"]
    lon_span = bounds["max_lon"] - bounds["min_lon"]
    safe_inset_lat = min(inset, lat_span * 0.20)
    safe_inset_lon = min(inset, lon_span * 0.20)

    lat_space = np.linspace(bounds["min_lat"] + safe_inset_lat, bounds["max_lat"] - safe_inset_lat, rows)
    lon_space = np.linspace(bounds["min_lon"] + safe_inset_lon, bounds["max_lon"] - safe_inset_lon, cols)

    grid = []
    for r in lat_space:
        for c in lon_space:
            if len(grid) < k:
                grid.append((float(r), float(c)))
    return grid


def _balanced_lloyd_assignment(centroids: np.ndarray, grid_points: np.ndarray, k: int, n_iter: int = 20):
    """
    Size-constrained Voronoi assignment with proper Lloyd iteration.
    Ensures each drone gets ~ (Total Cells / K) points.
    """
    n_points = len(grid_points)
    ideal_count = n_points // k

    gp_min = grid_points.min(axis=0)
    gp_max = grid_points.max(axis=0)
    gp_range = np.where(gp_max - gp_min > 0, gp_max - gp_min, 1.0)
    gp_norm = (grid_points - gp_min) / gp_range
    c_norm  = (centroids  - gp_min) / gp_range

    pair_dists = np.linalg.norm(c_norm[:, np.newaxis] - c_norm[np.newaxis, :], axis=2)
    np.fill_diagonal(pair_dists, np.inf)
    median_sep = float(np.median(pair_dists.min(axis=1)))
    weight_scale = max(median_sep * 0.15, 1e-4)

    weights = np.zeros(k)
    current_centroids = c_norm.copy()

    for _ in range(n_iter):
        dists = np.linalg.norm(gp_norm[:, np.newaxis] - current_centroids, axis=2)
        assignment = np.argmin(dists + weights, axis=1)
        counts = np.bincount(assignment, minlength=k)

        for i in range(k):
            mask = assignment == i
            if mask.sum() > 0:
                current_centroids[i] = gp_norm[mask].mean(axis=0)

        imbalance = (counts - ideal_count) / max(ideal_count, 1)
        weights += weight_scale * imbalance

    dists = np.linalg.norm(gp_norm[:, np.newaxis] - current_centroids, axis=2)
    assignment = np.argmin(dists + weights, axis=1)
    counts = np.bincount(assignment, minlength=k)

    return assignment, counts