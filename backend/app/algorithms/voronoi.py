import math
import numpy as np
from typing import List, Dict, Tuple
from app.algorithms.base import BaseSearchAlgorithm

def lloyd_step(grid_points: np.ndarray, centroids: np.ndarray):
    """
    One iteration of Lloyd's algorithm in 2D lat/lon space.
    """
    k = len(centroids)
    distances = np.linalg.norm(grid_points[:, np.newaxis] - centroids, axis=2)
    labels = np.argmin(distances, axis=1)

    new_centroids = []
    for i in range(k):
        cluster_pts = grid_points[labels == i]
        if len(cluster_pts) > 0:
            new_centroids.append(cluster_pts.mean(axis=0))
        else:
            new_centroids.append(centroids[i])

    return np.array(new_centroids), labels


class VoronoiCoverage(BaseSearchAlgorithm):
    def initialize(self, mission: dict) -> None:
        """Run once when the mission starts to generate the search grid."""

    def get_target_waypoints(self, mission: dict, free_drones: List[dict]) -> Dict[str, Tuple[float, float]]:
        """Run every simulation tick to get the next Voronoi centroid."""
        centroid_map = {}
        if not free_drones or "grid" not in mission:
            return centroid_map

        grid_np = np.array(mission["grid"])
        pos_list = []
        
        for drone in free_drones:
            tlat = drone.get("target_lat")
            tlon = drone.get("target_lon")
            dlat = drone.get("lat", 0)
            dlon = drone.get("lon", 0)
            
            if tlat is not None and tlon is not None:
                dist_to_target = math.hypot(dlat - tlat, dlon - tlon)
                if dist_to_target > 0.005:
                    pos_list.append([tlat, tlon])
                else:
                    pos_list.append([dlat, dlon])
            else:
                pos_list.append([dlat, dlon])
                
        positions = np.array(pos_list)
        new_centroids, _ = lloyd_step(grid_np, positions)
        
        for drone, centroid in zip(free_drones, new_centroids):
            # Ensure we return standard Python floats, not numpy types, so it's JSON serializable
            centroid_map[drone["id"]] = (float(centroid[0]), float(centroid[1]))
            
        return centroid_map