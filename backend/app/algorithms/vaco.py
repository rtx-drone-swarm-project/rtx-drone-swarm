import logging
from typing import Dict, List, Tuple

import numpy as np
from app.algorithms.base import BaseSearchAlgorithm
from app.algorithms.voronoi_aco_hybrid import (
    VoronoiACOPlanner,
    PlannerConfig,
    NavigationController,
    DroneState,
    _jitter_collinear_centroids,
    BOOTSTRAP_SPREAD_DEG,
    BOOTSTRAP_TIMEOUT_TICKS,
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
        mission._rtx_prev_positions = {}
        mission._rtx_bootstrapped = False
        mission._rtx_ticks = 0

    def get_target_waypoints(self, mission, free_drones: List[dict]) -> Dict[str, Tuple[float, float]]:
        planner = mission._rtx_planner
        territories = mission._rtx_territories
        navs = mission._rtx_navigators
        pcfg = mission._rtx_pcfg
        
        valid_drones = [d for d in free_drones if d.get("lat") is not None]
        if not valid_drones:
            return {}

        mission_time_s = float(getattr(mission, "elapsed_seconds", 0.0))

        # 1. Bootstrap Logic (Fan-out -> Partition)
        if not mission._rtx_bootstrapped:
            mission._rtx_ticks += 1
            lats = [d["lat"] for d in valid_drones]
            lons = [d["lon"] for d in valid_drones]
            current_spread = max(max(lats) - min(lats), max(lons) - min(lons))

            # Force start if spread reached OR timeout reached
            if current_spread >= BOOTSTRAP_SPREAD_DEG or mission._rtx_ticks > BOOTSTRAP_TIMEOUT_TICKS:
                log.info(f"[RTX] Bootstrap triggered (Spread: {current_spread:.5f}, Ticks: {mission._rtx_ticks})")
                mission._rtx_bootstrapped = True
                self._run_lloyd_partition(mission, valid_drones, current_spread)
                planner.transition_to_aco()
            else:
                # Still in fan-out mode: return the initial jittered grid points
                jittered = _jitter_collinear_centroids(valid_drones, mission.bounds)
                return {d["id"]: jittered[i] for i, d in enumerate(valid_drones)}

        # 2. Deterministic pheromone maintenance and path deposits
        planner.pheromone_grid.tick()
        prev_positions = mission._rtx_prev_positions
        for drone in valid_drones:
            d_id = drone["id"]
            curr_lat = float(drone["lat"])
            curr_lon = float(drone["lon"])
            prev = prev_positions.get(d_id)
            if prev is not None:
                planner.pheromone_grid.deposit_path(prev[0], prev[1], curr_lat, curr_lon)
            prev_positions[d_id] = (curr_lat, curr_lon)

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
            waypoints[d_id] = navs[d_id].get_waypoint(drone["lat"], drone["lon"], mission_time_s)

            # 3. Drift Correction: If drone wanders outside its Voronoi cell
            pos = np.array([drone["lat"], drone["lon"]])
            dist_to_cell = np.linalg.norm(territory - pos, axis=1).min()
            if dist_to_cell > self.DRIFT_THRESHOLD_DEG:
                nearest = territory[np.argmin(np.linalg.norm(territory - pos, axis=1))]
                waypoints[d_id] = (float(nearest[0]), float(nearest[1]))

        return waypoints

    def _run_lloyd_partition(self, mission, drones: List[dict], current_spread: float):
        """Compute balanced territories via planner-owned DroneState objects."""
        planner = mission._rtx_planner
        use_jitter = current_spread < BOOTSTRAP_SPREAD_DEG
        if use_jitter:
            seeded = _jitter_collinear_centroids(drones, mission.bounds)
            states = [
                DroneState(id=str(drone["id"]), lat=seeded[i][0], lon=seeded[i][1])
                for i, drone in enumerate(drones)
            ]
        else:
            states = [
                DroneState(
                    id=str(drone["id"]),
                    lat=float(drone["lat"]),
                    lon=float(drone["lon"]),
                )
                for drone in drones
            ]

        planner._run_lloyd(states)
        mission._rtx_territories = {}
        cell_sizes: list[int] = []
        for state in states:
            if state.territory is None or len(state.territory) == 0:
                continue
            mission._rtx_territories[state.id] = state.territory
            cell_sizes.append(int(len(state.territory)))

        if cell_sizes:
            log.info(
                "[RTX] Partition complete. Cell counts: min=%d, max=%d",
                min(cell_sizes),
                max(cell_sizes),
            )
