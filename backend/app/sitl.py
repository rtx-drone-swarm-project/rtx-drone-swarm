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
)

logger = logging.getLogger(__name__)

class SITLTelemetryBridge:
    """Adapter that exposes the new Swarm class to the rest of the FastAPI backend."""

    def __init__(
        self,
        host: str = DEFAULT_SITL_HOST,
        base_port: int = DEFAULT_SITL_BASE_PORT,
        count: int = DEFAULT_SITL_COUNT,
    ):
        self.host = host
        self.base_port = base_port
        self.count = count
        

        self.swarm = Swarm()
        
        # Keep tracking dispatching to prevent simulation.py from interrupting
        self._dispatching_sysids: set = set()
        #self._last_arm_time: Dict[int, float] = {}

    def start(self) -> None:
        """Start the swarm connections and background telemetry thread."""
        # Connect the swarm 
        self.swarm.connect(count=self.count, start_port=self.base_port)
        # Start the background thread
        self.swarm.start_background_telemetry()

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
        states = {}
        for drone in self.swarm.drones:
            d_state = drone.get_state()
            
            # Fetch battery if available
            battery = None
            if drone.last_status and getattr(drone.last_status, 'battery_remaining', -1) != -1:
                battery = drone.last_status.battery_remaining

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
                "heading": None, 
                "battery_remaining": battery,
                "armed": d_state["armed"],
                "mode": d_state["mode"],
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
            if drone.state["mode"] != "GUIDED":
                drone.set_mode("GUIDED")
            
            # Check if it needs to arm and takeoff
            if not drone.state["armed"]:
                drone.arm()
                #self._last_arm_time[sysid] = time.time()
                time.sleep(2) # Give it a second
                
            if drone.state["rel_alt"] < alt - 2:
                drone.takeoff(alt)
                # Wait briefly for takeoff to register before giving a goto
                time.sleep(3)

            # Send the goto command using your new method
            drone.goto(lat, lon, alt)

            return {"drone_id": drone_id, "sysid": sysid, "success": True, "message": "Dispatched via Swarm logic"}
        except Exception as exc:
            logger.error(f"Dispatch failed for sysid {sysid}: {exc}")
            return {"drone_id": drone_id, "sysid": sysid, "success": False, "message": str(exc)}
        finally:
            self._dispatching_sysids.discard(sysid)

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


from app.ws import manager
from app.missions import missions_db # Assuming this is where you track active missions

def _any_mission_running() -> bool:
    """Helper to check if simulation.py is currently handling telemetry."""
    for mission in missions_db.values():
        if mission.get("status") == "running":
            return True
    return False

async def idle_sitl_telemetry_loop() -> None:
    """Broadcast idle telemetry to the frontend when no mission is running."""
    while True:
        try:
            await asyncio.sleep(1.0) # Update the UI once per second when idle
            
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