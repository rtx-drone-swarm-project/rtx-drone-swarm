"""Voronoi-partitioned boustrophedon (lawnmower) coverage.

Design
------
Layer 1 — Voronoi partition (dense):
    A grid at DETECTION_RADIUS spacing is built directly from the mission bounds.
    Every cell is assigned to exactly one drone (nearest-neighbor Voronoi).
    This tiles the full search area with no gaps and no overlaps regardless of
    drone starting positions.

Layer 2 — Row-endpoint lawnmower sweep:
    For each latitude row in the drone's Voronoi cell we emit exactly two waypoints:
    (lat, min_lon) and (lat, max_lon). The drone sweeps the full row in continuous
    flight; the simulation detects targets within DETECTION_RADIUS at every tick,
    so coverage is identical to navigating every grid point but waypoint count drops
    from O(N_rows × N_cols) to O(N_rows × 2). This keeps large partitions tractable.

Why not bbox?
    The old approach computed each drone's bounding box from the sparse 15×15
    coverage grid (spacing ~0.007°). Adjacent bboxes ended at their outermost
    sparse grid point, leaving a ~0.007° = 3.5× DETECTION_RADIUS gap between
    them that was never swept.
"""

import logging
import math
from typing import Dict, List, Tuple

import numpy as np

from app.algorithms.base import BaseSearchAlgorithm, DETECTION_RADIUS

logger = logging.getLogger(__name__)

# Waypoint is consumed when the drone is within this distance of it.
# DETECTION_RADIUS (0.002) >> TARGET_STOP_RADIUS in simulation.py (0.00055),
# so the simulation stops the drone first and we pop on the very next tick.
_REACH_RADIUS = DETECTION_RADIUS


def _voronoi_assign(grid: np.ndarray, drone_positions: np.ndarray) -> np.ndarray:
    """Label each grid point with the index of its nearest drone."""
    distances = np.linalg.norm(grid[:, np.newaxis] - drone_positions, axis=2)
    return np.argmin(distances, axis=1)


def _build_dense_grid(bounds: dict) -> np.ndarray:
    """Dense grid at DETECTION_RADIUS spacing covering the full search bounds."""
    lats = np.arange(
        bounds["min_lat"],
        bounds["max_lat"] + DETECTION_RADIUS * 0.01,
        DETECTION_RADIUS,
    )
    lons = np.arange(
        bounds["min_lon"],
        bounds["max_lon"] + DETECTION_RADIUS * 0.01,
        DETECTION_RADIUS,
    )
    ll, lo = np.meshgrid(lats, lons)
    return np.column_stack([ll.ravel(), lo.ravel()])


def _row_endpoints_lawnmower(cell_points: np.ndarray) -> List[Tuple[float, float]]:
    """Two-endpoint boustrophedon path through a Voronoi cell.

    Instead of navigating every dense-grid point individually (O(N_rows * N_cols)
    waypoints, very slow for large cells), this emits only the start and end of
    each latitude row: (lat, min_lon) and (lat, max_lon). The drone sweeps the
    full row in continuous flight and the simulation detects targets within
    DETECTION_RADIUS at every tick, so coverage is identical but waypoint count
    drops to O(N_rows * 2).

    This also handles irregular Voronoi cells correctly: each row's longitude
    extent is computed from the actual assigned grid points, so the drone never
    overshoots into a neighbouring drone's region.
    """
    if len(cell_points) == 0:
        return []

    tol = DETECTION_RADIUS * 0.1
    rounded = np.round(cell_points[:, 0], 8)
    unique_lats = sorted(set(rounded.tolist()))

    path: List[Tuple[float, float]] = []
    for row_idx, lat in enumerate(unique_lats):
        mask = np.abs(cell_points[:, 0] - lat) < tol
        row = cell_points[mask]
        min_lon = float(row[:, 1].min())
        max_lon = float(row[:, 1].max())
        if row_idx % 2 == 0:
            path.append((lat, min_lon))
            path.append((lat, max_lon))
        else:
            path.append((lat, max_lon))
            path.append((lat, min_lon))
    return path


class VoronoiBoustrophedon(BaseSearchAlgorithm):
    """Voronoi partitioning (dense grid) + per-cell lawnmower coverage."""

    def _initialize_paths(self, mission: dict) -> None:
        all_drones = mission.get("drones", [])
        bounds = mission.get("bounds")
        if not all_drones or not bounds:
            return

        dense_grid = _build_dense_grid(bounds)
        positions = np.array([[d.get("lat", 0.0), d.get("lon", 0.0)] for d in all_drones])
        labels = _voronoi_assign(dense_grid, positions)

        sweep_paths: Dict[str, List[Tuple[float, float]]] = {}
        for i, drone in enumerate(all_drones):
            cell_points = dense_grid[labels == i]
            path = _row_endpoints_lawnmower(cell_points)
            sweep_paths[drone["id"]] = path
            logger.info(
                "sweep | %s: %d dense-grid points → %d row-endpoint waypoints",
                drone["id"], len(cell_points), len(path),
            )

        mission["sweep_paths"] = sweep_paths
        mission["sweep_reached_radius"] = _REACH_RADIUS

    def get_target_waypoints(
        self, mission: dict, free_drones: List[dict]
    ) -> Dict[str, Tuple[float, float]]:
        if not free_drones:
            return {}

        if "sweep_paths" not in mission:
            self._initialize_paths(mission)

        sweep_paths: Dict[str, List[Tuple[float, float]]] = mission.get("sweep_paths", {})
        reached_radius: float = mission.get("sweep_reached_radius", _REACH_RADIUS)
        waypoint_map: Dict[str, Tuple[float, float]] = {}

        for drone in free_drones:
            drone_id = drone["id"]
            path = sweep_paths.get(drone_id, [])

            dlat = drone.get("lat", 0.0)
            dlon = drone.get("lon", 0.0)

            consumed = 0
            while path and math.hypot(dlat - path[0][0], dlon - path[0][1]) < reached_radius:
                path.pop(0)
                consumed += 1
            if consumed:
                logger.debug(
                    "sweep | %s: consumed %d waypoint(s), %d remaining",
                    drone_id, consumed, len(path),
                )

            if not path:
                logger.info("sweep | %s: partition fully swept, drone idle", drone_id)
                continue

            waypoint_map[drone_id] = (float(path[0][0]), float(path[0][1]))
            logger.debug("sweep | %s: targeting (%.5f, %.5f)", drone_id, path[0][0], path[0][1])

        return waypoint_map
