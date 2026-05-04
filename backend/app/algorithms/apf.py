import math
import random
from typing import List, Dict, Tuple
from app.algorithms.base import BaseSearchAlgorithm
from app.models import Mission

class PotentialFieldsCoverage(BaseSearchAlgorithm):
    algorithm_key = "apf"
    display_name = "APF (Potential Fields)"
    description = "Artificial potential fields with drone and boundary repulsion."
    display_order = 30

    def initialize(self, mission: Mission) -> None:
        pass

    def get_target_waypoints(self, mission: Mission, free_drones: List[dict]) -> Dict[str, Tuple[float, float]]:
        waypoint_map = {}
        if not free_drones:
            return waypoint_map

        bounds = mission.bounds
        rng = getattr(mission, "_rng", random)
        
        REPULSION_DRONE = 0.0002  # How strongly drones push each other away
        REPULSION_WALL = 0.0005   # How strongly the boundaries push drones back in
        STEP_SIZE = 0.001         # How far to place the next waypoint

        for i, drone in enumerate(free_drones):
            dlat = drone.get("lat", 0.0)
            dlon = drone.get("lon", 0.0)

            force_lat = 0.0
            force_lon = 0.0

            # 1. Repel from other drones (Spread out!)
            for j, other_drone in enumerate(free_drones):
                if i == j:
                    continue
                olat = other_drone.get("lat", 0.0)
                olon = other_drone.get("lon", 0.0)

                dist = math.hypot(dlat - olat, dlon - olon)
                # Avoid division by zero, and only care if they are close
                if 0.0001 < dist < 0.02: 
                    mag = REPULSION_DRONE / (dist**2)
                    force_lat += mag * (dlat - olat) / dist
                    force_lon += mag * (dlon - olon) / dist

            # 2. Repel from walls (Stay in bounds!)
            dist_north = max(0.0001, bounds["max_lat"] - dlat)
            dist_south = max(0.0001, dlat - bounds["min_lat"])
            dist_east = max(0.0001, bounds["max_lon"] - dlon)
            dist_west = max(0.0001, dlon - bounds["min_lon"])

            force_lat -= REPULSION_WALL / (dist_north**2)  # Push south from north wall
            force_lat += REPULSION_WALL / (dist_south**2)  # Push north from south wall
            force_lon -= REPULSION_WALL / (dist_east**2)   # Push west from east wall
            force_lon += REPULSION_WALL / (dist_west**2)   # Push east from west wall

            # 3. Add a tiny bit of random jitter so they don't get stuck in a perfect tie
            force_lat += rng.uniform(-0.0001, 0.0001)
            force_lon += rng.uniform(-0.0001, 0.0001)

            # 4. Calculate the final waypoint coordinate
            force_mag = math.hypot(force_lat, force_lon)
            if force_mag > 0:
                step_lat = (force_lat / force_mag) * STEP_SIZE
                step_lon = (force_lon / force_mag) * STEP_SIZE
            else:
                step_lat, step_lon = 0, 0

            # Clamp the waypoint so we don't accidentally command a drone outside the box
            target_lat = max(bounds["min_lat"], min(bounds["max_lat"], dlat + step_lat))
            target_lon = max(bounds["min_lon"], min(bounds["max_lon"], dlon + step_lon))

            waypoint_map[drone["id"]] = (float(target_lat), float(target_lon))

        return waypoint_map
