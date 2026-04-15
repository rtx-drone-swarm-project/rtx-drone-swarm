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

  # Terminal 1 — SITL
  cd ~/Desktop/ICS/180/rtx-drone-swarm/ardupilot/ArduCopter && python3 ../Tools/autotest/sim_vehicle.py -v ArduCopter --count 5 --no-mavproxy --speedup 1 --auto-sysid --custom-location=-35.363262,149.165237,0,0

  # Terminal 2 — Swarm (MAVProxy map opens automatically)
  python3 swarm_main.py --drones 5
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
import threading
import numpy as np
from typing import List

from stigmergy_engine import InMemoryPheromoneGrid, GridConfig
from drone_agent import DroneAgent, haversine_m
from voronoi_aco_hybrid import VoronoiACOPlanner, DroneState
from metrics import MetricsTracker


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
SPAWN_RADIUS_M = 150.0
STATE_FILE     = os.path.join(os.path.dirname(__file__), ".agent_state.npy")
PATH_MAX_LEN   = 200


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
    parts.append("--load-module=mavproxy_voronoi")

    cmd = " ".join(parts)

    module_dir = os.path.dirname(os.path.abspath(__file__))
    venv       = os.environ.get("VIRTUAL_ENV", "")
    activate   = f"source {venv}/bin/activate && " if venv else ""
    pythonpath = f"export PYTHONPATH={module_dir}:$PYTHONPATH && "
    full       = activate + pythonpath + cmd

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


# ── State writer (feeds MAVProxy Voronoi module) ─────────────────────
def _write_state(agents: List[DroneAgent], planner: VoronoiACOPlanner):
    agent_data = []
    for a in agents:
        if a.lat is None:
            continue
        if not hasattr(a, "_path"):
            a._path = []
        a._path.append([a.lat, a.lon])
        if len(a._path) > PATH_MAX_LEN:
            a._path = a._path[-PATH_MAX_LEN:]

        agent_data.append({
            "id":        a.drone_id,
            "lat":       a.lat,
            "lon":       a.lon,
            "territory": a.territory.tolist() if a.territory is not None and len(a.territory) > 0 else [],
            "path":      list(a._path),
        })

    np.save(STATE_FILE, {
        "pheromone": planner.pheromone.get_snapshot(),
        "agents":    agent_data,
    })


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
    p.add_argument("--loop-hz",      type=float, default=5.0)
    p.add_argument("--print-homes",  action="store_true",
                   help="Print --home string for sim_vehicle.py and exit")
    p.add_argument("--home-lat",     type=float, default=-35.363262)
    p.add_argument("--home-lon",     type=float, default=149.165237)
    p.add_argument("--coverage-threshold", type=float, default=0.85,
                   help="Coverage fraction required before Lloyd repartitions (default: 0.85)")
    return p.parse_args()


# ── Lloyd helper ─────────────────────────────────────────────────────
def _lloyd_loop(planner, agents, interval=5, coverage_threshold=0.85):
    bootstrapped = False

    while True:
        time.sleep(interval)

        airborne = [a for a in agents if getattr(a, "airborne", False) and a.lat is not None]
        if len(airborne) < len(agents):
            log.info(f"Lloyd waiting — {len(airborne)}/{len(agents)} drones airborne")
            continue

        states = [
            DroneState(id=a.drone_id, lat=a.lat, lon=a.lon)
            for a in agents
        ]

        state_map = {s.id: s for s in states}
        for agent in agents:
            if agent.drone_id in state_map and agent.territory is not None:
                state_map[agent.drone_id].territory = agent.territory

        if not bootstrapped:
            lats = [a.lat for a in agents if a.lat is not None]
            lons = [a.lon for a in agents if a.lon is not None]
            distinct_lats = len(set(f"{l:.3f}" for l in lats))
            distinct_lons = len(set(f"{l:.3f}" for l in lons))
            if distinct_lats < 2 and distinct_lons < 2:
                log.info("Lloyd waiting — drone positions not yet distinct")
                continue

            log.info("Lloyd bootstrap — assigning initial territories to all drones")
            planner._run_lloyd(states)
            state_map = {s.id: s for s in states}
            for agent in agents:
                if agent.drone_id in state_map:
                    agent.territory = state_map[agent.drone_id].territory
                    ter_size = len(agent.territory) if agent.territory is not None else 0
                    log.info(f"  D{agent.drone_id + 1}: {ter_size} cells assigned")
            bootstrapped = True
            continue

        coverages = {
            s.id: planner._territory_coverage(s)
            for s in states
            if s.territory is not None and len(s.territory) > 0
        }

        if not coverages:
            continue

        all_covered = all(c >= coverage_threshold for c in coverages.values())

        if not all_covered:
            log.info(
                "Lloyd skipped — coverage: "
                + " ".join(f"D{k+1}:{v:.0%}" for k, v in sorted(coverages.items()))
            )
            continue

        log.info("All territories covered — running Lloyd repartition")
        planner._run_lloyd(states)
        state_map = {s.id: s for s in states}
        for agent in agents:
            if agent.drone_id in state_map:
                agent.territory = state_map[agent.drone_id].territory


# ── Main ─────────────────────────────────────────────────────────────
def main():
    args = parse_args()

    home_lat, home_lon = args.home_lat, args.home_lon
    span = 0.004

    positions = circular_spawn(args.drones, home_lat, home_lon, args.spawn_radius)

    if args.print_homes:
        homes = "|".join(f"{lat:.7f},{lon:.7f},0,0" for lat, lon in positions)
        print(f"--home='{homes}'")
        return

    log.info(
        f"Spawn circle: r={args.spawn_radius}m, "
        f"arc-gap≈{2 * math.pi * args.spawn_radius / args.drones:.1f}m"
    )

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

    bounds = {
        "min_lat": cfg.lat_min, "max_lat": cfg.lat_max,
        "min_lon": cfg.lon_min, "max_lon": cfg.lon_max,
    }
    planner = VoronoiACOPlanner(
        bounds=bounds,
        grid_config=cfg,
        pheromone_grid=grid,
        n_grid=30,
        lloyd_interval=10,
        aco_radius=2,
        alpha=0.3,
    )

    log.info(f"Pheromone grid {cfg.rows}×{cfg.cols} | evap={cfg.evaporation_rate}")

    wait_for_ports(args.drones, timeout=300.0)

    if not args.no_map:
        launch_mavproxy(args.drones)
        log.info("Waiting 20s for MAVProxy to stabilise…")
        time.sleep(20)
        log.info("MAVProxy ready ✓")

    drone_list = []
    for i, (lat, lon) in enumerate(positions):
        drone = DroneAgent(
            drone_id=i,
            connection=f"udpin:127.0.0.1:{agent_udp(i)}",
            grid=grid,
            planner=planner,
            altitude=args.altitude,
            loop_hz=args.loop_hz,
            expected_sysid=i + 1,
        )
        drone.start_lat = lat
        drone.start_lon = lon
        drone_list.append(drone)

    agents = connect_all(drone_list)
    if not agents:
        log.error("No drones connected — exiting.")
        sys.exit(1)

    time.sleep(3)
    for agent in agents:
        agent._update_position()
        log.info(f"[Drone {agent.drone_id + 1}] SITL position: ({agent.lat}, {agent.lon})")

    threading.Thread(
        target=_lloyd_loop,
        args=(planner, agents),
        kwargs={"coverage_threshold": args.coverage_threshold},
        daemon=True,
    ).start()
    log.info("Lloyd re-partition thread started ✓")

    log.info("Starting agents…")
    for agent in agents:
        agent.start()
        time.sleep(0.8)

    log.info("Waiting for all drones to reach altitude...")
    while not all(getattr(a, "airborne", False) for a in agents):
        time.sleep(1)
    log.info("All drones airborne — dispatching to spawn positions in parallel...")

    # Send all drones to spawn positions simultaneously in background threads
    def _fly_to_spawn(agent, lat, lon, alt):
        log.info(f"[Drone {agent.drone_id + 1}] → spawn ({lat:.5f},{lon:.5f})")
        agent._send_until_reached(lat, lon, alt, timeout=90)

    for agent, (lat, lon) in zip(agents, positions):
        threading.Thread(
            target=_fly_to_spawn,
            args=(agent, lat, lon, args.altitude),
            daemon=True,
        ).start()

    # Wait until positions are distinct or timeout
    log.info("Waiting for drones to spread to spawn positions...")
    deadline = time.time() + 90
    while time.time() < deadline:
        pos_data = [(a.drone_id, a.lat, a.lon) for a in agents if a.lat is not None]
        unique_lats = len(set(f"{lat:.3f}" for _, lat, _ in pos_data))
        unique_lons = len(set(f"{lon:.3f}" for _, _, lon in pos_data))
        log.info("  " + " ".join(f"D{d+1}=({la:.5f},{lo:.5f})" for d, la, lo in pos_data))
        log.info(f"  Distinct lat={unique_lats} lon={unique_lons} (need >=2 in either)")
        if unique_lats >= 2 or unique_lons >= 2:
            log.info("Drone positions distinct — Lloyd can bootstrap ✓")
            break
        time.sleep(5)
    else:
        log.warning("Drones didn't spread in 90s — Lloyd will bootstrap with current positions anyway")

    def _cleanup():
        log.info("Shutting down…")
        for a in agents:
            a.stop()
        grid.stop_evaporation()
        log.info("Done.")

    def _signal_handler(sig, frame):
        _cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    def _main_loop():
        metrics = MetricsTracker(planner, agents)

        log.info("Waiting for territory assignment...")
        while True:
            all_assigned = all(
                a.territory is not None and len(a.territory) > 0
                for a in agents
            )
            if all_assigned:
                log.info("All territories assigned — metrics starting")
                break
            time.sleep(1)

        while True:
            time.sleep(2)
            _write_state(agents, planner)
            metrics.report()

            for agent in agents:
                if agent.lat is None or agent.territory is None or len(agent.territory) == 0:
                    continue
                pos     = np.array([agent.lat, agent.lon])
                dists   = np.linalg.norm(agent.territory - pos, axis=1)
                nearest = dists.min()
                if nearest >= 0.002:
                    nearest_idx = np.argmin(dists)
                    recover_lat = float(agent.territory[nearest_idx, 0])
                    recover_lon = float(agent.territory[nearest_idx, 1])
                    log.warning(f"[Drone {agent.drone_id + 1}] DRIFT CORRECTION "
                                f"→ ({recover_lat:.5f},{recover_lon:.5f})")
                    agent._goto(recover_lat, recover_lon, agent.altitude)

    if args.duration > 0:
        log.info(f"Running for {args.duration}s — Ctrl+C to stop early")
        deadline = time.time() + args.duration
        while time.time() < deadline:
            _write_state(agents, planner)
            time.sleep(2)
        _cleanup()
    else:
        log.info("Running indefinitely — Ctrl+C to stop")
        _main_loop()


if __name__ == "__main__":
    main()