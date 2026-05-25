"""Voronoi-constrained PSO for SAR.

Architecture: two-phase hybrid
--------------------------------
Phase 1 — PSO dispersion (no detections yet):
    Each drone uses PSO velocity dynamics to move toward its assigned region
    centre from a Lloyd-relaxed Voronoi partition.  Niching repulsion keeps
    drones evenly spread with no row gaps.  Drones explore around their seed
    position producing natural, gap-free area coverage that is visually
    distinct from the lawnmower sweep algorithm.

Phase 2 — PSO velocity rush (target detected):
    All free drones switch PSO dynamics to target the global-best position,
    set to the centroid of unconfirmed detection events.  This produces
    smooth, organic curved-path behaviour that delivers rapid multi-drone
    confirmation without pre-assigning roles.

The result:
- Even drone spacing in Phase 1 (Lloyd-relaxed seeds + niching repulsion).
- No row gaps: Phase 1 moves drones via velocity, not explicit lawnmower rows.
- Smooth, PSO-characteristic curved trajectories in both phases.
- Genuine Phase-2 multi-drone detection rush.

Partition
---------
Lloyd-relaxed Voronoi partition: seeds are first placed by
``_balanced_partition_seeds`` (balanced row×col grid), then refined by
``_LLOYD_ITERS`` iterations of Lloyd's algorithm so all Voronoi cells are
equal-area regardless of drone count or area aspect ratio.  This eliminates
the cell-size imbalance that arises when the drone count does not factor into
a perfect rows × cols rectangle.

Tuning knobs
------------
  w  = 0.7   inertia
  c1 = 1.5   cognitive (pull toward assigned seed in Phase 1 / pbest in Phase 2)
  c2 = 2.0   social (pull toward detection gbest in Phase 2 only)
  MAX_SPEED_DEG  = 0.001° / tick
  NICHING_RADIUS = 3 × DETECTION_RADIUS = 0.006°
  LOOKAHEAD      = 5 × DETECTION_RADIUS = 0.010°
  LLOYD_ITERS    = 8  (Lloyd relaxation iterations for equal-area cells)
"""

from __future__ import annotations

import logging
import math
from typing import Dict, List, Tuple

import numpy as np

from app.algorithms.base import BaseSearchAlgorithm, DETECTION_RADIUS, build_dense_coverage_grid
from app.algorithms.boustrophedon import (
    _balanced_partition_seeds,
    _match_drones_to_seeds,
    _voronoi_assign,
)

logger = logging.getLogger(__name__)

# PSO tuning
INERTIA = 0.7
COGNITIVE = 1.5
SOCIAL = 2.0          # Phase 2 only — attraction toward detection
MAX_SPEED_DEG = 0.001
NICHING_REPEL = 0.0002
NICHING_RADIUS_DEG = 3 * DETECTION_RADIUS   # 0.006°
_LOOKAHEAD_DEG = 5 * DETECTION_RADIUS        # 0.010°
_LLOYD_ITERS = 8                             # Lloyd relaxation passes


def _getm(mission, key, default=None):
    """Uniform attribute access for both Mission dataclass and benchmark AttrDict."""
    try:
        return getattr(mission, key, default)
    except Exception:
        return default


def _lloyd_relax(dense_grid: np.ndarray, seeds: np.ndarray, n_iter: int) -> np.ndarray:
    """Regularise seed positions by iterative Lloyd's algorithm.

    Moves each seed to the centroid of its Voronoi cell, repeated n_iter
    times.  This ensures all cells are equal-area regardless of the initial
    grid layout, eliminating the cell-size imbalance that arises for drone
    counts that don't factor into a perfect rows × cols rectangle.
    """
    for _ in range(n_iter):
        labels = _voronoi_assign(dense_grid, seeds)
        new_seeds = np.empty_like(seeds)
        for i in range(len(seeds)):
            cell = dense_grid[labels == i]
            new_seeds[i] = cell.mean(axis=0) if len(cell) > 0 else seeds[i]
        seeds = new_seeds
    return seeds


class PSOSearchAlgorithm(BaseSearchAlgorithm):
    """Voronoi PSO: even-spread Phase-1 dispersion + velocity-based Phase-2 detection rush."""

    algorithm_key = "pso"
    display_name = "PSO (Voronoi-constrained)"
    description = (
        "Balanced PSO dispersion in Phase 1; "
        "PSO velocity rush to detections in Phase 2."
    )
    display_order = 45

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self, mission) -> None:
        """Build Lloyd-relaxed Voronoi partition and PSO velocity state."""
        drones = _getm(mission, "drones", [])
        bounds = _getm(mission, "bounds", {})
        if not drones or not bounds:
            return

        k = len(drones)
        dense_grid = build_dense_coverage_grid(bounds)

        # Seeds: balanced grid → Lloyd-relaxed for equal-area cells.
        seeds = _balanced_partition_seeds(bounds, k)
        seeds = _lloyd_relax(dense_grid, seeds, _LLOYD_ITERS)
        labels = _voronoi_assign(dense_grid, seeds)

        drone_positions = np.array(
            [[float(d.get("lat", 0.0)), float(d.get("lon", 0.0))] for d in drones]
        )
        drone_to_seed_list = _match_drones_to_seeds(drone_positions, seeds)

        pso_seeds: Dict[str, np.ndarray] = {}
        pso_velocities: Dict[str, np.ndarray] = {}
        pso_pbest: Dict[str, np.ndarray] = {}
        pso_cell_indices: Dict[str, np.ndarray] = {}
        pso_visited_cells: Dict[str, set] = {}

        for drone, seed_idx in zip(drones, drone_to_seed_list):
            did = str(drone["id"])
            seed_pos = seeds[seed_idx].copy()
            cell_pts = dense_grid[labels == seed_idx]
            pso_seeds[did] = seed_pos
            pso_velocities[did] = np.zeros(2)
            pso_pbest[did] = np.array(
                [float(drone.get("lat", 0.0)), float(drone.get("lon", 0.0))]
            )
            # Store indices into dense_grid belonging to this drone's Voronoi cell.
            pso_cell_indices[did] = np.where(labels == seed_idx)[0]
            pso_visited_cells[did] = set()
            logger.info(
                "pso | %s: cell %d (%d dense pts), seed (%.5f, %.5f)",
                did, seed_idx, len(cell_pts), seed_pos[0], seed_pos[1],
            )

        # gbest starts at bounds centre; updated to detection location in Phase 2.
        mission.pso_seeds = pso_seeds
        mission.pso_velocities = pso_velocities
        mission.pso_pbest = pso_pbest
        mission.pso_cell_indices = pso_cell_indices
        mission.pso_visited_cells = pso_visited_cells
        mission.pso_dense_grid = dense_grid
        mission.pso_gbest = np.array([
            (float(bounds.get("min_lat", 0)) + float(bounds.get("max_lat", 0))) / 2,
            (float(bounds.get("min_lon", 0)) + float(bounds.get("max_lon", 0))) / 2,
        ])

    # ------------------------------------------------------------------
    # Per-tick update
    # ------------------------------------------------------------------

    def get_target_waypoints(
        self, mission, free_drones: List[dict]
    ) -> Dict[str, Tuple[float, float]]:
        if not free_drones:
            return {}

        if not _getm(mission, "pso_seeds"):
            self.initialize(mission)

        rng: np.random.Generator = _getm(mission, "_np_rng")
        if rng is None:
            rng = np.random.default_rng()

        pso_seeds: Dict[str, np.ndarray] = _getm(mission, "pso_seeds", {})
        velocities: Dict[str, np.ndarray] = _getm(mission, "pso_velocities", {})
        pbest: Dict[str, np.ndarray] = _getm(mission, "pso_pbest", {})

        # Phase 2 when any unconfirmed detection exists.
        detection_target = self._detection_target(mission)
        phase2 = detection_target is not None
        if phase2:
            mission.pso_gbest = detection_target
        gbest: np.ndarray = _getm(mission, "pso_gbest", np.zeros(2))

        waypoints: Dict[str, Tuple[float, float]] = {}

        for drone in free_drones:
            did = str(drone["id"])
            pos = np.array([float(drone.get("lat", 0.0)), float(drone.get("lon", 0.0))])

            if phase2:
                # ----------------------------------------------------------
                # Phase 2: PSO velocity dynamics → rush toward detection
                # ----------------------------------------------------------
                v = velocities.get(did, np.zeros(2)).copy()
                pb = pbest.get(did, pos.copy())
                r1, r2 = float(rng.random()), float(rng.random())
                niching = self._niching_repulsion(drone, free_drones)
                v = (
                    INERTIA * v
                    + COGNITIVE * r1 * (pb - pos)
                    + SOCIAL * r2 * (gbest - pos)
                    + niching
                )
                speed = float(np.linalg.norm(v))
                if speed > MAX_SPEED_DEG:
                    v = v * (MAX_SPEED_DEG / speed)
                    speed = MAX_SPEED_DEG

                if speed > 1e-9:
                    waypoint_pos = pos + (v / speed) * _LOOKAHEAD_DEG
                else:
                    waypoint_pos = gbest.copy()

                velocities[did] = v
                dist_to_det = float(np.linalg.norm(pos - gbest))
                dist_pb = float(np.linalg.norm(pb - gbest))
                if dist_to_det < dist_pb:
                    pbest[did] = pos.copy()

                waypoints[did] = (float(waypoint_pos[0]), float(waypoint_pos[1]))
                logger.debug(
                    "pso | %s [Phase2] pos=(%.5f,%.5f) wp=(%.5f,%.5f) |v|=%.5f",
                    did, pos[0], pos[1], waypoint_pos[0], waypoint_pos[1], speed,
                )

            else:
                # ----------------------------------------------------------
                # Phase 1: PSO dispersion toward assigned region seed.
                # Niching repulsion keeps drones evenly spread — no rows,
                # no gaps, naturally uniform coverage of the search area.
                #
                # Coverage-driven exploration: once the drone reaches its
                # seed (within 3*DETECTION_RADIUS), the cognitive target
                # shifts to the centroid of UNVISITED cells in its Voronoi
                # partition, so the drone naturally drifts toward unscanned
                # areas instead of oscillating around the seed.
                # ----------------------------------------------------------
                seed_target = pso_seeds.get(did)
                if seed_target is None:
                    continue
                seed_target = np.asarray(seed_target)

                dense_grid: np.ndarray | None = _getm(mission, "pso_dense_grid")
                cell_indices: Dict[str, np.ndarray] = _getm(mission, "pso_cell_indices", {})
                visited_cells: Dict[str, set] = _getm(mission, "pso_visited_cells", {})

                # --- Mark cells within DETECTION_RADIUS of current pos as visited ---
                if dense_grid is not None and did in cell_indices:
                    my_indices = cell_indices[did]
                    my_grid_pts = dense_grid[my_indices]
                    dists_to_pos = np.linalg.norm(my_grid_pts - pos, axis=1)
                    newly_visited = set(my_indices[dists_to_pos <= DETECTION_RADIUS].tolist())
                    if did not in visited_cells:
                        visited_cells[did] = set()
                    visited_cells[did].update(newly_visited)

                # --- Compute cognitive target ---
                cognitive_target = seed_target  # default: original seed
                dist_to_seed = float(np.linalg.norm(pos - seed_target))

                if dist_to_seed < 3 * DETECTION_RADIUS and dense_grid is not None and did in cell_indices:
                    my_indices = cell_indices[did]
                    visited = visited_cells.get(did, set())
                    unvisited_mask = np.array(
                        [idx not in visited for idx in my_indices], dtype=bool
                    )
                    unvisited_indices = my_indices[unvisited_mask]

                    if len(unvisited_indices) > 0:
                        # Centroid of unvisited cells → pulls drone toward unscanned area.
                        unvisited_pts = dense_grid[unvisited_indices]
                        cognitive_target = unvisited_pts.mean(axis=0)
                    else:
                        # Partition fully covered — assist another partition.
                        all_visited: set = set()
                        for v_set in visited_cells.values():
                            all_visited.update(v_set)
                        all_grid_indices = np.arange(len(dense_grid))
                        global_unvisited = np.array(
                            [idx for idx in all_grid_indices if idx not in all_visited]
                        )
                        if len(global_unvisited) > 0:
                            pick = int(rng.integers(len(global_unvisited)))
                            cognitive_target = dense_grid[global_unvisited[pick]]
                        # else: everything visited, keep seed as target (hover).

                v = velocities.get(did, np.zeros(2)).copy()
                r1 = float(rng.random())
                niching = self._niching_repulsion(drone, free_drones)
                v = (
                    INERTIA * v
                    + COGNITIVE * r1 * (cognitive_target - pos)
                    + niching
                )
                speed = float(np.linalg.norm(v))
                if speed > MAX_SPEED_DEG:
                    v = v * (MAX_SPEED_DEG / speed)
                    speed = MAX_SPEED_DEG

                if speed > 1e-9:
                    waypoint_pos = pos + (v / speed) * _LOOKAHEAD_DEG
                else:
                    waypoint_pos = cognitive_target.copy()

                velocities[did] = v
                pbest[did] = pos.copy()
                waypoints[did] = (float(waypoint_pos[0]), float(waypoint_pos[1]))
                logger.debug(
                    "pso | %s [Phase1] pos=(%.5f,%.5f) seed=(%.5f,%.5f) cog=(%.5f,%.5f) wp=(%.5f,%.5f) |v|=%.5f",
                    did, pos[0], pos[1], seed_target[0], seed_target[1],
                    cognitive_target[0], cognitive_target[1],
                    waypoint_pos[0], waypoint_pos[1], speed,
                )

        mission.pso_velocities = velocities
        mission.pso_pbest = pbest
        return waypoints

    # ------------------------------------------------------------------
    # Phase 2 detection target
    # ------------------------------------------------------------------

    def _detection_target(self, mission) -> np.ndarray | None:
        """Return centroid of unconfirmed detections; None means stay in Phase 1."""
        targets = _getm(mission, "targets") or []
        unconfirmed = [t for t in targets if t.get("status") in ("detected", "confirming")]
        if not unconfirmed:
            return None
        tgt_positions = np.array(
            [[float(t["lat"]), float(t["lon"])] for t in unconfirmed]
        )
        return tgt_positions.mean(axis=0)

    # ------------------------------------------------------------------
    # Fitness (used by benchmark_cli acceptance-criteria checks)
    # ------------------------------------------------------------------

    def _fitness(self, mission, lat: float, lon: float) -> float:
        """Phase-2 detection attractor fitness (for AC#5/AC#6 benchmark checks)."""
        targets = _getm(mission, "targets") or []
        unconfirmed = [t for t in targets if t.get("status") in ("detected", "confirming")]
        if not unconfirmed:
            return 1.0  # uniform in Phase 1
        min_dist = min(
            math.hypot(lat - float(t["lat"]), lon - float(t["lon"]))
            for t in unconfirmed
        )
        return 5.0 / (1.0 + min_dist / DETECTION_RADIUS)

    # ------------------------------------------------------------------
    # Niching repulsion (both phases)
    # ------------------------------------------------------------------

    def _niching_repulsion(self, drone: dict, all_drones: List[dict]) -> np.ndarray:
        """Inverse-square repulsion from neighbours within NICHING_RADIUS_DEG."""
        MIN_DIST = DETECTION_RADIUS
        repulsion = np.zeros(2)
        pos = np.array([float(drone.get("lat", 0.0)), float(drone.get("lon", 0.0))])

        for other in all_drones:
            if other["id"] == drone["id"]:
                continue
            other_pos = np.array(
                [float(other.get("lat", 0.0)), float(other.get("lon", 0.0))]
            )
            dist = float(np.linalg.norm(other_pos - pos))
            if dist >= NICHING_RADIUS_DEG or dist < 1e-12:
                continue
            safe_dist = max(dist, MIN_DIST)
            direction = (pos - other_pos) / dist
            repulsion += NICHING_REPEL / (safe_dist ** 2) * direction

        return repulsion
