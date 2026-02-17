#!/usr/bin/env bash
# Check if this server can run N headless SITL drones (default 15).
# Run on your remote server: ./scripts/check_sitl_capacity.sh [N]

set -e
TARGET_DRONES="${1:-15}"

# Rough requirements per ArduPilot SITL instance (headless, no Gazebo):
# - CPU: ~0.1–0.5 cores steady-state (spikes during init; stagger launches helps)
# - RAM: ~150–300 MB per instance
# - Disk: ~500 MB for ArduPilot build + logs
PER_DRONE_CPU_CORES=0.3
PER_DRONE_RAM_MB=250
PER_DRONE_DISK_MB=600

echo "=============================================="
echo "  SITL capacity check (target: $TARGET_DRONES drones)"
echo "=============================================="
echo ""

# CPU
if command -v nproc &>/dev/null; then
  CPU_CORES=$(nproc)
else
  CPU_CORES=$(sysctl -n hw.ncpu 2>/dev/null || echo "unknown")
fi
if [[ "$CPU_CORES" =~ ^[0-9]+$ ]]; then
  REQUIRED_CPU=$(awk "BEGIN { printf \"%.0f\", $TARGET_DRONES * $PER_DRONE_CPU_CORES }")
  echo "CPU: $CPU_CORES cores (need ~$REQUIRED_CPU for $TARGET_DRONES SITL)"
  if [[ "$CPU_CORES" -ge "$REQUIRED_CPU" ]]; then
    echo "  -> OK for CPU"
  else
    echo "  -> WARNING: CPU may be tight; use staggered SITL startup (e.g. 30s apart)"
  fi
else
  echo "CPU: $CPU_CORES (could not parse cores)"
fi
echo ""

# RAM
if [[ -f /proc/meminfo ]]; then
  RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
  RAM_MB=$((RAM_KB / 1024))
  RAM_AVAIL_KB=$(grep MemAvailable /proc/meminfo | awk '{print $2}')
  RAM_AVAIL_MB=$((RAM_AVAIL_KB / 1024))
elif command -v vm_stat &>/dev/null; then
  RAM_BYTES=$(($(sysctl -n hw.memsize 2>/dev/null)))
  RAM_MB=$((RAM_BYTES / 1024 / 1024))
  RAM_AVAIL_MB=$((RAM_MB * 3 / 4))  # rough
else
  RAM_MB="unknown"
  RAM_AVAIL_MB="unknown"
fi
if [[ "$RAM_MB" =~ ^[0-9]+$ ]]; then
  REQUIRED_RAM=$((TARGET_DRONES * PER_DRONE_RAM_MB))
  echo "RAM: ${RAM_MB} MB total, ~${RAM_AVAIL_MB} MB available (need ~${REQUIRED_RAM} MB for $TARGET_DRONES SITL)"
  if [[ "$RAM_AVAIL_MB" =~ ^[0-9]+$ ]] && [[ $RAM_AVAIL_MB -ge $REQUIRED_RAM ]]; then
    echo "  -> OK for RAM"
  elif [[ "$RAM_AVAIL_MB" =~ ^[0-9]+$ ]]; then
    echo "  -> WARNING: RAM may be insufficient for $TARGET_DRONES SITL"
  fi
else
  echo "RAM: $RAM_MB"
fi
echo ""

# Disk (current dir or /tmp)
DISK_AVAIL_MB=$(df -m . 2>/dev/null | tail -1 | awk '{print $4}')
if [[ "$DISK_AVAIL_MB" =~ ^[0-9]+$ ]]; then
  REQUIRED_DISK=$((TARGET_DRONES * PER_DRONE_DISK_MB))
  echo "Disk: ${DISK_AVAIL_MB} MB free in $(pwd) (need ~${REQUIRED_DISK} MB for builds + logs)"
  if [[ $DISK_AVAIL_MB -ge $REQUIRED_DISK ]]; then
    echo "  -> OK for disk"
  else
    echo "  -> WARNING: free more space or use another volume"
  fi
else
  echo "Disk: (could not read df)"
fi
echo ""

echo "=============================================="
echo "  Recommendation"
echo "=============================================="
echo ""
echo "1. Run this script on your server: ./scripts/check_sitl_capacity.sh $TARGET_DRONES"
echo "2. If CPU/RAM look tight, start SITL instances staggered (e.g. 30s apart)."
echo "3. Run a real test: start 15 SITL instances and watch:"
echo "   watch -n 2 'top -b -n 1 | head -20; echo; free -h'"
echo ""
