import logging
import threading
from typing import Dict, List, Tuple

import numpy as np
from app.algorithms.base import BaseSearchAlgorithm, DETECTION_RADIUS
from app.algorithms.voronoi_aco_hybrid import (
    VoronoiACOPlanner,
    PlannerConfig,
    NavigationController,
    DroneState,
    _jitter_collinear_centroids
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
        # Convert detection radius to a config object
        pcfg = PlannerConfig(detection_radius_m=30.0) 
        
        planner = VoronoiACOPlanner(
            bounds=bounds,
            planner_config=pcfg
        )

        mission._rtx_planner = planner
        mission._rtx_pcfg = pcfg
        mission._rtx_territories = {}
        mission._rtx_navigators = {}
        mission._rtx_bootstrapped = False

    def get_target_waypoints(self, mission, free_drones: List[dict]) -> Dict[str, Tuple[float, float]]:
        planner = mission._rtx_planner
        territories = mission._rtx_territories
        navs = mission._rtx_navigators
        pcfg = mission._rtx_pcfg
        
        valid_drones = [d for d in free_drones if d.get("lat") is not None]
        if not valid_drones: return {}

        # 1. Bootstrap (Lloyd)
        if not mission._rtx_bootstrapped:
            # Placeholder: In a real run, this calls planner._run_lloyd 
            # and populates mission._rtx_territories
            mission._rtx_bootstrapped = True
            planner.transition_to_aco()

        # 2. Waypoint Generation
        waypoints = {}
        for drone in valid_drones:
            d_id = drone["id"]
            territory = territories.get(d_id)
            if territory is None: continue
            
            if d_id not in navs:
                navs[d_id] = NavigationController(d_id, pcfg, territory)
            
            navs[d_id].set_territory(territory)
            waypoints[d_id] = navs[d_id].get_waypoint(drone["lat"], drone["lon"])

            # 3. Drift Correction
            pos = np.array([drone["lat"], drone["lon"]])
            if np.linalg.norm(territory - pos, axis=1).min() > self.DRIFT_THRESHOLD_DEG:
                nearest = territory[np.argmin(np.linalg.norm(territory - pos, axis=1))]
                waypoints[d_id] = (float(nearest[0]), float(nearest[1]))

        return waypoints