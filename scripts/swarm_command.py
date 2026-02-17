#!/usr/bin/env python3
"""
Send a global command to all SITL drones via MAVLink.
Usage:
  python scripts/swarm_command.py hover
  python scripts/swarm_command.py arm
  python scripts/swarm_command.py disarm
  python scripts/swarm_command.py takeoff 5
  python scripts/swarm_command.py loiter   # same as hover

Requires: pymavlink. Connects to UDP 14550..14564 (MAVProxy outputs to these ports).
"""

import sys
import time
from pathlib import Path

# Ensure backend pymavlink is available
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from pymavlink import mavutil
from pymavlink.dialects.v20 import ardupilotmega as mav

HOST = "127.0.0.1"
BASE_PORT = 14550
COUNT = 15
LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "swarm"
CLOUD_LOG = Path(__file__).resolve().parent.parent / "logs" / "cloud"


def _log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    CLOUD_LOG.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    line = f"{ts} {msg}\n"
    print(line.strip())
    for p in [LOG_DIR / "commands.log", CLOUD_LOG / "commands.log"]:
        with p.open("a") as f:
            f.write(line)


def connect_all(count: int = COUNT) -> list:
    conns = []
    for i in range(count):
        port = BASE_PORT + i
        addr = f"udpin:0.0.0.0:{port}"
        try:
            m = mavutil.mavlink_connection(addr, input=False)
            m.wait_heartbeat(timeout=3)
            conns.append((i, m))
        except Exception as e:
            _log(f"drone {i} ({addr}): no heartbeat - {e}")
    return conns


def send_command(conn, cmd_id: int, p1: float = 0, p2: float = 0, p3: float = 0, p4: float = 0, p5: float = 0, p6: float = 0, p7: float = 0):
    conn.mav.command_long_send(
        conn.target_system, conn.target_component,
        cmd_id, 0, p1, p2, p3, p4, p5, p6, p7
    )


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1].lower()
    arg = float(sys.argv[2]) if len(sys.argv) > 2 else 0

    conns = connect_all()
    if not conns:
        _log("No drones connected. Start SITL swarm first.")
        sys.exit(1)

    _log(f"Global command: {cmd} (to {len(conns)} drones)")

    for i, conn in conns:
        try:
            if cmd in ("arm", "arm_throttle"):
                send_command(conn, mav.MAV_CMD_COMPONENT_ARM_DISARM, 1, 21196)
            elif cmd == "disarm":
                send_command(conn, mav.MAV_CMD_COMPONENT_ARM_DISARM, 0, 0)
            elif cmd in ("hover", "loiter"):
                # ArduCopter LOITER = 5
                send_command(conn, mav.MAV_CMD_DO_SET_MODE, 1, 5, 0, 0, 0, 0, 0)
            elif cmd == "takeoff":
                send_command(conn, mav.MAV_CMD_NAV_TAKEOFF, 0, 0, 0, 0, 0, 0, arg or 5)
            elif cmd == "rtl":
                # ArduCopter RTL = 6
                send_command(conn, mav.MAV_CMD_DO_SET_MODE, 1, 6, 0, 0, 0, 0, 0)
            elif cmd == "land":
                # ArduCopter LAND = 9
                send_command(conn, mav.MAV_CMD_DO_SET_MODE, 1, 9, 0, 0, 0, 0, 0)
            else:
                _log(f"Unknown command: {cmd}")
                sys.exit(1)
        except Exception as e:
            _log(f"drone {i}: {e}")

    _log("Command sent to all drones.")


if __name__ == "__main__":
    main()
