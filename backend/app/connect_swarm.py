#!/usr/bin/env python3
import time
import threading
from pymavlink import mavutil



ARM_CMD = mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM
TAKEOFF_CMD = mavutil.mavlink.MAV_CMD_NAV_TAKEOFF
ACCEPTED_ACK_RESULTS = {
    mavutil.mavlink.MAV_RESULT_ACCEPTED,
    mavutil.mavlink.MAV_RESULT_IN_PROGRESS,
}

class Drone:
    TELEMETRY_MSGS = {"HEARTBEAT", "VFR_HUD", "GLOBAL_POSITION_INT", "SYS_STATUS", "EKF_STATUS_REPORT"}
    EVENT_MSGS = {"COMMAND_ACK", "STATUSTEXT"}
    
    def __init__(self, conn, sysid, index):
        self.conn = conn
        self.sysid = sysid
        self.index = index
        self.comp = conn.target_component

        self._lock = threading.Lock()

        self.target_alt = None
        self.target_location = {"lat": None, "lon": None, "alt": None}

        self.last_hb = None
        self.last_hud = None
        self.last_gps = None
        self.last_status = None
        self.last_ekf = None
        self.last_ack = None

        self.state = {
            "index": self.index,
            "sysid": self.sysid,
            "timestamp": time.time(),
            "armed": False,
            "mode": "UNKNOWN",
            "throttle": 0,
            "altitude": 0.0,
            "groundspeed": 0.0,
            "lat": 0.0,
            "lon": 0.0,
            "rel_alt": 0.0
        }

    

    def send_command(self, command, params=None, wait_ack=True, timeout=3):
        if params is None:
            params = [0] * 7

        self.conn.mav.command_long_send(self.sysid, self.comp, command, 0, *(params[:7]))
        result = self.wait_ack(command, timeout=timeout)
        if result not in ACCEPTED_ACK_RESULTS:
            raise RuntimeError(f"Drone {self.sysid}: command {command} rejected with ACK result {result}")
        return result


    def goto(self, lat, lon, alt):
        self.target_location = {"lat": lat, "lon": lon, "alt": alt}
        self.target_alt = alt
        self.conn.mav.set_position_target_global_int_send(
            0,       # time_boot_ms (not used)
            self.sysid, self.comp,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT, # Use relative altitude
            0b110111111000, # Type mask: ignore velocity/accel, use only pos
            int(lat * 1e7), # Latitude (int)
            int(lon * 1e7), # Longitude (int)
            alt,            # Altitude
            0, 0, 0,        # Velocity (ignored)
            0, 0, 0,        # Acceleration (ignored)
            0, 0            # Yaw/Yaw rate (ignored)
        )

    def is_reached_location(self, margin=1.5):
        if self.target_location["lat"] is None: return True
        dist = self.get_distance_to_target(self.target_location["lat"], self.target_location["lon"])
        return dist < margin
    
    def is_reached_altitude(self, margin=0.2):
        if self.target_alt is None: return True
        return abs(self.state["rel_alt"] - self.target_alt) < margin

    def set_mode(self, mode_name):
        mode_map = self.conn.mode_mapping()
        if mode_name not in mode_map:
            raise ValueError(f"Mode {mode_name} not supported")

        self.conn.mav.set_mode_send(self.sysid, mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, mode_map[mode_name])

    def arm(self, timeout = 5):
        self.conn.mav.command_long_send(self.sysid, self.comp, ARM_CMD, 0, 1, 0, 0, 0, 0, 0, 0)
        result = self.wait_ack(ARM_CMD, timeout=timeout)
        if result not in ACCEPTED_ACK_RESULTS:
            raise RuntimeError(f"Drone {self.sysid}: arm rejected with ACK result {result}")
        return result

    def takeoff(self, altitude, timeout = 5):
        self.target_alt = altitude
        self.conn.mav.command_long_send(self.sysid, self.comp,TAKEOFF_CMD,0, 0, 0, 0, 0, 0, 0, altitude)
        result = self.wait_ack(TAKEOFF_CMD, timeout=timeout)
        if result not in ACCEPTED_ACK_RESULTS:
            raise RuntimeError(f"Drone {self.sysid}: takeoff rejected with ACK result {result}")
        return result

    def wait_ack(self, command, timeout=5):
        start = time.time()
        self.last_ack = None # Clear old ACKs
        
        while time.time() - start < timeout:
            if self.last_ack and self.last_ack.command == command:
                result = self.last_ack.result
                self.last_ack = None # Consume it
                return result
            time.sleep(0.05)
        
        raise TimeoutError(f"Drone {self.sysid}: No ACK for {command}")

    def request_data_streams(self, rate=10):
        self.conn.mav.request_data_stream_send(self.sysid, self.comp, mavutil.mavlink.MAV_DATA_STREAM_ALL, rate, 1)

    def update(self):
        latest_telemetry = {}
        events = []

        # 1. Drain the OS buffer as fast as physically possible
        while True:
            msg = self.conn.recv_match(blocking=False)
            if msg is None:
                break

            msg_type = msg.get_type()
            
            # Route the message efficiently
            if msg_type in self.TELEMETRY_MSGS:
                latest_telemetry[msg_type] = msg
            elif msg_type in self.EVENT_MSGS:
                events.append(msg)               

        if latest_telemetry or events:
            with self._lock:
                
                # Apply Events
                for event in events:
                    if event.get_type() == "COMMAND_ACK" and event.get_srcSystem() == self.sysid:
                        self.last_ack = event

                # Apply freshest Telemetry
                for msg_type, msg in latest_telemetry.items():
                    if msg_type == "HEARTBEAT":
                        self.last_hb = msg
                        self.state["armed"] = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                        self.state["mode"] = msg.custom_mode if msg else None
                        
                    elif msg_type == "VFR_HUD":
                        self.last_hud = msg
                        self.state["throttle"] = msg.throttle
                        self.state["altitude"] = msg.alt
                        self.state["groundspeed"] = msg.groundspeed
                        
                    elif msg_type == "GLOBAL_POSITION_INT":
                        self.last_gps = msg
                        self.state["lat"] = msg.lat / 1e7
                        self.state["lon"] = msg.lon / 1e7
                        self.state["rel_alt"] = msg.relative_alt / 1000.0
                        
                    elif msg_type == "SYS_STATUS":
                        self.last_status = msg
                        
                    elif msg_type == "EKF_STATUS_REPORT":
                        self.last_ekf = msg

    def is_ekf_gps_ready(self):
        #self.update()
        if not self.last_ekf:
            return False

        flags = self.last_ekf.flags
        
        # 8 = GPS Horizontal Position Absolute
        # 1 = Horizontal Velocity
        # We check if these two are set.
        has_gps_pos = bool(flags & 8)
        has_velocity = bool(flags & 1)
        
        # Your variances are great (0.009 and 0.003), so we check against 0.1
        is_healthy = self.last_ekf.velocity_variance < 0.1 and self.last_ekf.pos_horiz_variance < 0.1
    
        return has_gps_pos and has_velocity and is_healthy
    
    def is_prearm_passed(self):
        """Returns True if the drone has passed all internal ArduPilot pre-arm checks."""
        #self.update()
        
        if self.last_status is None:
            return False

        # The pre-arm bit is the 22nd bit (0x400000)
        # We check if this bit is set in the sensors_health field
        prearm_bit = mavutil.mavlink.MAV_SYS_STATUS_PREARM_CHECK
        
        # If the bit is 1, pre-arm checks are passing
        return bool(self.last_status.onboard_control_sensors_health & prearm_bit)
    
    def get_state(self):
        with self._lock:
            return self.state.copy()
    

class Swarm:
    def __init__(self):
        self.drones = []
        self.is_running = True
        self.telemetry_thread = None

    def __enter__(self):
        self.is_running = True
        self.start_background_telemetry()
        return self

    def __exit__(self, exc_type, exc, tb):
        print("\nShutting down telemetry thread...")
        self.is_running = False

        if self.telemetry_thread is not None:
            self.telemetry_thread.join(timeout=5)

    def start_background_telemetry(self):
        """Spawns the fast background thread to read MAVLink data"""
        print("Starting MAVLink telemetry thread...")
        self.telemetry_thread = threading.Thread(target=self._telemetry_loop)
        self.telemetry_thread.daemon = True
        self.telemetry_thread.start()

    def _telemetry_loop(self):
        """Runs constantly in the background draining the MAVLink buffer"""
        while self.is_running:
            for drone in self.drones:
                drone.update()
            time.sleep(0.005) # Tiny sleep to save CPU

    def get_states(self):
        return [d.get_state() for d in self.drones]

    def connect(self, count, host="127.0.0.1", start_port=5762, port_step=10):
        connected_drones = []
        for i in range(count):
            port = start_port + i * port_step
            print(f"Connecting to {host}:{port}...")
            conn = mavutil.mavlink_connection(f"tcp:{host}:{port}")
            hb = conn.wait_heartbeat(timeout=15)

            drone = Drone(conn=conn, sysid=hb.get_srcSystem(), index=i + 1)
            drone.request_data_streams()

            connected_drones.append(drone)
            print(f"  Drone {i+1} connected (sysid={drone.sysid})")

        self.drones = connected_drones
        print(f"\nConnected {len(self.drones)} drones\n")


    def set_mode_all(self, mode="GUIDED"):
        for d in self.drones:
            d.set_mode(mode)
        print(f"Mode {mode} sent to all drones")

    def arm_all(self):
        for d in self.drones:
            d.arm()

        print("Arm sequence complete")

    def takeoff_all(self, altitude):
        for d in self.drones:
            d.takeoff(altitude)

        print(f"Takeoff to {altitude}m complete")

    def wait_for_all_prearm(self, timeout=60):
        print("Checking swarm health...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Check every drone
            statuses = [d.is_prearm_passed() for d in self.drones]
            ready_count = sum(statuses)
            
            print(f"Drones ready: {ready_count}/{len(self.drones)}", end='\r')
            
            if ready_count == len(self.drones):
                print(f"\nAll {len(self.drones)} drones are READY.")
                return True
                
            time.sleep(1)
            
        raise TimeoutError("Pre-arm checks timed out. Check GPS/EKF status.")
    
    def wait_for_ekf_alignment(self, timeout=120):
        print("Waiting for EKF3 Origin and GPS Fusion...")
        start = time.time()
        while time.time() - start < timeout:
            ready_count = sum([d.is_ekf_gps_ready() for d in self.drones])
            print(f"EKF Ready: {ready_count}/{len(self.drones)}", end='\r')
            
            if ready_count == len(self.drones):
                print(f"\nAll {len(self.drones)} drones: Origin set and GPS active.")
                return True
            time.sleep(1)
        raise TimeoutError("EKF alignment timed out.")


if __name__ == "__main__":

    swarm = Swarm()

    swarm.connect(count=15)
    swarm.start_background_telemetry()

    swarm.wait_for_all_prearm(timeout=120)
    swarm.wait_for_ekf_alignment(timeout=120)

    swarm.set_mode_all("GUIDED")
    time.sleep(3)

    swarm.arm_all()

    swarm.takeoff_all(40)

    time.sleep(30)
    #for state in swarm.get_states():
        #print(state)

    print("\n--- Starting GOTO Test ---")
    test_lat = -35.362000 
    test_lon = 149.164000
    
    # It's better to use a Swarm method to avoid collisions
    # This example sends them to a line formation starting at the test coordinate
    for i, drone in enumerate(swarm.drones):
        # Offset each drone by ~2 meters (0.00002 degrees) so they don't crash
        offset = i * 0.00002
        drone.goto(test_lat, test_lon + offset, 40)
    
    print("Move commands sent. Monitoring movement...")

    try:
        while True:
            states = swarm.get_states()
            for s in states:
                print(f"ID: {s['sysid']} | Mode: {s['mode']} | Armed: {s['armed']} | Alt: {s['rel_alt']:.2f}m | | Lat: {s['lat']:.6f} | Lon: {s['lon']:.6f}")
            print("-" * 30)
            time.sleep(1)
    except KeyboardInterrupt: 
        print("Stopping telemetry...")
        swarm.is_running = False
    

    print("\nSwarm takeoff sequence complete\n")
