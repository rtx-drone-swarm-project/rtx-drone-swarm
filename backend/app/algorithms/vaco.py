import logging
import math
from typing import Dict, List, Tuple

import numpy as np
from app.algorithms.base import BaseSearchAlgorithm
from app.algorithms.voronoi_aco_hybrid import (
    VoronoiACOPlanner,
    PlannerConfig,
    NavigationController,
    DroneState,
    _jitter_collinear_centroids,
)

log = logging.getLogger(__name__)

class VoronoiACOHybridCoverage(BaseSearchAlgorithm):
    algorithm_key = "vaco"
    display_name = "VACO Hybrid (Optimized)"
    description = "Optimized Lloyd partitioning with pheromone-guided sweep navigation."
    display_order = 25

    # ── Bootstrap ────────────────────────────────────────────────────────────
    BOOTSTRAP_SPREAD_TARGET = 0.005        # ~555m spread for 15 drones
    BOOTSTRAP_TIMEOUT_TICKS = 20           # Increased from 15 for SITL lag

    # ── Drift correction ─────────────────────────────────────────────────────
    DRIFT_THRESHOLD_DEG = 0.005            # 555m; only active during Lloyd phase

    # ── Adaptive repartitioning ───────────────────────────────────────────────
    REPARTITION_INTERVAL_TICKS = 300       # Every 5 minutes
    REPARTITION_COVERAGE_THRESHOLD = 0.75  # 75% explored triggers rebalance

    # ── Grid resolution ───────────────────────────────────────────────────────
    # FIX: Raised from 50 → 100. At 15 drones this gives ~667 cells per drone
    # (was ~167), making the pheromone map 4× denser and the Lloyd territories
    # proportionally more detailed. Memory cost: 100×100 float32 = 40KB (trivial).
    LLOYD_GRID_N = 100

    def initialize(self, mission) -> None:
        bounds = mission.bounds
        pcfg = PlannerConfig(detection_radius_m=30.0)

        planner = VoronoiACOPlanner(
            bounds=bounds,
            planner_config=pcfg,
            grid_n=self.LLOYD_GRID_N,
        )

        mission._rtx_planner = planner
        mission._rtx_pcfg = pcfg
        mission._rtx_territories = {}
        mission._rtx_navigators = {}
        mission._rtx_prev_positions = {}
        mission._rtx_bootstrapped = False
        mission._rtx_ticks = 0
        mission._rtx_last_repartition = 0

        planner.pheromone_grid.start_evaporation()
        log.info("[VACO] Algorithm initialized with pheromone grid active")

    def get_target_waypoints(self, mission, free_drones: List[dict]) -> Dict[str, Tuple[float, float]]:
        planner = mission._rtx_planner
        pcfg = mission._rtx_pcfg

        valid_drones = [
            d for d in free_drones
            if d.get("lat") is not None and d.get("lon") is not None
        ]
        if not valid_drones:
            return {}

        mission_time_s = float(getattr(mission, "elapsed_seconds", 0.0))
        mission._rtx_ticks += 1

        # ═══════════════════════════════════════════════════════════
        # PHASE 1: BOOTSTRAP (Fan-out → Partition)
        # ═══════════════════════════════════════════════════════════
        if not mission._rtx_bootstrapped:
            lats = [d["lat"] for d in valid_drones]
            lons = [d["lon"] for d in valid_drones]

            lat_spread = max(lats) - min(lats)
            lon_spread = max(lons) - min(lons)
            current_spread = max(lat_spread, lon_spread)

            n_drones = len(valid_drones)
            adaptive_spread = max(self.BOOTSTRAP_SPREAD_TARGET, 0.0003 * math.sqrt(n_drones))

            if current_spread >= adaptive_spread or mission._rtx_ticks > self.BOOTSTRAP_TIMEOUT_TICKS:
                log.info(
                    "[VACO] Bootstrap complete: spread=%.5f (target=%.5f), ticks=%d",
                    current_spread, adaptive_spread, mission._rtx_ticks
                )
                mission._rtx_bootstrapped = True
                mission._rtx_last_repartition = mission._rtx_ticks

                self._run_lloyd_partition(mission, valid_drones, current_spread)
                planner.transition_to_aco()
                log.info("[VACO] Transitioned to ACO phase")

                # FIX: Re-read territories AFTER partition so the first post-
                # bootstrap tick uses the freshly written dict, not the empty
                # one captured in a local variable before _run_lloyd_partition ran.
                # This was the cause of "Drone N has no territory assigned" on
                # the tick immediately following bootstrap completion.
            else:
                jittered = _jitter_collinear_centroids(valid_drones, mission.bounds)
                log.debug(
                    "[VACO] Bootstrap spreading: spread=%.5f, tick=%d/%d",
                    current_spread, mission._rtx_ticks, self.BOOTSTRAP_TIMEOUT_TICKS
                )
                return {d["id"]: jittered[i] for i, d in enumerate(valid_drones)}

        # ═══════════════════════════════════════════════════════════
        # PHASE 2: PHEROMONE MAINTENANCE (ACO Active)
        # ═══════════════════════════════════════════════════════════
        planner.pheromone_grid.tick()

        prev_positions = mission._rtx_prev_positions
        for drone in valid_drones:
            d_id = str(drone["id"])
            curr_lat = float(drone["lat"])
            curr_lon = float(drone["lon"])

            prev = prev_positions.get(d_id)
            if prev is not None:
                planner.pheromone_grid.deposit_path(
                    prev[0], prev[1], curr_lat, curr_lon, steps=4
                )
            else:
                planner.pheromone_grid.deposit(curr_lat, curr_lon)

            prev_positions[d_id] = (curr_lat, curr_lon)

        # ═══════════════════════════════════════════════════════════
        # PHASE 3: ADAPTIVE REPARTITIONING
        # ═══════════════════════════════════════════════════════════
        ticks_since_partition = mission._rtx_ticks - mission._rtx_last_repartition

        # FIX: Read territories fresh at the start of each tick so we always
        # see the dict written by _run_lloyd_partition (it replaces the dict
        # reference on mission, so a local alias captured before the call
        # would be stale). This was the root cause of the "no territory" warnings.
        territories = mission._rtx_territories
        navs = mission._rtx_navigators

        if ticks_since_partition > self.REPARTITION_INTERVAL_TICKS:
            should_repartition = False
            states = []

            for drone in valid_drones:
                d_id = str(drone["id"])
                territory = territories.get(d_id)
                if territory is not None:
                    state = DroneState(
                        id=d_id,
                        lat=float(drone["lat"]),
                        lon=float(drone["lon"]),
                        territory=territory
                    )
                    states.append(state)

                    coverage = planner._territory_coverage(state)
                    if coverage >= self.REPARTITION_COVERAGE_THRESHOLD:
                        should_repartition = True
                        log.info(
                            "[VACO] Drone %s coverage: %.1f%% - triggering repartition",
                            d_id, coverage * 100
                        )

            if should_repartition and len(states) > 1:
                log.info("[VACO] Executing adaptive repartition")
                self._run_lloyd_partition(mission, valid_drones, current_spread=0.01)
                mission._rtx_last_repartition = mission._rtx_ticks
                planner.pheromone_grid.reset()
                # Re-read after repartition
                territories = mission._rtx_territories
                navs = mission._rtx_navigators
                for nav in navs.values():
                    nav._territory_hash = 0
                log.info("[VACO] Pheromone grid reset and sweep paths invalidated after repartition")

        # ═══════════════════════════════════════════════════════════
        # PHASE 4: WAYPOINT GENERATION (ACO-Guided Sweep)
        # ═══════════════════════════════════════════════════════════
        waypoints = {}
        for drone in valid_drones:
            d_id = str(drone["id"])
            territory = territories.get(d_id)

            if territory is None:
                log.warning("[VACO] Drone %s has no territory assigned", d_id)
                continue

            if d_id not in navs:
                navs[d_id] = NavigationController(d_id, pcfg, territory)

            navs[d_id].set_territory(territory)

            base_waypoint = navs[d_id].get_waypoint(
                drone["lat"], drone["lon"], mission_time_s
            )

            # FIX: ACO blend reduced from 30% → 10% pheromone gradient influence.
            # At 30% the gradient was pulling drones significantly off their
            # boustrophedon paths, creating clustering around previously-visited
            # areas and leaving large unswept strips. 10% provides just enough
            # gradient signal to nudge toward unexplored cells at row turns
            # without corrupting the structural sweep geometry.
            # Also raised the sweep_index guard from 3 → 5 so the first full
            # row completes before any gradient influence kicks in.
            if planner.phase.value == "aco" and navs[d_id]._sweep_index > 5:
                pheromone_target = planner.pheromone_grid.get_gradient(
                    base_waypoint[0], base_waypoint[1], radius=3
                )
                blended_lat = 0.90 * base_waypoint[0] + 0.10 * pheromone_target[0]
                blended_lon = 0.90 * base_waypoint[1] + 0.10 * pheromone_target[1]
                waypoint = (blended_lat, blended_lon)
            else:
                waypoint = base_waypoint

            # ═══════════════════════════════════════════════════════
            # PHASE 5: DRIFT CORRECTION (Only During Lloyd Phase)
            # ═══════════════════════════════════════════════════════
            if planner.phase.value == "lloyd":
                pos = np.array([drone["lat"], drone["lon"]])
                dist_to_cell = np.linalg.norm(territory - pos, axis=1).min()

                if dist_to_cell > self.DRIFT_THRESHOLD_DEG:
                    nearest = territory[np.argmin(np.linalg.norm(territory - pos, axis=1))]
                    waypoint = (float(nearest[0]), float(nearest[1]))
                    log.debug("[VACO] Drift correction for drone %s: %.5f deg", d_id, dist_to_cell)

            waypoints[d_id] = waypoint

        log.debug(
            "[VACO] Generated %d waypoints (tick=%d, phase=%s)",
            len(waypoints), mission._rtx_ticks, planner.phase.value
        )
        return waypoints

    def _run_lloyd_partition(self, mission, drones: List[dict], current_spread: float):
        """Compute balanced territories via planner-owned DroneState objects."""
        planner = mission._rtx_planner
        bounds = mission.bounds

        use_jitter = current_spread < self.BOOTSTRAP_SPREAD_TARGET

        if use_jitter:
            log.info(
                "[VACO] Using jittered positions for Lloyd (spread=%.5f < target=%.5f). "
                "Bounds: lat=[%.5f, %.5f] lon=[%.5f, %.5f]",
                current_spread, self.BOOTSTRAP_SPREAD_TARGET,
                bounds["min_lat"], bounds["max_lat"],
                bounds["min_lon"], bounds["max_lon"],
            )
            seeded = _jitter_collinear_centroids(drones, bounds)
            seeded = [
                (
                    max(bounds["min_lat"], min(bounds["max_lat"], lat)),
                    max(bounds["min_lon"], min(bounds["max_lon"], lon)),
                )
                for lat, lon in seeded
            ]
            states = [
                DroneState(id=str(drone["id"]), lat=seeded[i][0], lon=seeded[i][1])
                for i, drone in enumerate(drones)
            ]
        else:
            states = [
                DroneState(
                    id=str(drone["id"]),
                    lat=float(drone["lat"]),
                    lon=float(drone["lon"]),
                )
                for drone in drones
            ]

        planner._run_lloyd(states, grid_n=self.LLOYD_GRID_N)

        # FIX: Write a fresh dict to mission._rtx_territories rather than
        # clearing and repopulating the existing one. get_target_waypoints
        # re-reads `mission._rtx_territories` at the top of every tick, so
        # assigning a new dict here is safe and avoids any window where the
        # dict is partially populated.
        new_territories: dict = {}
        new_navs: dict = {}
        cell_sizes: list[int] = []

        for state in states:
            if state.territory is None or len(state.territory) == 0:
                log.warning("[VACO] Drone %s received empty territory!", state.id)
                continue
            new_territories[state.id] = state.territory
            cell_sizes.append(int(len(state.territory)))

            # Preserve any existing navigator so sweep_index is not lost
            # across repartitions when the territory hash happens to change.
            if state.id in mission._rtx_navigators:
                new_navs[state.id] = mission._rtx_navigators[state.id]

        mission._rtx_territories = new_territories
        mission._rtx_navigators = new_navs

        if cell_sizes:
            log.info(
                "[VACO] Partition complete. Cells: min=%d, max=%d, mean=%.1f, std=%.1f",
                min(cell_sizes), max(cell_sizes),
                np.mean(cell_sizes), np.std(cell_sizes)
            )
        else:
            log.error("[VACO] Partition failed - no territories assigned!")