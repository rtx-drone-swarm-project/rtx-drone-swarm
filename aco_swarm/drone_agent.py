"""
drone_agent.py
--------------
Modular drone agent with separated concerns:
  - MAVLinkConnection: low-level MAVLink communication
  - FlightController: vehicle state and flight commands
  - NavigationController: high-level waypoint following
  - DroneAgent: orchestrates everything

Architecture:
    DroneAgent
        ├── MAVLinkConnection (handles messaging)
        ├── FlightController  (handles arm/takeoff/goto)
        └── NavigationController (handles planner integration)
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
    """GPS position with validation."""
    lat: float
    lon: float
    alt: float = 0.0
    
    def is_valid(self) -> bool:
        """Check if position is non-zero (SITL returns 0,0 before GPS lock)."""
        return abs(self.lat) > 0.001 and abs(self.lon) > 0.001
    
    def distance_to(self, other: 'Position') -> float:
        """Haversine distance in meters."""
        return haversine_m(self.lat, self.lon, other.lat, other.lon)
    
    def to_tuple(self) -> Tuple[float, float]:
        return (self.lat, self.lon)


class DronePhase(Enum):
    """Drone operational phases."""
    INITIALIZING = "initializing"
    SPAWNING = "spawning"
    TERRITORY_ASSIGNED = "territory_assigned"
    COVERING = "covering"
    ERROR = "error"


# ═══════════════════════════════════════════════════════════════════
# MAVLink Communication Layer
# ═══════════════════════════════════════════════════════════════════

class MAVLinkConnection:
    """
    Low-level MAVLink message handling.
    Filters by sysid to prevent cross-drone message contamination.
    """
    
    def __init__(self, connection_str: str, drone_id: int, expected_sysid: int):
        self.connection_str = connection_str
        self.drone_id = drone_id
        self.expected_sysid = expected_sysid
        self.source_system = drone_id + 100  # avoid clash with MAVProxy (255)
        self.master: Optional[mavutil.mavfile] = None
    
    def connect(self, timeout: float = 60.0) -> bool:
        """Establish connection and wait for heartbeat."""
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
                    self.master.target_system = msg.get_srcSystem()
                    self.master.target_component = msg.get_srcComponent()
                    log.info(f"[Drone {self.drone_id + 1}] MAVLink connected ✓")
                    return True
            
            log.error(f"[Drone {self.drone_id + 1}] No heartbeat from sysid={self.expected_sysid}")
            return False
            
        except Exception as e:
            log.error(f"[Drone {self.drone_id + 1}] Connection failed: {e}")
            return False
    
    def wait_for_gps_lock(self, timeout: float = 120) -> bool:
        """Wait for 3D GPS fix."""
        log.info(f"[Drone {self.drone_id + 1}] Waiting for GPS lock...")
        start = time.time()
        
        while time.time() - start < timeout:
            msg = self.master.recv_match(type="GPS_RAW_INT", blocking=True, timeout=2)
            if msg and msg.get_srcSystem() == self.expected_sysid:
                if msg.fix_type >= 3:  # 3D fix
                    log.info(f"[Drone {self.drone_id + 1}] GPS lock OK ✓ (sats={msg.satellites_visible})")
                    return True
        
        return False
    
    def wait_for_ekf(self, timeout: float = 30) -> bool:
        """Wait for EKF attitude/velocity/position flags."""
        start = time.time()
        
        while time.time() - start < timeout:
            msg = self.master.recv_match(type="EKF_STATUS_REPORT", blocking=True, timeout=2)
            if msg:
                if (msg.flags & 0b111) == 0b111:  # attitude + velocity + position
                    log.info(f"[Drone {self.drone_id + 1}] EKF ready ✓")
                    return True
        
        return False
    
    def get_position(self) -> Optional[Position]:
        """Get current GPS position (non-blocking)."""
        msg = self.master.recv_match(type="GLOBAL_POSITION_INT", blocking=False)
        if msg and msg.get_srcSystem() == self.expected_sysid:
            pos = Position(
                lat=msg.lat / 1e7,
                lon=msg.lon / 1e7,
                alt=msg.relative_alt / 1000.0
            )
            return pos if pos.is_valid() else None
        return None
    
    def wait_for_position(self, timeout: float = 60) -> Optional[Position]:
        """Wait for valid position estimate (blocking)."""
        log.info(f"[Drone {self.drone_id + 1}] Waiting for position...")
        start = time.time()
        
        while time.time() - start < timeout:
            msg = self.master.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=2)
            if msg and msg.get_srcSystem() == self.expected_sysid:
                pos = Position(
                    lat=msg.lat / 1e7,
                    lon=msg.lon / 1e7,
                    alt=msg.relative_alt / 1000.0
                )
                if pos.is_valid():
                    log.info(f"[Drone {self.drone_id + 1}] Position OK ✓")
                    return pos
            time.sleep(0.5)
        
        return None


# ═══════════════════════════════════════════════════════════════════
# Flight Control Layer
# ═══════════════════════════════════════════════════════════════════

class FlightController:
    """
    Mid-level flight commands: arm, takeoff, goto, mode changes.
    """
    
    def __init__(self, connection: MAVLinkConnection, drone_id: int):
        self.conn = connection
        self.drone_id = drone_id
        self.master = connection.master
    
    def set_mode(self, mode: str) -> bool:
        """Set flight mode (GUIDED, LOITER, etc)."""
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
        """Arm the vehicle."""
        log.info(f"[Drone {self.drone_id + 1}] Arming...")
        start = time.time()
        last_arm_cmd = time.time()
        
        while time.time() - start < timeout:
            # Retry arm command every 5s
            if time.time() - last_arm_cmd > 5:
                self.master.arducopter_arm()
                last_arm_cmd = time.time()
            
            msg = self.master.recv_match(blocking=True, timeout=2)
            if msg is None:
                continue
            
            # Check heartbeat for armed state
            if msg.get_type() == "HEARTBEAT" and msg.get_srcSystem() == self.conn.expected_sysid:
                if (msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED) != 0:
                    log.info(f"[Drone {self.drone_id + 1}] Armed ✓")
                    return True
            
            # Log prearm failures
            elif msg.get_type() == "STATUSTEXT" and msg.get_srcSystem() == self.conn.expected_sysid:
                if "PreArm" in msg.text or "prearm" in msg.text.lower():
                    log.warning(f"[Drone {self.drone_id + 1}] {msg.text.strip()}")
        
        log.error(f"[Drone {self.drone_id + 1}] Arming timeout")
        return False
    
    def takeoff(self, altitude: float) -> bool:
        """Takeoff to target altitude."""
        log.info(f"[Drone {self.drone_id + 1}] Takeoff → {altitude}m...")
        
        self.master.mav.command_long_send(
            self.master.target_system,
            self.master.target_component,
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            0, 0, 0, 0, 0, 0, 0, altitude,
        )
        
        # Wait for altitude
        while True:
            msg = self.master.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=2)
            if msg and msg.get_srcSystem() == self.conn.expected_sysid:
                current_alt = msg.relative_alt / 1000.0
                if current_alt >= altitude * 0.90:
                    log.info(f"[Drone {self.drone_id + 1}] Reached {current_alt:.1f}m ✓")
                    return True
            time.sleep(0.5)
    
    def goto(self, lat: float, lon: float, alt: float):
        """Send position target (non-blocking)."""
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
            self.master.target_system,
            self.master.target_component,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
            type_mask,
            int(lat * 1e7),
            int(lon * 1e7),
            alt,
            0, 0, 0, 0, 0, 0, 0, 0,
        )
    
    def goto_until_reached(self, target: Position, altitude: float, 
                           threshold_m: float = 3.0, timeout: float = 60) -> bool:
        """Send goto commands until position reached (blocking)."""
        start = time.time()
        
        while time.time() - start < timeout:
            self.goto(target.lat, target.lon, altitude)
            
            current_pos = self.conn.get_position()
            if current_pos:
                dist = current_pos.distance_to(target)
                if dist < threshold_m:
                    log.info(f"[Drone {self.drone_id + 1}] Reached target ✓")
                    return True
            
            time.sleep(0.2)
        
        log.warning(f"[Drone {self.drone_id + 1}] Failed to reach target (timeout)")
        return False


# ═══════════════════════════════════════════════════════════════════
# Navigation Controller
# ═══════════════════════════════════════════════════════════════════

class NavigationController:
    """
    High-level navigation using planner integration.
    Handles phase transitions: LLOYD → ACO.
    """
    
    def __init__(self, drone_id: int, planner: VoronoiACOPlanner, grid: InMemoryPheromoneGrid):
        self.drone_id = drone_id
        self.planner = planner
        self.grid = grid
        self.territory: Optional[np.ndarray] = None
        self.prev_position: Optional[Position] = None
    
    def can_navigate(self) -> bool:
        """Check if navigation is possible (has territory assignment)."""
        return self.territory is not None and len(self.territory) > 0
    
    def should_defer_to_lloyd(self) -> bool:
        """Check if Lloyd is currently active (blocks ACO navigation)."""
        return getattr(self.planner, "lloyd_active", False)
    
    def get_waypoint(self, current_pos: Position) -> Optional[Tuple[float, float]]:
        """
        Get next waypoint using ACO within assigned territory.
        Returns None if Lloyd is active or no territory assigned.
        """
        if self.should_defer_to_lloyd():
            return None
        
        if not self.can_navigate():
            return None
        
        # Build drone state
        state = DroneState(
            id=self.drone_id,
            lat=current_pos.lat,
            lon=current_pos.lon
        )
        state.territory = self.territory
        
        # Get ACO waypoint
        target_lat, target_lon = self.planner._aco_waypoint(state)
        
        # Clamp to territory boundaries
        target_lat, target_lon = self.planner.clamp_to_territory(state, target_lat, target_lon)
        
        # Deposit pheromone along path
        if self.prev_position:
            self.planner.pheromone.deposit_path(
                self.prev_position.lat, self.prev_position.lon,
                current_pos.lat, current_pos.lon
            )
        
        self.prev_position = current_pos
        return (target_lat, target_lon)


# ═══════════════════════════════════════════════════════════════════
# Main Drone Agent
# ═══════════════════════════════════════════════════════════════════

class DroneAgent:
    """
    Main drone orchestrator.
    Coordinates: connection → flight control → navigation.
    
    Lifecycle:
        1. connect()  — establish MAVLink connection
        2. start()    — spawn agent thread
        3. Agent runs: initialize → spawn → navigate
        4. stop()     — graceful shutdown
    """
    
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
        self.drone_id = drone_id
        self.altitude = altitude
        self.loop_interval = 1.0 / loop_hz
        
        # Spawn position (set externally before start())
        self.spawn_position: Optional[Position] = None
        
        # Operational state
        self.phase = DronePhase.INITIALIZING
        self.airborne = False
        self.current_position: Optional[Position] = None
        
        # Modular components
        self.conn = MAVLinkConnection(connection_str, drone_id, 
                                      expected_sysid if expected_sysid else drone_id + 1)
        self.flight = None  # initialized after connection
        self.nav = NavigationController(drone_id, planner, grid)
        
        # Threading
        self._running = False
        self._thread: Optional[threading.Thread] = None
    
    @property
    def territory(self):
        """Proxy to navigation controller territory."""
        return self.nav.territory
    
    @territory.setter
    def territory(self, value):
        """Proxy to navigation controller territory."""
        self.nav.territory = value
    
    @property
    def lat(self):
        """Current latitude (for metrics/compatibility)."""
        return self.current_position.lat if self.current_position else None
    
    @property
    def lon(self):
        """Current longitude (for metrics/compatibility)."""
        return self.current_position.lon if self.current_position else None
    
    @property
    def start_lat(self):
        """Spawn latitude."""
        return self.spawn_position.lat if self.spawn_position else None
    
    @start_lat.setter
    def start_lat(self, value):
        """Set spawn latitude."""
        if self.spawn_position is None:
            self.spawn_position = Position(value, 0)
        else:
            self.spawn_position.lat = value
    
    @property
    def start_lon(self):
        """Spawn longitude."""
        return self.spawn_position.lon if self.spawn_position else None
    
    @start_lon.setter
    def start_lon(self, value):
        """Set spawn longitude."""
        if self.spawn_position is None:
            self.spawn_position = Position(0, value)
        else:
            self.spawn_position.lon = value
    
    # ══════════════════════════════════════════════════════════════
    # Lifecycle
    # ══════════════════════════════════════════════════════════════
    
    def connect(self, timeout: float = 60.0) -> bool:
        """Establish MAVLink connection."""
        if not self.conn.connect(timeout):
            return False
        
        # Initialize flight controller after connection
        self.flight = FlightController(self.conn, self.drone_id)
        return True

    
    def start(self):
        """Start agent thread."""
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=f"drone-{self.drone_id + 1}"
        )
        self._thread.start()
    
    def stop(self):
        """Stop agent thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
    
    # ══════════════════════════════════════════════════════════════
    # Main Loop
    # ══════════════════════════════════════════════════════════════
    
    def _run(self):
        """Main agent loop: initialize → spawn → navigate."""
        try:
            # Phase 1: Initialize vehicle
            if not self._initialize_vehicle():
                return
            
            # Phase 2: Takeoff and mark airborne
            if not self.flight.takeoff(self.altitude):
                return
            
            self.airborne = True
            self.phase = DronePhase.SPAWNING
            log.info(f"[Drone {self.drone_id + 1}] Airborne ✓")
            
            # Phase 3: Navigate (ACO coverage loop)
            self._navigation_loop()
        
        except Exception as e:
            log.error(f"[Drone {self.drone_id + 1}] Fatal error: {e}", exc_info=True)
            self.phase = DronePhase.ERROR
    
    def _initialize_vehicle(self) -> bool:
        """
        Vehicle initialization sequence:
          - Set GUIDED mode
          - Wait for position/EKF/GPS
          - Arm motors
        """
        if not self.flight.set_mode("GUIDED"):
            return False
        
        # Wait for position estimate
        pos = self.conn.wait_for_position(timeout=60)
        if not pos:
            log.error(f"[Drone {self.drone_id + 1}] No position estimate")
            return False
        self.current_position = pos
        
        # Wait for EKF ready
        if not self.conn.wait_for_ekf(timeout=30):
            log.error(f"[Drone {self.drone_id + 1}] EKF not ready")
            return False
        
        # Wait for GPS lock
        if not self.conn.wait_for_gps_lock(timeout=120):
            log.error(f"[Drone {self.drone_id + 1}] No GPS lock")
            return False
        
        # Arm vehicle
        if not self.flight.arm(timeout=60):
            log.error(f"[Drone {self.drone_id + 1}] Arming failed")
            return False
        
        log.info(f"[Drone {self.drone_id + 1}] Initialization complete ✓")
        return True
    
    def _navigation_loop(self):
        """
        Main navigation loop: ACO coverage within assigned territory.
        Runs at loop_hz frequency.
        """
        log.info(f"[Drone {self.drone_id + 1}] Navigation loop started")
        
        while self._running:
            t0 = time.time()
            
            # Update current position
            pos = self.conn.get_position()
            if pos:
                self.current_position = pos
                self._execute_navigation_step()
            
            # Sleep for remaining interval
            elapsed = time.time() - t0
            sleep_time = max(0, self.loop_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)
    
    def _execute_navigation_step(self):
        """
        Single navigation step:
          - Get waypoint from planner (ACO)
          - Send goto command
        """
        # Skip if Lloyd is active or no territory assigned
        waypoint = self.nav.get_waypoint(self.current_position)
        if waypoint is None:
            return
        
        # Update phase if we have territory
        if self.phase == DronePhase.SPAWNING and self.nav.can_navigate():
            self.phase = DronePhase.COVERING
        
        # Execute goto
        target_lat, target_lon = waypoint
        self.flight.goto(target_lat, target_lon, self.altitude)
    
    # ══════════════════════════════════════════════════════════════
    # Public Methods (for external control)
    # ══════════════════════════════════════════════════════════════
    
    def _send_until_reached(self, lat: float, lon: float, alt: float, timeout: float = 60):
        """
        Blocking goto — used by swarm_main.py for spawn dispatch.
        Compatibility wrapper around FlightController.goto_until_reached.
        """
        target = Position(lat, lon, alt)
        return self.flight.goto_until_reached(target, alt, threshold_m=3.0, timeout=timeout)
    
    def _goto(self, lat: float, lon: float, alt: float):
        """
        Non-blocking goto — compatibility wrapper.
        """
        self.flight.goto(lat, lon, alt)
    
    def _update_position(self):
        """
        Update position — compatibility wrapper for metrics.py.
        """
        pos = self.conn.get_position()
        if pos:
            self.current_position = pos


# ═══════════════════════════════════════════════════════════════════
# Utility Functions
# ═══════════════════════════════════════════════════════════════════

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate Haversine distance between two GPS coordinates in meters."""
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    
    a = (math.sin(dphi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))