"""Background SITL telemetry bridge and direct MAVLink dispatch helpers.

This module is the backend's adapter between mission logic and ArduPilot SITL.
It owns long-lived MAVLink TCP connections, turns raw MAVLink messages into a
small cached state model, and exposes two control surfaces:

- a passive telemetry snapshot used by routes and the simulation loop
- an active command path for direct dispatch and lightweight goto updates

The bridge assumes SITL drones are launched in numbered slots whose TCP ports
increase by a fixed step. Internally we store connections by slot index and map
sysid -> slot with the simplifying assumption that sysids are allocated
sequentially starting at 1 by the swarm launcher.
"""

import asyncio
import logging
import threading
import time
from typing import Dict, List, Optional

from pymavlink import mavutil

from app.missions import missions_db
from app.settings import (
    DEFAULT_SITL_BASE_PORT,
    DEFAULT_SITL_COUNT,
    DEFAULT_SITL_HOST,
    DEFAULT_SITL_POLL_INTERVAL_SECONDS,
    DEFAULT_SITL_PORT_STEP,
    GOTO_TYPE_MASK,
)
from app.ws import manager


logger = logging.getLogger(__name__)


class SITLTelemetryBridge:
    """Maintains MAVLink TCP connections and exposes live drone state by sysid."""

    def __init__(
        self,
        host: str = DEFAULT_SITL_HOST,
        base_port: int = DEFAULT_SITL_BASE_PORT,
        port_step: int = DEFAULT_SITL_PORT_STEP,
        count: int = DEFAULT_SITL_COUNT,
        poll_interval_seconds: float = DEFAULT_SITL_POLL_INTERVAL_SECONDS,
    ):
        """Configure bridge networking, polling cadence, and internal connection state."""
        self.host = host
        self.base_port = base_port
        self.port_step = port_step
        self.count = count
        self.poll_interval_seconds = poll_interval_seconds
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        # Connection objects are keyed by spawn slot index, not sysid. Other
        # helpers derive the slot as sysid - 1 because the current SITL
        # launcher uses auto-incremented sysids starting at 1.
        self._conn_locks: Dict[int, threading.Lock] = {}
        self._connections: Dict[int, object] = {}
        # _states_by_sysid is the public-facing cache. Route handlers and
        # simulation code read copies of this state instead of touching pymavlink
        # connections directly.
        self._states_by_sysid: Dict[int, dict] = {}
        self._connect_fail_logged: set = set()
        # This set prevents the simulation loop from issuing background gotos or
        # re-arm commands while a drone is already inside a staged dispatch flow.
        self._dispatching_sysids: set = set()
        self._last_arm_time: Dict[int, float] = {}

    def start(self) -> None:
        """Start the background polling thread if it is not already running."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="sitl-telemetry-bridge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background polling thread and wait briefly for it to exit."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def get_states_by_sysid(self) -> Dict[int, dict]:
        """Return a copy of the latest known telemetry state for each connected sysid."""
        with self._lock:
            return {sysid: dict(state) for sysid, state in self._states_by_sysid.items()}

    def _run(self) -> None:
        """Continuously connect to configured ports and drain MAVLink messages into state."""
        while not self._stop_event.is_set():
            for index in range(self.count):
                if self._stop_event.is_set():
                    break
                if index not in self._connections:
                    # Each slot corresponds to one expected SITL vehicle.
                    self._try_connect(index)

            for index, conn in list[tuple[int, object]](self._connections.items()):
                try:
                    while True:
                        msg = conn.recv_match(blocking=False)
                        if msg is None:
                            break
                        self._handle_message(msg)
                except Exception:
                    # Drop broken connections and let the next outer-loop pass
                    # attempt to recreate them.
                    self._connections.pop(index, None)

            self._stop_event.wait(self.poll_interval_seconds)

    def _try_connect(self, index: int) -> None:
        """Attempt to open one MAVLink TCP connection and request telemetry streams."""
        port = self.base_port + index * self.port_step
        address = self._connection_address(port)
        try:
            conn = mavutil.mavlink_connection(address, source_system=255)
            conn.wait_heartbeat(timeout=5)
            sysid = conn.target_system
            # Ask SITL to emit the common streams at a steady rate so the bridge
            # can derive position, arm state, mode, readiness, and battery data.
            conn.mav.request_data_stream_send(
                sysid,
                conn.target_component,
                mavutil.mavlink.MAV_DATA_STREAM_ALL,
                10,
                1,
            )
            self._connections[index] = conn
            self._conn_locks[index] = threading.Lock()
            logger.info("SITL bridge connected to %s (sysid=%s)", address, sysid)
            self._connect_fail_logged.discard(index)
        except Exception as exc:
            if index not in self._connect_fail_logged:
                self._connect_fail_logged.add(index)
                logger.warning(
                    "SITL telemetry bridge cannot connect to %s (port %s): %s",
                    address,
                    port,
                    exc,
                )

    def _connection_address(self, port: int) -> str:
        """Build the MAVLink connection string for one TCP SITL endpoint."""
        return f"tcp:{self.host}:{port}"

    def _handle_message(self, msg: object) -> None:
        """Merge one MAVLink message into the cached per-sysid state dictionary."""
        message_type = msg.get_type()
        sysid = int(msg.get_srcSystem())
        if sysid <= 0:
            return

        with self._lock:
            # The cache is intentionally flatter than the MAVLink model. It holds
            # only the fields the routes, frontend, and simulation loop actually
            # consume.
            state = self._states_by_sysid.setdefault(
                sysid,
                {
                    "sysid": sysid,
                    "armed": False,
                    "mode": "UNKNOWN",
                    "lat": None,
                    "lon": None,
                    "alt": None,
                    "heading": None,
                    "groundspeed": None,
                    "battery_remaining": None,
                    "has_position": False,
                    "prearm_ok": False,
                    "ekf_ok": False,
                    "last_seen": time.time(),
                },
            )
            state["last_seen"] = time.time()

            if message_type == "HEARTBEAT":
                # HEARTBEAT gives us the vehicle's arm bit and current flight mode.
                state["armed"] = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                mode_name = "UNKNOWN"
                mode_mapping = mavutil.mode_string_v10(msg)
                if isinstance(mode_mapping, str) and mode_mapping:
                    mode_name = mode_mapping
                state["mode"] = mode_name
            elif message_type == "VFR_HUD":
                # VFR_HUD carries a convenient relative-altitude and groundspeed
                # view, which is good enough for frontend display and dispatch gating.
                state["groundspeed"] = float(msg.groundspeed)
                state["alt"] = float(msg.alt)
                heading = getattr(msg, "heading", None)
                if heading not in (None, 65535):
                    state["heading"] = float(heading)
            elif message_type == "GLOBAL_POSITION_INT":
                # GLOBAL_POSITION_INT is the authoritative position feed used for
                # map display and for marking the drone as telemetry-backed.
                state["lat"] = msg.lat / 1e7
                state["lon"] = msg.lon / 1e7
                state["alt"] = msg.relative_alt / 1000.0
                heading = getattr(msg, "hdg", None)
                if heading not in (None, 65535):
                    state["heading"] = heading / 100.0
                state["has_position"] = True
            elif message_type == "SYS_STATUS":
                battery_remaining = getattr(msg, "battery_remaining", None)
                if battery_remaining not in (None, -1):
                    state["battery_remaining"] = int(battery_remaining)
                # ArduPilot exposes pre-arm health through the sensor-health bitset.
                prearm_bit = mavutil.mavlink.MAV_SYS_STATUS_PREARM_CHECK
                state["prearm_ok"] = bool(msg.onboard_control_sensors_health & prearm_bit)
            elif message_type == "EKF_STATUS_REPORT":
                # The bridge treats EKF readiness as a simple "GPS fused and
                # reasonably healthy" check rather than reproducing ArduPilot's
                # full estimator state machine.
                flags = msg.flags
                has_gps = bool(flags & 8)
                has_vel = bool(flags & 1)
                healthy = msg.velocity_variance < 0.5 and msg.pos_horiz_variance < 0.5
                state["ekf_ok"] = has_gps and has_vel and healthy
            elif message_type == "COMMAND_ACK":
                cmd = getattr(msg, "command", None)
                result = getattr(msg, "result", None)
                result_names = {
                    0: "ACCEPTED",
                    1: "TEMPORARILY_REJECTED",
                    2: "DENIED",
                    3: "UNSUPPORTED",
                    4: "FAILED",
                }
                logger.info(
                    "COMMAND_ACK sysid=%s cmd=%s result=%s(%s)",
                    sysid,
                    cmd,
                    result,
                    result_names.get(result, "?"),
                )

    def _send_command(
        self,
        conn: object,
        sysid: int,
        cmd_id: int,
        p1: float = 0,
        p2: float = 0,
        p3: float = 0,
        p4: float = 0,
        p5: float = 0,
        p6: float = 0,
        p7: float = 0,
    ) -> None:
        """Send a MAVLink command-long message to one vehicle."""
        conn.mav.command_long_send(
            sysid,
            conn.target_component,
            cmd_id,
            0,
            p1,
            p2,
            p3,
            p4,
            p5,
            p6,
            p7,
        )

    def _send_position_target(self, conn: object, sysid: int, lat: float, lon: float, alt: float) -> None:
        """Send a global-relative-altitude goto target to one vehicle."""
        # GOTO_TYPE_MASK disables velocity/acceleration/yaw control so only
        # the position target is honored.
        conn.mav.set_position_target_global_int_send(
            0,
            sysid,
            conn.target_component,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
            GOTO_TYPE_MASK,
            int(lat * 1e7),
            int(lon * 1e7),
            alt,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        )

    def _get_conn(self, sysid: int) -> Optional[object]:
        """Return the raw MAVLink connection for a sysid if the bridge owns one."""
        with self._lock:
            # Current SITL swarm config implies sysid 1 -> slot 0, sysid 2 -> slot 1, etc.
            return self._connections.get(sysid - 1)

    def _get_conn_lock(self, sysid: int) -> Optional[threading.Lock]:
        """Return the per-connection lock used to serialize MAVLink writes."""
        with self._lock:
            return self._conn_locks.get(sysid - 1)

    def is_dispatching(self, sysid: int) -> bool:
        """Report whether a drone is currently inside the direct dispatch flow."""
        return sysid in self._dispatching_sysids

    def is_ready(self, sysid: int) -> bool:
        """Report whether a drone has passed both pre-arm and EKF readiness checks."""
        with self._lock:
            st = self._states_by_sysid.get(sysid)
            if not st:
                return False
            return bool(st.get("prearm_ok") and st.get("ekf_ok"))

    def _poll_state(self, sysid: int, key: str, target, timeout: float) -> bool:
        """Wait until one cached state field reaches an expected value or times out."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                st = self._states_by_sysid.get(sysid, {})
                if st.get(key) == target:
                    return True
            time.sleep(0.25)
        return False

    def _poll_alt_above(self, sysid: int, threshold: float, timeout: float) -> bool:
        """Wait until a drone's cached altitude reaches the requested threshold."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                st = self._states_by_sysid.get(sysid, {})
                alt = st.get("alt") or 0
                if alt >= threshold:
                    return True
            time.sleep(0.5)
        return False

    def dispatch_drone(
        self,
        sysid: int,
        lat: float,
        lon: float,
        alt: float,
        drone_id: Optional[str] = None,
    ) -> dict:
        """Run GUIDED, arm, takeoff, and goto for one drone through the bridge connection."""
        conn = self._get_conn(sysid)
        conn_lock = self._get_conn_lock(sysid)
        if conn is None or conn_lock is None:
            logger.warning("dispatch_drone sysid=%s: no TCP connection", sysid)
            return {
                "drone_id": drone_id,
                "sysid": sysid,
                "success": False,
                "message": f"No active connection for sysid {sysid}",
            }

        self._dispatching_sysids.add(sysid)
        try:
            # Dispatch waits for both pre-arm and EKF readiness because sending
            # arm/takeoff too early is a common source of silent SITL failures.
            for wait_i in range(60):
                if self.is_ready(sysid):
                    break
                if wait_i == 0:
                    logger.info("dispatch_drone sysid=%s: waiting for prearm+EKF...", sysid)
                time.sleep(1.0)
            else:
                logger.warning("dispatch_drone sysid=%s: timed out waiting for readiness", sysid)
                return {
                    "drone_id": drone_id,
                    "sysid": sysid,
                    "success": False,
                    "message": "Timed out waiting for prearm/EKF readiness",
                }

            logger.info(
                "dispatch_drone sysid=%s: GUIDED+arm+takeoff+goto lat=%.6f lon=%.6f alt=%.1f",
                sysid,
                lat,
                lon,
                alt,
            )

            mode_map = conn.mode_mapping()
            guided_mode = mode_map.get("GUIDED", 4)
            with conn_lock:
                conn.mav.set_mode_send(
                    sysid,
                    mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
                    guided_mode,
                )
            # Mode changes are not always instant, so poll the cached heartbeat
            # state before moving on. If it never confirms, continue anyway and
            # let later checks decide whether the vehicle is responsive enough.
            if not self._poll_state(sysid, "mode", "GUIDED", 5.0):
                logger.warning("dispatch_drone sysid=%s: GUIDED not confirmed, continuing", sysid)

            with conn_lock:
                self._send_command(conn, sysid, mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1)
            self._last_arm_time[sysid] = time.time()

            # Arming must be observed through telemetry before takeoff; otherwise
            # the backend risks pushing commands at a vehicle that ignored arm.
            if not self._poll_state(sysid, "armed", True, 10.0):
                logger.warning("dispatch_drone sysid=%s: armed not confirmed by heartbeat", sysid)
                return {
                    "drone_id": drone_id,
                    "sysid": sysid,
                    "success": False,
                    "message": "Armed state not confirmed by heartbeat",
                }

            logger.info("dispatch_drone sysid=%s: armed confirmed, sending takeoff to %.0fm", sysid, alt)
            with conn_lock:
                self._send_command(conn, sysid, mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, p7=alt)

            # Wait until the vehicle is plausibly airborne before sending the
            # first goto. If the altitude never clears the threshold, still send
            # goto so the mission is not deadlocked on a slow climb.
            if not self._poll_alt_above(sysid, 3.0, 15.0):
                logger.warning("dispatch_drone sysid=%s: alt < 3m after 15s, sending goto anyway", sysid)
            else:
                logger.info("dispatch_drone sysid=%s: alt >= 3m, sending goto", sysid)

            with conn_lock:
                self._send_position_target(conn, sysid, lat, lon, alt)

            logger.info("dispatch_drone sysid=%s: dispatch complete", sysid)
            return {
                "drone_id": drone_id,
                "sysid": sysid,
                "success": True,
                "message": f"Direct dispatch GUIDED/arm/takeoff/goto lat={lat:.6f} lon={lon:.6f} alt={alt:.1f}",
            }
        except Exception as exc:
            logger.error("dispatch_drone sysid=%s: send error: %s", sysid, exc)
            return {
                "drone_id": drone_id,
                "sysid": sysid,
                "success": False,
                "message": str(exc),
            }
        finally:
            self._dispatching_sysids.discard(sysid)

    def send_goto(self, sysid: int, lat: float, lon: float, alt: float) -> bool:
        """Send a single goto target to a connected drone without the full dispatch flow."""
        conn = self._get_conn(sysid)
        conn_lock = self._get_conn_lock(sysid)
        if conn is None or conn_lock is None:
            return False
        try:
            with conn_lock:
                self._send_position_target(conn, sysid, lat, lon, alt)
            return True
        except Exception:
            return False


sitl_bridge = SITLTelemetryBridge()


def _any_mission_running() -> bool:
    """Return True when any in-memory mission is currently marked running."""
    return any(m.get("status") == "running" for m in missions_db.values())


def telemetry_drones_from_sitl_bridge() -> List[dict]:
    """Convert the cached SITL bridge snapshot into frontend-facing drone payloads."""
    states = sitl_bridge.get_states_by_sysid()
    drones: List[dict] = []
    for sysid in sorted(states.keys()):
        st = states[sysid]
        # Ignore vehicles that have not reported a usable position yet; the
        # frontend only treats these payloads as map-ready drones.
        if not st.get("has_position"):
            continue
        lat, lon = st.get("lat"), st.get("lon")
        if lat is None or lon is None:
            continue
        drones.append(
            {
                "id": str(sysid),
                "sysid": sysid,
                "lat": float(lat),
                "lon": float(lon),
                "alt": st.get("alt"),
                "heading": st.get("heading"),
                "groundspeed": st.get("groundspeed"),
                "battery_remaining": st.get("battery_remaining"),
                "armed": st.get("armed"),
                "mode": st.get("mode"),
                "telemetry_source": "sitl",
            }
        )
    return drones


async def idle_sitl_telemetry_loop() -> None:
    """Broadcast idle telemetry when clients are connected but no mission is running."""
    while True:
        try:
            await asyncio.sleep(1.0)
            if not manager.active_connections:
                continue
            if _any_mission_running():
                # Active missions own their own broadcast cadence through the
                # simulation loop; this idle loop is only for the pre-mission UI.
                continue
            drones = telemetry_drones_from_sitl_bridge()
            if not drones:
                continue
            await manager.broadcast({"type": "telemetry", "drones": drones})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("idle_sitl_telemetry_loop error")
