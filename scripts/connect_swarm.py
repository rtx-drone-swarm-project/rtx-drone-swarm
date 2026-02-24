import time
from pymavlink import mavutil


def connect_swarm(count, start_port=5762):
    swarm = []
    for i in range(count):
        port = start_port + i * 10
        print(f"Connecting to drone {i+1} on port {port}")
        conn = mavutil.mavlink_connection(f"tcp:127.0.0.1:{port}")
        conn.wait_heartbeat()
        print(f"  Heartbeat received from system {conn.target_system}")
        swarm.append(conn)
    return swarm


def wait_ack(conn, command, timeout=3):
    """Wait for COMMAND_ACK for a specific command"""
    start = time.time()
    while time.time() - start < timeout:
        msg = conn.recv_match(type='COMMAND_ACK', blocking=False)
        if msg and msg.command == command:
            if msg.result == mavutil.mavlink.MAV_RESULT_ACCEPTED:
                return True
            else:
                return False
        time.sleep(0.05)
    return False


def verify_armed(conn, timeout=3):
    """Check heartbeat to see if drone is armed"""
    start = time.time()
    while time.time() - start < timeout:
        hb = conn.recv_match(type='HEARTBEAT', blocking=False)
        if hb and (hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED):
            return True
        time.sleep(0.05)
    return False


def arm_all(swarm):
    print("Arming all drones...")
    for conn in swarm:
        conn.mav.command_long_send(
            conn.target_system, 1,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0, 1, SAFETY_OVERRIDE, 0, 0, 0, 0, 0
        )

    # Wait for ACK and verify armed
    for conn in swarm:
        if wait_ack(conn, mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM):
            print(f"Drone {conn.target_system} arm command accepted")
        else:
            print(f"Drone {conn.target_system} arm command FAILED")

        if verify_armed(conn):
            print(f"Drone {conn.target_system} is now armed")
        else:
            print(f"Drone {conn.target_system} NOT armed")


def takeoff_all(swarm, altitude=5):
    print(f"Taking off all drones to {altitude} meters...")
    for conn in swarm:
        # Set GUIDED mode first
        conn.mav.set_mode_send(conn.target_system, mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, 4)
        time.sleep(0.3)

        # Send takeoff command
        conn.mav.command_long_send(
            conn.target_system, 1,
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            0, 0, 0, 0, 0, 0, 0, altitude
        )
        if wait_ack(conn, mavutil.mavlink.MAV_CMD_NAV_TAKEOFF):
            print(f"Drone {conn.target_system} takeoff command accepted")
        time.sleep(0.2)


def hover_all(swarm):
    print("Setting all drones to hover (LOITER) mode...")
    for conn in swarm:
        conn.mav.set_mode_send(conn.target_system, mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, 5)
        time.sleep(0.2)
        # Optionally, verify mode change
        print(f"Drone {conn.target_system} set to LOITER mode")


if __name__ == "__main__":
    swarm = connect_swarm(count=15, start_port=5762)
    time.sleep(1)
    print("Commands: arm, takeoff <altitude>, hover, exit")

    while True:
        user_input = input("> ").strip().lower()
        if not user_input:
            continue

        parts = user_input.split()
        cmd = parts[0]
        arg = float(parts[1]) if len(parts) > 1 else 5

        if cmd == "arm":
            arm_all(swarm)
        elif cmd == "takeoff":
            takeoff_all(swarm, altitude=arg)
        elif cmd == "hover":
            hover_all(swarm)
        elif cmd == "exit":
            print("Exiting controller...")
            break
        else:
            print("Unknown command. Available: arm, takeoff <alt>, hover, exit")

        time.sleep(0.5)