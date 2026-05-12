import logging
import threading
from typing import Dict, List, Tuple

import numpy as np
from app.algorithms.base import BaseSearchAlgorithm, DETECTION_RADIUS, build_search_grid
from app.algorithms.voronoi_aco_hybrid import (
    VoronoiACOPlanner,
    PlannerConfig,
    NavigationController,
    DroneState,
    _jitter_collinear_centroids,
    _balanced_lloyd_assignment,
    BOOTSTRAP_SPREAD_DEG,
    BOOTSTRAP_TIMEOUT_TICKS
)

log = logging.getLogger(__name__)

class VoronoiACOHybridCoverage(BaseSearchAlgorithm):
    algorithm_key = "vaco"
    display_name = "VACO Hybrid (Optimized)"
    description = "Optimized Lloyd partitioning with long-axis sweep navigation."
    display_order = 25

    DRIFT_THRESHOLD_DEG = 0.002

    def initialize(self, mission) -> None:
        bounds = mission.bounds
        pcfg = PlannerConfig(detection_radius_m=30.0) 
        
        # Use **kwargs to match the flexible __init__ we created
        planner = VoronoiACOPlanner(
            bounds=bounds,
            planner_config=pcfg
        )

        mission._rtx_planner = planner
        mission._rtx_pcfg = pcfg
        mission._rtx_territories = {}
        mission._rtx_navigators = {}
        mission._rtx_bootstrapped = False
        mission._rtx_ticks = 0

    def get_target_waypoints(self, mission, free_drones: List[dict]) -> Dict[str, Tuple[float, float]]:
        planner = mission._rtx_planner
        territories = mission._rtx_territories
        navs = mission._rtx_navigators
        pcfg = mission._rtx_pcfg
        
        valid_drones = [d for d in free_drones if d.get("lat") is not None]
        if not valid_drones: return {}

        # 1. Bootstrap Logic (Fan-out -> Partition)
        if not mission._rtx_bootstrapped:
            mission._rtx_ticks += 1
            lats = [d["lat"] for d in valid_drones]
            current_spread = max(lats) - min(lats)

            # Force start if spread reached OR timeout reached
            if current_spread >= 0.001 or mission._rtx_ticks > 15:
                log.info(f"[RTX] Bootstrap triggered (Spread: {current_spread:.5f}, Ticks: {mission._rtx_ticks})")
                mission._rtx_bootstrapped = True
                self._run_lloyd_partition(mission, valid_drones)
                planner.transition_to_aco()
            else:
                # Still in fan-out mode: return the initial jittered grid points
                jittered = _jitter_collinear_centroids(valid_drones, mission.bounds)
                return {d["id"]: jittered[i] for i, d in enumerate(valid_drones)}

        # 2. Waypoint Generation (Post-Bootstrap)
        waypoints = {}
        for drone in valid_drones:
            d_id = drone["id"]
            territory = territories.get(d_id)
            
            if territory is None:
                continue
            
            if d_id not in navs:
                navs[d_id] = NavigationController(d_id, pcfg, territory)
            
            # Update territory in case of repartition
            navs[d_id].set_territory(territory)
            waypoints[d_id] = navs[d_id].get_waypoint(drone["lat"], drone["lon"])

            # 3. Drift Correction: If drone wanders outside its Voronoi cell
            pos = np.array([drone["lat"], drone["lon"]])
            dist_to_cell = np.linalg.norm(territory - pos, axis=1).min()
            if dist_to_cell > self.DRIFT_THRESHOLD_DEG:
                nearest = territory[np.argmin(np.linalg.norm(territory - pos, axis=1))]
                waypoints[d_id] = (float(nearest[0]), float(nearest[1]))

        return waypoints

    def _run_lloyd_partition(self, mission, drones: List[dict]):
        """Computes balanced territories for each drone."""
        bounds = mission.bounds
        # Create a 60x60 grid for high-resolution partitioning
        grid_points = build_search_grid(bounds, n=60)
        
        centroids = np.array([[d["lat"], d["lon"]] for d in drones])
        
        # Use the balanced assignment to ensure 15 equal-sized zones
        assignment, counts = _balanced_lloyd_assignment(
            centroids, grid_points, len(drones), n_iter=15
        )

        log.info(f"[RTX] Partition complete. Cell counts: min={counts.min()}, max={counts.max()}")

        # Update the mission territories
        for i, drone in enumerate(drones):
            mask = (assignment == i)
            if mask.sum() > 0:
                mission._rtx_territories[drone["id"]] = grid_points[mask]