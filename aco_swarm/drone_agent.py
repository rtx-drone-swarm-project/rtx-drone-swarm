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
    ):
        self.drone_id       = drone_id
        self.connection_str = connection
        self.grid           = grid
        self.altitude       = altitude
        self.loop_interval  = 1.0 / loop_hz
        self.start_lat      = None
        self.start_lon      = None

        self.master: Optional[mavutil.mavfile] = None
        self.lat:    Optional[float] = None
        self.lon:    Optional[float] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ── Lifecycle ───────────────────────────────────────────────────

    def connect(self, timeout: float = 60.0):
        log.info(f"[Drone {self.drone_id}] Connecting → {self.connection_str}")

        is_udp = self.connection_str.startswith("udp")

        self.master = mavutil.mavlink_connection(
            self.connection_str,
            source_system = self.drone_id + 100,  # 100-114, avoids MAVProxy (255)
            # udpin is passive — MAVProxy pushes to us, no autoreconnect needed
            autoreconnect = not is_udp,
        )

        # Wait specifically for a vehicle heartbeat (not MAVProxy's GCS heartbeat)
        # MAVProxy heartbeat has type MAV_TYPE_GCS (6), vehicle is MAV_TYPE_QUADROTOR (2)
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self.master.recv_match(type='HEARTBEAT', blocking=True, timeout=2)
            if msg:
                self.master.target_system    = msg.get_srcSystem()
                self.master.target_component = msg.get_srcComponent()
                break
        else:
            raise TimeoutError(f"[Drone {self.drone_id}] No vehicle heartbeat within {timeout}s")

        # Request position data at 5Hz
        self.master.mav.request_data_stream_send(
            self.master.target_system,
            self.master.target_component,
            mavutil.mavlink.MAV_DATA_STREAM_POSITION,
            5, 1
        )

        log.info(
            f"[Drone {self.drone_id}] Heartbeat OK "
            f"(sysid={self.master.target_system})"
        )

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

            self._wait_for_ekf()

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
        self.grid.deposit(self.lat, self.lon)
        target_lat, target_lon = self.grid.get_gradient(self.lat, self.lon)
        self._goto(target_lat, target_lon, self.altitude)
        log.debug(
            f"[Drone {self.drone_id}] ({self.lat:.5f},{self.lon:.5f}) "
            f"→ ({target_lat:.5f},{target_lon:.5f})"
        )

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
        log.info(f"[Drone {self.drone_id}] Arming…")
        self.master.arducopter_arm()

        start = time.time()
        while not self.master.motors_armed():
            if time.time() - start > 30:
                log.error(f"[Drone {self.drone_id}] Arming timed out — check pre-arm failures above")
                return False
            msg = self.master.recv_match(type="STATUSTEXT", blocking=False)
            if msg:
                log.info(f"[Drone {self.drone_id}] VEHICLE: {msg.text.strip()}")
            time.sleep(0.5)

        log.info(f"[Drone {self.drone_id}] Armed ✓")
        return True

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