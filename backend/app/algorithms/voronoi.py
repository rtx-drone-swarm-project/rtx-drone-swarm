import math
import numpy as np
import pyned2lla
from typing import List, Dict, Tuple
from app.algorithms.base import BaseSearchAlgorithm, build_dense_coverage_grid
from app.algorithms.boustrophedon import _balanced_partition_seeds, _match_drones_to_seeds
from app.models import Mission

def lloyd_step(grid_points: np.ndarray, centroids: np.ndarray, bounds):
    """
    One iteration of Lloyd's algorithm in 2D lat/lon space.
    """
    D2R = math.pi/180
    R2D = 180/math.pi
    lat = bounds["min_lat"]
    lon = bounds["min_lon"]

    for i in range(len(centroids)):
        centroids[i] = pyned2lla.lla2ned(lat*D2R, lon*D2R, 0, centroids[i][0]*D2R, centroids[i][1]*D2R, 0, pyned2lla.wgs84())[:2] # convert to NED coordinates

    k = len(centroids) # number of centroids

    distances = np.linalg.norm(grid_points[:, np.newaxis] - centroids, axis=2) # compute distances from points to centroids
    labels = np.argmin(distances, axis=1) # assign points to nearest centroid

    new_centroids = []

    for i in range(k): # compute new centroid for each
        cluster_points = grid_points[labels == i]

        if len(cluster_points) > 0: # if cluster has points, move towards mean, else random point in subregion
            target = cluster_points.mean(axis=0)
        else:
            target = grid_points[np.random.randint(0, len(grid_points))]

        new_centroids.append(target)

    new_centroids = np.array(new_centroids)

    for i in range(len(centroids)):
        centroids[i] = pyned2lla.ned2lla(lat*D2R, lon*D2R, 0, new_centroids[i][0], new_centroids[i][1], 0, pyned2lla.wgs84())[:2] # convert back to lat/lon

    centroids *= R2D # convert to degrees
        
    return centroids, labels

def _rng_int(rng, high: int) -> int:
    if hasattr(rng, "integers"):
        return int(rng.integers(0, high))
    if hasattr(rng, "randrange"):
        return int(rng.randrange(high))
    if high <= 0:
        return 0
    return int(rng.randint(0, high - 1))


def lloyd_step_aco(X, centroids, old_centroids, pheromone, bounds, decay=0.9, deposit=0.5, rng=None):
    D2R = math.pi/180
    R2D = 180/math.pi
    lat = bounds["min_lat"]
    lon = bounds["min_lon"]

    for i in range(len(centroids)):
        centroids[i] = pyned2lla.lla2ned(lat*D2R, lon*D2R, 0, centroids[i][0]*D2R, centroids[i][1]*D2R, 0, pyned2lla.wgs84())[:2] # convert to NED coordinates

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

    for i in range(len(centroids)):
        centroids[i] = pyned2lla.ned2lla(lat*D2R, lon*D2R, 0, new_centroids[i][0], new_centroids[i][1], 0, pyned2lla.wgs84())[:2] # convert back to lat/lon

    centroids *= R2D # convert to degrees

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

    def initialize(self, mission: Mission) -> None:
        """Run once when the mission starts.

        Centroid and pheromone state are sized on the first tick from ``free_drones``
        (same count as ``lloyd_step_aco`` centroids), matching ``voronoi_vis.py`` setup
        where the pheromone matrix is ``(len(grid), k)`` for k active centroids.
        """
        self._reset_state()

    def get_target_waypoints(self, mission: Mission, free_drones: List[dict]) -> Dict[str, Tuple[float, float]]:
        """Run every simulation tick to get the next Voronoi centroid."""
        centroid_map = {}
        if not free_drones:
            return centroid_map

        raw_grid = getattr(mission, "grid", None)
        if raw_grid is None and isinstance(mission, dict):
            raw_grid = mission.get("grid")
        if raw_grid is None:
            return centroid_map

        grid_np = np.array(raw_grid)
        if grid_np.size == 0:
            return centroid_map

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
            mission.bounds,
            rng=getattr(mission, "_np_rng", self._np_rng),
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

    def initialize(self, mission: Mission) -> None:
        """Run once when the mission starts to generate the search grid."""
        if isinstance(mission, dict):
            mission.pop("virtual_centroids", None)
            bounds = mission.get("bounds")
            if bounds:
                mission["grid"] = build_dense_coverage_grid(bounds).tolist()
            return
        if hasattr(mission, "virtual_centroids"):
            delattr(mission, "virtual_centroids")
        if mission.bounds:
            mission.grid = build_dense_coverage_grid(mission.bounds)

    def get_target_waypoints(self, mission: Mission, free_drones: List[dict]) -> Dict[str, Tuple[float, float]]:
        """Run every simulation tick to get the next Voronoi centroid."""
        centroid_map = {}
        if not free_drones:
            return centroid_map

        raw_grid = getattr(mission, "grid", None)
        if raw_grid is None and isinstance(mission, dict):
            raw_grid = mission.get("grid")
        bounds = getattr(mission, "bounds", None)
        if bounds is None and isinstance(mission, dict):
            bounds = mission.get("bounds")

        if raw_grid is None:
            return centroid_map

        grid_np = np.array(raw_grid)
        if grid_np.size == 0:
            return centroid_map
        k = len(free_drones)

        # Initialize virtual centroids
        # If they don't exist yet, or if a drone dropped out and swarm size changed
        current_virtual = getattr(mission, "virtual_centroids", None)
        if current_virtual is None and isinstance(mission, dict):
            current_virtual = mission.get("virtual_centroids")
        if current_virtual is None or len(current_virtual) != k:
            if not bounds:
                return centroid_map
            seeds = _balanced_partition_seeds(bounds, k)
            virtual_np = seeds
            for _ in range(100):
                virtual_np, _ = lloyd_step(grid_np, virtual_np, bounds)
            if isinstance(mission, dict):
                mission["virtual_centroids"] = virtual_np.tolist()
            else:
                setattr(mission, "virtual_centroids", virtual_np.tolist())
            current_virtual = virtual_np.tolist()

        virtual_np = np.array(current_virtual)


        new_centroids, _ = lloyd_step(grid_np, virtual_np, mission.bounds)
        
        # Save the updated optimized points back into the mission dictionary
        if isinstance(mission, dict):
            mission["virtual_centroids"] = new_centroids.tolist()
        else:
            setattr(mission, "virtual_centroids", new_centroids.tolist())

        # Extract the current physical locations of the drones
        drone_positions = np.array([[d.get("lat", 0.0), d.get("lon", 0.0)] for d in free_drones])
        
        # Use greedy nearest-neighbor matching
        drone_to_seed_indices = _match_drones_to_seeds(drone_positions, new_centroids)

        # Build the final waypoint map
        for drone, seed_idx in zip(free_drones, drone_to_seed_indices):
            target = new_centroids[seed_idx]
            centroid_map[drone["id"]] = (float(target[0]), float(target[1]))
            
        return centroid_map
