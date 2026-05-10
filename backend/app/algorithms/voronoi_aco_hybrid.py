"""
voronoi_aco_hybrid.py
---------------------
Two-phase hybrid planner:
  Phase 1: LLOYD — Spatial partitioning (assigns territories)
  Phase 2: ACO   — Pheromone-based coverage navigation (within territories)

RECENT FIX (centroid lock):
  Removed centroid bias blending from get_waypoint(). Pure ACO with jitter
  produces natural lawn-mower patterns. The centroid bias was causing some
  drones to orbit territory centers instead of systematic coverage.
"""

import numpy as np
import random
import sys
import os
#sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

import logging
log = logging.getLogger(__name__)

from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from enum import Enum

from app.algorithms.stigmergy_engine import InMemoryPheromoneGrid, GridConfig
from app.voronoi import build_search_grid, lloyd_step


# ═══════════════════════════════════════════════════════════════════
# Data Classes & Enums
# ═══════════════════════════════════════════════════════════════════

class PlannerPhase(Enum):
    LLOYD = "lloyd"
    ACO   = "aco"


@dataclass
class DroneState:
    id: int
    lat: float
    lon: float
    territory: np.ndarray = field(default_factory=lambda: np.empty((0, 2)))

    def has_territory(self) -> bool:
        return self.territory is not None and len(self.territory) > 0

    def territory_centroid(self) -> Optional[Tuple[float, float]]:
        if not self.has_territory():
            return None
        mean = np.mean(self.territory, axis=0)
        return (float(mean[0]), float(mean[1]))


# ═══════════════════════════════════════════════════════════════════
# Lloyd Partitioner
# ═══════════════════════════════════════════════════════════════════

class LloydPartitioner:
    def __init__(self, grid_points: np.ndarray):
        self.grid_points = grid_points

    def partition(self, drones: List[DroneState]) -> None:
        if len(drones) == 0:
            return
        centroids = np.array([[d.lat, d.lon] for d in drones])
        new_centroids, labels = lloyd_step(self.grid_points, centroids)
        for i, drone in enumerate(drones):
            mask = labels == i
            drone.territory = self.grid_points[mask]
            if len(drone.territory) == 0:
                log.warning(f"[Lloyd] Drone {drone.id} got 0 cells — assigning nearest")
                dists = np.linalg.norm(
                    self.grid_points - np.array([drone.lat, drone.lon]), axis=1)
                drone.territory = self.grid_points[np.argsort(dists)[:5]]
        log.info(f"[Lloyd] Partitioned {len(self.grid_points)} cells across {len(drones)} drones")


# ═══════════════════════════════════════════════════════════════════
# ACO Navigator
# ═══════════════════════════════════════════════════════════════════

class ACONavigator:
    def __init__(
        self,
        pheromone_grid: InMemoryPheromoneGrid,
        aco_radius: int = 2,
        centroid_bias: float = 0.0,  # Now unused but kept for API compat
    ):
        self.pheromone    = pheromone_grid
        self.aco_radius   = aco_radius
        self.centroid_bias = centroid_bias  # Legacy param, ignored

    def get_waypoint(self, drone: DroneState) -> Tuple[float, float]:
        if not drone.has_territory():
            return self._pheromone_gradient_fallback(drone)

        valid_points = self._get_valid_territory_points(drone)
        if len(valid_points) == 0:
            idx = np.random.randint(len(drone.territory))
            return tuple(drone.territory[idx])

        # ACO: pick least-visited cell with jitter — NO centroid blending.
        # Pure ACO produces lawn-mower patterns naturally as drones avoid
        # visited cells. Centroid bias was causing lock-on behavior where
        # drones orbited territory centers instead of systematic coverage.
        aco_target = self._select_least_visited(valid_points)

        return (float(aco_target[0]), float(aco_target[1]))

    def _pheromone_gradient_fallback(self, drone: DroneState) -> Tuple[float, float]:
        return self.pheromone.get_gradient(drone.lat, drone.lon, radius=self.aco_radius)

    def _get_valid_territory_points(self, drone: DroneState) -> np.ndarray:
        """Return all territory points (they're already within territory by definition)."""
        # Original code re-checked each point with _point_in_territory which
        # had a 0.0005° distance threshold — redundant and occasionally wrong.
        # Territory points ARE territory by definition; just return them all.
        if not drone.has_territory():
            return np.empty((0, 2))
        return drone.territory

    def _select_least_visited(self, points: np.ndarray) -> np.ndarray:
        """
        Boustrophedon (lawnmower) sweep selector.
        
        Sorts territory cells into row-major order (north→south, 
        alternating left→right / right→left per row). Picks the 
        first unvisited cell in sweep order. This produces clean
        parallel sweeps instead of random jumps.
        
        Falls back to lowest-pheromone if all cells visited (for 
        repartition passes).
        """
        UNVISITED_THRESHOLD = 0.01   # pheromone below this = unvisited
        ROW_BAND_DEG = 0.0003        # ~33m row height — matches detection radius
        
        # Get pheromone for all points
        pher_vals = np.array([
            self.pheromone.get_value(p[0], p[1]) for p in points
        ])
        
        # Find unvisited cells
        unvisited_mask = pher_vals < UNVISITED_THRESHOLD
        unvisited = points[unvisited_mask]
        
        if len(unvisited) == 0:
            # All visited — pick global minimum for re-sweep
            chosen = points[np.argmin(pher_vals)].copy()
            return chosen + np.random.uniform(-0.00005, 0.00005, 2)
        
        # Assign row bands (quantize latitude into strips)
        lat_min = unvisited[:, 0].min()
        row_idx = ((unvisited[:, 0] - lat_min) / ROW_BAND_DEG).astype(int)
        
        # Sort: primary = row (north to south = descending lat),
        #       secondary = col alternating by row (boustrophedon)
        sorted_indices = []
        for row in sorted(set(row_idx)):
            mask = row_idx == row
            row_points = unvisited[mask]
            # Alternate direction per row
            reverse = (row % 2 == 1)
            order = np.argsort(row_points[:, 1])  # sort by longitude
            if reverse:
                order = order[::-1]
            sorted_indices.extend(np.where(mask)[0][order])
        
        if len(sorted_indices) == 0:
            chosen = points[np.argmin(pher_vals)].copy()
        else:
            chosen = unvisited[sorted_indices[0]].copy()
        
        # Small jitter (~5m) to prevent exact waypoint stacking
        return chosen + np.random.uniform(-0.00005, 0.00005, 2)

    def clamp_to_territory(self, drone: DroneState, lat: float, lon: float) -> Tuple[float, float]:
        if not drone.has_territory():
            return lat, lon
        target     = np.array([lat, lon])
        dists      = np.linalg.norm(drone.territory - target, axis=1)
        nearest_idx = np.argmin(dists)
        # Snap to nearest territory point if the jitter/blend pushed us outside
        if dists[nearest_idx] > 0.0003:   # ~33m — snaps back much sooner
            nearest = drone.territory[nearest_idx]
            return (float(nearest[0]), float(nearest[1]))
        return lat, lon


# ═══════════════════════════════════════════════════════════════════
# Main Hybrid Planner
# ═══════════════════════════════════════════════════════════════════

class VoronoiACOPlanner:
    def __init__(
        self,
        bounds: dict,
        grid_config: GridConfig,
        pheromone_grid: Optional[InMemoryPheromoneGrid] = None,
        n_grid: int = 30,
        lloyd_interval: int = 10,
        aco_radius: int = 2,
        alpha: float = 0.3,
    ):
        self.bounds      = bounds
        self.grid_points = build_search_grid(bounds, n=n_grid)

        self.pheromone = (pheromone_grid if pheromone_grid is not None
                          else InMemoryPheromoneGrid(grid_config))
        if pheromone_grid is None:
            self.pheromone.start_evaporation()

        self.lloyd = LloydPartitioner(self.grid_points)
        self.aco   = ACONavigator(
            self.pheromone,
            aco_radius=aco_radius,
            centroid_bias=0.0,  # Force zero — pure ACO navigation
        )

        self.phase        = PlannerPhase.LLOYD
        self.lloyd_active = False

        # Legacy compat
        self.lloyd_interval = lloyd_interval
        self.aco_radius     = aco_radius
        self.alpha          = alpha
        self._tick          = 0

    # ── Phase management ───────────────────────────────────────────

    def is_lloyd_phase(self) -> bool:
        return self.phase == PlannerPhase.LLOYD

    def is_aco_phase(self) -> bool:
        return self.phase == PlannerPhase.ACO

    def transition_to_aco(self):
        if self.phase == PlannerPhase.LLOYD:
            self.phase = PlannerPhase.ACO
            log.info("[Planner] Phase transition: LLOYD → ACO")

    # ── Lloyd ──────────────────────────────────────────────────────

    def _run_lloyd(self, drones: List[DroneState]) -> None:
        self.lloyd.partition(drones)

    # ── ACO ────────────────────────────────────────────────────────

    def _aco_waypoint(self, drone: DroneState) -> Tuple[float, float]:
        return self.aco.get_waypoint(drone)

    def clamp_to_territory(self, drone: DroneState, lat: float, lon: float) -> Tuple[float, float]:
        return self.aco.clamp_to_territory(drone, lat, lon)

    # ── Coverage metrics ───────────────────────────────────────────

    def _territory_coverage(self, drone: DroneState) -> float:
        """
        Coverage = fraction of territory cells that have been visited.
        
        A cell is 'visited' if pheromone > 0 in its grid neighborhood OR
        if the drone has passed within PHYSICAL_VISIT_RADIUS_DEG of it.
        
        Using a larger neighborhood (5x5 instead of 3x3) prevents the metric
        from requiring exact waypoint-on-cell hits, which are rare at edges.
        """
        if not drone.has_territory():
            return 0.0
        snap    = self.pheromone.get_snapshot()
        visited = 0
        RADIUS  = 2   # 5×5 neighborhood instead of 3×3

        for pt in drone.territory:
            row, col = self.pheromone.world_to_grid(pt[0], pt[1])
            found = False
            for dr in range(-RADIUS, RADIUS + 1):
                if found:
                    break
                for dc in range(-RADIUS, RADIUS + 1):
                    r = max(0, min(self.pheromone.config.rows - 1, row + dr))
                    c = max(0, min(self.pheromone.config.cols - 1, col + dc))
                    if snap[r, c] > 0:
                        visited += 1
                        found    = True
                        break
        return visited / len(drone.territory)

    # ── Legacy ─────────────────────────────────────────────────────

    def step(self, drones: List[DroneState]) -> List[Tuple[float, float]]:
        self._tick += 1
        if self._tick % self.lloyd_interval == 0:
            self._run_lloyd(drones)
        waypoints = []
        for drone in drones:
            wp = self._aco_waypoint(drone)
            self.pheromone.deposit(drone.lat, drone.lon)
            waypoints.append(wp)
        return waypoints