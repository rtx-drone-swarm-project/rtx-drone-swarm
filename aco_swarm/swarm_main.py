"""
swarm_main.py
-------------
macOS entry point for the stigmergy swarm.

Architecture
------------
  SITL TCP 5760-5900
      ├── DroneAgents  (source_system 100-114, direct TCP)
      └── MAVProxy     (source_system 255, same TCP ports, map only)

ArduPilot SITL supports multiple simultaneous TCP clients per port.
Agents and MAVProxy connect independently — no port competition.
MAVProxy opens in a new Terminal window via osascript (fixes wxPython crash).

Usage
-----
  # Terminal 1 — SITL
  cd ardupilot/ArduCopter
  python3 ../Tools/autotest/sim_vehicle.py \
    -v ArduCopter --count 15 --no-mavproxy --speedup 1 --auto-sysid

  # Terminal 2 — Swarm (MAVProxy map opens automatically)
  python3 swarm_main.py --drones 15 --no-sitl
"""

import argparse
import concurrent.futures
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from typing import List

from stigmergy_engine import InMemoryPheromoneGrid, GridConfig
from drone_agent import DroneAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

SITL_TCP_BASE  = 5760
SITL_PORT_STEP = 10


def drone_port(i: int) -> int:
    return SITL_TCP_BASE + i * SITL_PORT_STEP


# ────────────────────────────────────────────────────────────────────
#  Port readiness check
# ────────────────────────────────────────────────────────────────────

def wait_for_ports(num_drones: int, timeout: float = 300.0):
    ports = [drone_port(i) for i in range(num_drones)]
    pending = set(ports)
    deadline = time.time() + timeout

    log.info(f"Waiting for {num_drones} SITL ports…")
    while pending and time.time() < deadline:
        for port in list(pending):
            try:
                s = socket.create_connection(("127.0.0.1", port), timeout=1)
                s.close()
                pending.discard(port)
                log.info(f"  :{port} ready")
            except OSError:
                pass
        if pending:
            time.sleep(2)

    if pending:
        raise RuntimeError(
            f"Timed out waiting for ports: {sorted(pending)}\n"
            "Check: lsof -i TCP | grep arducopter"
        )
    log.info("All SITL ports open ✓")


# ────────────────────────────────────────────────────────────────────
#  MAVProxy — opens in a new Terminal window via osascript
#  Connects to same TCP ports as agents — SITL allows multiple clients
#  Uses default source_system=255 (GCS) which doesn't clash with agents
# ────────────────────────────────────────────────────────────────────

def launch_mavproxy(num_drones: int):
    parts = ["mavproxy.py"]
    for i in range(num_drones):
        parts.append(f"--master=tcp:127.0.0.1:{drone_port(i)}")
    parts += ["--map", "--console"]

    mavproxy_cmd = " ".join(parts)
    venv = os.environ.get("VIRTUAL_ENV", "")
    activate = f"source {venv}/bin/activate && " if venv else ""
    full_cmd = f"{activate}{mavproxy_cmd}"

    script = f'tell application "Terminal" to do script "{full_cmd}"'
    log.info("Opening MAVProxy map in a new Terminal window…")
    subprocess.Popen(["osascript", "-e", script])


# ────────────────────────────────────────────────────────────────────
#  Parallel connection
# ────────────────────────────────────────────────────────────────────
def wait_for_heartbeat(port, timeout=180):
    import pymavlink.mavutil as mavutil
    master = mavutil.mavlink_connection(f'tcp:127.0.0.1:{port}', autoreconnect=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            msg = master.recv_match(type='HEARTBEAT', blocking=False)
            if msg:
                master.close()
                return True
        except Exception:
            pass
        time.sleep(0.5)
    master.close()
    raise RuntimeError(f"No heartbeat on port {port}")


def connect_all(drone_list: List[DroneAgent]) -> List[DroneAgent]:
    log.info(f"Connecting {len(drone_list)} drones in batches…")
    agents = []
    for i, agent in enumerate(drone_list):
        try:
            wait_for_heartbeat(drone_port(agent.drone_id))
            agent.connect(timeout=180)  # increase timeout
            agents.append(agent)
            log.info(f"[Drone {agent.drone_id}] connected")
        except Exception as e:
            log.error(f"[Drone {agent.drone_id}] Failed: {e}")
        time.sleep(2)  # small delay between connections
    return agents



# ────────────────────────────────────────────────────────────────────
#  CLI
# ────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Stigmergy swarm — macOS SITL")
    p.add_argument("--drones",    type=int,   default=15)
    p.add_argument("--duration",  type=float, default=0,
                   help="Seconds to run, 0 = forever (default: forever)")
    p.add_argument("--altitude",  type=float, default=10.0)
    p.add_argument("--speedup",   type=int,   default=1)
    p.add_argument("--no-sitl",   action="store_true",
                   help="Skip SITL launch — connect to already-running instances")
    p.add_argument("--no-map",    action="store_true",
                   help="Skip MAVProxy map window")
    p.add_argument("--grid-rows", type=int,   default=40)
    p.add_argument("--grid-cols", type=int,   default=40)
    p.add_argument("--evap-rate", type=float, default=0.97)
    p.add_argument("--loop-hz",   type=float, default=0.5)
    return p.parse_args()


# ────────────────────────────────────────────────────────────────────
#  Main
# ────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()

    home_lat, home_lon = -35.363262, 149.165237
    span = 0.004

    cfg = GridConfig(
        lat_min=home_lat - span, lat_max=home_lat + span,
        lon_min=home_lon - span, lon_max=home_lon + span,
        rows=args.grid_rows, cols=args.grid_cols,
        evaporation_rate=args.evap_rate,
        deposit_strength=1.0,
        tick_interval=1.0,
    )

    grid = InMemoryPheromoneGrid(cfg)
    grid.start_evaporation()
    log.info(f"Pheromone grid {cfg.rows}×{cfg.cols} | evap={cfg.evaporation_rate}")

    # 1. Wait for SITL ports
    wait_for_ports(args.drones, timeout=300.0)

    # 2. Launch MAVProxy FIRST so it connects to all TCP ports before agents
    #    SITL supports multiple TCP clients per port — both can connect
    if not args.no_map:
        launch_mavproxy(args.drones)
        log.info("Waiting 15s for MAVProxy to connect all vehicles…")
        time.sleep(15)
        log.info("MAVProxy ready ✓")

    # 3. Connect agents directly via TCP — unique source_system per agent
    rows = cols = int(args.drones**0.5) + 1
    drone_list = []
    for i in range(args.drones):
        row = i // cols
        col = i % cols
        start_lat = home_lat - span + 2 * span * row / rows
        start_lon = home_lon - span + 2 * span * col / cols

        drone = DroneAgent(
            drone_id=i,
            connection=f"tcp:127.0.0.1:{drone_port(i)}",
            grid=grid,
            altitude=args.altitude,
            loop_hz=args.loop_hz,
        )
        drone.start_lat = start_lat
        drone.start_lon = start_lon
        drone_list.append(drone)

    agents = connect_all(drone_list)
    if not agents:
        log.error("No drones connected — exiting.")
        sys.exit(1)

    # 4. Staggered takeoffs
    log.info("Starting agents…")
    for agent in agents:
        agent.start()
        time.sleep(0.8)

    # 5. Shutdown
    def _cleanup():
        log.info("Shutting down…")
        for a in agents:
            a.stop()
        grid.stop_evaporation()
        log.info("Done.")

    def _signal_handler(sig, frame):
        _cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    if args.duration > 0:
        log.info(f"Running for {args.duration}s — Ctrl+C to stop early")
        time.sleep(args.duration)
        _cleanup()
    else:
        log.info("Running indefinitely — Ctrl+C to stop")
        while True:
            time.sleep(1)


if __name__ == "__main__":
    main()