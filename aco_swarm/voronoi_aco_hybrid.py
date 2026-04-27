"""
voronoi_aco_hybrid.py
---------------------
Two-phase hybrid planner:
  Phase 1: LLOYD — Spatial partitioning (assigns territories)
  Phase 2: ACO   — Pheromone-based coverage navigation (within territories)

Architecture:
    VoronoiACOPlanner
        ├── LloydPartitioner   (territory assignment)
        ├── ACONavigator       (waypoint selection)
        └── Phase Manager      (LLOYD → ACO transition)

Design principle:
    Lloyd defines WHERE each drone operates (territory boundaries).
    ACO defines HOW each drone covers its territory (navigation strategy).
"""

import numpy as np
import random
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

import logging
log = logging.getLogger(__name__)

from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from enum import Enum

from stigmergy_engine import InMemoryPheromoneGrid, GridConfig
from voronoi import build_search_grid, lloyd_step


# ═══════════════════════════════════════════════════════════════════
# Data Classes & Enums
# ═══════════════════════════════════════════════════════════════════

class PlannerPhase(Enum):
    """Planner operational phases."""
    LLOYD = "lloyd"  # Territory assignment phase
    ACO = "aco"      # Coverage navigation phase


@dataclass
class DroneState:
    """
    Drone state for planner operations.
    
    Attributes:
        id: Drone unique identifier
        lat, lon: Current GPS position
        territory: Assigned Voronoi cell points (lat/lon pairs)
    """
    id: int
    lat: float
    lon: float
    territory: np.ndarray = field(default_factory=lambda: np.empty((0, 2)))
    
    def has_territory(self) -> bool:
        """Check if drone has assigned territory."""
        return self.territory is not None and len(self.territory) > 0
    
    def territory_centroid(self) -> Optional[Tuple[float, float]]:
        """Calculate territory centroid."""
        if not self.has_territory():
            return None
        mean = np.mean(self.territory, axis=0)
        return (float(mean[0]), float(mean[1]))


# ═══════════════════════════════════════════════════════════════════
# Lloyd Partitioner
# ═══════════════════════════════════════════════════════════════════

class LloydPartitioner:
    """
    Lloyd/Voronoi spatial partitioning.
    Assigns territory cells to drones based on Voronoi diagram.
    """
    
    def __init__(self, grid_points: np.ndarray):
        self.grid_points = grid_points
    
    def partition(self, drones: List[DroneState]) -> None:
        """
        Run Lloyd iteration and assign territories.
        Mutates drone.territory in-place.
        """
        if len(drones) == 0:
            return
        
        # Build centroids from current drone positions
        centroids = np.array([[d.lat, d.lon] for d in drones])
        
        # Run Lloyd step
        new_centroids, labels = lloyd_step(self.grid_points, centroids)
        
        # Assign territory cells to each drone
        for i, drone in enumerate(drones):
            mask = labels == i
            drone.territory = self.grid_points[mask]
            
            # Fallback if drone got zero cells
            if len(drone.territory) == 0:
                log.warning(f"[Lloyd] Drone {drone.id} got 0 cells — assigning nearest")
                dists = np.linalg.norm(
                    self.grid_points - np.array([drone.lat, drone.lon]),
                    axis=1
                )
                drone.territory = self.grid_points[np.argsort(dists)[:5]]
        
        log.info(f"[Lloyd] Partitioned {len(self.grid_points)} cells across {len(drones)} drones")


# ═══════════════════════════════════════════════════════════════════
# ACO Navigator
# ═══════════════════════════════════════════════════════════════════

class ACONavigator:
    """
    Ant Colony Optimization navigator.
    Selects least-visited cells within drone's territory using pheromone gradients.
    """
    
    def __init__(
        self,
        pheromone_grid: InMemoryPheromoneGrid,
        aco_radius: int = 2,
        centroid_bias: float = 0.2,
    ):
        self.pheromone = pheromone_grid
        self.aco_radius = aco_radius
        self.centroid_bias = centroid_bias
    
    def get_waypoint(self, drone: DroneState) -> Tuple[float, float]:
        """
        Get next waypoint using ACO within drone's territory.
        
        Returns:
            (lat, lon) tuple of next waypoint
        """
        # Fallback if no territory assigned
        if not drone.has_territory():
            return self._pheromone_gradient_fallback(drone)
        
        # Filter valid territory points
        valid_points = self._get_valid_territory_points(drone)
        
        if len(valid_points) == 0:
            # No valid points — return random territory cell
            idx = np.random.randint(len(drone.territory))
            return tuple(drone.territory[idx])
        
        # ACO selection: least-visited cells
        aco_target = self._select_least_visited(valid_points)
        
        # Apply centroid bias
        if self.centroid_bias > 0:
            centroid = np.mean(drone.territory, axis=0)
            aco_target = ((1 - self.centroid_bias) * aco_target +
                         self.centroid_bias * centroid)
        
        return (float(aco_target[0]), float(aco_target[1]))
    
    def _pheromone_gradient_fallback(self, drone: DroneState) -> Tuple[float, float]:
        """Fallback: use raw pheromone gradient (no territory constraint)."""
        return self.pheromone.get_gradient(
            drone.lat, drone.lon,
            radius=self.aco_radius
        )
    
    def _get_valid_territory_points(self, drone: DroneState) -> np.ndarray:
        """Filter territory points that are within reasonable bounds."""
        valid = []
        for point in drone.territory:
            if self._point_in_territory(drone, point[0], point[1]):
                valid.append(point)
        return np.array(valid) if valid else np.empty((0, 2))
    
    def _point_in_territory(self, drone: DroneState, lat: float, lon: float) -> bool:
        """Check if point is within drone's territory (simple nearest-neighbor)."""
        if not drone.has_territory():
            return False
        dists = np.linalg.norm(drone.territory - np.array([lat, lon]), axis=1)
        return np.min(dists) < 0.0005  # ~50m threshold
    
    def _select_least_visited(self, points: np.ndarray) -> np.ndarray:
        """Select least-visited point from candidates using pheromone values."""
        best_val = float("inf")
        candidates = []
        
        for point in points:
            pher = self.pheromone.get_value(point[0], point[1])
            
            if pher < best_val:
                best_val = pher
                candidates = [point]
            elif pher == best_val:
                candidates.append(point)
        
        return np.array(random.choice(candidates))
    
    def clamp_to_territory(self, drone: DroneState, lat: float, lon: float) -> Tuple[float, float]:
        """
        Clamp waypoint to nearest territory point if outside bounds.
        """
        if not drone.has_territory():
            return lat, lon
        
        target = np.array([lat, lon])
        dists = np.linalg.norm(drone.territory - target, axis=1)
        nearest_idx = np.argmin(dists)
        
        # If too far, snap to nearest territory point
        if dists[nearest_idx] > 0.001:  # ~100m
            nearest = drone.territory[nearest_idx]
            return (float(nearest[0]), float(nearest[1]))
        
        return lat, lon


# ═══════════════════════════════════════════════════════════════════
# Main Hybrid Planner
# ═══════════════════════════════════════════════════════════════════

class VoronoiACOPlanner:
    """
    Hybrid planner coordinating Lloyd partitioning and ACO navigation.
    
    Operational flow:
        1. LLOYD phase: Partition space, assign territories
        2. Transition: Set phase = ACO
        3. ACO phase: Navigate within territories using pheromone
    
    The planner is designed so Lloyd runs FIRST (via bootstrap in swarm_main.py),
    then ACO takes over as the navigation layer.
    """
    
    def __init__(
        self,
        bounds: dict,
        grid_config: GridConfig,
        pheromone_grid: Optional[InMemoryPheromoneGrid] = None,
        n_grid: int = 30,
        lloyd_interval: int = 10,
        aco_radius: int = 2,
        alpha: float = 0.3,  # DEPRECATED: use centroid_bias instead
    ):
        # Grid configuration
        self.bounds = bounds
        self.grid_points = build_search_grid(bounds, n=n_grid)
        
        # Pheromone grid
        self.pheromone = (pheromone_grid if pheromone_grid is not None
                         else InMemoryPheromoneGrid(grid_config))
        if pheromone_grid is None:
            self.pheromone.start_evaporation()
        
        # Sub-components
        self.lloyd = LloydPartitioner(self.grid_points)
        self.aco = ACONavigator(
            self.pheromone,
            aco_radius=aco_radius,
            centroid_bias=alpha  # alpha parameter maps to centroid_bias
        )
        
        # Phase management
        self.phase = PlannerPhase.LLOYD
        self.lloyd_active = False  # Locking flag for concurrent access
        
        # Legacy parameters (unused but kept for compatibility)
        self.lloyd_interval = lloyd_interval
        self.aco_radius = aco_radius
        self.alpha = alpha
        self._tick = 0
    
    # ══════════════════════════════════════════════════════════════
    # Phase Management
    # ══════════════════════════════════════════════════════════════
    
    def is_lloyd_phase(self) -> bool:
        """Check if planner is in LLOYD phase."""
        return self.phase == PlannerPhase.LLOYD
    
    def is_aco_phase(self) -> bool:
        """Check if planner is in ACO phase."""
        return self.phase == PlannerPhase.ACO
    
    def transition_to_aco(self):
        """Transition from LLOYD → ACO phase."""
        if self.phase == PlannerPhase.LLOYD:
            self.phase = PlannerPhase.ACO
            log.info("[Planner] Phase transition: LLOYD → ACO")
    
    # ══════════════════════════════════════════════════════════════
    # Lloyd Operations
    # ══════════════════════════════════════════════════════════════
    
    def _run_lloyd(self, drones: List[DroneState]) -> None:
        """
        Run Lloyd partitioning step.
        This is the PRIMARY partitioning mechanism.
        
        Call this during bootstrap to assign initial territories,
        then optionally during coverage for adaptive repartitioning.
        """
        self.lloyd.partition(drones)
    
    # ══════════════════════════════════════════════════════════════
    # ACO Operations
    # ══════════════════════════════════════════════════════════════
    
    def _aco_waypoint(self, drone: DroneState) -> Tuple[float, float]:
        """
        Get ACO waypoint for drone.
        This is the FALLBACK navigation mechanism within territories.
        
        Returns:
            (lat, lon) tuple
        """
        return self.aco.get_waypoint(drone)
    
    def clamp_to_territory(self, drone: DroneState, lat: float, lon: float) -> Tuple[float, float]:
        """
        Clamp waypoint to territory boundaries.
        Wrapper for ACONavigator.clamp_to_territory.
        """
        return self.aco.clamp_to_territory(drone, lat, lon)
    
    # ══════════════════════════════════════════════════════════════
    # Coverage Metrics
    # ══════════════════════════════════════════════════════════════
    
    def _territory_coverage(self, drone: DroneState) -> float:
        """
        Calculate fraction of territory visited using pheromone grid.
        Uses 3×3 neighborhood lookup to handle GPS/grid coordinate mismatch.
        
        Returns:
            Coverage fraction [0.0, 1.0]
        """
        if not drone.has_territory():
            return 0.0
        
        snap = self.pheromone.get_snapshot()
        visited = 0
        
        for pt in drone.territory:
            row, col = self.pheromone.world_to_grid(pt[0], pt[1])
            
            # Check 3×3 neighborhood
            found = False
            for dr in range(-1, 2):
                if found:
                    break
                for dc in range(-1, 2):
                    r = max(0, min(self.pheromone.config.rows - 1, row + dr))
                    c = max(0, min(self.pheromone.config.cols - 1, col + dc))
                    if snap[r, c] > 0:
                        visited += 1
                        found = True
                        break
        
        return visited / len(drone.territory)
    
    # ══════════════════════════════════════════════════════════════
    # Legacy Interface (compatibility)
    # ══════════════════════════════════════════════════════════════
    
    def step(self, drones: List[DroneState]) -> List[Tuple[float, float]]:
        """
        LEGACY: Single-tick planner step.
        
        Not recommended — use explicit phase management instead:
          1. Call _run_lloyd() once during bootstrap
          2. Call transition_to_aco()
          3. Call _aco_waypoint() per drone per tick
        
        This method retained for backward compatibility only.
        """
        self._tick += 1
        
        # Periodic Lloyd repartitioning
        if self._tick % self.lloyd_interval == 0:
            self._run_lloyd(drones)
        
        # ACO waypoints
        waypoints = []
        for drone in drones:
            wp = self._aco_waypoint(drone)
            self.pheromone.deposit(drone.lat, drone.lon)
            waypoints.append(wp)
        
        return waypoints