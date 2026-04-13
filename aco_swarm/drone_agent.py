"""
drone_agent.py
--------------
One drone connected via MAVLink.
Supports both TCP (direct to SITL) and UDP (via MAVProxy udpout).

When using udpin: agent listens on its port, MAVProxy pushes to it.
source_system = drone_id + 100 avoids clashing with MAVProxy (255).
"""

import time
import threading
import logging
from typing import Optional

from pymavlink import mavutil
from stigmergy_engine import InMemoryPheromoneGrid
from voronoi_aco_hybrid import VoronoiACOPlanner, DroneState

log = logging.getLogger(__name__)


class DroneAgent:
    """
    Parameters
    ----------
    drone_id   : unique index (0–14)
    connection : pymavlink connection string
                 TCP:  'tcp:127.0.0.1:5760'
                 UDP:  'udpin:127.0.0.1:14560'
    grid       : shared pheromone grid
    altitude   : target altitude above home in metres
    loop_hz    : stigmergy decisions per second
    """

    def __init__(
        self,
        drone_id: int,
        connection: str,
        grid: InMemoryPheromoneGrid,
        altitude: float = 10.0,
        loop_hz: float  = 0.5,
        expected_sysid: int = None,
        planner=None,    
    ):
        self.drone_id       = drone_id
        self.connection_str = connection
        self.grid           = grid
        self.altitude       = altitude
        self.loop_interval  = 1.0 / loop_hz
        self.expected_sysid = expected_sysid if expected_sysid is not None else drone_id + 1
        self.start_lat      = None
        self.start_lon      = None

        self.master: Optional[mavutil.mavfile] = None
        self.lat:    Optional[float] = None
        self.lon:    Optional[float] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.planner = planner
        self.territory = None   

    # ── Lifecycle ───────────────────────────────────────────────────

    def _wait_for_gps_lock(self, timeout=120):
        log.info(f"[Drone {self.drone_id}] Waiting for GPS lock...")
        start = time.time()
        while time.time() - start < timeout:
            msg = self.master.recv_match(type="GPS_RAW_INT", blocking=True, timeout=2)
            if msg and msg.get_srcSystem() == self.expected_sysid:
                # fix_type: 0=no fix, 1=no fix, 2=2D, 3=3D
                if msg.fix_type >= 3:
                    log.info(f"[Drone {self.drone_id}] GPS lock OK (fix={msg.fix_type}, sats={msg.satellites_visible})")
                    return True
        return False

    def connect(self, timeout=60.0):
        self.master = mavutil.mavlink_connection(self.connection_str,
            source_system=self.drone_id + 100, autoreconnect=False)
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self.master.recv_match(type="HEARTBEAT", blocking=True, timeout=2)
            if msg and msg.get_srcSystem() == self.expected_sysid:
                self.master.target_system    = msg.get_srcSystem()
                self.master.target_component = msg.get_srcComponent()
                break
        else:
            raise TimeoutError(f"No heartbeat from sysid={self.expected_sysid}")

    def start(self):
        self._running = True
        self._thread  = threading.Thread(
            target=self._run, daemon=True, name=f"drone-{self.drone_id}"
        )
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    # ── Main loop ───────────────────────────────────────────────────

    def _run(self):
        try:
            self._set_mode("GUIDED")

            # Wait for EKF/GPS first
            if not self._wait_for_position_estimate():
                log.error(f"[Drone {self.drone_id}] No position estimate — aborting")
                return

            if not self._wait_for_ekf():
                log.error(f"[Drone {self.drone_id}] EKF not ready — aborting")
                return

            if not self._wait_for_gps_lock():
                log.error(f"[Drone {self.drone_id}] No GPS lock — aborting")
                return

            # Arm, but only continue if it worked
            if not self._arm():
                return

            self._takeoff(self.altitude)
            log.info(f"[Drone {self.drone_id}] Airborne ✓ — stigmergy loop started")

            while self._running:
                t0 = time.time()
                self._update_position()
                if self.lat is not None:
                    self._stigmergy_step()
                sleep_for = self.loop_interval - (time.time() - t0)
                if sleep_for > 0:
                    time.sleep(sleep_for)

        except Exception as e:
            log.error(f"[Drone {self.drone_id}] Fatal: {e}", exc_info=True)

    def _stigmergy_step(self):
        prev_lat, prev_lon = self.lat, self.lon   # snapshot before goto

        if self.planner:
            state = DroneState(id=self.drone_id, lat=self.lat, lon=self.lon)
            if self.territory is not None:
                state.territory = self.territory
            target_lat, target_lon = self.planner._aco_waypoint(state)
            target_lat, target_lon = self.planner.clamp_to_territory(
                state, target_lat, target_lon
            )
            # Deposit along the path traveled since last tick, not just current cell
            self.planner.pheromone.deposit_path(prev_lat, prev_lon, self.lat, self.lon)
        else:
            target_lat, target_lon = self.grid.get_gradient(self.lat, self.lon)
            self.grid.deposit_path(prev_lat, prev_lon, self.lat, self.lon)

        self._goto(target_lat, target_lon, self.altitude)

    # ── MAVLink helpers ─────────────────────────────────────────────

    def _set_mode(self, mode: str):
        mode_id = self.master.mode_mapping()[mode]
        self.master.mav.set_mode_send(
            self.master.target_system,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            mode_id,
        )
        log.info(f"[Drone {self.drone_id}] Mode → {mode}")
        time.sleep(1)

    def _wait_for_ekf(self, timeout=30):
        start = time.time()
        while time.time() - start < timeout:
            msg = self.master.recv_match(type="EKF_STATUS_REPORT", blocking=True, timeout=2)
            if msg:
                # bit 0 = attitude, bit 1 = velocity, bit 2 = position
                if (msg.flags & 0b111) == 0b111:
                    log.info(f"[Drone {self.drone_id}] EKF OK ✓")
                    return True
        return False

    def _wait_for_position_estimate(self, timeout=60):
        log.info(f"[Drone {self.drone_id}] Waiting for position…")
        start = time.time()

        while time.time() - start < timeout:
            msg = self.master.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=2)
            if msg:
                lat = msg.lat / 1e7
                lon = msg.lon / 1e7
                # SITL gives (0,0) until GPS/EKF ready
                if abs(lat) > 0.001 and abs(lon) > 0.001:
                    self.lat = lat
                    self.lon = lon
                    log.info(f"[Drone {self.drone_id}] Position OK ✓")
                    return True
            time.sleep(0.5)

        return False

    def _arm(self):
        log.info(f"[Drone {self.drone_id}] Arming...")
        self.master.arducopter_arm()
        start        = time.time()
        last_arm_cmd = time.time()          # ← was missing, caused UnboundLocalError
        while time.time() - start < 60:
            if time.time() - last_arm_cmd > 5:
                self.master.arducopter_arm()
                last_arm_cmd = time.time()
            msg = self.master.recv_match(blocking=True, timeout=2)
            if msg is None:
                continue
            if msg.get_type() == "HEARTBEAT" and msg.get_srcSystem() == self.expected_sysid:
                if (msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED) != 0:
                    log.info(f"[Drone {self.drone_id}] Armed ✓")
                    return True
            elif msg.get_type() == "STATUSTEXT" and msg.get_srcSystem() == self.expected_sysid:
                log.info(f"[Drone {self.drone_id}] VEHICLE: {msg.text.strip()}")
                if "PreArm" in msg.text or "prearm" in msg.text.lower():
                    log.warning(f"[Drone {self.drone_id}] Pre-arm block: {msg.text.strip()}")
        log.error(f"[Drone {self.drone_id}] Arming timed out")
        return False

    def _takeoff(self, alt: float):
        log.info(f"[Drone {self.drone_id}] Taking off to {alt}m…")
        self.master.mav.command_long_send(
            self.master.target_system,
            self.master.target_component,
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            0, 0, 0, 0, 0, 0, 0, alt,
        )
        while True:
            self._update_position()
            msg = self.master.recv_match(
                type="GLOBAL_POSITION_INT", blocking=True, timeout=2
            )
            if msg and msg.relative_alt / 1000.0 >= alt * 0.90:
                log.info(f"[Drone {self.drone_id}] Reached {msg.relative_alt/1000:.1f}m ✓")
                break
            time.sleep(0.5)

    def _goto(self, lat: float, lon: float, alt: float):
        self.master.mav.set_position_target_global_int_send(
            0,
            self.master.target_system,
            self.master.target_component,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
            0b0000111111111000,
            int(lat * 1e7),
            int(lon * 1e7),
            alt,
            0, 0, 0,
            0, 0, 0,
            0, 0,
        )

    def _update_position(self):
        msg = self.master.recv_match(type="GLOBAL_POSITION_INT", blocking=False)
        if msg:
            self.lat = msg.lat / 1e7
            self.lon = msg.lon / 1e7