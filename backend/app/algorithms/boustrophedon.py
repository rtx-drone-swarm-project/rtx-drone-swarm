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
    count drops from O(N_rows * N_cols) to O(N_rows * 2). Phase transitions and
    completion are logged per drone.

Why not bbox?
    The old approach computed each drone's bounding box from the sparse 15*15
    coverage grid (spacing ~0.007°). Adjacent bboxes ended at their outermost
    sparse grid point, leaving a ~0.007° = 3.5x DETECTION_RADIUS gap between
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
# DETECTION_RADIUS (0.002) >> TARGET_STOP_RADIUS in simulation.py (0.00015),
# so the simulation stops the drone first and we pop on the very next tick.
_REACH_RADIUS = DETECTION_RADIUS
_SEED_LLOYD_ITERS = 8


def _voronoi_assign(grid: np.ndarray, seed_positions: np.ndarray) -> np.ndarray:
    """Label each grid point with the index of its nearest seed."""
    distances = np.linalg.norm(grid[:, np.newaxis] - seed_positions, axis=2)
    return np.argmin(distances, axis=1)


def _partition_shape(bounds: dict, k: int) -> tuple[int, int]:
    """Choose rows/cols for k seeds, preferring factor-aware, aspect-fit layouts.

    - If k has non-trivial factors, pick the exact rows * cols factorization that
      best matches the bounds aspect ratio.
    - Otherwise (prime/awkward k), pick a near-square oversubscribed layout
      using a combined slack + aspect-fit score.
    """
    if k <= 0:
        return (0, 0)
    if k == 1:
        return (1, 1)

    height = max(bounds["max_lat"] - bounds["min_lat"], 1e-9)
    width = max(bounds["max_lon"] - bounds["min_lon"], 1e-9)
    aspect = width / height  # ideal cols / rows

    def _shape_key(rows: int, cols: int, include_slack: bool) -> tuple[float, int, int, int]:
        ratio = max(cols / max(rows, 1), 1e-9)
        ratio_err = abs(math.log(ratio / aspect))
        orientation_penalty = 0
        if aspect >= 1.0 and cols < rows:
            orientation_penalty = 1
        if aspect < 1.0 and rows < cols:
            orientation_penalty = 1
        slack = rows * cols - k
        if include_slack:
            # Combined objective: low oversubscription + good aspect fit.
            # The k-normalized slack keeps the score scale stable across sizes.
            return (slack / max(k, 1) + ratio_err, orientation_penalty, abs(rows - cols), slack)
        return (ratio_err, orientation_penalty, abs(rows - cols), 0)

    exact: list[tuple[int, int]] = []
    for rows in range(2, int(math.sqrt(k)) + 1):
        if k % rows != 0:
            continue
        cols = k // rows
        exact.append((rows, cols))
        if rows != cols:
            exact.append((cols, rows))
    if exact:
        return min(exact, key=lambda rc: _shape_key(rc[0], rc[1], include_slack=False))

    candidates: list[tuple[int, int]] = []
    for rows in range(1, k + 1):
        cols = math.ceil(k / rows)
        candidates.append((rows, cols))
    return min(candidates, key=lambda rc: _shape_key(rc[0], rc[1], include_slack=True))


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

    rows, cols = _partition_shape(bounds, k)
    height = max(bounds["max_lat"] - bounds["min_lat"], 1e-9)
    width = max(bounds["max_lon"] - bounds["min_lon"], 1e-9)

    lat_step = height / rows
    lon_step = width / cols

    # How many seeds the last (possibly partial) row receives.
    full_rows = k // cols
    last_row_count = k % cols  # 0 means every row is full

    seeds = []
    for r in range(rows):
        if last_row_count == 0 or r < full_rows:
            # Full row: one seed per column, evenly spaced.
            for c in range(cols):
                seeds.append([
                    bounds["min_lat"] + (r + 0.5) * lat_step,
                    bounds["min_lon"] + (c + 0.5) * lon_step,
                ])
                if len(seeds) == k:
                    return np.array(seeds)
        else:
            # Partial last row: spread seeds evenly across the FULL row width
            # so each seed is centred in its own even sub-interval.
            # e.g. k=13, cols=4, last_row_count=1 → single seed at 50% lon.
            # e.g. k=10, cols=4, last_row_count=2 → seeds at 25% and 75% lon.
            m = last_row_count
            lat_centre = bounds["min_lat"] + (r + 0.5) * lat_step
            for j in range(m):
                lon_centre = bounds["min_lon"] + (j + 0.5) / m * width
                seeds.append([lat_centre, lon_centre])
                if len(seeds) == k:
                    return np.array(seeds)
    return np.array(seeds[:k])


def _lloyd_relax_seeds(dense_grid: np.ndarray, seeds: np.ndarray, n_iter: int) -> np.ndarray:
    """Run n Lloyd passes so seed layout reflects Voronoi cell centroids."""
    if n_iter <= 0 or len(seeds) <= 1:
        return seeds
    relaxed = seeds.copy()
    for _ in range(n_iter):
        labels = _voronoi_assign(dense_grid, relaxed)
        updated = np.empty_like(relaxed)
        for i in range(len(relaxed)):
            cell = dense_grid[labels == i]
            updated[i] = cell.mean(axis=0) if len(cell) > 0 else relaxed[i]
        relaxed = updated
    return relaxed


def _partition_seeds(
    bounds: dict,
    k: int,
    *,
    lloyd_iters: int = 0,
    dense_grid: np.ndarray | None = None,
) -> np.ndarray:
    """Generate partition seeds with optional Lloyd relaxation."""
    seeds = _balanced_partition_seeds(bounds, k)
    if lloyd_iters <= 0 or len(seeds) <= 1:
        return seeds
    grid = dense_grid if dense_grid is not None else _build_dense_grid(bounds)
    return _lloyd_relax_seeds(grid, seeds, lloyd_iters)


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
    algorithm_key = "sweep"
    display_name = "Sweep (Voronoi + Lawnmower)"
    description = "Balanced Voronoi partitions with boustrophedon coverage paths."
    display_order = 40

    def _initialize_paths(self, mission: Mission) -> None:
        all_drones = mission.drones
        bounds = mission.bounds
        if not all_drones or not bounds:
            return

        k = len(all_drones)
        dense_grid = _build_dense_grid(bounds)

        # Partition is derived from bounds, not drone positions, so cells are
        # always equal-area regardless of how drones spawned/clustered.
        seeds = _partition_seeds(
            bounds,
            k,
            lloyd_iters=_SEED_LLOYD_ITERS,
            dense_grid=dense_grid,
        )
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

                # Post-completion assistance: steal half the remaining path
                # from the drone with the most work left so idle drones
                # contribute to overall coverage instead of parking.
                path = self._steal_remaining_work(
                    drone_id, sweep_paths, sweep_phase,
                )
                if path:
                    sweep_paths[drone_id] = path
                    sweep_phase[drone_id] = "assisting"
                    drone["sweep_phase"] = "assisting"
                    logger.info(
                        "sweep | %s: assisting — took %d waypoints from busiest drone",
                        drone_id, len(path),
                    )

            if not path:
                continue

            waypoint_map[drone_id] = (float(path[0][0]), float(path[0][1]))
            logger.debug(
                "sweep | %s [%s]: targeting (%.5f, %.5f)",
                drone_id, phase, path[0][0], path[0][1],
            )

        return waypoint_map

    @staticmethod
    def _steal_remaining_work(
        idle_drone_id: str,
        sweep_paths: Dict[str, List[Tuple[float, float]]],
        sweep_phase: Dict[str, str],
    ) -> List[Tuple[float, float]]:
        """Find the drone with the most remaining waypoints and take half its path.

        This ensures idle drones don't sit around while other drones are
        still sweeping large partitions.  The stolen segment is always the
        *second* half so the donor keeps its immediate next waypoints and
        the idle drone flies to a new area.
        """
        busiest_id: str | None = None
        busiest_len = 0
        for did, path in sweep_paths.items():
            if did == idle_drone_id:
                continue
            phase = sweep_phase.get(did, "")
            if phase in ("complete", "assisting") and not path:
                continue
            if len(path) > busiest_len:
                busiest_len = len(path)
                busiest_id = did

        # Only steal if the donor has enough work to share (at least 6
        # waypoints = 3 row sweeps).
        if busiest_id is None or busiest_len < 6:
            return []

        donor_path = sweep_paths[busiest_id]
        split_point = busiest_len // 2
        stolen = donor_path[split_point:]
        sweep_paths[busiest_id] = donor_path[:split_point]

        logger.info(
            "sweep | %s: donated %d waypoints to %s (%d remaining)",
            busiest_id, len(stolen), idle_drone_id,
            len(sweep_paths[busiest_id]),
        )
        return stolen

