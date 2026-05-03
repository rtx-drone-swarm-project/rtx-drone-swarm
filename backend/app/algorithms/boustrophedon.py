"""Voronoi-partitioned boustrophedon (lawnmower) coverage.

Design
------
Layer 1 — Balanced Voronoi partition:
    A grid at DETECTION_RADIUS spacing is built from the mission bounds and
    Voronoi-assigned to k EVENLY-SPACED PARTITION SEEDS (NOT drone positions).
    Drones are then matched to cells by greedy nearest-neighbor. This produces
    equal-area cells for any drone count, including the small-N (2-4 drones)
    case where drones often start clustered at the dispatch home.

Layer 2 — Deploy-then-sweep:
    Phase A (en_route): the first waypoint is the drone's cell centroid, so each
    drone first flies to the middle of its partition before searching.
    Phase B (sweeping): row-endpoint lawnmower. For each latitude row two waypoints
    are emitted: (lat, min_lon) and (lat, max_lon). The drone sweeps the full row
    in continuous flight; the simulation detects targets within DETECTION_RADIUS
    every tick, so coverage is identical to navigating every grid point but waypoint
    count drops from O(N_rows × N_cols) to O(N_rows × 2). Phase transitions and
    completion are logged per drone.

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

from app.algorithms.base import BaseSearchAlgorithm, DETECTION_RADIUS, build_dense_coverage_grid
from app.models import Mission

logger = logging.getLogger(__name__)

# Waypoint is consumed when the drone is within this distance of it.
# DETECTION_RADIUS (0.002) >> TARGET_STOP_RADIUS in simulation.py (0.00055),
# so the simulation stops the drone first and we pop on the very next tick.
_REACH_RADIUS = DETECTION_RADIUS


def _voronoi_assign(grid: np.ndarray, seed_positions: np.ndarray) -> np.ndarray:
    """Label each grid point with the index of its nearest seed."""
    distances = np.linalg.norm(grid[:, np.newaxis] - seed_positions, axis=2)
    return np.argmin(distances, axis=1)


def _balanced_partition_seeds(bounds: dict, k: int) -> np.ndarray:
    """k partition seed points distributed to match the bounds aspect ratio.

    Rows and cols are chosen so each cell is roughly square in lat/lon space,
    minimising elongated partitions that force drones to fly long rows.
    Cells are equal-area regardless of where drones happen to start.
    """
    if k <= 0:
        return np.empty((0, 2))
    if k == 1:
        # Single drone: sit at the bounds center.
        return np.array([[
            (bounds["min_lat"] + bounds["max_lat"]) / 2,
            (bounds["min_lon"] + bounds["max_lon"]) / 2,
        ]])

    height = max(bounds["max_lat"] - bounds["min_lat"], 1e-9)
    width = max(bounds["max_lon"] - bounds["min_lon"], 1e-9)
    aspect = width / height  # >1 → wider than tall → prefer more columns

    # Pick cols so cell aspect ≈ 1:1:  cols/rows ≈ aspect, rows*cols ≈ k
    cols = max(1, int(round(math.sqrt(k * aspect))))
    rows = math.ceil(k / cols)
    # If the product overshoots significantly, try shrinking to avoid big empty gaps.
    while rows * cols - k >= cols and rows > 1:
        rows -= 1
        cols = math.ceil(k / rows)

    lat_step = height / rows
    lon_step = width / cols

    seeds = []
    for r in range(rows):
        for c in range(cols):
            seeds.append([
                bounds["min_lat"] + (r + 0.5) * lat_step,
                bounds["min_lon"] + (c + 0.5) * lon_step,
            ])
            if len(seeds) == k:
                return np.array(seeds)
    return np.array(seeds[:k])


def _match_drones_to_seeds(
    drone_positions: np.ndarray, seeds: np.ndarray
) -> List[int]:
    """Greedy nearest-neighbor matching: returns seed_index for each drone.

    Each seed is claimed by exactly one drone. Greedy is fine here — for SAR
    with k < 20 drones the optimum vs greedy difference is negligible and
    keeps the code obvious.
    """
    if len(drone_positions) == 0 or len(seeds) == 0:
        return []

    dists = np.linalg.norm(drone_positions[:, np.newaxis] - seeds, axis=2)
    drone_to_seed: List[int] = [-1] * len(drone_positions)
    used_seeds: set = set()

    flat = [(dists[d, s], d, s) for d in range(len(drone_positions)) for s in range(len(seeds))]
    flat.sort(key=lambda x: x[0])
    for _, d, s in flat:
        if drone_to_seed[d] != -1 or s in used_seeds:
            continue
        drone_to_seed[d] = s
        used_seeds.add(s)
        if all(x != -1 for x in drone_to_seed):
            break
    return drone_to_seed


_build_dense_grid = build_dense_coverage_grid


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

    def _initialize_paths(self, mission: Mission) -> None:
        all_drones = mission.drones
        bounds = mission.bounds
        if not all_drones or not bounds:
            return

        k = len(all_drones)
        dense_grid = _build_dense_grid(bounds)

        # Partition is derived from bounds, not drone positions, so cells are
        # always equal-area regardless of how drones spawned/clustered.
        seeds = _balanced_partition_seeds(bounds, k)
        labels = _voronoi_assign(dense_grid, seeds)

        # Each drone gets the cell whose seed it's closest to.
        drone_positions = np.array([[d.get("lat", 0.0), d.get("lon", 0.0)] for d in all_drones])
        drone_to_seed = _match_drones_to_seeds(drone_positions, seeds)

        sweep_paths: Dict[str, List[Tuple[float, float]]] = {}
        sweep_centroids: Dict[str, Tuple[float, float]] = {}
        sweep_phase: Dict[str, str] = {}

        for drone, seed_idx in zip(all_drones, drone_to_seed):
            cell_points = dense_grid[labels == seed_idx]
            lawnmower = _row_endpoints_lawnmower(cell_points)

            if len(cell_points) > 0:
                centroid = (float(cell_points[:, 0].mean()), float(cell_points[:, 1].mean()))
            else:
                centroid = (float(seeds[seed_idx, 0]), float(seeds[seed_idx, 1]))

            # Deploy-then-sweep: centroid is the first waypoint, then lawnmower.
            path = [centroid, *lawnmower]
            sweep_paths[drone["id"]] = path
            sweep_centroids[drone["id"]] = centroid
            sweep_phase[drone["id"]] = "en_route"

            # Expose centroid on the drone object so telemetry broadcasts carry it.
            drone["sweep_centroid"] = [centroid[0], centroid[1]]
            drone["sweep_phase"] = "en_route"

            logger.info(
                "sweep | %s: cell %d (%d dense pts), centroid (%.5f, %.5f), en route to centroid",
                drone["id"], seed_idx, len(cell_points), centroid[0], centroid[1],
            )

        mission.sweep_paths = sweep_paths
        mission.sweep_centroids = sweep_centroids
        mission.sweep_phase = sweep_phase
        mission.sweep_reached_radius = _REACH_RADIUS

    def get_target_waypoints(
        self, mission: Mission, free_drones: List[dict]
    ) -> Dict[str, Tuple[float, float]]:
        if not free_drones:
            return {}
            
        if not mission.sweep_paths:
            self._initialize_paths(mission)

        sweep_paths: Dict[str, List[Tuple[float, float]]] = mission.sweep_paths
        sweep_phase: Dict[str, str] = mission.sweep_phase
        reached_radius: float = mission.sweep_reached_radius
        waypoint_map: Dict[str, Tuple[float, float]] = {}

        for drone in free_drones:
            drone_id = drone["id"]
            path = sweep_paths.get(drone_id, [])
            phase = sweep_phase.get(drone_id, "en_route")

            dlat = drone.get("lat", 0.0)
            dlon = drone.get("lon", 0.0)

            consumed = 0
            while path and math.hypot(dlat - path[0][0], dlon - path[0][1]) < reached_radius:
                path.pop(0)
                consumed += 1
                # First waypoint consumed == drone arrived at centroid → switch to sweeping
                if phase == "en_route":
                    phase = "sweeping"
                    sweep_phase[drone_id] = phase
                    drone["sweep_phase"] = phase
                    logger.info(
                        "sweep | %s: reached centroid — beginning lawnmower sweep "
                        "(%d row-endpoint waypoints remaining)",
                        drone_id, len(path),
                    )

            if consumed and phase == "sweeping":
                logger.debug(
                    "sweep | %s: consumed %d waypoint(s), %d remaining",
                    drone_id, consumed, len(path),
                )

            if not path:
                if sweep_phase.get(drone_id) != "complete":
                    sweep_phase[drone_id] = "complete"
                    drone["sweep_phase"] = "complete"
                    logger.info("sweep | %s: partition fully swept, drone idle", drone_id)
                continue

            waypoint_map[drone_id] = (float(path[0][0]), float(path[0][1]))
            logger.debug(
                "sweep | %s [%s]: targeting (%.5f, %.5f)",
                drone_id, phase, path[0][0], path[0][1],
            )

        return waypoint_map
