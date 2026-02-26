#!/usr/bin/env python3
import sys, os
# Ensure project root is on path regardless of where script is called from
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import subprocess, time, math, threading
from pymavlink import mavutil
from sar_aco import aco_partition

NUM_DRONES = 15
BASE_PORT  = 14550
PORT_STEP  = 10
VIZ_OFFSET = 5   # visualizer listens on BASE_PORT + i*PORT_STEP + VIZ_OFFSET
SITL_PATH  = os.environ.get("ARDUPILOT_PATH", os.path.expanduser("~/ardupilot"))
ORIGIN_LAT, ORIGIN_LON = 33.6405, -117.8443


# ---------------------------------------------------------------------------
# MAVLink mission upload (correct request/response handshake)
# ---------------------------------------------------------------------------
def send_waypoints(drone_id, waypoints, master):
    """
    Upload a list of (lat, lon) waypoints to an already-connected master.
    Follows the MAVLink mission upload protocol:
      GCS sends MISSION_COUNT → drone requests each item → GCS sends item → drone ACKs

    Fixes applied:
      - Set GUIDED mode first so drone accepts mission protocol
      - Clear existing mission before upload
      - Retry up to 3 times on timeout
      - 10s timeout per item (bumped from 5s)
    """
    n = len(waypoints)
    if n == 0:
        print(f"  Drone {drone_id}: no waypoints to send")
        return False

    print(f"  Drone {drone_id}: uploading {n} waypoints...")

    # Must be in GUIDED mode before drone will respond to mission protocol
    master.set_mode('GUIDED')
    time.sleep(0.5)

    # Clear any existing mission so drone doesn't reject the upload
    master.mav.mission_clear_all_send(master.target_system, master.target_component)
    time.sleep(0.3)

    for attempt in range(3):
        # Step 1: announce how many items are coming
        master.mav.mission_count_send(master.target_system, master.target_component, n)

        success = True
        for _ in range(n):
            # Step 2: wait for drone to request each item
            msg = master.recv_match(
                type=["MISSION_REQUEST", "MISSION_REQUEST_INT"],
                blocking=True, timeout=10   # 10s — SITL under load can be slow
            )
            if not msg:
                print(f"  Drone {drone_id}: timeout on attempt {attempt+1}, retrying...")
                success = False
                break

            seq = msg.seq
            lat, lon = waypoints[seq]
            master.mav.mission_item_int_send(
                master.target_system,
                master.target_component,
                seq,
                mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
                0,          # current (0 = not current)
                1,          # autocontinue
                0, 0, 0, 0, # param1-4 (hold time, accept radius, pass radius, yaw)
                int(lat * 1e7),
                int(lon * 1e7),
                10          # altitude in meters
            )

        if not success:
            continue

        # Step 3: wait for MISSION_ACK
        ack = master.recv_match(type="MISSION_ACK", blocking=True, timeout=10)
        if ack and ack.type == 0:
            print(f"  Drone {drone_id}: mission upload OK")
            return True
        print(f"  Drone {drone_id}: bad ACK ({ack}), retrying...")

    print(f"  Drone {drone_id}: mission upload FAILED after 3 attempts")
    return False


# ---------------------------------------------------------------------------
# Wait until SITL drone is fully booted (EKF ready, sysid non-zero)
# ---------------------------------------------------------------------------
def wait_for_ready(drone_id, master, timeout_s=60):
    """
    Block until the drone has a valid sysid and EKF is healthy.
    sysid=0 means SITL is still initializing — we must not send
    missions until this resolves or the drone ignores everything.
    """
    print(f"  Drone {drone_id+1}: waiting for EKF/GPS ready...")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        hb = master.recv_match(type="HEARTBEAT", blocking=True, timeout=2)
        if hb and hb.get_srcSystem() != 0:
            # Also wait for SYS_STATUS to confirm EKF
            status = master.recv_match(type="SYS_STATUS", blocking=True, timeout=3)
            if status:
                print(f"  Drone {drone_id+1}: ready (sysid={hb.get_srcSystem()})")
                # Re-target master to correct sysid now that we know it
                master.target_system = hb.get_srcSystem()
                return True
        time.sleep(0.5)
    print(f"  Drone {drone_id+1}: WARNING — timed out waiting for ready state")
    return False


# ---------------------------------------------------------------------------
# Arm drone and switch to AUTO after mission upload
# ---------------------------------------------------------------------------
def arm_and_send(drone_id, master, waypoints):
    try:
        # 0. Wait for SITL to fully initialize before touching mission protocol
        if not wait_for_ready(drone_id, master):
            print(f"  Drone {drone_id+1}: skipping — never became ready")
            return

        # 1. Upload waypoints (requires GUIDED mode + initialized drone)
        if not send_waypoints(drone_id + 1, waypoints, master):
            return
        time.sleep(1)

        # 2. Arm
        master.arducopter_arm()
        timeout = time.time() + 30
        while not master.motors_armed():
            if time.time() > timeout:
                print(f"  Warning: Drone {drone_id+1} arm timeout")
                return
            time.sleep(0.5)
        print(f"  Drone {drone_id+1} armed.")

        # 3. Switch to AUTO (only valid after arm + mission upload)
        master.set_mode_auto()
        print(f"  Drone {drone_id+1} set to AUTO.")

    except Exception as e:
        print(f"  Error on drone {drone_id+1}: {e}")


# ---------------------------------------------------------------------------
# Grid -> GPS conversion
# ---------------------------------------------------------------------------
def grid_to_gps(grid, origin_lat, origin_lon, cell_size_km=0.5):
    drone_waypoints = {}
    for row in grid:
        for cell in row:
            drone_waypoints.setdefault(cell.drone, [])
            lat = origin_lat + (cell.r * cell_size_km) / 110.574
            lon = origin_lon + (cell.c * cell_size_km) / (111.320 * math.cos(math.radians(origin_lat)))
            drone_waypoints[cell.drone].append((lat, lon))
    return drone_waypoints


# ---------------------------------------------------------------------------
# Spread drone home positions in a circle around origin
# ---------------------------------------------------------------------------
def home_position(i, num_drones, origin_lat, origin_lon, radius_m=5):
    """Place drone i on a circle of radius_m metres around origin."""
    import math
    angle = 2 * math.pi * i / num_drones
    lat = origin_lat + (radius_m / 110574) * math.cos(angle)
    lon = origin_lon + (radius_m / 111320) * math.sin(angle)
    heading = int(math.degrees(angle)) % 360
    return f"{lat:.7f},{lon:.7f},0,{heading}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":

    # --- Start SITL instances ---
    print(f"Starting {NUM_DRONES} SITL drones...")
    sitl_procs = []

    for i in range(NUM_DRONES):
        port = BASE_PORT + i * PORT_STEP
        cmd = [
            os.path.join(SITL_PATH, "Tools/autotest/sim_vehicle.py"),
            "-v", "ArduCopter",
            "-f", "quad",
            "--sysid",    str(i + 1),
            "--instance", str(i),           # prevents internal port collisions
            "--home",     home_position(i, NUM_DRONES, ORIGIN_LAT, ORIGIN_LON),
            "--out",      f"127.0.0.1:{port}",
            "--out",      f"127.0.0.1:{port + VIZ_OFFSET}",  # visualizer stream
            "--map"
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        sitl_procs.append(proc)
        print(f"  Drone {i+1} started on port {port}")
        time.sleep(2.5)  # stagger startup — SITL needs time to bind its own ports

    # --- Bind all ports first, then wait for heartbeats ---
    # Must separate these two steps: doing connect+wait in one loop causes
    # "Address already in use" because wait_heartbeat() blocks while the
    # remaining ports haven't been bound yet.
    print("\nBinding ports...")
    masters = []
    for i in range(NUM_DRONES):
        port = BASE_PORT + i * PORT_STEP
        conn_str = f"udpin:0.0.0.0:{port}"
        master = mavutil.mavlink_connection(conn_str)
        masters.append(master)
        print(f"  Port {port} bound")

    print("\nWaiting for heartbeats...")
    for i, master in enumerate(masters):
        # Keep waiting until sysid is non-zero — sysid=0 means SITL still booting
        while True:
            master.wait_heartbeat(timeout=30)
            if master.target_system != 0:
                break
            time.sleep(0.5)
        print(f"  Drone {i+1} heartbeat received (sysid={master.target_system})")

    print("All drones initialized.\n")

    # --- Run ACO partition ---
    print("Running ACO partition...")
    grid, bases, history = aco_partition(NUM_DRONES, seed=42)
    print("ACO partition complete.\n")

    drone_waypoints = grid_to_gps(grid, ORIGIN_LAT, ORIGIN_LON)

    # --- Arm & upload waypoints concurrently (staggered to avoid packet flood) ---
    threads = []
    for drone_id, master in enumerate(masters):
        waypoints = drone_waypoints.get(drone_id, [])
        if not waypoints:
            print(f"  Warning: no waypoints for drone {drone_id+1}, skipping")
            continue
        t = threading.Thread(target=arm_and_send, args=(drone_id, master, waypoints))
        t.start()
        threads.append(t)
        time.sleep(1.5)  # stagger so drones don't all upload simultaneously

    for t in threads:
        t.join()

    print("\nAll waypoints sent. Drones should start flying their sections!")

    # --- Keep script alive until Ctrl+C ---
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down SITL drones...")
        for p in sitl_procs:
            p.terminate()