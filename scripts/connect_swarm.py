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

    def set_mode(self, mode_name):
        mode_map = self.conn.mode_mapping()
        if mode_name not in mode_map:
            raise ValueError(f"Mode {mode_name} not supported")

        self.conn.mav.set_mode_send(
            self.sysid,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            mode_map[mode_name]
        )

    def arm(self):
        self.conn.mav.command_long_send(self.sysid, self.comp, ARM_CMD, 0, 1, 0, 0, 0, 0, 0, 0)

    def takeoff(self, altitude):
        self.conn.mav.command_long_send(self.sysid, self.comp,TAKEOFF_CMD,0, 0, 0, 0, 0, 0, 0, altitude)

    def wait_ack(self, command, timeout=3):
        start = time.time()
        while time.time() - start < timeout:
            msg = self.conn.recv_match(
                type="COMMAND_ACK",
                blocking=True,
                timeout=timeout
            )
            if msg and msg.command == command:
                return msg.result == mavutil.mavlink.MAV_RESULT_ACCEPTED
        return False


class Swarm:
    def __init__(self):
        self.drones = []

    def connect(self, count, start_port=5762):
        for i in range(count):
            port = start_port + i * 10
            print(f"Connecting to port {port}...")
            conn = mavutil.mavlink_connection(f"tcp:127.0.0.1:{port}")
            hb = conn.wait_heartbeat()

            drone = Drone(
                conn=conn,
                sysid=hb.get_srcSystem(),
                index=i
            )

            self.drones.append(drone)
            print(f"  Drone {i} connected (sysid={drone.sysid})")

        print(f"\nConnected {len(self.drones)} drones\n")


    def set_mode_all(self, mode="GUIDED"):
        for d in self.drones:
            d.set_mode(mode)
        print(f"Mode {mode} sent to all drones")

    def arm_all(self):
        for d in self.drones:
            d.arm()

        for d in self.drones:
            if not d.wait_ack(ARM_CMD):
                print(f"WARNING: Drone {d.index} failed to arm")

        print("Arm sequence complete")

    def takeoff_all(self, altitude):
        for d in self.drones:
            d.takeoff(altitude)

        for d in self.drones:
            if not d.wait_ack(TAKEOFF_CMD):
                print(f"WARNING: Drone {d.index} failed to takeoff")

        print(f"Takeoff to {altitude}m complete")


if __name__ == "__main__":

    swarm = Swarm()

    swarm.connect(count=15)

    swarm.set_mode_all("GUIDED")
    time.sleep(2)

    swarm.arm_all()
    time.sleep(3)

    swarm.takeoff_all(40)

    print("\nSwarm takeoff sequence complete\n")