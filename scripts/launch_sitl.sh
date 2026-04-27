#!/usr/bin/env bash
# Start 15 headless SITL drones (ArduCopter swarm).
# Requires ArduPilot clone. Set ARDUPILOT_PATH if not ~/ardupilot.
#
# File logging is disabled by default; see scripts/sitl_params.param.

set -e
COUNT="${1:-15}"
ARDUPILOT_PATH="${ARDUPILOT_PATH:-$HOME/ardupilot}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PARAM_FILE="${2:-$SCRIPT_DIR/sitl_params.param}"
SITL_LOCATION="${SITL_LOCATION:-CMAC}"
SITL_ENABLE_MAP="${SITL_ENABLE_MAP:-1}"
SITL_ENABLE_MAVPROXY="${SITL_ENABLE_MAVPROXY:-1}"
SITL_MAVPROXY_CMD="${SITL_MAVPROXY_CMD:-}"

# In headless environments sim_vehicle.py otherwise falls back to /tmp/ArduCopter.log.
export SITL_RITW_TERMINAL="${SITL_RITW_TERMINAL:-bash}"

if [[ ! -d "$ARDUPILOT_PATH" ]]; then
  echo "ArduPilot not found at $ARDUPILOT_PATH"
  echo "Set ARDUPILOT_PATH or clone: git clone https://github.com/ArduPilot/ardupilot.git"
  echo ""
  echo "Docker alternative: see docs/SITL_QUICKSTART.md"
  exit 1
fi

echo "Starting $COUNT headless SITL drones"
echo "SITL file logging: disabled"
echo ""

cd "$ARDUPILOT_PATH"
# Use swarm mode: --count, --auto-sysid, --location, --auto-offset-line so they don't overlap
# Omit --map --console for headless (no GUI). MAVProxy runs for MAVLink on UDP 14550, 14551, ...
SIM_VEHICLE_ARGS=(
  -v ArduCopter
  -f quad
  --count "$COUNT"
  --auto-sysid
  --location "$SITL_LOCATION"
  --auto-offset-line 90,10
  --speedup 2
  --add-param-file "$PARAM_FILE"
)

if [[ "$SITL_ENABLE_MAP" == "1" ]]; then
  SIM_VEHICLE_ARGS+=(--map)
fi

if [[ "$SITL_ENABLE_MAVPROXY" != "1" ]]; then
  SIM_VEHICLE_ARGS+=(--no-mavproxy)
elif [[ -n "$SITL_MAVPROXY_CMD" ]]; then
  SIM_VEHICLE_ARGS+=(--mavproxy-args="--cmd=\"$SITL_MAVPROXY_CMD\"")
fi

# Start SITL with separate TCP outputs for each drone.
./Tools/autotest/sim_vehicle.py "${SIM_VEHICLE_ARGS[@]}" 2>&1 | tee "$SWARM_LOG"
