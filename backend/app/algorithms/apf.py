import math
import random
from typing import List, Dict, Tuple

import numpy as np

from app.algorithms.base import BaseSearchAlgorithm, DETECTION_RADIUS, build_dense_coverage_grid
from app.models import Mission


def _getm(mission, key: str, default=None):
    """Uniform attribute access for both Mission dataclass and benchmark AttrDict."""
    if isinstance(mission, dict):
        return mission.get(key, default)
    return getattr(mission, key, default)


def _setm(mission, key: str, value) -> None:
    """Uniform attribute setter for both Mission dataclass and benchmark AttrDict."""
    if isinstance(mission, dict):
        mission[key] = value
    else:
        setattr(mission, key, value)


class PotentialFieldsCoverage(BaseSearchAlgorithm):
    algorithm_key = "apf"
    display_name = "APF (Potential Fields)"
    description = "Artificial potential fields with drone and boundary repulsion."
    display_order = 30

    def initialize(self, mission: Mission) -> None:
        bounds = _getm(mission, "bounds", {})
        if not bounds:
            return

        # Build the dense coverage grid for exploration tracking.
        dense_grid = build_dense_coverage_grid(bounds)
        _setm(mission, "apf_dense_grid", dense_grid)

        # Track which cells have been visited — namespaced to avoid conflicts
        # with simulation.py's own coverage tracking.
        _setm(mission, "apf_covered_cells", set())

        # Per-drone last-known positions for wanderlust / stagnation detection.
        _setm(mission, "apf_last_positions", {})

        # Per-drone wanderlust multiplier — starts at 1.0, grows when stagnant.
        _setm(mission, "apf_wanderlust", {})

    def get_target_waypoints(self, mission, free_drones: List[dict]) -> Dict[str, Tuple[float, float]]:
        waypoint_map = {}
        if not free_drones:
            return waypoint_map

        bounds = mission.bounds
        rng = getattr(mission, "_rng", random)

        # --- Integrated Hyperparameters ---
        STEP_SIZE = 0.001                 # How far to place the next waypoint
        
        # Stateful Exploration (From your logic)
        REPULSION_DRONE = 0.0006          # Spreads drones out
        REPULSION_BBOX = 0.0005           # Bounding box push-back
        ATTRACTION_COVERAGE = 0.0003      # Pull toward unvisited cells
        STAGNATION_RADIUS = 0.001         # Wanderlust trigger
        DETECTION_RADIUS = 0.005          # Radius for marking cells as covered
        
        # Priority & Exclusion (From previous step)
        REPULSION_EXCLUDED = 0.40         # Hard Wall for exclusion zones (Label 5)
        ATTRACTION_PRIORITY = 0.005       # Pull toward hotspots
        EXCLUSION_RADIUS = 0.025          # Distance at which the exclusion wall pushes

        # --- Priority & Exclusion Dynamic Data ---
        prob_flat = getattr(mission, "probability_grid", None) 
        grid_coords = getattr(mission, "grid", None) 
        grid_shape = getattr(mission, "grid_shape", (18, 21)) 

        hotspots = []
        exclusions = [] 

        if prob_flat is not None and grid_coords is not None:
            try:
                prob_grid = prob_flat.reshape(grid_shape) 
                rows, cols = prob_grid.shape
                for r in range(rows):
                    for c in range(cols):
                        val = prob_grid[r, c]
                        idx = r * cols + c
                        if idx < len(grid_coords):
                            pos = grid_coords[idx]
                            if val <= 0.0001: 
                                exclusions.append(pos)
                            else:
                                hotspots.append((pos, val))
            except Exception:
                pass # Graceful degradation to purely exploratory search if shape mismatches

        # --- Lazy-init if initialize() was never called ---
        dense_grid = _getm(mission, "apf_dense_grid")
        if dense_grid is None:
            self.initialize(mission)
            dense_grid = _getm(mission, "apf_dense_grid")
        dense_grid = np.asarray(dense_grid, dtype=float)

        covered_cells = _getm(mission, "apf_covered_cells")
        if covered_cells is None:
            covered_cells = set()
            _setm(mission, "apf_covered_cells", covered_cells)

        last_positions = _getm(mission, "apf_last_positions")
        if last_positions is None:
            last_positions = {}
            _setm(mission, "apf_last_positions", last_positions)

        wanderlust = _getm(mission, "apf_wanderlust")
        if wanderlust is None:
            wanderlust = {}
            _setm(mission, "apf_wanderlust", wanderlust)

        # --- Coverage tracking: mark cells near each drone as visited ---
        for drone in free_drones:
            dlat = drone.get("lat", 0.0)
            dlon = drone.get("lon", 0.0)
            lat_mask = np.abs(dense_grid[:, 0] - dlat) <= DETECTION_RADIUS
            lon_mask = np.abs(dense_grid[:, 1] - dlon) <= DETECTION_RADIUS
            candidates = np.where(lat_mask & lon_mask)[0]
            if len(candidates) > 0:
                sub = dense_grid[candidates]
                within = candidates[
                    np.hypot(sub[:, 0] - dlat, sub[:, 1] - dlon) <= DETECTION_RADIUS
                ]
                covered_cells.update(int(i) for i in within)

        # --- Pre-compute unvisited cell indices and positions ---
        all_indices = np.arange(len(dense_grid))
        covered_mask = np.zeros(len(dense_grid), dtype=bool)
        if covered_cells:
            covered_arr = np.array(list(covered_cells), dtype=int)
            covered_mask[covered_arr] = True
        unvisited_mask = ~covered_mask
        unvisited_indices = all_indices[unvisited_mask]
        unvisited_points = dense_grid[unvisited_mask] if len(unvisited_indices) > 0 else np.empty((0, 2))

        for i, drone in enumerate(free_drones):
            dlat = drone.get("lat", 0.0)
            dlon = drone.get("lon", 0.0)
            drone_id = drone["id"]

            force_lat = 0.0
            force_lon = 0.0

            # 1. Repel from other drones (Spread out!)
            for j, other_drone in enumerate(free_drones):
                if i == j:
                    continue
                olat = other_drone.get("lat", 0.0)
                olon = other_drone.get("lon", 0.0)
                dist = math.hypot(dlat - olat, dlon - olon)
                if 0.0001 < dist < 0.02: 
                    mag = REPULSION_DRONE / (dist**2)
                    force_lat += mag * (dlat - olat) / dist
                    force_lon += mag * (dlon - olon) / dist

            # 2. Repel from Bounding Box Walls (Stay in bounds!)
            dist_north = max(0.0001, bounds["max_lat"] - dlat)
            dist_south = max(0.0001, dlat - bounds["min_lat"])
            dist_east = max(0.0001, bounds["max_lon"] - dlon)
            dist_west = max(0.0001, dlon - bounds["min_lon"])

            force_lat -= REPULSION_BBOX / (dist_north**2)  
            force_lat += REPULSION_BBOX / (dist_south**2)  
            force_lon -= REPULSION_BBOX / (dist_east**2)   
            force_lon += REPULSION_BBOX / (dist_west**2)   

            # 3. NEW: Hard Wall Repulsion (Exclusion Zones)
            for ex_lat, ex_lon in exclusions:
                dist = math.hypot(dlat - ex_lat, dlon - ex_lon)
                if dist < EXCLUSION_RADIUS:
                    dist = max(dist, 0.0002) 
                    mag = REPULSION_EXCLUDED / (dist**4) 
                    force_lat += mag * (dlat - ex_lat) / dist
                    force_lon += mag * (dlon - ex_lon) / dist

            # 4. NEW: Priority Attraction (Hotspots)
            for (h_lat, h_lon), priority in hotspots:
                dist = math.hypot(dlat - h_lat, dlon - h_lon)
                if dist > 0.0001:
                    mag = (ATTRACTION_PRIORITY * (priority)) / (dist + 0.07)
                    force_lat += mag * (h_lat - dlat) / dist
                    force_lon += mag * (h_lon - dlon) / dist

            # 5. Exploration attraction: pull toward nearest unvisited cluster
            if len(unvisited_points) > 0:
                dists_to_unvisited = np.hypot(
                    unvisited_points[:, 0] - dlat,
                    unvisited_points[:, 1] - dlon,
                )
                k_nearest = min(10, len(unvisited_points))
                kth = k_nearest - 1
                nearest_idx = np.argpartition(dists_to_unvisited, kth)[:k_nearest]
                cluster_center = unvisited_points[nearest_idx].mean(axis=0)

                attract_dlat = cluster_center[0] - dlat
                attract_dlon = cluster_center[1] - dlon
                attract_dist = math.hypot(attract_dlat, attract_dlon)

                if attract_dist > 1e-9:
                    wl = wanderlust.get(drone_id, 1.0)
                    attract_mag = ATTRACTION_COVERAGE * wl
                    force_lat += attract_mag * (attract_dlat / attract_dist)
                    force_lon += attract_mag * (attract_dlon / attract_dist)

            # 6. Update wanderlust
            last_pos = last_positions.get(drone_id)
            if last_pos is not None:
                moved = math.hypot(dlat - last_pos[0], dlon - last_pos[1])
                if moved < STAGNATION_RADIUS:
                    wanderlust[drone_id] = min(5.0, wanderlust.get(drone_id, 1.0) + 0.1)
                else:
                    wanderlust[drone_id] = max(1.0, wanderlust.get(drone_id, 1.0) - 0.05)
            else:
                wanderlust[drone_id] = 1.0
            last_positions[drone_id] = (dlat, dlon)

            # 7. Random Jitter
            force_lat += rng.uniform(-0.0001, 0.0001)
            force_lon += rng.uniform(-0.0001, 0.0001)

            # 8. Calculate final waypoint
            force_mag = math.hypot(force_lat, force_lon)
            if force_mag > 0:
                step_lat = (force_lat / force_mag) * STEP_SIZE
                step_lon = (force_lon / force_mag) * STEP_SIZE
            else:
                step_lat, step_lon = 0, 0

            target_lat = max(bounds["min_lat"], min(bounds["max_lat"], dlat + step_lat))
            target_lon = max(bounds["min_lon"], min(bounds["max_lon"], dlon + step_lon))

            waypoint_map[drone["id"]] = (float(target_lat), float(target_lon))

        return waypoint_map