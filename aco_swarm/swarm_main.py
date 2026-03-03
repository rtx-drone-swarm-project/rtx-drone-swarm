"""
swarm_main.py
-------------
macOS entry point for the stigmergy swarm.

Architecture
------------
  SITL TCP 5760-5900
      ├── DroneAgents  (source_system 100-114, UDP via MAVProxy udpout)
      └── MAVProxy     (source_system 255, same TCP ports, map only)

Start SITL manually before running this script:

  # Terminal 1 — get home positions
  python3 swarm_main.py --print-homes

  # Terminal 2 — SITL (paste --home output from above)
  cd ~/ardupilot/ArduCopter
  python3 ../Tools/autotest/sim_vehicle.py \
    -v ArduCopter --count=15 --no-mavproxy --speedup=1 --auto-sysid \
    '--home=<paste here>'

  # Terminal 3 — Swarm (MAVProxy map opens automatically)
  python3 swarm_main.py --drones 15
"""

import argparse
import concurrent.futures
import logging
import math
import os
import signal
import socket
import subprocess
import sys
import time
from typing import List

from stigmergy_engine import InMemoryPheromoneGrid, GridConfig
from drone_agent import DroneAgent
from visualiser import SwarmVisualiser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────
SITL_TCP_BASE  = 5760
SITL_PORT_STEP = 10
AGENT_UDP_BASE = 14560
MAVPROXY_WAIT  = 40
SPAWN_RADIUS_M = 15.0


# ── Port helpers ─────────────────────────────────────────────────────
def drone_port(i: int) -> int:
    return SITL_TCP_BASE + i * SITL_PORT_STEP

def agent_udp(i: int) -> int:
    return AGENT_UDP_BASE + i


# ── Geo helpers ──────────────────────────────────────────────────────
def metres_to_deg_lat(m: float) -> float:
    return m / 111_111.0

def metres_to_deg_lon(m: float, lat: float) -> float:
    return m / (111_111.0 * math.cos(math.radians(lat)))

def circular_spawn(n: int, home_lat: float, home_lon: float, radius_m: float):
    positions = []
    for i in range(n):
        angle = 2 * math.pi * i / n
        dlat  = metres_to_deg_lat(radius_m * math.sin(angle))
        dlon  = metres_to_deg_lon(radius_m * math.cos(angle), home_lat)
        positions.append((home_lat + dlat, home_lon + dlon))
    return positions


# ── MAVProxy ─────────────────────────────────────────────────────────
def launch_mavproxy(num_drones: int):
    parts = ["mavproxy.py"]
    for i in range(num_drones):
        parts.append(f"--master=tcp:127.0.0.1:{drone_port(i)}")
    for i in range(num_drones):
        parts.append(f"--out=udpout:127.0.0.1:{agent_udp(i)}")
    parts += ["--map", "--console"]
    cmd = " ".join(parts)

    venv     = os.environ.get("VIRTUAL_ENV", "")
    activate = f"source {venv}/bin/activate && " if venv else ""
    full     = activate + cmd
    applescript = 'tell application "Terminal" to do script "' + full + '"'
    subprocess.Popen(["osascript", "-e", applescript])
    log.info(f"MAVProxy launched — waiting {MAVPROXY_WAIT}s…")
    time.sleep(MAVPROXY_WAIT)
    log.info("MAVProxy ready ✓")


# ── Port readiness ───────────────────────────────────────────────────
def wait_for_ports(num_drones: int, timeout: float = 300.0):
    ports    = [drone_port(i) for i in range(num_drones)]
    pending  = set(ports)
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
            "Is SITL running? Check: lsof -i TCP | grep arducopter"
        )
    log.info("All SITL ports open ✓")


# ── Parallel connect ─────────────────────────────────────────────────
def connect_all(drone_list: List[DroneAgent]) -> List[DroneAgent]:
    log.info(f"Connecting {len(drone_list)} drones in parallel…")

    def _connect(agent):
        agent.connect(timeout=60)
        return agent

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(drone_list)) as ex:
        futures = {ex.submit(_connect, a): a for a in drone_list}
        agents  = []
        for fut in concurrent.futures.as_completed(futures):
            try:
                agents.append(fut.result())
            except Exception as e:
                log.error(f"[Drone {futures[fut].drone_id}] Failed: {e}")

    agents.sort(key=lambda a: a.drone_id)
    log.info(f"Connected {len(agents)}/{len(drone_list)} drones")
    return agents


# ── CLI ──────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="Stigmergy swarm — macOS SITL")
    p.add_argument("--drones",       type=int,   default=5)
    p.add_argument("--duration",     type=float, default=0,
                   help="Seconds to run, 0 = forever (default: forever)")
    p.add_argument("--altitude",     type=float, default=10.0)
    p.add_argument("--spawn-radius", type=float, default=SPAWN_RADIUS_M,
                   help="Spawn circle radius in metres")
    p.add_argument("--no-map",       action="store_true",
                   help="Skip MAVProxy launch")
    p.add_argument("--grid-rows",    type=int,   default=40)
    p.add_argument("--grid-cols",    type=int,   default=40)
    p.add_argument("--evap-rate",    type=float, default=0.97)
    p.add_argument("--loop-hz",      type=float, default=0.5)
    p.add_argument("--print-homes",  action="store_true",
                   help="Print --home string for sim_vehicle.py and exit")
    return p.parse_args()


# ── Main ─────────────────────────────────────────────────────────────
def main():
    args = parse_args()

    home_lat, home_lon = -35.363262, 149.165237
    span = 0.004

    positions = circular_spawn(args.drones, home_lat, home_lon, args.spawn_radius)

    # Just print the --home string for SITL and exit
    if args.print_homes:
        homes = "|".join(f"{lat:.7f},{lon:.7f},0,0" for lat, lon in positions)
        print(f"--home='{homes}'")
        return

    log.info(
        f"Spawn circle: r={args.spawn_radius}m, "
        f"arc-gap≈{2 * math.pi * args.spawn_radius / args.drones:.1f}m"
    )

    # Pheromone grid
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

    # 2. Launch MAVProxy (provides udpout to agents)
    if not args.no_map:
        launch_mavproxy(args.drones)
        log.info("Waiting 20s for MAVProxy to stabilise…")
        time.sleep(20)
        log.info("MAVProxy ready ✓")

    # 3. Build agents — UDP via MAVProxy udpout
    drone_list = []
    for i, (lat, lon) in enumerate(positions):
        drone = DroneAgent(
            drone_id=i,
            connection=f"udpin:127.0.0.1:{agent_udp(i)}",
            grid=grid,
            altitude=args.altitude,
            loop_hz=args.loop_hz,
            expected_sysid=i + 1,
        )
        drone.start_lat = lat
        drone.start_lon = lon
        drone_list.append(drone)

    # 4. Connect
    agents = connect_all(drone_list)
    if not agents:
        log.error("No drones connected — exiting.")
        sys.exit(1)

    # 5. Staggered takeoffs
    log.info("Starting agents…")
    for agent in agents:
        agent.start()
        time.sleep(0.8)
    #vis = SwarmVisualiser(grid, agents)
    #vis._run()

    # 6. Shutdown
    def _cleanup():
        log.info("Shutting down…")
        for a in agents:
            a.stop()
        grid.stop_evaporation()
        #vis.stop()
        log.info("Done.")

    def _signal_handler(sig, frame):
        _cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _signal_handler)
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