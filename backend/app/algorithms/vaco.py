import logging
import math
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from app.algorithms.base import BaseSearchAlgorithm, DETECTION_RADIUS

log = logging.getLogger(__name__)

try:
    from app.algorithms.stigmergy_engine import InMemoryPheromoneGrid, GridConfig
    from app.algorithms.voronoi_aco_hybrid import (
        VoronoiACOPlanner,
        DroneState,
        PlannerPhase,
    )
except ImportError:
    # Stub fallback so the module loads without crashing
    class InMemoryPheromoneGrid:
        pass
    class GridConfig:
        pass
    class VoronoiACOPlanner:
        pass
    class DroneState:
        pass
    class PlannerPhase:
        pass


# ══════════════════════════════════════════════════════════════════
# Minimal NavigationController (extracted from drone_agent.py)
# ══════════════════════════════════════════════════════════════════

class NavigationController:
    """
    Stateless sweep navigator — computes boustrophedon waypoints on-demand.
    Does NOT hold MAVLink connections or flight control — this is purely
    waypoint math extracted from your drone_agent.py NavigationController.
    """
    
    ROW_BAND_DEG = 0.0008  # ~88m row height (= 2× detection radius)
    MIN_WP_DIST_DEG = 0.0006  # ~66m — thinning threshold
    WAYPOINT_THRESHOLD_M = 12.0
    
    def __init__(self, drone_id: int, territory: Optional[np.ndarray] = None):
        self.drone_id = drone_id
        self.territory = territory
        self._sweep_order: Optional[np.ndarray] = None
        self._sweep_index: int = 0
        self._territory_hash: int = 0
        self._current_waypoint: Optional[Tuple[float, float]] = None
        self._waypoint_set_time: float = 0.0
    
    def set_territory(self, territory: np.ndarray, current_lat: float, current_lon: float):
        """Update territory and recompute sweep from nearest row."""
        new_hash = hash(territory.tobytes()) if territory is not None else 0
        if new_hash == self._territory_hash:
            return  # no change
        
        self.territory = territory
        self._territory_hash = new_hash
        self._current_waypoint = None
        
        if territory is None or len(territory) == 0:
            self._sweep_order = None
            return
        
        # Compute sweep order
        self._sweep_order = self._compute_sweep_order(territory)
        
        # Start from nearest row to avoid long initial transit
        if len(self._sweep_order) > 0:
            dists = np.array([
                self._haversine_m(current_lat, current_lon, float(pt[0]), float(pt[1]))
                for pt in self._sweep_order
            ])
            nearest_idx = int(np.argmin(dists))
            lat_min = self._sweep_order[:, 0].min()
            nearest_row = int((self._sweep_order[nearest_idx, 0] - lat_min) / self.ROW_BAND_DEG)
            # Walk back to row start
            row_start = nearest_idx
            while row_start > 0:
                prev_row = int((self._sweep_order[row_start-1, 0] - lat_min) / self.ROW_BAND_DEG)
                if prev_row != nearest_row:
                    break
                row_start -= 1
            self._sweep_index = row_start
    
    def _compute_sweep_order(self, territory: np.ndarray) -> np.ndarray:
        """Build thinned boustrophedon sweep array."""
        lat_min = territory[:, 0].min()
        row_idx = ((territory[:, 0] - lat_min) / self.ROW_BAND_DEG).astype(int)
        ordered = []
        for row in sorted(set(row_idx)):
            mask = row_idx == row
            row_pts = territory[mask]
            lon_order = np.argsort(row_pts[:, 1])
            if row % 2 == 1:
                lon_order = lon_order[::-1]
            ordered.append(row_pts[lon_order])
        
        if not ordered:
            return territory.copy()
        
        all_pts = np.vstack(ordered)
        
        # Thin waypoints — skip any closer than MIN_WP_DIST_DEG
        thinned = [all_pts[0]]
        for pt in all_pts[1:]:
            last = thinned[-1]
            dist = np.sqrt((pt[0] - last[0])**2 + (pt[1] - last[1])**2)
            if dist >= self.MIN_WP_DIST_DEG:
                thinned.append(pt)
        return np.array(thinned)
    
    def get_waypoint(self, current_lat: float, current_lon: float) -> Optional[Tuple[float, float]]:
        """Return next waypoint in sweep, advancing on arrival."""
        if self._sweep_order is None or len(self._sweep_order) == 0:
            return None
        
        # Check arrival at current waypoint
        if self._current_waypoint is not None:
            wp_lat, wp_lon = self._current_waypoint
            dist_to_wp = self._haversine_m(current_lat, current_lon, wp_lat, wp_lon)
            if dist_to_wp > self.WAYPOINT_THRESHOLD_M:
                # Not yet arrived — hold current waypoint
                return self._current_waypoint
        
        # Arrived (or no waypoint yet) — advance to next
        n = len(self._sweep_order)
        pt = self._sweep_order[self._sweep_index % n]
        self._sweep_index = (self._sweep_index + 1) % n
        self._current_waypoint = (float(pt[0]), float(pt[1]))
        self._waypoint_set_time = time.time()
        return self._current_waypoint
    
    @staticmethod
    def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        R = 6371000
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = (math.sin(dphi / 2) ** 2 +
             math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ══════════════════════════════════════════════════════════════════
# Main Adapter Class
# ══════════════════════════════════════════════════════════════════

class VoronoiACOHybridCoverage(BaseSearchAlgorithm):
    
    COVERAGE_THRESHOLD = 0.85  # Trigger Lloyd repartition when all drones ≥85% covered

    @staticmethod
    def _mget(mission, key: str, default=None):
        if isinstance(mission, dict):
            return mission.get(key, default)
        return getattr(mission, key, default)

    @staticmethod
    def _mset(mission, key: str, value) -> None:
        if isinstance(mission, dict):
            mission[key] = value
        else:
            setattr(mission, key, value)
    
    def initialize(self, mission: dict) -> None:
        """Set up pheromone grid, planner, and per-drone navigation state."""
        bounds = self._mget(mission, "bounds")
        if bounds is None:
            raise ValueError("Mission bounds are required for vaco initialization")
        span = max(
            bounds["max_lat"] - bounds["min_lat"],
            bounds["max_lon"] - bounds["min_lon"]
        )
        
        # Pheromone grid config
        cfg = GridConfig(
            lat_min=bounds["min_lat"],
            lat_max=bounds["max_lat"],
            lon_min=bounds["min_lon"],
            lon_max=bounds["max_lon"],
            rows=50,
            cols=50,
            evaporation_rate=0.97,
            deposit_strength=0.1,
            tick_interval=1.0,
        )
        grid = InMemoryPheromoneGrid(cfg)
        grid.start_evaporation()
        
        # Planner (handles Lloyd partitioning)
        planner = VoronoiACOPlanner(
            bounds={
                "min_lat": cfg.lat_min,
                "max_lat": cfg.lat_max,
                "min_lon": cfg.lon_min,
                "max_lon": cfg.lon_max,
            },
            grid_config=cfg,
            pheromone_grid=grid,
            n_grid=30,
            lloyd_interval=10,
            aco_radius=2,
            alpha=0.3,
        )
        planner.phase = PlannerPhase.LLOYD
        planner.lloyd_active = False  # Start unlocked
        
        # Store in mission state
        self._mset(mission, "_rtx_grid", grid)
        self._mset(mission, "_rtx_planner", planner)
        self._mset(mission, "_rtx_territories", {})  # drone_id → np.ndarray
        self._mset(mission, "_rtx_navigators", {})   # drone_id → NavigationController
        self._mset(mission, "_rtx_bootstrapped", False)
        
        log.info(
            "[RTX] Initialized: grid %dx%d, evap=%.2f, coverage_threshold=%.0f%%",
            cfg.rows, cfg.cols, cfg.evaporation_rate, self.COVERAGE_THRESHOLD * 100
        )
    
    def get_target_waypoints(
        self,
        mission: dict,
        free_drones: List[dict]
    ) -> Dict[str, Tuple[float, float]]:
        """
        Compute next waypoint for each free drone using Lloyd + boustrophedon sweep.
        
        Flow:
        1. Bootstrap Lloyd once (initial partition)
        2. Each drone sweeps its territory via NavigationController
        3. Deposit pheromone at current position each tick
        4. Repartition when ALL drones exceed coverage threshold
        """
        planner = self._mget(mission, "_rtx_planner")
        grid = self._mget(mission, "_rtx_grid")
        if planner is None or grid is None:
            log.warning("[RTX] Planner/grid not initialized — skipping tick")
            return {}
        
        # Filter out drones without valid positions
        valid_drones = [
            d for d in free_drones
            if d.get("lat") is not None and d.get("lon") is not None
        ]
        if not valid_drones:
            return {}
        
        # ── Bootstrap Lloyd partition (runs once) ──────────────────────
        if not self._mget(mission, "_rtx_bootstrapped", False):
            self._run_lloyd_partition(mission, valid_drones, planner)
            self._mset(mission, "_rtx_bootstrapped", True)
            planner.transition_to_aco()  # Unlock navigation
            log.info("[RTX] Bootstrap complete — navigation unlocked")
        
        # ── Deposit pheromone at current positions ─────────────────────
        for drone in valid_drones:
            grid.deposit(drone["lat"], drone["lon"])
        
        territories = self._mget(mission, "_rtx_territories", {})
        navigators = self._mget(mission, "_rtx_navigators", {})

        # ── Check for repartition trigger ──────────────────────────────
        coverages = []
        for drone in valid_drones:
            territory = territories.get(drone["id"])
            if territory is None or len(territory) == 0:
                continue
            drone_state = DroneState(
                id=drone["id"],
                lat=drone["lat"],
                lon=drone["lon"],
                territory=territory
            )
            cov = planner._territory_coverage(drone_state)
            coverages.append(cov)
        
        if coverages and all(c >= self.COVERAGE_THRESHOLD for c in coverages):
            log.info(
                "[RTX] All drones ≥%.0f%% covered %s — repartitioning",
                self.COVERAGE_THRESHOLD * 100,
                [f"{c:.0%}" for c in coverages]
            )
            self._run_lloyd_partition(mission, valid_drones, planner)
            grid.reset()  # Clear pheromone for fresh pass
            log.info("[RTX] Repartition complete, pheromone reset")
        
        # ── Compute waypoints via sweep navigation ─────────────────────
        waypoints = {}
        for drone in valid_drones:
            drone_id = drone["id"]
            territory = territories.get(drone_id)
            if territory is None or len(territory) == 0:
                continue
            
            # Get or create navigator for this drone
            nav = navigators.get(drone_id)
            if nav is None:
                nav = NavigationController(drone_id, territory)
                navigators[drone_id] = nav
            
            # Update territory if it changed (Lloyd repartition)
            nav.set_territory(territory, drone["lat"], drone["lon"])
            
            # Get next sweep waypoint
            wp = nav.get_waypoint(drone["lat"], drone["lon"])
            if wp is not None:
                waypoints[drone_id] = wp
        
        return waypoints
    
    def _run_lloyd_partition(
        self,
        mission: dict,
        drones: List[dict],
        planner: VoronoiACOPlanner
    ):
        """Run one Lloyd iteration and assign territories to drones."""
        states = [
            DroneState(id=d["id"], lat=d["lat"], lon=d["lon"])
            for d in drones
        ]
        territories = self._mget(mission, "_rtx_territories", {})
        
        # Preserve existing territories (Lloyd updates them in-place)
        for s in states:
            existing = territories.get(s.id)
            if existing is not None:
                s.territory = existing
        
        planner._run_lloyd(states)
        
        # Write back to mission state
        for s in states:
            if s.territory is not None and len(s.territory) > 0:
                territories[s.id] = s.territory
        
        log.info(
            "[RTX] Lloyd partition: %d drones, cell counts=%s",
            len(states),
            [len(s.territory) for s in states]
        )