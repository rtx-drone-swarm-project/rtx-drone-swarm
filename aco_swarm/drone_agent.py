"""
drone_agent.py
--------------
Modular drone agent with separated concerns:
  - MAVLinkConnection: low-level MAVLink communication
  - FlightController: vehicle state and flight commands
  - NavigationController: high-level waypoint following
  - DroneAgent: orchestrates everything

SEARCH ADDITIONS:
  - DroneAgent.__init__: _target_manager, _validation_protocol,
    _validation_target attributes
  - NavigationController.get_waypoint: validation override check
  - DroneAgent._execute_navigation_step: detection check each tick
"""

import time
import threading
import logging
import numpy as np
import math
from enum import Enum
from typing import Optional, Tuple
from dataclasses import dataclass
 
from pymavlink import mavutil
from stigmergy_engine import InMemoryPheromoneGrid
from voronoi_aco_hybrid import VoronoiACOPlanner, DroneState
 
log = logging.getLogger(__name__)
 
 
# ═══════════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════════
 
@dataclass
class Position:
    lat: float
    lon: float
    alt: float = 0.0
 
    def is_valid(self) -> bool:
        return abs(self.lat) > 0.001 and abs(self.lon) > 0.001
 
    def distance_to(self, other: 'Position') -> float:
        return haversine_m(self.lat, self.lon, other.lat, other.lon)
 
    def to_tuple(self) -> Tuple[float, float]:
        return (self.lat, self.lon)
 
 
class DronePhase(Enum):
    INITIALIZING       = "initializing"
    SPAWNING           = "spawning"
    TERRITORY_ASSIGNED = "territory_assigned"
    COVERING           = "covering"
    ERROR              = "error"
 
 
# ═══════════════════════════════════════════════════════════════════
# MAVLink Communication Layer
# ═══════════════════════════════════════════════════════════════════
 
class MAVLinkConnection:
    def __init__(self, connection_str: str, drone_id: int, expected_sysid: int):
        self.connection_str = connection_str
        self.drone_id       = drone_id
        self.expected_sysid = expected_sysid
        self.source_system  = drone_id + 100
        self.master: Optional[mavutil.mavfile] = None
 
    def connect(self, timeout: float = 60.0) -> bool:
        try:
            self.master = mavutil.mavlink_connection(
                self.connection_str,
                source_system=self.source_system,
                autoreconnect=False
            )
            deadline = time.time() + timeout
            while time.time() < deadline:
                msg = self.master.recv_match(type="HEARTBEAT", blocking=True, timeout=2)
                if msg and msg.get_srcSystem() == self.expected_sysid:
                    self.master.target_system    = msg.get_srcSystem()
                    self.master.target_component = msg.get_srcComponent()
                    log.info(f"[Drone {self.drone_id + 1}] MAVLink connected ✓")
                    return True
            log.error(f"[Drone {self.drone_id + 1}] No heartbeat from sysid={self.expected_sysid}")
            return False
        except Exception as e:
            log.error(f"[Drone {self.drone_id + 1}] Connection failed: {e}")
            return False
 
    def wait_for_gps_lock(self, timeout: float = 120) -> bool:
        log.info(f"[Drone {self.drone_id + 1}] Waiting for GPS lock...")
        start = time.time()
        while time.time() - start < timeout:
            msg = self.master.recv_match(type="GPS_RAW_INT", blocking=True, timeout=2)
            if msg and msg.get_srcSystem() == self.expected_sysid:
                if msg.fix_type >= 3:
                    log.info(f"[Drone {self.drone_id + 1}] GPS lock OK ✓ (sats={msg.satellites_visible})")
                    return True
        return False
 
    def wait_for_ekf(self, timeout: float = 30) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            msg = self.master.recv_match(type="EKF_STATUS_REPORT", blocking=True, timeout=2)
            if msg:
                if (msg.flags & 0b111) == 0b111:
                    log.info(f"[Drone {self.drone_id + 1}] EKF ready ✓")
                    return True
        return False
 
    def get_position(self) -> Optional[Position]:
        msg = self.master.recv_match(type="GLOBAL_POSITION_INT", blocking=False)
        if msg and msg.get_srcSystem() == self.expected_sysid:
            pos = Position(lat=msg.lat / 1e7, lon=msg.lon / 1e7,
                           alt=msg.relative_alt / 1000.0)
            return pos if pos.is_valid() else None
        return None
 
    def wait_for_position(self, timeout: float = 60) -> Optional[Position]:
        log.info(f"[Drone {self.drone_id + 1}] Waiting for position...")
        start = time.time()
        while time.time() - start < timeout:
            msg = self.master.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=2)
            if msg and msg.get_srcSystem() == self.expected_sysid:
                pos = Position(lat=msg.lat / 1e7, lon=msg.lon / 1e7,
                               alt=msg.relative_alt / 1000.0)
                if pos.is_valid():
                    log.info(f"[Drone {self.drone_id + 1}] Position OK ✓")
                    return pos
            time.sleep(0.5)
        return None
 
 
# ═══════════════════════════════════════════════════════════════════
# Flight Control Layer
# ═══════════════════════════════════════════════════════════════════
 
class FlightController:
    def __init__(self, connection: MAVLinkConnection, drone_id: int):
        self.conn      = connection
        self.drone_id  = drone_id
        self.master    = connection.master
 
    def set_mode(self, mode: str) -> bool:
        try:
            mode_id = self.master.mode_mapping()[mode]
            self.master.mav.set_mode_send(
                self.master.target_system,
                mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
                mode_id,
            )
            log.info(f"[Drone {self.drone_id + 1}] Mode → {mode}")
            time.sleep(1)
            return True
        except Exception as e:
            log.error(f"[Drone {self.drone_id + 1}] Mode change failed: {e}")
            return False
 
    def arm(self, timeout: float = 60) -> bool:
        log.info(f"[Drone {self.drone_id + 1}] Arming...")
        start         = time.time()
        last_arm_cmd  = time.time()
        while time.time() - start < timeout:
            if time.time() - last_arm_cmd > 5:
                self.master.arducopter_arm()
                last_arm_cmd = time.time()
            msg = self.master.recv_match(blocking=True, timeout=2)
            if msg is None:
                continue
            if msg.get_type() == "HEARTBEAT" and msg.get_srcSystem() == self.conn.expected_sysid:
                if (msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED) != 0:
                    log.info(f"[Drone {self.drone_id + 1}] Armed ✓")
                    return True
            elif msg.get_type() == "STATUSTEXT" and msg.get_srcSystem() == self.conn.expected_sysid:
                if "PreArm" in msg.text or "prearm" in msg.text.lower():
                    log.warning(f"[Drone {self.drone_id + 1}] {msg.text.strip()}")
        log.error(f"[Drone {self.drone_id + 1}] Arming timeout")
        return False
 
    def takeoff(self, altitude: float) -> bool:
        log.info(f"[Drone {self.drone_id + 1}] Takeoff → {altitude}m...")
        self.master.mav.command_long_send(
            self.master.target_system, self.master.target_component,
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            0, 0, 0, 0, 0, 0, 0, altitude,
        )
        while True:
            msg = self.master.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=2)
            if msg and msg.get_srcSystem() == self.conn.expected_sysid:
                if msg.relative_alt / 1000.0 >= altitude * 0.90:
                    log.info(f"[Drone {self.drone_id + 1}] Reached {msg.relative_alt/1000:.1f}m ✓")
                    return True
            time.sleep(0.5)
 
    def goto(self, lat: float, lon: float, alt: float):
        type_mask = (
            mavutil.mavlink.POSITION_TARGET_TYPEMASK_VX_IGNORE |
            mavutil.mavlink.POSITION_TARGET_TYPEMASK_VY_IGNORE |
            mavutil.mavlink.POSITION_TARGET_TYPEMASK_VZ_IGNORE |
            mavutil.mavlink.POSITION_TARGET_TYPEMASK_AX_IGNORE |
            mavutil.mavlink.POSITION_TARGET_TYPEMASK_AY_IGNORE |
            mavutil.mavlink.POSITION_TARGET_TYPEMASK_AZ_IGNORE |
            mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_IGNORE |
            mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_RATE_IGNORE
        )
        self.master.mav.set_position_target_global_int_send(
            0,
            self.master.target_system, self.master.target_component,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
            type_mask,
            int(lat * 1e7), int(lon * 1e7), alt,
            0, 0, 0, 0, 0, 0, 0, 0,
        )
 
    def goto_until_reached(self, target: Position, altitude: float,
                           threshold_m: float = 3.0, timeout: float = 60) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            self.goto(target.lat, target.lon, altitude)
            pos = self.conn.get_position()
            if pos and pos.distance_to(target) < threshold_m:
                log.info(f"[Drone {self.drone_id + 1}] Reached target ✓")
                return True
            time.sleep(0.2)
        log.warning(f"[Drone {self.drone_id + 1}] Failed to reach target (timeout)")
        return False
 
 
# ═══════════════════════════════════════════════════════════════════
# Navigation Controller
# ═══════════════════════════════════════════════════════════════════
 
class NavigationController:
    def __init__(self, drone_id: int, planner: VoronoiACOPlanner, grid: InMemoryPheromoneGrid):
        self.drone_id     = drone_id
        self.planner      = planner
        self.grid         = grid
        self.territory: Optional[np.ndarray] = None
        self.prev_position: Optional[Position] = None
        self._current_waypoint: Optional[Tuple[float, float]] = None
        self._waypoint_threshold_m = 12.0
        self._sweep_order: Optional[np.ndarray] = None
        self._sweep_index: int = 0
        self._territory_hash: int = 0
        self._waypoint_set_time: float = 0.0
        self._last_pos_for_timeout: Optional[Tuple[float, float]] = None
        self._waypoint_timeout_s = 20.0   # force-advance if stuck this long
 
    def can_navigate(self) -> bool:
        return self.territory is not None and len(self.territory) > 0
 
    def should_defer_to_lloyd(self) -> bool:
        return getattr(self.planner, "lloyd_active", False)
 
    def _compute_sweep_order(self, territory: np.ndarray) -> np.ndarray:
        ROW_BAND_DEG    = 0.0008
        MIN_WP_DIST_DEG = 0.0006   # ~66m — skip waypoints closer than this
 
        lat_min = territory[:, 0].min()
        row_idx = ((territory[:, 0] - lat_min) / ROW_BAND_DEG).astype(int)
        ordered = []
        for row in sorted(set(row_idx)):
            mask      = row_idx == row
            row_pts   = territory[mask]
            lon_order = np.argsort(row_pts[:, 1])
            if row % 2 == 1:
                lon_order = lon_order[::-1]
            ordered.append(row_pts[lon_order])
 
        if not ordered:
            return territory.copy()
 
        all_pts = np.vstack(ordered)
 
        # Thin the sweep — keep only waypoints MIN_WP_DIST_DEG apart
        thinned   = [all_pts[0]]
        for pt in all_pts[1:]:
            last = thinned[-1]
            dist = np.sqrt((pt[0] - last[0])**2 + (pt[1] - last[1])**2)
            if dist >= MIN_WP_DIST_DEG:
                thinned.append(pt)
        return np.array(thinned)
 
    def get_waypoint(
        self,
        current_pos: Position,
        validation_target: Optional[Tuple[float, float]] = None,
    ) -> Optional[Tuple[float, float]]:
        # Priority 1: validation override
        if validation_target is not None:
            self._current_waypoint = validation_target
            return validation_target
 
        # Priority 2: Lloyd repartition in progress
        if self.should_defer_to_lloyd():
            return None
 
        # Priority 3: sweep navigation
        if not self.can_navigate():
            return None
 
        # ─────────────────────────────────────────────────────────────
        # FIX: Removed duplicate sweep recompute block
        # ─────────────────────────────────────────────────────────────
        # Recompute sweep if territory content changed (Lloyd repartition)
        new_hash = hash(self.territory.tobytes()) if self.territory is not None else 0
        if new_hash != self._territory_hash:
            self._sweep_order    = self._compute_sweep_order(self.territory)
            self._territory_hash = new_hash
            self._current_waypoint = None
 
            # Start from nearest point in sweep to avoid long initial transit
            if len(self._sweep_order) > 0:
                dists = np.array([
                    haversine_m(current_pos.lat, current_pos.lon,
                                float(pt[0]), float(pt[1]))
                    for pt in self._sweep_order
                ])
                nearest_idx = int(np.argmin(dists))
                # Find which row this nearest point belongs to and start at row boundary
                # so we begin a clean full-width sweep from the nearest row
                ROW_BAND_DEG = 0.0008
                lat_min = self._sweep_order[:, 0].min()
                nearest_row = int((self._sweep_order[nearest_idx, 0] - lat_min) / ROW_BAND_DEG)
                # Walk back to find the start of this row in the sweep
                row_start = nearest_idx
                while row_start > 0:
                    prev_row = int((self._sweep_order[row_start-1, 0] - lat_min) / ROW_BAND_DEG)
                    if prev_row != nearest_row:
                        break
                    row_start -= 1
                self._sweep_index = row_start
 
            log.info(f"[Nav D{self.drone_id + 1}] Sweep recomputed: "
                    f"{len(self._sweep_order)} waypoints, starting row at index {self._sweep_index}")
 
        # Hold current waypoint until arrival or timeout
        if self._current_waypoint is not None:
            wp_lat, wp_lon = self._current_waypoint
            dist_to_wp = haversine_m(current_pos.lat, current_pos.lon,
                                    wp_lat, wp_lon)
            if dist_to_wp > self._waypoint_threshold_m:
                # Dynamic timeout based on distance
                expected_travel_s = dist_to_wp / 8.0   # 8 m/s conservative
                timeout = min(max(expected_travel_s * 1.5, 15.0), 90.0)
                time_on_wp = time.time() - self._waypoint_set_time
                if time_on_wp < timeout:
                    return self._current_waypoint
                else:
                    log.warning(f"[Nav D{self.drone_id+1}] WP timeout after "
                                f"{time_on_wp:.0f}s ({dist_to_wp:.0f}m away) — advancing")
                # Fall through to advance
 
        # Arrived (or no waypoint yet) — advance to next in sweep
        if self._sweep_order is not None and len(self._sweep_order) > 0:
            n  = len(self._sweep_order)
            pt = self._sweep_order[self._sweep_index % n]
            self._sweep_index      = (self._sweep_index + 1) % n
            self._current_waypoint = (float(pt[0]), float(pt[1]))
            self._waypoint_set_time = time.time() 
            return self._current_waypoint
 
        # Fallback: ACO gradient
        state           = DroneState(id=self.drone_id,
                                    lat=current_pos.lat, lon=current_pos.lon)
        state.territory = self.territory
        target_lat, target_lon = self.planner._aco_waypoint(state)
        target_lat, target_lon = self.planner.clamp_to_territory(
            state, target_lat, target_lon)
        self._current_waypoint = (target_lat, target_lon)
        return self._current_waypoint
 
 
# ═══════════════════════════════════════════════════════════════════
# Main Drone Agent
# ═══════════════════════════════════════════════════════════════════
 
class DroneAgent:
    def __init__(
        self,
        drone_id: int,
        connection_str: str,
        grid: InMemoryPheromoneGrid,
        planner: VoronoiACOPlanner,
        altitude: float = 10.0,
        loop_hz: float = 5.0,
        expected_sysid: int = None,
    ):
        self.drone_id      = drone_id
        self.altitude      = altitude
        self.loop_interval = 1.0 / loop_hz
 
        self.spawn_position: Optional[Position] = None
        self.phase          = DronePhase.INITIALIZING
        self.airborne       = False
        self.current_position: Optional[Position] = None
 
        self.conn   = MAVLinkConnection(connection_str, drone_id,
                                        expected_sysid if expected_sysid else drone_id + 1)
        self.flight = None
        self.nav    = NavigationController(drone_id, planner, grid)
 
        self._target_manager      = None
        self._validation_protocol = None
        self._validation_target: Optional[Tuple[float, float]] = None
 
        self._running = False
        self._thread: Optional[threading.Thread] = None
 
    @property
    def territory(self):
        return self.nav.territory
 
    @territory.setter
    def territory(self, value):
        self.nav.territory = value
 
    @property
    def lat(self):
        return self.current_position.lat if self.current_position else None
 
    @property
    def lon(self):
        return self.current_position.lon if self.current_position else None
 
    @property
    def start_lat(self):
        return self.spawn_position.lat if self.spawn_position else None
 
    @start_lat.setter
    def start_lat(self, value):
        if self.spawn_position is None:
            self.spawn_position = Position(value, 0)
        else:
            self.spawn_position.lat = value
 
    @property
    def start_lon(self):
        return self.spawn_position.lon if self.spawn_position else None
 
    @start_lon.setter
    def start_lon(self, value):
        if self.spawn_position is None:
            self.spawn_position = Position(0, value)
        else:
            self.spawn_position.lon = value
 
    def connect(self, timeout: float = 60.0) -> bool:
        if not self.conn.connect(timeout):
            return False
        self.flight = FlightController(self.conn, self.drone_id)
        return True
 
    def start(self):
        self._running = True
        self._thread  = threading.Thread(
            target=self._run, daemon=True, name=f"drone-{self.drone_id + 1}")
        self._thread.start()
 
    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
 
    def _run(self):
        try:
            if not self._initialize_vehicle():
                return
            if not self.flight.takeoff(self.altitude):
                return
            self.airborne = True
            self.phase    = DronePhase.SPAWNING
            log.info(f"[Drone {self.drone_id + 1}] Airborne ✓")
            self._navigation_loop()
        except Exception as e:
            log.error(f"[Drone {self.drone_id + 1}] Fatal error: {e}", exc_info=True)
            self.phase = DronePhase.ERROR
 
    def _initialize_vehicle(self) -> bool:
        if not self.flight.set_mode("GUIDED"):
            return False
        pos = self.conn.wait_for_position(timeout=60)
        if not pos:
            log.error(f"[Drone {self.drone_id + 1}] No position estimate")
            return False
        self.current_position = pos
        if not self.conn.wait_for_ekf(timeout=30):
            log.error(f"[Drone {self.drone_id + 1}] EKF not ready")
            return False
        if not self.conn.wait_for_gps_lock(timeout=120):
            log.error(f"[Drone {self.drone_id + 1}] No GPS lock")
            return False
        if not self.flight.arm(timeout=60):
            log.error(f"[Drone {self.drone_id + 1}] Arming failed")
            return False
        log.info(f"[Drone {self.drone_id + 1}] Initialization complete ✓")
        return True
 
    def _navigation_loop(self):
        log.info(f"[Drone {self.drone_id + 1}] Navigation loop started")
        while self._running:
            t0  = time.time()
            pos = self.conn.get_position()
            if pos:
                self.current_position = pos
                self.nav.grid.deposit(pos.lat, pos.lon)
                self._check_detections()
                self._execute_navigation_step()
            elapsed    = time.time() - t0
            sleep_time = max(0, self.loop_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)
 
    def _check_detections(self):
        if self._target_manager is None:
            return
        if self.current_position is None:
            return
        if self.phase != DronePhase.COVERING:
            return
 
        hit = self._target_manager.check_detection(
            drone_id=self.drone_id,
            lat=self.current_position.lat,
            lon=self.current_position.lon,
        )
        if hit is not None and self._validation_protocol is not None:
            self._validation_protocol.on_detection(hit)
 
    def _execute_navigation_step(self):
        waypoint = self.nav.get_waypoint(
            self.current_position,
            validation_target=self._validation_target,
        )
        if waypoint is None:
            return
        if self.phase == DronePhase.SPAWNING and self.nav.can_navigate():
            self.phase = DronePhase.COVERING
        target_lat, target_lon = waypoint
        self.flight.goto(target_lat, target_lon, self.altitude)
 
    def _send_until_reached(self, lat: float, lon: float, alt: float, timeout: float = 60):
        target = Position(lat, lon, alt)
        return self.flight.goto_until_reached(target, alt, threshold_m=3.0, timeout=timeout)
 
    def _goto(self, lat: float, lon: float, alt: float):
        self.flight.goto(lat, lon, alt)
 
    def _update_position(self):
        pos = self.conn.get_position()
        if pos:
            self.current_position = pos
 
 
# ═══════════════════════════════════════════════════════════════════
# Utility
# ═══════════════════════════════════════════════════════════════════
 
def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R      = 6371000
    phi1   = math.radians(lat1)
    phi2   = math.radians(lat2)
    dphi   = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))