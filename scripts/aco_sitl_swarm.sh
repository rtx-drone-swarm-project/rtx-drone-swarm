#!/bin/bash
# launch_map.sh — Launch MAVProxy with all 15 drone viz streams
# Run from project root after aco_sitl_swarm.py is running:
#   bash scripts/launch_map.sh

BASE_PORT=14550
PORT_STEP=10
VIZ_OFFSET=5
NUM_DRONES=15

echo "Launching MAVProxy map for $NUM_DRONES drones..."

# Build --master args for all viz ports
MASTERS=""
for i in $(seq 0 $((NUM_DRONES - 1))); do
    PORT=$((BASE_PORT + i * PORT_STEP + VIZ_OFFSET))
    MASTERS="$MASTERS --master udpin:0.0.0.0:$PORT"
done

echo "Connecting to ports:"
for i in $(seq 0 $((NUM_DRONES - 1))); do
    PORT=$((BASE_PORT + i * PORT_STEP + VIZ_OFFSET))
    echo "  Drone $((i+1)) → port $PORT"
done
echo ""

mavproxy.py $MASTERS \
    --map \
    --console \
    --aircraft RTX-Swarm