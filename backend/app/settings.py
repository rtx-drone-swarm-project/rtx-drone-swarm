"""Shared backend configuration constants and script paths."""

from pathlib import Path
import os


SWARM_COMMAND_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "swarm_command.py"
LAUNCH_SITL_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "launch_sitl.sh"

DEFAULT_DISPATCH_HOST = "127.0.0.1"
DEFAULT_DISPATCH_TIMEOUT_SECONDS = 15.0
DEFAULT_DISPATCH_ALT = 30.0

DISPATCH_MAX_WORKERS = 15
SLEEP_BETWEEN_DISPATCH_SECONDS = 0.5

AUTO_START_SITL_ON_MISSION_START = os.environ.get("AUTO_START_SITL_ON_MISSION_START", "0") == "1"
DEFAULT_SITL_HOME_ALT = float(os.environ.get("SITL_HOME_ALT", "0"))
DEFAULT_SITL_HOST = os.environ.get("SITL_HOST", "127.0.0.1")
DEFAULT_SITL_BASE_PORT = int(os.environ.get("SITL_BASE_PORT", "5760"))
DEFAULT_SITL_PORT_STEP = int(os.environ.get("SITL_PORT_STEP", "10"))
DEFAULT_SITL_COUNT = int(os.environ.get("SITL_COUNT", "15"))
DEFAULT_SITL_POLL_INTERVAL_SECONDS = float(os.environ.get("SITL_POLL_INTERVAL_SECONDS", "0.2"))

GOTO_TYPE_MASK = 0b110111111000
