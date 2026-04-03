#!/usr/bin/env bash
# Start 15 headless SITL drones (ArduCopter swarm).
# Requires ArduPilot clone. Set ARDUPILOT_PATH if not ~/ardupilot.
#
# Logs: SITL outputs to logs/sitl/<run_id>/, capacity metrics to logs/swarm/
#
# Networking:
# - By default SITL sends MAVLink UDP outputs to 127.0.0.1:14550,14560,...
# - Override SITL_OUT_HOST to route telemetry to a backend container/service/VM.
# Spawn:
# - Set SITL_HOME="lat,lon,alt,heading" to start the swarm near a mission area.
# - Otherwise the script uses SITL_LOCATION (default: CMAC).

set -e
COUNT="${1:-15}"
ARDUPILOT_PATH="${ARDUPILOT_PATH:-$HOME/ardupilot}"
SITL_OUT_HOST="${SITL_OUT_HOST:-127.0.0.1}"
SITL_HOME="${SITL_HOME:-}"
SITL_LOCATION="${SITL_LOCATION:-CMAC}"
BASE_PORT="${SITL_BASE_PORT:-14550}"
PORT_STEP="${SITL_PORT_STEP:-10}"
RUN_ID="$(date +%Y%m%d-%H%M%S)"
LOG_BASE="$(cd "$(dirname "$0")/.." && pwd)/logs"
mkdir -p "$LOG_BASE/sitl" "$LOG_BASE/swarm" "$LOG_BASE/cloud"

if [[ ! -d "$ARDUPILOT_PATH" ]]; then
  echo "ArduPilot not found at $ARDUPILOT_PATH"
  echo "Set ARDUPILOT_PATH or clone: git clone https://github.com/ArduPilot/ardupilot.git"
  echo ""
  echo "Docker alternative: see docs/SITL_QUICKSTART.md"
  exit 1
fi

SITL_LOG="$LOG_BASE/sitl/swarm-$RUN_ID"
SWARM_LOG="$LOG_BASE/swarm/start-$RUN_ID.log"
mkdir -p "$SITL_LOG"

echo "Starting $COUNT headless SITL drones (run $RUN_ID)"
echo "SITL logs: $SITL_LOG"
echo "Swarm log: $SWARM_LOG"
echo "Cloud log dir: $LOG_BASE/cloud"
echo "Telemetry target: $SITL_OUT_HOST:$BASE_PORT step $PORT_STEP"
if [[ -n "$SITL_HOME" ]]; then
  echo "Spawn home: $SITL_HOME"
else
  echo "Spawn location: $SITL_LOCATION"
fi
echo ""

cd "$ARDUPILOT_PATH"
# Use swarm mode: --count, --auto-sysid, --location, --auto-offset-line so they don't overlap
# Omit --map --console for headless (no GUI).

# Construct --out parameters for each drone
OUT_ARGS=""
for ((i=0;i<COUNT;i++)); do
  PORT=$((BASE_PORT + i*PORT_STEP))
  OUT_ARGS+=" --out ${SITL_OUT_HOST}:$PORT"
done

SIM_VEHICLE_ARGS=(
  ./Tools/autotest/sim_vehicle.py
  -v ArduCopter
  -f quad
  --count "$COUNT"
  --auto-sysid
  --auto-offset-line 90,10
  --mavproxy-args="--cmd=\"module load swarm\""
  -w
)

if [[ -n "$SITL_HOME" ]]; then
  SIM_VEHICLE_ARGS+=(--custom-location "$SITL_HOME")
else
  SIM_VEHICLE_ARGS+=(--location "$SITL_LOCATION")
fi

# Start SITL with separate UDP outputs for each drone
"${SIM_VEHICLE_ARGS[@]}" $OUT_ARGS 2>&1 | tee "$SWARM_LOG"
