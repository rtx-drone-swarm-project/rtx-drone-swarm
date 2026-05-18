import logging
import math
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np
from app.algorithms.stigmergy_engine import GridConfig, InMemoryPheromoneGrid

log = logging.getLogger(__name__)

# Constants
BOOTSTRAP_SPREAD_DEG = 0.0001
BOOTSTRAP_TIMEOUT_TICKS = 15

class PlannerPhase(Enum):
    LLOYD = "lloyd"
    ACO = "aco"

@dataclass
class PlannerConfig:
    """Consolidates geometry and mission settings."""
    detection_radius_m: float = 30.0
    coverage_threshold: float = 0.85
    row_band_deg: float = field(init=False)
    min_wp_dist_deg: float = field(init=False)

    def __post_init__(self):
        # 1m approx 0.00001 degrees. 
        # Set row spacing to 1.8x radius to ensure slight overlap.
        self.row_band_deg = (self.detection_radius_m * 1.8) * 0.00001
        self.min_wp_dist_deg = (self.detection_radius_m * 0.8) * 0.00001

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
            timeout = min(max(dist/self.SPEED_MS * self.TIMEOUT_FACTOR, self.TIMEOUT_MIN_S), self.TIMEOUT_MAX_S)
            
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
        dlat, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

class VoronoiACOPlanner:
    """Manages the Lloyd partitioning and swarm state."""
    def __init__(self, **kwargs):
        self.bounds = kwargs.get("bounds")
        self.pcfg = kwargs.get("planner_config")
        self._repart_lock = threading.Lock()
        self._repart_pending = False
        self.phase = PlannerPhase.LLOYD
        cfg = GridConfig(
            lat_min=self.bounds["min_lat"],
            lat_max=self.bounds["max_lat"],
            lon_min=self.bounds["min_lon"],
            lon_max=self.bounds["max_lon"],
            rows=50,
            cols=50,
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
            return 1.0 # Empty is technically 'done'
            
        visited = 0
        for pt in drone.territory:
            # Check if pheromone exists at this GPS coordinate
            if self.pheromone_grid.get_value(pt[0], pt[1]) > 0.01:
                visited += 1
                
        return visited / len(drone.territory)

    def _run_lloyd(self, states: List[DroneState]):
        """
        Executes the spatial partitioning. 
        Updates each DroneState.territory in-place.
        """
        k = len(states)
        # 1. Generate the discrete grid points for the search area
        # Using n_grid=60 as established in vaco.py
        lats = np.linspace(self.bounds["min_lat"], self.bounds["max_lat"], 60)
        lons = np.linspace(self.bounds["min_lon"], self.bounds["max_lon"], 60)
        ll, lo = np.meshgrid(lats, lons)
        grid_points = np.column_stack([ll.ravel(), lo.ravel()])

        # 2. Get current drone positions as initial centroids
        centroids = np.array([[s.lat, s.lon] for s in states])

        # 3. Perform balanced assignment
        assignment, counts = _balanced_lloyd_assignment(centroids, grid_points, k)

        # 4. Commit territories back to drone objects
        for i, state in enumerate(states):
            mask = (assignment == i)
            if mask.sum() > 0:
                state.territory = grid_points[mask]
            else:
                log.warning(f"Drone {state.id} received 0 Voronoi cells!")

def _jitter_collinear_centroids(drones: List[dict], bounds: dict) -> List[Tuple[float, float]]:
    """
    If drones are too close or on a line, spread them into a grid
    so Lloyd doesn't collapse on the first tick.
    """
    k = len(drones)
    cols = math.ceil(math.sqrt(k))
    rows = math.ceil(k / cols)
    
    lat_space = np.linspace(bounds["min_lat"] + 0.0005, bounds["max_lat"] - 0.0005, rows)
    lon_space = np.linspace(bounds["min_lon"] + 0.0005, bounds["max_lon"] - 0.0005, cols)
    
    grid = []
    for r in lat_space:
        for c in lon_space:
            if len(grid) < k:
                grid.append((float(r), float(c)))
    return grid

def _balanced_lloyd_assignment(centroids: np.ndarray, grid_points: np.ndarray, k: int, n_iter: int = 10):
    """
    Size-constrained Voronoi assignment. 
    Ensures each drone gets ~ (Total Cells / K) points.
    """
    n_points = len(grid_points)
    ideal_count = n_points // k
    
    # Calculate distance matrix (Points x Centroids)
    dists = np.linalg.norm(grid_points[:, np.newaxis] - centroids, axis=2)
    
    # Weights for each centroid to 'push' or 'pull' points to balance counts
    weights = np.ones(k)
    
    for _ in range(n_iter):
        # Adjusted distances based on current balance weights
        adj_dists = dists + weights
        assignment = np.argmin(adj_dists, axis=1)
        
        # Update weights: if a drone has too many points, increase its weight 
        # (making it 'further away' effectively)
        counts = np.bincount(assignment, minlength=k)
        weights += 0.1 * (counts - ideal_count) / ideal_count
        
    return assignment, counts
