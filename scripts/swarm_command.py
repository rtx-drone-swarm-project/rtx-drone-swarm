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

# ArduCopter custom_mode -> name (subset)
COPTER_MODE_NAMES = {
    0: "STABILIZE",
    2: "ALT_HOLD",
    3: "LOITER",
    5: "GUIDED",
    6: "RTL",
    7: "CIRCLE",
    9: "LAND",
    15: "AUTO",
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
            m = mavutil.mavlink_connection(addr, input=False)
            m.wait_heartbeat(timeout=5)
            conns.append((i, m))
        except Exception as e:
            _log(f"drone {i} ({addr}): no heartbeat - {e}")
    return conns


def send_command(conn, cmd_id: int, p1: float = 0, p2: float = 0, p3: float = 0, p4: float = 0, p5: float = 0, p6: float = 0, p7: float = 0):
    conn.mav.command_long_send(
        conn.target_system, conn.target_component,
        cmd_id, 0, p1, p2, p3, p4, p5, p6, p7
    )


def run_status(host: str, base_port: int, port_step: int, count: int) -> None:
    """Print armed state and flight mode for each drone (confirms they're alive and what they did)."""
    conns = connect_all(host=host, base_port=base_port, port_step=port_step, count=count)
    if not conns:
        last_port = base_port + (count - 1) * port_step
        print(f"No drones at {host}:{base_port}..{last_port} (step {port_step}). Start SITL swarm first.")
        return
    print(f"{'#':<4} {'sysid':<6} {'armed':<6} {'mode':<12}")
    print("-" * 32)
    for i, conn in conns:
        # Next HEARTBEAT is ~1 Hz; wait up to 4 s (first was consumed in wait_heartbeat)
        msg = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=4)
        if msg is None:
            print(f"{i:<4} {conn.target_system:<6} {'?':<6} {'(no heartbeat)':<12}")
            continue
        armed = "yes" if (msg.base_mode & mav.MAV_MODE_FLAG_SAFETY_ARMED) else "no"
        mode_name = COPTER_MODE_NAMES.get(msg.custom_mode, f"({msg.custom_mode})")
        print(f"{i:<4} {conn.target_system:<6} {armed:<6} {mode_name:<12}")
    print(f"\nTotal: {len(conns)} drones.")


def wait_command_ack(conn, cmd_id: int, timeout: float = 2.0) -> bool:
    """Wait for COMMAND_ACK for the given command. Returns True if ACK result is success."""
    t0 = time.monotonic()
    while (time.monotonic() - t0) < timeout:
        msg = conn.recv_match(type="COMMAND_ACK", blocking=True, timeout=0.5)
        if msg is not None and msg.command == cmd_id:
            return msg.result == mav.MAV_RESULT_ACCEPTED
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send commands to SITL drone swarm via MAVLink",
        epilog="Example: python scripts/swarm_command.py status  # confirm state",
    )
    parser.add_argument("command", help="status, arm, disarm, hover, loiter, takeoff, rtl, land")
    parser.add_argument("arg", nargs="?", type=float, default=0, help="Optional arg (e.g. altitude for takeoff)")
    parser.add_argument("--host", default="127.0.0.1", help="SITL server IP or hostname")
    parser.add_argument("--port", type=int, default=BASE_PORT, help=f"Base UDP port (default: {BASE_PORT})")
    parser.add_argument("--port-step", type=int, default=PORT_STEP, dest="port_step", help=f"Port step for multi-vehicle (default: {PORT_STEP}; use 10 for sim_vehicle.py --count)")
    parser.add_argument("--count", type=int, default=COUNT, help=f"Number of drones (default: {COUNT})")
    parser.add_argument("--wait-ack", action="store_true", help="After sending command, wait for COMMAND_ACK from each drone")
    args = parser.parse_args()

    cmd = args.command.lower()
    arg = args.arg

    if cmd == "status":
        run_status(host=args.host, base_port=args.port, port_step=args.port_step, count=args.count)
        return

    conns = connect_all(host=args.host, base_port=args.port, port_step=args.port_step, count=args.count)
    if not conns:
        last_port = args.port + (args.count - 1) * args.port_step
        _log(f"No drones connected to {args.host}:{args.port}..{last_port}. Start SITL swarm first.")
        sys.exit(1)

    _log(f"Global command: {cmd} (to {len(conns)} drones)")

    cmd_id = None
    for i, conn in conns:
        try:
            if cmd in ("arm", "arm_throttle"):
                cmd_id = mav.MAV_CMD_COMPONENT_ARM_DISARM
                send_command(conn, cmd_id, 1, 21196)
            elif cmd == "disarm":
                cmd_id = mav.MAV_CMD_COMPONENT_ARM_DISARM
                send_command(conn, cmd_id, 0, 0)
            elif cmd in ("hover", "loiter"):
                cmd_id = mav.MAV_CMD_DO_SET_MODE
                send_command(conn, cmd_id, 1, 5, 0, 0, 0, 0, 0)
            elif cmd == "takeoff":
                cmd_id = mav.MAV_CMD_NAV_TAKEOFF
                send_command(conn, cmd_id, 0, 0, 0, 0, 0, 0, arg or 5)
            elif cmd == "rtl":
                cmd_id = mav.MAV_CMD_DO_SET_MODE
                send_command(conn, cmd_id, 1, 6, 0, 0, 0, 0, 0)
            elif cmd == "land":
                cmd_id = mav.MAV_CMD_DO_SET_MODE
                send_command(conn, cmd_id, 1, 9, 0, 0, 0, 0, 0)
            else:
                _log(f"Unknown command: {cmd}")
                sys.exit(1)
            if args.wait_ack and cmd_id is not None:
                ok = wait_command_ack(conn, cmd_id)
                print(f"  drone {i} (sysid {conn.target_system}): {'ACK OK' if ok else 'ACK timeout/fail'}")
        except Exception as e:
            _log(f"drone {i}: {e}")

    _log("Command sent to all drones.")


if __name__ == "__main__":
    main()
