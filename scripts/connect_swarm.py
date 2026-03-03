#!/usr/bin/env python3
import time
from pymavlink import mavutil

ARM_CMD = mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM
TAKEOFF_CMD = mavutil.mavlink.MAV_CMD_NAV_TAKEOFF


import time
from pymavlink import mavutil

class Drone:
    def __init__(self, conn, sysid, index):
        self.conn = conn
        self.sysid = sysid
        self.index = index
        self.comp = conn.target_component

        self.last_hb = None
        self.last_hud = None
        self.last_gps = None

        self.last_status = None

    

    def send_command(self, command, params=None, wait_ack=True, timeout=3):
        if params is None:
            params = [0] * 7

        self.conn.mav.command_long_send(self.sysid, self.comp, command, 0, *(params[:7]))
        self.wait_ack(command)


    def goto(self, lat, lon, alt):
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

    def set_mode(self, mode_name):
        mode_map = self.conn.mode_mapping()
        if mode_name not in mode_map:
            raise ValueError(f"Mode {mode_name} not supported")

        self.conn.mav.set_mode_send(self.sysid, mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, mode_map[mode_name])

    def arm(self, timeout = 5):
        self.conn.mav.command_long_send(self.sysid, self.comp, ARM_CMD, 0, 1, 0, 0, 0, 0, 0, 0)
        self.wait_ack(ARM_CMD)

        '''start = time.time()
        while time.time() - start < timeout:
            self.update()
            if self.last_hb and (self.last_hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED):
                print(f"Drone {self.sysid} armed")
                return True
            time.sleep(0.1)
        raise TimeoutError(f"Drone {self.sysid} failed to arm in {timeout}s")'''

    def takeoff(self, altitude, timeout = 5):
        self.conn.mav.command_long_send(self.sysid, self.comp,TAKEOFF_CMD,0, 0, 0, 0, 0, 0, 0, altitude)
        self.wait_ack(TAKEOFF_CMD)

    def wait_ack(self, command, timeout=5):
        start = time.time()
        while time.time() - start < timeout:
            msg = self.conn.recv_match(type="COMMAND_ACK", blocking=False)
            if msg and msg.command == command and msg.get_srcSystem() == self.sysid:
                return msg.result
            print(msg)
            time.sleep(0.05)
        
        raise TimeoutError(f"Drone {self.sysid}: No ACK for {command}")

    def request_data_streams(self, rate=10):
        self.conn.mav.request_data_stream_send(self.sysid, self.comp, mavutil.mavlink.MAV_DATA_STREAM_ALL, rate, 1)

    def update(self):
        while True:
            msg = self.conn.recv_match(blocking=False)
            if msg is None:
                break

            t = msg.get_type()
            if t == "HEARTBEAT":
                self.last_hb = msg
            elif t == "SYS_STATUS":
                self.last_status = msg
            elif t == "VFR_HUD":
                self.last_hud = msg
            elif t == "GLOBAL_POSITION_INT":
                self.last_gps = msg

    def is_prearm_passed(self):
        """Returns True if the drone has passed all internal ArduPilot pre-arm checks."""
        self.update()
        
        if self.last_status is None:
            return False

        # The pre-arm bit is the 22nd bit (0x400000)
        # We check if this bit is set in the sensors_health field
        prearm_bit = mavutil.mavlink.MAV_SYS_STATUS_PREARM_CHECK
        
        # If the bit is 1, pre-arm checks are passing
        return bool(self.last_status.onboard_control_sensors_health & prearm_bit)
    
    def get_state(self):
        self.update()

        hb = self.last_hb
        hud = self.last_hud
        gps = self.last_gps

        if not hb:
            print(hb)

        armed = hb and (hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
        mode = hb.custom_mode if hb else None

        return {
            "index": self.index,
            "sysid": self.sysid,
            "armed": bool(armed) if hb else None,
            "mode": mode,
            "throttle": hud.throttle if hud else None,
            "altitude": hud.alt if hud else None,
            "groundspeed": hud.groundspeed if hud else None,
            "lat": gps.lat / 1e7 if gps else None,
            "lon": gps.lon / 1e7 if gps else None,
            "rel_alt": gps.relative_alt / 1000 if gps else None
        }
    

class Swarm:
    def __init__(self):
        self.drones = []

    def get_states(self):
        return [d.get_state() for d in self.drones]

    def connect(self, count, start_port=5762):
        for i in range(count):
            port = start_port + i * 10
            print(f"Connecting to port {port}...")
            conn = mavutil.mavlink_connection(f"tcp:127.0.0.1:{port}")
            hb = conn.wait_heartbeat()

            drone = Drone(conn=conn, sysid=hb.get_srcSystem(), index=i + 1)
            drone.request_data_streams()

            self.drones.append(drone)
            print(f"  Drone {i+1} connected (sysid={drone.sysid})")

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


if __name__ == "__main__":

    swarm = Swarm()

    swarm.connect(count=15)

    #swarm.wait_for_all_prearm(timeout=120)
    #time.sleep(10)

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
                print(f"ID: {s['sysid']} | Mode: {s['mode']} | Armed: {s['armed']} | Alt: {s['rel_alt']:.2f}m")
            print("-" * 30)
            time.sleep(1)
    except KeyboardInterrupt: print("Stopping telemetry...")

    print("\nSwarm takeoff sequence complete\n")