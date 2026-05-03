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

def _rng_int(rng, high: int) -> int:
    if hasattr(rng, "integers"):
        return int(rng.integers(0, high))
    if hasattr(rng, "randrange"):
        return int(rng.randrange(high))
    return int(rng.randint(0, high))


def lloyd_step_aco(X, centroids, old_centroids, pheromone, decay=0.9, deposit=0.5, rng=None):
    k = len(centroids)
    rng = rng or np.random.default_rng()

    distances = np.linalg.norm(X[:, np.newaxis] - centroids, axis=2)
    similarity = 1 / (distances + 1e-8)
    avoidance = np.exp(-1 * pheromone)
    scores = similarity * avoidance

    labels = np.argmax(scores, axis=1)

    new_centroids = []
    for i in range(k):
        cluster_points = X[labels == i]

        if len(cluster_points) > 0:
            target = cluster_points.mean(axis=0)
        else:
            target = X[_rng_int(rng, len(X))]

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
    algorithm_key = "voronoi_aco"
    display_name = "Voronoi (ACO)"
    description = "Voronoi centroid coverage with ant-colony pheromone avoidance."
    display_order = 20

    def __init__(self) -> None:
        self._reset_state()

    def _reset_state(self) -> None:
        self.old_centroids: np.ndarray | None = None
        self.pheromone_matrix: np.ndarray | None = None
        self._drone_order: list[str] = []
        self._np_rng = np.random.default_rng()

    def initialize(self, mission: dict) -> None:
        """Run once when the mission starts.

        Centroid and pheromone state are sized on the first tick from ``free_drones``
        (same count as ``lloyd_step_aco`` centroids), matching ``voronoi_vis.py`` setup
        where the pheromone matrix is ``(len(grid), k)`` for k active centroids.
        """
        self._reset_state()

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
                
        positions = np.asarray(pos_list, dtype=float)
        drone_ids = [str(d["id"]) for d in free_drones]
        k = positions.shape[0]

        # Preserve pheromone/history by drone id when free-drone membership/order changes.
        if self.pheromone_matrix is None or self.pheromone_matrix.shape[0] != len(grid_np):
            self.pheromone_matrix = np.ones((len(grid_np), k))
        elif self.pheromone_matrix.shape[1] != k or self._drone_order != drone_ids:
            remapped = np.ones((len(grid_np), k))
            old_index = {drone_id: idx for idx, drone_id in enumerate(self._drone_order)}
            for new_idx, drone_id in enumerate(drone_ids):
                idx = old_index.get(drone_id)
                if idx is not None and idx < self.pheromone_matrix.shape[1]:
                    remapped[:, new_idx] = self.pheromone_matrix[:, idx]
            self.pheromone_matrix = remapped

        # Keep previous-tick positions keyed by drone id to avoid state drifting
        # to the wrong drone when the free set changes.
        if self.old_centroids is None or self.old_centroids.shape[0] != len(self._drone_order):
            old_by_id: dict[str, np.ndarray] = {}
        else:
            old_by_id = {
                drone_id: self.old_centroids[idx]
                for idx, drone_id in enumerate(self._drone_order)
            }
        self.old_centroids = np.vstack(
            [old_by_id.get(drone_id, positions[idx]) for idx, drone_id in enumerate(drone_ids)]
        )
        self._drone_order = drone_ids

        new_centroids, _, self.pheromone_matrix = lloyd_step_aco(
            grid_np,
            positions,
            self.old_centroids,
            self.pheromone_matrix,
            rng=mission.get("_np_rng", self._np_rng),
        )

        self.old_centroids = positions.copy()

        for drone, centroid in zip(free_drones, new_centroids):
            # Ensure we return standard Python floats, not numpy types, so it's JSON serializable
            centroid_map[drone["id"]] = (float(centroid[0]), float(centroid[1]))
            
        return centroid_map

class VoronoiCoverage(BaseSearchAlgorithm):
    algorithm_key = "voronoi"
    display_name = "Voronoi (Lloyd's)"
    description = "Lloyd-relaxed Voronoi centroid positioning."
    display_order = 10

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
