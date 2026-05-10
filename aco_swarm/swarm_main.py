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
  cd ~/Desktop/ICS/180/rtx-drone-swarm/ardupilot/ArduCopter && python3 ../Tools/autotest/sim_vehicle.py \
    -v ArduCopter --count 5 --no-mavproxy --speedup 1 --auto-sysid \
    --custom-location=-35.363262,149.165237,0,0

  # Terminal 2 — Swarm (MAVProxy map opens automatically)
  python3 swarm_main.py --drones 5

  # With search targets:
  python3 swarm_main.py --drones 5 \
    --targets="-35.364:149.166,-35.361:149.168" \
    --detection-radius 30 --validation-window 60

Phase flow
----------
  1. All drones initialize, arm, and take off
  2. All drones fly in parallel to circular spawn positions
  3. Lloyd bootstrap runs once (using spawn positions as centroids)
  4. Territories are assigned; planner transitions → ACO
  5. ACO navigation loop begins per drone
  6. While covering, each drone checks for target proximity each tick
  7. On detection: TargetManager → PENDING; ValidationProtocol dispatches
     nearest other drone to corroborate within validation_window seconds
  8. On confirmation: pheromone spike deposited; both drones resume ACO
  9. Lloyd repartitions adaptively when ALL drones exceed coverage_threshold
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
from pymavlink import mavutil
from voronoi_aco_hybrid import VoronoiACOPlanner, DroneState, PlannerPhase
from metrics import MetricsTracker
from target_manager import TargetManager
from validation_protocol import ValidationProtocol


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
MIN_TERRITORY_FRACTION = 0.10   # each drone must hold ≥10% of grid cells


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
    state_file = os.path.join(module_dir, ".agent_state.npy")
    venv       = os.environ.get("VIRTUAL_ENV", "")
    activate   = f"source {venv}/bin/activate && " if venv else ""
    pythonpath = f"export PYTHONPATH={module_dir}:$PYTHONPATH && "
    state_env  = f"export SWARM_STATE_FILE={state_file} && "
    full       = activate + pythonpath + state_env + cmd

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
def _write_state(
    agents: List[DroneAgent],
    planner: VoronoiACOPlanner,
    target_manager: TargetManager = None,
):
    agent_data = []
    for a in agents:
        if a.lat is None:
            continue
        if not hasattr(a, "_path"):
            a._path = []

        a._path.append([a.lat, a.lon])
        if len(a._path) > PATH_MAX_LEN:
            del a._path[:-PATH_MAX_LEN]

        agent_data.append({
            "id":                  a.drone_id,
            "lat":                 a.lat,
            "lon":                 a.lon,
            "territory":           a.territory.tolist() if a.territory is not None and len(a.territory) > 0 else [],
            "path":                list(a._path),
            "on_validation":       a._validation_target is not None,
        })

    # Build confirmed-targets list for MAVProxy overlay (future use)
    confirmed = []
    if target_manager is not None:
        for t in target_manager.get_confirmed_targets():
            confirmed.append({"id": t.target_id, "lat": t.lat, "lon": t.lon})
    
    # Build pending-targets list for MAVProxy overlay
    pending = []
    if target_manager is not None:
        for t in target_manager.get_pending_targets():
            pending.append({
                "id": t.target_id, "lat": t.lat, "lon": t.lon,
                "detected_by": t.detected_by
            })
    # Also expose ALL targets (including undetected) so map can show them
    all_targets = []
    if target_manager is not None:
        for t in target_manager._targets.values():
            all_targets.append({
                "id": t.target_id, "lat": t.lat, "lon": t.lon,
                "state": t.state.name
            })

    # np.save always appends .npy, so name the tmp WITHOUT .npy extension.
    
    try:
        tmp_base = STATE_FILE[:-4] + ".tmp"
        tmp_file = tmp_base + ".npy"
        np.save(tmp_base, {
            "pheromone":         planner.pheromone.get_snapshot(),
            "agents":            agent_data,
            "confirmed_targets": confirmed,
            "pending_targets":   pending,
            "all_targets":       all_targets,
        })
        # np.save is synchronous but rename needs the file to exist
        if os.path.exists(tmp_file):
            os.replace(tmp_file, STATE_FILE)
        else:
            log.warning("[state-writer] tmp file missing — skipping replace")
    except Exception as e:
        log.warning(f"[state-writer] write failed: {e}")


def _state_writer_loop(
    agents: List[DroneAgent],
    planner: VoronoiACOPlanner,
    target_manager: TargetManager = None,
):
    while True:
        try:
            _write_state(agents, planner, target_manager)
        except Exception as e:
            log.warning(f"[state-writer] write failed (skipping): {e}")
        time.sleep(1)


# ── Spawn helpers ─────────────────────────────────────────────────────
def _fly_to_spawn(agent: DroneAgent, lat: float, lon: float, alt: float):
    log.info(f"[Drone {agent.drone_id + 1}] → spawn ({lat:.5f},{lon:.5f})")
    agent._send_until_reached(lat, lon, alt)


# ── Territory balance check ───────────────────────────────────────────
def _check_territory_balance(agents: List[DroneAgent]) -> bool:
    """Return True if every drone holds at least MIN_TERRITORY_FRACTION of total cells."""
    sizes = np.array([
        len(a.territory) if a.territory is not None else 0
        for a in agents
    ])
    total = sizes.sum()
    if total == 0:
        return False
    fractions = sizes / total
    return fractions.min() >= MIN_TERRITORY_FRACTION


def _build_drone_states(agents: List[DroneAgent]) -> List[DroneState]:
    """Build DroneState list from agents, preserving existing territories."""
    states = []
    for a in agents:
        s = DroneState(id=a.drone_id, lat=a.lat, lon=a.lon)
        if a.territory is not None:
            s.territory = a.territory
        states.append(s)
    return states


def _push_territories(agents: List[DroneAgent], states: List[DroneState]):
    """Write partitioned territories back into agents."""
    for s in states:
        if s.territory is not None and len(s.territory) > 0:
            agents[s.id].territory = s.territory

def _seed_edge_pheromone(agents, planner, boost=0.1):
    """
    Deposit a tiny amount of pheromone at territory CENTROIDS so that
    the edge-bias formula in _select_least_visited() immediately pulls
    drones outward on the first tick (centroid has pheromone > 0,
    edges have 0, so edges win the score comparison).
    """
    for agent in agents:
        if agent.territory is None or len(agent.territory) == 0:
            continue
        centroid = agent.territory.mean(axis=0)
        # Deposit at centroid so it's "already visited" — forces outward pull
        planner.pheromone.deposit(float(centroid[0]), float(centroid[1]))
        planner.pheromone.deposit(float(centroid[0]), float(centroid[1]))

# ── Lloyd bootstrap + adaptive repartition loop ───────────────────────
def _lloyd_loop(
    planner: VoronoiACOPlanner,
    agents: List[DroneAgent],
    spawn_ready: threading.Event,
    coverage_threshold: float = 0.85,
):
    """
    Phase-aware Lloyd loop.

    Flow:
      1. Wait for spawn_ready Event (set by main after all drones reach
         their circular spawn positions — guarantees well-separated centroids).
      2. Run Lloyd bootstrap once using actual spawn positions as centroids.
      3. Push territories into agents.
      4. Transition planner → ACO so drone navigation begins.
      5. Periodically check per-drone coverage; repartition when ALL
         drones exceed coverage_threshold (indicating their zone is
         saturated and rebalancing would improve global coverage).
    """
    bootstrapped = False

    while True:
        time.sleep(1)

        # ── Gate 1: all drones airborne with valid GPS ────────────────
        airborne = [
            a for a in agents
            if getattr(a, "airborne", False) and a.lat is not None
        ]
        if len(airborne) < len(agents):
            log.debug(f"[Lloyd] Waiting for airborne drones ({len(airborne)}/{len(agents)})")
            continue

        # ── Gate 2: wait until drones are at spawn positions ──────────
        if not spawn_ready.is_set():
            log.debug("[Lloyd] Waiting for spawn_ready signal…")
            continue

        # ── BOOTSTRAP (runs exactly once) ─────────────────────────────
        if not bootstrapped:
            log.info("[Lloyd] Running bootstrap partition…")
            states = _build_drone_states(agents)
            planner._run_lloyd(states)
            _push_territories(agents, states)
            #_seed_edge_pheromone(agents, planner) 

            if not _check_territory_balance(agents):
                log.warning("[Lloyd] Bootstrap produced imbalanced territories — "
                            "consider increasing --spawn-radius")

            planner.lloyd_active = False
            planner.transition_to_aco()
            bootstrapped = True

            log.info("[Lloyd] Bootstrap complete — ACO navigation unlocked ✓")
            continue

        # ── ADAPTIVE REPARTITION ──────────────────────────────────────
        coverages = [
            planner._territory_coverage(
                DroneState(id=a.drone_id, lat=a.lat, lon=a.lon,
                           territory=a.territory)
            )
            for a in agents
            if a.territory is not None and len(a.territory) > 0
        ]

        if len(coverages) < len(agents):
            time.sleep(2)
            continue

        all_saturated = all(c >= coverage_threshold for c in coverages)
        if not all_saturated:
            time.sleep(2)
            continue

        log.info(
            f"[Lloyd] All drones ≥{coverage_threshold:.0%} coverage "
            f"({[f'{c:.0%}' for c in coverages]}) — repartitioning…"
        )

        planner.lloyd_active = True
        try:
            states = _build_drone_states(agents)
            planner._run_lloyd(states)
            _push_territories(agents, states)

            if not _check_territory_balance(agents):
                log.warning("[Lloyd] Repartition imbalance — territories may be uneven")
        finally:
            planner.lloyd_active = False

        log.info("[Lloyd] Repartition complete ✓")

        planner.pheromone.reset()
        log.info("[Lloyd] Pheromone grid reset for fresh ACO pass ✓")

        time.sleep(10)


# ── CLI ──────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="Stigmergy swarm — macOS SITL")
    p.add_argument("--drones",             type=int,   default=5)
    p.add_argument("--duration",           type=float, default=0,
                   help="Seconds to run, 0 = forever (default: forever)")
    p.add_argument("--altitude",           type=float, default=10.0)
    p.add_argument("--spawn-radius",       type=float, default=SPAWN_RADIUS_M,
                   help="Spawn circle radius in metres")
    p.add_argument("--no-map",             action="store_true",
                   help="Skip MAVProxy launch")
    p.add_argument("--grid-rows",          type=int,   default=40)
    p.add_argument("--grid-cols",          type=int,   default=40)
    p.add_argument("--evap-rate",          type=float, default=0.97)
    p.add_argument("--loop-hz",            type=float, default=5.0)
    p.add_argument("--print-homes",        action="store_true",
                   help="Print --home string for sim_vehicle.py and exit")
    p.add_argument("--home-lat",           type=float, default=-35.363262)
    p.add_argument("--home-lon",           type=float, default=149.165237)
    p.add_argument("--coverage-threshold", type=float, default=0.85,
                   help="Per-drone coverage fraction that triggers Lloyd repartition "
                        "(default: 0.85)")
    # ── Search arguments ──────────────────────────────────────────────
    p.add_argument(
        "--targets",
        type=str,
        default="",
        help=(
            "Comma-separated target positions as lat:lon pairs. "
            "Example: --targets=-35.364:149.165,-35.361:149.168"
        ),
    )
    p.add_argument(
        "--detection-radius",
        type=float,
        default=30.0,
        help="Metres within which a drone detects a target (default: 30)",
    )
    p.add_argument(
        "--validation-window",
        type=float,
        default=60.0,
        help="Seconds a PENDING sighting stays open for corroboration (default: 60)",
    )
    p.add_argument(
        "--pheromone-boost",
        type=float,
        default=50.0,
        help="Pheromone deposits at a confirmed target site (default: 50, deters re-visits)",
    )
    return p.parse_args()


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

    # Delete stale state file so MAVProxy doesn't show previous run's data
    for _stale in (STATE_FILE, STATE_FILE[:-4] + ".tmp.npy"):
        try:
            os.remove(_stale)
            log.info(f"Removed stale state file: {_stale}")
        except FileNotFoundError:
            pass

    # ── Pheromone grid ────────────────────────────────────────────────
    cfg = GridConfig(
        lat_min=home_lat - span, lat_max=home_lat + span,
        lon_min=home_lon - span, lon_max=home_lon + span,
        rows=args.grid_rows, cols=args.grid_cols,
        evaporation_rate=0.97,
        deposit_strength=0.1,
        tick_interval=1.0,
    )
    grid = InMemoryPheromoneGrid(cfg)
    grid.start_evaporation()

    bounds = {
        "min_lat": cfg.lat_min, "max_lat": cfg.lat_max,
        "min_lon": cfg.lon_min, "max_lon": cfg.lon_max,
    }

    # ── Planner ───────────────────────────────────────────────────────
    planner = VoronoiACOPlanner(
        bounds=bounds,
        grid_config=cfg,
        pheromone_grid=grid,
        n_grid=30,
        lloyd_interval=10,
        aco_radius=2,
        alpha=0.3,
    )
    planner.phase = PlannerPhase.LLOYD
    planner.lloyd_active = True

    log.info(f"Pheromone grid {cfg.rows}×{cfg.cols} | evap={cfg.evaporation_rate}")

    # ── Target manager ────────────────────────────────────────────────
    target_positions = []
    if args.targets.strip():
        for pair in args.targets.split(","):
            pair = pair.strip()
            if ":" in pair:
                lat_s, lon_s = pair.split(":", 1)
                target_positions.append((float(lat_s), float(lon_s)))

    target_csv = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f"targets_{int(time.time())}.csv",
    )
    target_manager = TargetManager(
        targets=target_positions,
        detection_radius=args.detection_radius,
        validation_window=args.validation_window,
        csv_path=target_csv if target_positions else None,
    )
    if target_positions:
        log.info(
            f"TargetManager: {len(target_positions)} targets loaded | "
            f"radius={args.detection_radius}m | window={args.validation_window}s | "
            f"CSV → {target_csv}"
        )
    else:
        log.info("TargetManager: no targets specified (search disabled) — "
                 "use --targets=lat:lon,lat:lon to enable")

    # ── SITL readiness ────────────────────────────────────────────────
    wait_for_ports(args.drones, timeout=300.0)

    if not args.no_map:
        launch_mavproxy(args.drones)
        log.info("Waiting 20s for MAVProxy to stabilise…")
        time.sleep(20)
        log.info("MAVProxy ready ✓")

    # ── Build drone agents ────────────────────────────────────────────
    drone_list = []
    for i, (lat, lon) in enumerate(positions):
        drone = DroneAgent(
            drone_id=i,
            connection_str=f"udpin:127.0.0.1:{agent_udp(i)}",
            grid=grid,
            planner=planner,
            altitude=args.altitude,
            loop_hz=args.loop_hz,
            expected_sysid=i + 1,
        )
        drone.start_lat = lat
        drone.start_lon = lon
        drone_list.append(drone)

    # ── Connect all drones in parallel ────────────────────────────────
    agents = connect_all(drone_list)

    for a in agents:
        log.info(f"[ID CHECK] Drone {a.drone_id} "
                 f"sysid={a.conn.expected_sysid}")

    # ── Infinite battery ──────────────────────────────────────────────
    for a in agents:
        try:
            a.conn.master.param_set_send(
                "SIM_BATT_CAPACITY",
                0,
                mavutil.mavlink.MAV_PARAM_TYPE_REAL32
            )
            log.info(f"[Drone {a.drone_id + 1}] SIM_BATT_CAPACITY=0 (infinite battery) ✓")
        except Exception as e:
            log.warning(f"[Drone {a.drone_id + 1}] Could not set battery param: {e}")

    if not agents:
        log.error("No drones connected — exiting.")
        sys.exit(1)

    # ── Validation protocol ───────────────────────────────────────────
    # Constructed after agents are connected so _select_validator() has
    # a full list to work with from the start.
    validation_protocol = ValidationProtocol(
        target_manager=target_manager,
        agents=agents,
        planner=planner,
        pheromone_boost=args.pheromone_boost,
    )

    # Inject search context into every agent
    for agent in agents:
        agent._target_manager      = target_manager
        agent._validation_protocol = validation_protocol

    log.info("ValidationProtocol ready ✓")

    # Initial position snapshot
    time.sleep(3)
    for agent in agents:
        agent._update_position()
        log.info(f"[Drone {agent.drone_id + 1}] SITL position: "
                 f"({agent.lat}, {agent.lon})")

    time.sleep(2)

    spawn_ready = threading.Event()

    # ── Start Lloyd thread ────────────────────────────────────────────
    threading.Thread(
        target=_lloyd_loop,
        args=(planner, agents, spawn_ready, args.coverage_threshold),
        daemon=True,
        name="lloyd-loop",
    ).start()
    log.info("Lloyd loop thread started ✓")

    # ── Start drone agents ────────────────────────────────────────────
    log.info("Starting agents…")
    for agent in agents:
        agent.start()
        time.sleep(0.8)

    # ── Start state writer ────────────────────────────────────────────
    threading.Thread(
        target=_state_writer_loop,
        args=(agents, planner, target_manager),
        daemon=True,
        name="state-writer",
    ).start()

    # ── Wait for all drones airborne ──────────────────────────────────
    log.info("Waiting for all drones to reach altitude…")
    while not all(getattr(a, "airborne", False) for a in agents):
        time.sleep(1)
    log.info("All drones airborne ✓")

    # ── Dispatch spawn flights in parallel ────────────────────────────
    log.info("Dispatching drones to spawn positions in parallel…")
    for agent, (lat, lon) in zip(agents, positions):
        threading.Thread(
            target=_fly_to_spawn,
            args=(agent, lat, lon, args.altitude),
            daemon=True,
            name=f"spawn-{agent.drone_id}",
        ).start()

    # ── Wait for spawn convergence ────────────────────────────────────
    log.info("Waiting for drones to reach spawn positions…")
    spawn_deadline = time.time() + 120

    while time.time() < spawn_deadline:
        if any(a.lat is None for a in agents):
            time.sleep(2)
            continue

        all_reached = all(
            haversine_m(a.lat, a.lon, lat, lon) < 3.0
            for a, (lat, lon) in zip(agents, positions)
        )
        if all_reached:
            log.info("All drones at spawn positions — signalling Lloyd bootstrap ✓")
            spawn_ready.set()
            break

        time.sleep(2)
    else:
        log.warning("Spawn timeout — signalling Lloyd with current positions")
        spawn_ready.set()

    # ── Shutdown handlers ─────────────────────────────────────────────
    def _cleanup():
        log.info("Shutting down…")
        for a in agents:
            a.stop()
        grid.stop_evaporation()
        log.info("Done.")

    signal.signal(signal.SIGINT,  lambda sig, frame: (_cleanup(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda sig, frame: (_cleanup(), sys.exit(0)))

    # ── Main metrics + drift correction loop ─────────────────────────
    def _main_loop():
        metrics = MetricsTracker(planner, agents)

        log.info("Waiting for territory assignment…")
        while not all(
            a.territory is not None and len(a.territory) > 0
            for a in agents
        ):
            time.sleep(1)
        log.info("All territories assigned — metrics starting ✓")

        while True:
            time.sleep(2)
            try:
                _write_state(agents, planner, target_manager)
            except Exception as e:
                log.warning(f"[main-loop] state write failed: {e}")
            metrics.report()

            # Target status summary (only when targets are configured)
            if target_positions:
                log.info(target_manager.summary())

            # Drift correction: push drones back toward their territory
            for agent in agents:
                # Skip drift correction if drone is on a validation mission —
                # it's intentionally outside its territory right now.
                if agent._validation_target is not None:
                    continue
                if (agent.lat is None
                        or agent.territory is None
                        or len(agent.territory) == 0):
                    continue
                pos     = np.array([agent.lat, agent.lon])
                dists   = np.linalg.norm(agent.territory - pos, axis=1)
                nearest = dists.min()
                if nearest >= 0.002:   # ~200m
                    idx = np.argmin(dists)
                    recover_lat = float(agent.territory[idx, 0])
                    recover_lon = float(agent.territory[idx, 1])
                    log.warning(f"[Drone {agent.drone_id + 1}] DRIFT CORRECTION "
                                f"→ ({recover_lat:.5f},{recover_lon:.5f})")
                    agent._goto(recover_lat, recover_lon, agent.altitude)

    if args.duration > 0:
        log.info(f"Running for {args.duration}s — Ctrl+C to stop early")
        run_deadline = time.time() + args.duration
        while time.time() < run_deadline:
            try:
                _write_state(agents, planner, target_manager)
            except Exception as e:
                log.warning(f"[main-loop] state write failed: {e}")
            time.sleep(2)
        _cleanup()
    else:
        log.info("Running indefinitely — Ctrl+C to stop")
        _main_loop()


if __name__ == "__main__":
    main()