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

def lloyd_step_aco(X, centroids, old_centroids, pheromone, decay=0.9, deposit=0.5):
    k = len(centroids)

    distances = np.linalg.norm(X[:, np.newaxis] - centroids, axis=2)
    similarity = 1 / (distances + 1e-8)
    avoidance = np.exp(-1 * pheromone)
    scores = similarity * avoidance

    distance_labels = np.argmin(distances, axis=1) 
    labels = np.argmax(scores, axis=1)

    new_centroids = []
    for i in range(k):
        cluster_points = X[labels == i]

        if len(cluster_points) > 0:
            target = cluster_points.mean(axis=0)
        else:
            target = X[np.random.randint(0, len(X))]

        new_centroids.append(target)

    new_centroids = np.array(new_centroids)

    pheromone *= decay

    for i in range(k):
        start = old_centroids[i]
        end = centroids[i]

        path = np.linspace(start, end, 30)

        for p in path:
            weights = np.exp(-np.linalg.norm(X - p, axis=1))
            pheromone[:, i] += weights * deposit

    # pheromone_intensity = pheromone.sum(axis=1)
    # pheromone_intensity = pheromone_intensity / (pheromone_intensity.max() + 1e-8)

    return new_centroids, labels, pheromone

class VoronoiACOCoverage(BaseSearchAlgorithm):
    def initialize(self, mission: dict) -> None:
        """Run once when the mission starts to generate the search grid."""
        self.old_centroids = []
        for drone in mission["drones"]:
            self.old_centroids.append([drone.get("lat",0), drone.get("lon",0)])
        self.pheromone_matrix = np.ones((len(mission["grid"]), len(mission["drones"]))) # initialize pheromone matrix for ACO

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
        new_centroids, _, self.pheromone_matrix = lloyd_step_aco(grid_np, positions, self.old_centroids, self.pheromone_matrix)
        
        self.old_centroids = new_centroids

        for drone, centroid in zip(free_drones, new_centroids):
            # Ensure we return standard Python floats, not numpy types, so it's JSON serializable
            centroid_map[drone["id"]] = (float(centroid[0]), float(centroid[1]))
            
        return centroid_map

class VoronoiACOCoverage(BaseSearchAlgorithm):
    def initialize(self, mission: dict) -> None:
        """Run once when the mission starts to generate the search grid."""
        pass

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