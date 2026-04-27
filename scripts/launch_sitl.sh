#!/usr/bin/env bash
# Start 15 headless SITL drones (ArduCopter swarm).
# Requires ArduPilot clone. Set ARDUPILOT_PATH if not ~/ardupilot.
#
# Logs: SITL outputs to logs/sitl/<run_id>/, capacity metrics to logs/swarm/

set -e
COUNT="${1:-15}"
ARDUPILOT_PATH="${ARDUPILOT_PATH:-$HOME/ardupilot}"
PARAM_FILE="${2:-$PWD/sitl_params.param}"
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
echo ""

cd "$ARDUPILOT_PATH"
# Use swarm mode: --count, --auto-sysid, --location, --auto-offset-line so they don't overlap
# Omit --map --console for headless (no GUI). MAVProxy runs for MAVLink on UDP 14550, 14551, ...



# Start SITL with separate UDP outputs for each drone
./Tools/autotest/sim_vehicle.py -v ArduCopter -f quad \
  --count "$COUNT" \
  --auto-sysid \
  --location CMAC \
  --auto-offset-line 90,10 \
  --add-param-file "$PARAM_FILE" \
  --map \
  --mavproxy-args="--cmd=\"module load swarm\"" \
  2>&1 | tee "$SWARM_LOG"
