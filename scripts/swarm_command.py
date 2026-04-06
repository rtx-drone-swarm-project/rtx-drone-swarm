#!/usr/bin/env python3
"""
Send a global command to all SITL drones via MAVLink.
Usage:
  python scripts/swarm_command.py status              # confirm state of all drones (armed, mode)
  python scripts/swarm_command.py arm
  python scripts/swarm_command.py disarm
  python scripts/swarm_command.py takeoff 5
  python scripts/swarm_command.py hover   # same as loiter
  python scripts/swarm_command.py arm --wait-ack      # send arm and wait for ACK from each
  python scripts/swarm_command.py arm --host <remote_ip> --count 15

Requires: pymavlink. MAVProxy multi-vehicle uses UDP 14550, 14560, 14570, ... (step 10).
"""

import argparse
import sys
import time
import json
from pathlib import Path

# Ensure backend pymavlink is available
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from pymavlink import mavutil  # type: ignore[import-untyped]
from pymavlink.dialects.v20 import ardupilotmega as mav  # type: ignore[import-untyped]

BASE_PORT = 14550
PORT_STEP = 10  # sim_vehicle.py --count uses 14550, 14560, 14570, ... (not 14551, 14552)
COUNT = 15
LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "swarm"
CLOUD_LOG = Path(__file__).resolve().parent.parent / "logs" / "cloud"
STATUS_SAMPLE_SECONDS = 2.5
COMMAND_RETRIES = 2
COMMAND_RETRY_DELAY_SECONDS = 0.2
VERIFY_TIMEOUT_SECONDS = 4.0
GOTO_TYPE_MASK = 0b110111111000

# ArduCopter custom_mode -> name (subset)
COPTER_MODE_NAMES = {
    0: "STABILIZE",
    1: "ACRO",
    2: "ALT_HOLD",
    3: "AUTO",
    4: "GUIDED",
    5: "LOITER",
    6: "RTL",
    7: "CIRCLE",
    9: "LAND",
    15: "AUTOTUNE",
}


def _log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    CLOUD_LOG.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    line = f"{ts} {msg}\n"
    print(line.strip())
    for p in [LOG_DIR / "commands.log", CLOUD_LOG / "commands.log"]:
        with p.open("a") as f:
            f.write(line)


def connect_all(host: str = "127.0.0.1", base_port: int = BASE_PORT, port_step: int = PORT_STEP, count: int = COUNT) -> list:
    """
    Connect to all SITL drones.
    Args:
        host: Hostname or IP of the SITL server (default: localhost)
        base_port: Base UDP port (default: 14550)
        port_step: Step between ports (default: 10; sim_vehicle.py uses 14550, 14560, ...)
        count: Number of drones (default: 15)
    """
    conns = []
    for i in range(count):
        port = base_port + i * port_step
        # MAVProxy multi-vehicle uses --out 127.0.0.1:14550, :14560, :14570, ... so it SENDS to those ports.
        # We must LISTEN on those ports (udpin). For remote, we connect to host:port (udp).
        if host in ("127.0.0.1", "localhost"):
            addr = f"udpin:0.0.0.0:{port}"
        else:
            addr = f"udp:{host}:{port}"
        try:
            # Keep defaults so this connection can both receive telemetry and send commands.
            m = mavutil.mavlink_connection(addr, source_system=255)
            m.wait_heartbeat(timeout=5)
            conns.append((i, m))
        except Exception as e:
            _log(f"drone {i} ({addr}): no heartbeat - {e}")
    return conns


def send_command(
    conn,
    cmd_id: int,
    target_system: int,
    target_component: int = 1,
    p1: float = 0,
    p2: float = 0,
    p3: float = 0,
    p4: float = 0,
    p5: float = 0,
    p6: float = 0,
    p7: float = 0,
):
    conn.mav.command_long_send(
        target_system,
        target_component,
        cmd_id, 0, p1, p2, p3, p4, p5, p6, p7
    )


def send_position_target(conn, target_system: int, lat: float, lon: float, alt: float, target_component: int = 1):
    conn.mav.set_position_target_global_int_send(
        0,
        target_system,
        target_component,
        mav.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
        GOTO_TYPE_MASK,
        int(lat * 1e7),
        int(lon * 1e7),
        alt,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    )


def prime_guided_takeoff(conn, target_system: int, alt: float, target_component: int = 1) -> None:
    # Put the copter into GUIDED, arm it, and request takeoff before sending goto.
    send_command(conn, mav.MAV_CMD_DO_SET_MODE, target_system, target_component, 1, 4, 0, 0, 0, 0, 0)
    send_command(conn, mav.MAV_CMD_COMPONENT_ARM_DISARM, target_system, target_component, 1, 21196)
    send_command(conn, mav.MAV_CMD_NAV_TAKEOFF, target_system, target_component, 0, 0, 0, 0, 0, 0, alt)


def parse_dispatch_assignments(assignments_json: str) -> list:
    try:
        parsed = json.loads(assignments_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid --assignments-json payload: {exc}") from exc

    if not isinstance(parsed, list):
        raise ValueError("--assignments-json must be a JSON array")

    assignments = []
    for index, row in enumerate(parsed):
        if not isinstance(row, dict):
            raise ValueError(f"Assignment at index {index} must be an object")

        sysid = row.get("sysid")
        if sysid is None:
            raise ValueError(f"Assignment at index {index} is missing required field 'sysid'")

        try:
            sysid_int = int(sysid)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Assignment at index {index} has invalid sysid: {sysid}") from exc
        if sysid_int <= 0:
            raise ValueError(f"Assignment at index {index} has non-positive sysid: {sysid_int}")

        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
            alt = float(row["alt"])
        except KeyError as exc:
            raise ValueError(f"Assignment at index {index} missing field: {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Assignment at index {index} has non-numeric coordinate") from exc

        assignments.append(
            {
                "drone_id": row.get("drone_id"),
                "sysid": sysid_int,
                "lat": lat,
                "lon": lon,
                "alt": alt,
            }
        )

    return assignments


def run_dispatch_targets(args) -> None:
    try:
        assignments = parse_dispatch_assignments(args.assignments_json)
    except ValueError as exc:
        print(json.dumps([{"drone_id": None, "sysid": None, "success": False, "message": str(exc)}]))
        sys.exit(1)

    if not assignments:
        print("[]")
        return

    conns = connect_all(host=args.host, base_port=args.port, port_step=args.port_step, count=args.count)
    if not conns:
        results = [
            {
                "drone_id": item.get("drone_id"),
                "sysid": item["sysid"],
                "success": False,
                "message": "No SITL drones connected.",
            }
            for item in assignments
        ]
        print(json.dumps(results))
        sys.exit(1)

    conn_by_sysid = {}
    for index, conn in conns:
        sysid = int(getattr(conn, "target_system", 0) or 0)
        if sysid > 0 and sysid not in conn_by_sysid:
            conn_by_sysid[sysid] = conn
        expected_sysid = index + 1
        if expected_sysid not in conn_by_sysid:
            conn_by_sysid[expected_sysid] = conn

    results = []
    for item in assignments:
        target_sysid = item["sysid"]
        conn = conn_by_sysid.get(target_sysid)
        if conn is None:
            results.append(
                {
                    "drone_id": item.get("drone_id"),
                    "sysid": target_sysid,
                    "success": False,
                    "message": f"No MAVLink connection for sysid {target_sysid}.",
                }
            )
            continue

        try:
            prime_guided_takeoff(
                conn,
                target_system=target_sysid,
                alt=item["alt"],
            )
            send_position_target(
                conn,
                target_system=target_sysid,
                lat=item["lat"],
                lon=item["lon"],
                alt=item["alt"],
            )
            results.append(
                {
                    "drone_id": item.get("drone_id"),
                    "sysid": target_sysid,
                    "success": True,
                    "message": (
                        f"Dispatched GUIDED/arm/takeoff/goto "
                        f"lat={item['lat']:.6f} lon={item['lon']:.6f} alt={item['alt']:.1f}"
                    ),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "drone_id": item.get("drone_id"),
                    "sysid": target_sysid,
                    "success": False,
                    "message": f"Dispatch failed: {exc}",
                }
            )

    print(json.dumps(results))


def collect_heartbeat_states(conns: list, count: int, timeout: float = STATUS_SAMPLE_SECONDS) -> dict:
    """
    Aggregate latest HEARTBEAT by sysid across all links.
    Returns {sysid: {"armed": bool, "mode_name": str}} for sysid in 1..count when seen.
    """
    states = {}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        got_any = False
        for _, conn in conns:
            msg = conn.recv_match(type="HEARTBEAT", blocking=False)
            while msg is not None:
                got_any = True
                sysid = int(msg.get_srcSystem())
                if 1 <= sysid <= count:
                    states[sysid] = {
                        "armed": bool(msg.base_mode & mav.MAV_MODE_FLAG_SAFETY_ARMED),
                        "mode_name": COPTER_MODE_NAMES.get(msg.custom_mode, f"({msg.custom_mode})"),
                    }
                msg = conn.recv_match(type="HEARTBEAT", blocking=False)
        if not got_any:
            time.sleep(0.05)
    return states


def run_status(host: str, base_port: int, port_step: int, count: int) -> None:
    """Print armed state and flight mode for each drone (confirms they're alive and what they did)."""
    conns = connect_all(host=host, base_port=base_port, port_step=port_step, count=count)
    if not conns:
        last_port = base_port + (count - 1) * port_step
        print(f"No drones at {host}:{base_port}..{last_port} (step {port_step}). Start SITL swarm first.")
        return
    states = collect_heartbeat_states(conns, count=count, timeout=STATUS_SAMPLE_SECONDS)
    print(f"{'#':<4} {'sysid':<6} {'armed':<6} {'mode':<12}")
    print("-" * 32)
    for sysid in range(1, count + 1):
        state = states.get(sysid)
        if state is None:
            print(f"{sysid:<4} {sysid:<6} {'?':<6} {'(no heartbeat)':<12}")
            continue
        armed = "yes" if state["armed"] else "no"
        print(f"{sysid:<4} {sysid:<6} {armed:<6} {state['mode_name']:<12}")
    if len(states) < count:
        missing = [s for s in range(1, count + 1) if s not in states]
        print(f"\nWarning: saw {len(states)}/{count} unique sysids. Missing: {missing}")
    print(f"\nTotal links: {len(conns)}. Drones with heartbeat: {len(states)}/{count}.")


def wait_command_ack(conns: list, target_system: int, cmd_id: int, timeout: float = 2.0) -> bool:
    """Wait for COMMAND_ACK from target_system for cmd_id. Returns True on ACCEPTED."""
    t0 = time.monotonic()
    while (time.monotonic() - t0) < timeout:
        got_any = False
        for _, conn in conns:
            msg = conn.recv_match(type="COMMAND_ACK", blocking=False)
            while msg is not None:
                got_any = True
                if int(msg.get_srcSystem()) == target_system and msg.command == cmd_id:
                    return msg.result == mav.MAV_RESULT_ACCEPTED
                msg = conn.recv_match(type="COMMAND_ACK", blocking=False)
        if not got_any:
            time.sleep(0.05)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send commands to SITL drone swarm via MAVLink",
        epilog="Example: python scripts/swarm_command.py status  # confirm state",
    )
    parser.add_argument("command", help="status, arm, disarm, hover, loiter, takeoff, rtl, land, dispatch-targets")
    parser.add_argument("arg", nargs="?", type=float, default=0, help="Optional arg (e.g. altitude for takeoff)")
    parser.add_argument("--host", default="127.0.0.1", help="SITL server IP or hostname")
    parser.add_argument("--port", type=int, default=BASE_PORT, help=f"Base UDP port (default: {BASE_PORT})")
    parser.add_argument("--port-step", type=int, default=PORT_STEP, dest="port_step", help=f"Port step for multi-vehicle (default: {PORT_STEP}; use 10 for sim_vehicle.py --count)")
    parser.add_argument("--count", type=int, default=COUNT, help=f"Number of drones (default: {COUNT})")
    parser.add_argument("--assignments-json", default="[]", help="JSON list of per-drone assignments for dispatch-targets")
    parser.add_argument("--wait-ack", action="store_true", help="After sending command, wait for COMMAND_ACK from each drone")
    parser.add_argument("--retries", type=int, default=COMMAND_RETRIES, help=f"Resend passes for reliability (default: {COMMAND_RETRIES})")
    parser.add_argument("--no-verify", action="store_true", help="Skip post-command verification from HEARTBEAT state")
    args = parser.parse_args()

    cmd = args.command.lower()
    arg = args.arg

    if cmd == "status":
        run_status(host=args.host, base_port=args.port, port_step=args.port_step, count=args.count)
        return

    if cmd == "dispatch-targets":
        run_dispatch_targets(args)
        return

    conns = connect_all(host=args.host, base_port=args.port, port_step=args.port_step, count=args.count)
    if not conns:
        last_port = args.port + (args.count - 1) * args.port_step
        _log(f"No drones connected to {args.host}:{args.port}..{last_port}. Start SITL swarm first.")
        sys.exit(1)

    _log(f"Global command: {cmd} (to {len(conns)} drones)")

    if cmd not in ("arm", "arm_throttle", "disarm", "hover", "loiter", "takeoff", "rtl", "land"):
        _log(f"Unknown command: {cmd}")
        sys.exit(1)

    retries = max(1, args.retries)
    sent_targets = set()
    ack_results = {}
    for attempt in range(retries):
        for target_system in range(1, args.count + 1):
            conn = conns[(target_system - 1) % len(conns)][1]
            try:
                if cmd in ("arm", "arm_throttle"):
                    send_command(conn, mav.MAV_CMD_COMPONENT_ARM_DISARM, target_system, 1, 1, 21196)
                elif cmd == "disarm":
                    send_command(conn, mav.MAV_CMD_COMPONENT_ARM_DISARM, target_system, 1, 0, 0)
                elif cmd in ("hover", "loiter"):
                    # LOITER mode = 5 in ArduCopter.
                    send_command(conn, mav.MAV_CMD_DO_SET_MODE, target_system, 1, 1, 5, 0, 0, 0, 0, 0)
                elif cmd == "takeoff":
                    # Auto-arm + GUIDED before takeoff for better reliability in SITL.
                    send_command(conn, mav.MAV_CMD_COMPONENT_ARM_DISARM, target_system, 1, 1, 21196)
                    send_command(conn, mav.MAV_CMD_DO_SET_MODE, target_system, 1, 1, 4, 0, 0, 0, 0, 0)
                    send_command(conn, mav.MAV_CMD_NAV_TAKEOFF, target_system, 1, 0, 0, 0, 0, 0, 0, arg or 5)
                elif cmd == "rtl":
                    send_command(conn, mav.MAV_CMD_DO_SET_MODE, target_system, 1, 1, 6, 0, 0, 0, 0, 0)
                elif cmd == "land":
                    send_command(conn, mav.MAV_CMD_DO_SET_MODE, target_system, 1, 1, 9, 0, 0, 0, 0, 0)
                sent_targets.add(target_system)
            except Exception as e:
                _log(f"drone {target_system}: {e}")
        if attempt < retries - 1:
            time.sleep(COMMAND_RETRY_DELAY_SECONDS)

    if args.wait_ack:
        ack_cmd = mav.MAV_CMD_NAV_TAKEOFF if cmd == "takeoff" else mav.MAV_CMD_COMPONENT_ARM_DISARM
        if cmd in ("hover", "loiter", "rtl", "land"):
            ack_cmd = mav.MAV_CMD_DO_SET_MODE
        for target_system in range(1, args.count + 1):
            ok = wait_command_ack(conns, target_system=target_system, cmd_id=ack_cmd)
            ack_results[target_system] = ok
            print(f"  sysid {target_system}: {'ACK OK' if ok else 'ACK timeout/fail'}")

    missing_targets = [s for s in range(1, args.count + 1) if s not in sent_targets]
    if missing_targets:
        _log(f"Command send incomplete; missing target sysids: {missing_targets}")
    else:
        _log(f"Command sent to {len(sent_targets)} target sysids (retries={retries}).")

    if not args.no_verify:
        states = collect_heartbeat_states(conns, count=args.count, timeout=VERIFY_TIMEOUT_SECONDS)
        failed = []
        for sysid in range(1, args.count + 1):
            state = states.get(sysid)
            if state is None:
                failed.append(sysid)
                continue
            if cmd in ("arm", "arm_throttle") and not state["armed"]:
                failed.append(sysid)
            elif cmd == "disarm" and state["armed"]:
                failed.append(sysid)
            elif cmd in ("hover", "loiter") and state["mode_name"] != "LOITER":
                failed.append(sysid)
            elif cmd == "takeoff" and (not state["armed"] or state["mode_name"] != "GUIDED"):
                failed.append(sysid)
            elif cmd == "rtl" and state["mode_name"] != "RTL":
                failed.append(sysid)
            elif cmd == "land" and state["mode_name"] != "LAND":
                failed.append(sysid)

        if failed:
            _log(f"Post-check failed for sysids: {failed}")
        else:
            _log("Post-check passed for all target sysids.")


if __name__ == "__main__":
    main()
