"""
voronoi_aco_hybrid.py
---------------------
Combines Lloyd/Voronoi spatial partitioning with ACO pheromone
gradient navigation. Lloyd answers "whose territory is this cell?"
ACO answers "which unvisited cell should I go to next?"
"""

import numpy as np
import random
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from dataclasses import dataclass, field
from typing import List, Tuple

from stigmergy_engine import InMemoryPheromoneGrid, GridConfig
from voronoi import build_search_grid, lloyd_step


@dataclass
class DroneState:
    id: int
    lat: float
    lon: float
    # Voronoi cell points assigned to this drone (refreshed each Lloyd step)
    territory: np.ndarray = field(default_factory=lambda: np.empty((0, 2)))


class VoronoiACOPlanner:
    """
    Hybrid planner: Lloyd partitions space, ACO steers within each partition.

    lloyd_interval  — how many ticks between Lloyd re-partitions
    aco_radius      — pheromone gradient search radius (grid cells)
    alpha           — blend weight: 0 = pure ACO, 1 = pure Voronoi centroid
    """

    def __init__(
        self,
        bounds: dict,
        grid_config: GridConfig,
        pheromone_grid=None,
        n_grid: int = 15,
        lloyd_interval: int = 10,
        aco_radius: int = 2,
        alpha: float = 0.3,         # pull toward Voronoi centroid
    ):
        self.bounds = bounds
        self.grid_points = build_search_grid(bounds, n=n_grid)
        # Use the shared grid if provided, otherwise create one
        self.pheromone = pheromone_grid if pheromone_grid is not None else InMemoryPheromoneGrid(grid_config)
        if pheromone_grid is None:
            self.pheromone.start_evaporation()

        self.lloyd_interval = lloyd_interval
        self.aco_radius = aco_radius
        self.alpha = alpha
        self._tick = 0

    # ------------------------------------------------------------------ #
    #  Main entry point — call once per simulation tick per drone          #
    # ------------------------------------------------------------------ #

    def step(self, drones: List[DroneState]) -> List[Tuple[float, float]]:
        """
        Returns a (lat, lon) waypoint for each drone.
        Mutates drone.territory during Lloyd steps.
        """
        self._tick += 1
        if self._tick % self.lloyd_interval == 0:
            self._run_lloyd(drones)

        waypoints = []
        for drone in drones:
            wp = self._aco_waypoint(drone)
            # Deposit on current position before moving
            self.pheromone.deposit(drone.lat, drone.lon)
            waypoints.append(wp)

        return waypoints

    # ------------------------------------------------------------------ #
    #  Lloyd re-partition                                                  #
    # ------------------------------------------------------------------ #

    def _run_lloyd(self, drones: List[DroneState]):
        centroids = np.array([[d.lat, d.lon] for d in drones])
        new_centroids, labels = lloyd_step(self.grid_points, centroids)

        for i, drone in enumerate(drones):
            drone.territory = self.grid_points[labels == i]

        # Optional: nudge drones toward their new centroid
        # (you can instead just let ACO steer them there naturally)
        for i, drone in enumerate(drones):
            drone.lat = float(new_centroids[i, 0])
            drone.lon = float(new_centroids[i, 1])

    # ------------------------------------------------------------------ #
    #  ACO waypoint — least-visited cell, constrained to Voronoi region   #
    # ------------------------------------------------------------------ #

    def _aco_waypoint(self, drone: DroneState) -> Tuple[float, float]:
        if len(drone.territory) == 0:
            return self.pheromone.get_gradient(
                drone.lat, drone.lon, radius=self.aco_radius
            )

        best_val = float("inf")
        candidates = []

        for point in drone.territory:
            pher = self.pheromone.get_value(point[0], point[1])
            if pher < best_val:
                best_val = pher
                candidates = [point]
            elif pher == best_val:
                candidates.append(point)

        aco_target = random.choice(candidates)

        if len(drone.territory) > 0 and self.alpha > 0:
            centroid = drone.territory.mean(axis=0)
            blended = (1 - self.alpha) * aco_target + self.alpha * centroid
            lat, lon = float(blended[0]), float(blended[1])
        else:
            lat, lon = float(aco_target[0]), float(aco_target[1])

        # Hard clamp — never leave territory
        return self.clamp_to_territory(drone, lat, lon)

    def clamp_to_territory(self, drone: DroneState, lat: float, lon: float):
        """
        If (lat, lon) is outside the drone's territory, snap it to the
        nearest territory point instead.
        """
        if len(drone.territory) == 0:
            return lat, lon

        target = np.array([lat, lon])
        dists  = np.linalg.norm(drone.territory - target, axis=1)
        nearest_idx = np.argmin(dists)
        nearest = drone.territory[nearest_idx]

        # Only snap if the point is farther than the grid cell spacing
        if dists[nearest_idx] > 0.001:   # ~100m in degrees
            return float(nearest[0]), float(nearest[1])
        return lat, lon