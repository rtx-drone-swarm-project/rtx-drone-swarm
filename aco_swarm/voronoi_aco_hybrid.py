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

import logging
log = logging.getLogger(__name__)

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

    lloyd_interval  — how many ticks between Lloyd re-partitions (used by step())
    aco_radius      — pheromone gradient search radius (grid cells)
    alpha           — blend weight: 0 = pure ACO, 1 = pure Voronoi centroid
    """

    def __init__(
        self,
        bounds: dict,
        grid_config: GridConfig,
        pheromone_grid=None,
        n_grid: int = 30,
        lloyd_interval: int = 10,
        aco_radius: int = 2,
        alpha: float = 0.3,
    ):
        self.bounds = bounds
        self.grid_points = build_search_grid(bounds, n=n_grid)
        self.pheromone = pheromone_grid if pheromone_grid is not None else InMemoryPheromoneGrid(grid_config)
        if pheromone_grid is None:
            self.pheromone.start_evaporation()

        self.lloyd_interval = lloyd_interval
        self.aco_radius = aco_radius
        self.alpha = alpha
        self._tick = 0
        self.lloyd_active = False


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
            mask = labels == i
            drone.territory = self.grid_points[mask]
            if len(drone.territory) == 0:
                log.warning(f"[Lloyd] Drone {drone.id} got 0 territory cells — assigning nearest points")
                dists = np.linalg.norm(self.grid_points - np.array([drone.lat, drone.lon]), axis=1)
                drone.territory = self.grid_points[np.argsort(dists)[:5]]

        # drone.lat/lon intentionally NOT updated here —
        # alpha blending in _aco_waypoint steers toward centroid naturally.

    # ------------------------------------------------------------------ #
    #  ACO waypoint — least-visited cell, constrained to Voronoi region   #
    # ------------------------------------------------------------------ #

    def _point_in_territory(self, state, lat, lon):
        # simple nearest-neighbor validity check
        if state.territory is None or len(state.territory) == 0:
            return False
        d = np.linalg.norm(state.territory - np.array([lat, lon]), axis=1)
        return np.min(d) < 0.0005

    def _aco_waypoint(self, drone: DroneState):
        # 1. fallback if no territory
        if len(drone.territory) == 0:
            return self.pheromone.get_gradient(
                drone.lat, drone.lon, radius=self.aco_radius
            )

        # 2. filter VALID territory points FIRST
        valid_points = [
            p for p in drone.territory
            if self._point_in_territory(drone, p[0], p[1])
        ]

        if len(valid_points) == 0:
            idx = np.random.randint(len(drone.territory))
            return tuple(drone.territory[idx])

        # 3. ACO selection
        best_val = float("inf")
        candidates = []

        for point in valid_points:
            pher = self.pheromone.get_value(point[0], point[1])

            if pher < best_val:
                best_val = pher
                candidates = [point]
            elif pher == best_val:
                candidates.append(point)

        aco_target = np.array(random.choice(candidates))

        # 4. centroid bias
        centroid = np.mean(drone.territory, axis=0)
        aco_target = 0.8 * aco_target + 0.2 * centroid

        # 5. final blending
        if self.alpha > 0:
            blended = (1 - self.alpha) * aco_target + self.alpha * centroid
        else:
            blended = aco_target

        lat, lon = float(blended[0]), float(blended[1])
        return self.clamp_to_territory(drone, lat, lon)


    # def _aco_waypoint(self, drone: DroneState) -> Tuple[float, float]:
    #     if len(drone.territory) == 0:
    #         return self.pheromone.get_gradient(
    #             drone.lat, drone.lon, radius=self.aco_radius
    #         )

    #     best_val = float("inf")
    #     candidates = []

    #     for point in drone.territory:
    #         pher = self.pheromone.get_value(point[0], point[1])
    #         if pher < best_val:
    #             best_val = pher
    #             candidates = [point]
    #         elif pher == best_val:
    #             candidates.append(point)

    #     aco_target = random.choice(candidates)

    #     if len(drone.territory) > 0:
    #         centroid = drone.territory.mean(axis=0)

    #         aco_target = np.array(aco_target)

    #         aco_target = np.array([
    #             0.8 * aco_target[0] + 0.2 * centroid[0],
    #             0.8 * aco_target[1] + 0.2 * centroid[1],
    #         ])


    #     if drone.territory is not None and len(drone.territory) > 0:
    #         candidates = [
    #             p for p in candidates
    #             if self._point_in_territory(drone, p[0], p[1])
    #         ]

    #         if len(candidates) == 0:
    #             idx = np.random.randint(len(drone.territory))
    #             return tuple(drone.territory[idx])

    #     if len(drone.territory) > 0 and self.alpha > 0:
    #         centroid = drone.territory.mean(axis=0)
    #         blended = (1 - self.alpha) * aco_target + self.alpha * centroid
    #         lat, lon = float(blended[0]), float(blended[1])
    #     else:
    #         lat, lon = float(aco_target[0]), float(aco_target[1])

    #     return self.clamp_to_territory(drone, lat, lon)

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

        if dists[nearest_idx] > 0.001:   # ~100m in degrees
            return float(nearest[0]), float(nearest[1])
        return lat, lon

    def _territory_coverage(self, drone: DroneState) -> float:
        """
        Fraction of territory cells visited, using a 3x3 neighborhood
        around each territory point to account for coordinate mismatch
        between drone GPS positions and Voronoi grid points.
        """
        if drone.territory is None or len(drone.territory) == 0:
            return 0.0
        snap = self.pheromone.get_snapshot()
        visited = 0
        for pt in drone.territory:
            row, col = self.pheromone.world_to_grid(pt[0], pt[1])
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