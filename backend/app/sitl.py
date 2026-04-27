"""Background SITL telemetry bridge using the new Swarm and Drone architecture."""

import logging
import threading
import time
from typing import Dict, Optional
import asyncio

# IMPORTANT: Import your new classes here!
from app.connect_swarm import Swarm, Drone 

from app.settings import (
    DEFAULT_SITL_BASE_PORT,
    DEFAULT_SITL_COUNT,
    DEFAULT_SITL_HOST,
    DEFAULT_SITL_PORT_STEP,
    DEFAULT_RECALL_ALT,
)

logger = logging.getLogger(__name__)


def _wait_for_condition(predicate, timeout: float, interval: float = 0.25) -> bool:
    """Poll a state predicate until it becomes true or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())

class SITLTelemetryBridge:
    """Adapter that exposes the new Swarm class to the rest of the FastAPI backend."""

    def __init__(
        self,
        host: str = DEFAULT_SITL_HOST,
        base_port: int = DEFAULT_SITL_BASE_PORT,
        port_step: int = DEFAULT_SITL_PORT_STEP,
        count: int = DEFAULT_SITL_COUNT,
    ):
        self.host = host
        self.base_port = base_port
        self.port_step = port_step
        self.count = count
        self.swarm = Swarm()
        # Keep tracking dispatching to prevent simulation.py from interrupting
        self._dispatching_sysids: set = set()
        self._connect_lock = threading.Lock()
        self._last_connect_error: str | None = None
        self._last_connect_attempt_at = 0.0
        self._retry_interval_seconds = 5.0
        self._stale_connection_seconds = 5.0
        self._recall_states: Dict[int, dict] = {}

    def start(self) -> None:
        """Start the telemetry thread and attempt an initial TCP SITL connection."""
        if not self.swarm.telemetry_thread or not self.swarm.telemetry_thread.is_alive():
            self.swarm.start_background_telemetry()
        self.ensure_connected(force=True)

    def _connections_healthy(self) -> bool:
        if not self.swarm.drones:
            return False
        return all(drone.is_connection_alive(self._stale_connection_seconds) for drone in self.swarm.drones)

    def _drop_stale_connections(self, reason: str) -> None:
        if not self.swarm.drones:
            return
        logger.warning(reason)
        self.swarm.reset_connections()
        self._last_connect_error = reason

    def ensure_connected(self, force: bool = False) -> bool:
        """Attempt to connect to SITL over TCP without crashing the API on failure."""
        if self._connections_healthy():
            self._last_connect_error = None
            return True

        if self.swarm.drones:
            self._drop_stale_connections(
                f"SITL TCP connection lost at tcp://{self.host}:{self.base_port} step {self.port_step}; waiting for reconnection"
            )

        now = time.time()
        if not force and now - self._last_connect_attempt_at < self._retry_interval_seconds:
            return False

        with self._connect_lock:
            if self.swarm.drones:
                self._last_connect_error = None
                return True

            now = time.time()
            if not force and now - self._last_connect_attempt_at < self._retry_interval_seconds:
                return False

            self._last_connect_attempt_at = now

            try:
                self.swarm.connect(
                    count=self.count,
                    host=self.host,
                    start_port=self.base_port,
                    port_step=self.port_step,
                )
                self._last_connect_error = None
                logger.info(
                    "Connected to %s SITL drone(s) at tcp://%s:%s step %s",
                    len(self.swarm.drones),
                    self.host,
                    self.base_port,
                    self.port_step,
                )
                return True
            except Exception as exc:
                self._last_connect_error = str(exc)
                logger.warning(
                    "SITL connection failed at tcp://%s:%s step %s: %s",
                    self.host,
                    self.base_port,
                    self.port_step,
                    exc,
                )
                return False

        #self.swarm.wait_for_all_prearm(timeout = 60)  #IF CURRENT PRE-FLIGHT CHECK LOGIC DOESN'T WORK, UNCOMMENT THIS TO FALL BACK TO A BLOCKING WAIT DURING STARTUP
        #self.swarm.wait_for_ekf_alignment(timeout = 60)

    def stop(self) -> None:
        """Stop the background polling thread."""
        self.swarm.is_running = False
        if self.swarm.telemetry_thread:
            self.swarm.telemetry_thread.join(timeout=1.0)

    def _get_drone(self, sysid: int) -> Optional[Drone]:
        """Helper to find a drone object by sysid."""
        for drone in self.swarm.drones:
            if drone.sysid == sysid:
                return drone
        return None

    def get_states_by_sysid(self) -> Dict[int, dict]:
        """Map the Swarm's internal state format to what the backend expects."""
        self.ensure_connected()
        self.update_recall_states()
        states = {}
        for drone in self.swarm.drones:
            d_state = drone.get_state()
            recall_state = self._recall_states.get(drone.sysid, {})
            
            has_pos = bool(d_state["lat"] and d_state["lon"])
            
            # Only add drones to the telemetry payload if they have a position
            if not has_pos:
                continue

            states[drone.sysid] = {
                "id": str(drone.sysid),               # ADDED THIS FOR FRONTEND
                "sysid": drone.sysid,
                "lat": d_state["lat"],
                "lon": d_state["lon"],
                "alt": d_state["rel_alt"], 
                "groundspeed": d_state["groundspeed"],
                "heading": d_state["heading"],
                "armed": d_state["armed"],
                "mode": d_state["mode"],
                "recall_phase": recall_state.get("phase"),
                "telemetry_source": "sitl",           # ADDED THIS FOR FRONTEND
                "has_position": has_pos,
                "prearm_ok": drone.is_prearm_passed(),
                "ekf_ok": drone.is_ekf_gps_ready(),
                "last_seen": d_state.get("timestamp", time.time())
            }
        return states

    def is_dispatching(self, sysid: int) -> bool:
        return sysid in self._dispatching_sysids

    def is_ready(self, sysid: int) -> bool:
        drone = self._get_drone(sysid)
        if not drone:
            return False
        return drone.is_prearm_passed() and drone.is_ekf_gps_ready()

    def dispatch_drone(self, sysid: int, lat: float, lon: float, alt: float, drone_id: Optional[str] = None) -> dict:
        """Execute the dispatch using your new Drone methods."""
        self._dispatching_sysids.add(sysid)
        try:
            drone = self._get_drone(sysid)
            if not drone:
                return {"drone_id": drone_id, "sysid": sysid, "success": False, "message": "Not connected"}

            # Standardize mode
            if not drone.is_mode("GUIDED"):
                drone.set_mode("GUIDED")
                if not _wait_for_condition(
                    lambda: drone.is_mode("GUIDED"),
                    timeout=10.0
                ):
                    return {
                        "drone_id": drone_id,
                        "sysid": sysid,
                        "success": False,
                        "message": "Failed to enter GUIDED mode before arming",
                    }
            
            # Check if it needs to arm and takeoff
            if not drone.get_state()["armed"]:
                drone.arm()
                if not _wait_for_condition(
                    lambda: drone.get_state()["armed"],
                    timeout=10.0
                ):
                    return {
                        "drone_id": drone_id,
                        "sysid": sysid,
                        "success": False,
                        "message": "Arm command ACKed but drone never reported armed state",
                    }
                
            if drone.get_state()["rel_alt"] < alt - 2:
                drone.takeoff(alt)
                if not _wait_for_condition(
                    lambda: float(drone.get_state()["rel_alt"]) >= min(alt - 2.0, 3.0),
                    timeout=20.0,
                ):
                    return {
                        "drone_id": drone_id,
                        "sysid": sysid,
                        "success": False,
                        "message": "Takeoff ACKed but drone never reached safe goto altitude",
                    }

            # Send the goto command using your new method
            drone.goto(lat, lon, alt)

            return {"drone_id": drone_id, "sysid": sysid, "success": True, "message": "Dispatched via Swarm logic"}
        except Exception as exc:
            logger.error(f"Dispatch failed for sysid {sysid}: {exc}")
            return {"drone_id": drone_id, "sysid": sysid, "success": False, "message": str(exc)}
        finally:
            self._dispatching_sysids.discard(sysid)

    def recall_drone(self, sysid: int, drone_id: Optional[str] = None) -> dict:
        try:
            drone = self._get_drone(sysid)
            if not drone:
                return {"drone_id": drone_id, "sysid": sysid, "success": False, "message": "Not connected"}

            home = drone.home_location.copy()
            if home.get("lat") is None or home.get("lon") is None:
                return {
                    "drone_id": drone_id,
                    "sysid": sysid,
                    "success": False,
                    "message": "Home location not captured",
                }

            state = drone.get_state()
            if not state["armed"]:
                self._recall_states.pop(sysid, None)
                drone.recall_phase = "complete"
                return {"drone_id": drone_id, "sysid": sysid, "success": True, "message": "Drone already disarmed at recall start"}

            if not drone.is_mode("GUIDED"):
                logger.info(f"Sending GUIDED to sysid={sysid}")
                drone.set_mode("GUIDED")
            
            return_alt = max(float(state.get("rel_alt") or 0.0), float(DEFAULT_RECALL_ALT))
            self.send_goto(sysid, home["lat"], home["lon"], return_alt)
            self._recall_states[sysid] = {
                "phase": "returning",
                "drone_id": drone_id,
                "home": home,
                "last_action_at": time.time(),
            }
            drone.recall_phase = "returning"

            return {
                "drone_id": drone_id,
                "sysid": sysid,
                "success": True,
                "message": "Recall initiated: returning to stored home in GUIDED mode",
            }
        
        except Exception as exc:
            logger.error(f"Recall failed for sysid {sysid}: {exc}")
            return {"drone_id": drone_id, "sysid": sysid, "success": False, "message": str(exc)}

    def update_recall_states(self) -> None:
        for sysid, recall in list(self._recall_states.items()):
            drone = self._get_drone(sysid)
            if not drone:
                self._recall_states.pop(sysid, None)
                continue

            state = drone.get_state()
            if not state.get("armed"):
                drone.recall_phase = "complete"
                self._recall_states.pop(sysid, None)
                continue

            home = recall.get("home") or {}
            home_lat = home.get("lat")
            home_lon = home.get("lon")
            if home_lat is None or home_lon is None:
                drone.recall_phase = "error"
                self._recall_states.pop(sysid, None)
                continue

            phase = recall.get("phase")
            if phase == "returning":
                distance_m = drone.distance_to(float(home_lat), float(home_lon))
                if distance_m <= 3.0:
                    if not drone.is_mode("LAND"):
                        logger.info("Recall: sending LAND to sysid=%s at home radius %.2fm", sysid, distance_m)
                        drone.set_mode("LAND")
                    recall["phase"] = "landing"
                    recall["last_action_at"] = time.time()
                    drone.recall_phase = "landing"
                elif time.time() - float(recall.get("last_action_at", 0.0)) >= 10.0:
                    return_alt = max(float(state.get("rel_alt") or 0.0), float(DEFAULT_RECALL_ALT))
                    drone.goto(float(home_lat), float(home_lon), return_alt)
                    recall["last_action_at"] = time.time()
                    drone.recall_phase = "returning"

            elif phase == "landing":
                drone.recall_phase = "landing"
                if float(state.get("rel_alt") or 0.0) <= 0.3:
                    try:
                        logger.info("Recall: sending disarm to sysid=%s after touchdown", sysid)
                        drone.disarm(timeout=3)
                    except Exception as exc:
                        logger.info("Recall: disarm attempt for sysid=%s did not complete yet: %s", sysid, exc)
                    recall["phase"] = "disarming"
                    recall["last_action_at"] = time.time()

            elif phase == "disarming":
                drone.recall_phase = "disarming"
                if not state.get("armed"):
                    drone.recall_phase = "complete"
                    self._recall_states.pop(sysid, None)
                elif float(state.get("rel_alt") or 0.0) <= 0.3 and time.time() - float(recall.get("last_action_at", 0.0)) >= 2.0:
                    try:
                        drone.disarm(timeout=3)
                    except Exception:
                        pass
                    recall["last_action_at"] = time.time()

    def send_goto(self, sysid: int, lat: float, lon: float, alt: float) -> None:
        """Lightweight goto wrapper for the simulation loop."""
        drone = self._get_drone(sysid)
        if drone:
            drone.goto(lat, lon, alt)
            
    '''def rearm_drone(self, sysid: int, takeoff_alt: float) -> None:
        """Helper for simulation.py to recover drones without needing raw MAVLink locks."""
        drone = self._get_drone(sysid)
        if not drone: return
        
        if drone.state["mode"] != "GUIDED":
            drone.set_mode("GUIDED")
        elif not drone.state["armed"]:
            drone.arm()
            self._last_arm_time[sysid] = time.time()
            time.sleep(2)
            drone.takeoff(takeoff_alt) '''

    def send_mode(self, sysid: int, mode: str) -> None:
        drone = self._get_drone(sysid)
        if drone:
            state = drone.get_state()
            print("rel_alt:", state["rel_alt"])
            print("armed:", state["armed"])
            print("mode:", state["mode"])
            
            drone.set_mode(mode)


from app.ws import manager
from app.missions import mission_db # Assuming this is where you track active missions

def wait_for_armed(drone, timeout=10.0):
    start = time.time()
    seen_armed = False

    while time.time() - start < timeout:
        state = drone.get_state()
        if state["armed"]:
            seen_armed = True
            return True
        time.sleep(0.2)

    return seen_armed

def _any_mission_running() -> bool:
    """Helper to check if simulation.py is currently handling telemetry."""
    for mission in mission_db.values():
        if mission.status != "idle":
            return True
    return False

async def idle_sitl_telemetry_loop() -> None:
    """Broadcast idle telemetry to the frontend when no mission is running."""
    while True:
        try:
            await asyncio.sleep(1.0) # Update the UI once per second when idle
            sitl_bridge.ensure_connected()
            
            # Don't waste CPU if no one is looking at the web page
            if not manager.active_connections:
                continue
                
            # If a mission is running, let simulation.py handle the WebSockets
            if _any_mission_running():
                continue
                
            # 1. Grab the latest state from your new Swarm adapter!
            states_dict = sitl_bridge.get_states_by_sysid()
            if not states_dict:
                continue
                
            # 2. Convert the dictionary values into a flat list for the Frontend
            drones_list = list(states_dict.values())
            
            # 3. Push it to the React/Vue frontend
            await manager.broadcast({"type": "telemetry", "drones": drones_list})
            
        except asyncio.CancelledError:
            raise # Expected during shutdown in main.py
        except Exception as e:
            logger.error(f"idle_sitl_telemetry_loop error: {e}")

# Initialize the global instance expected by the rest of the app
sitl_bridge = SITLTelemetryBridge()
