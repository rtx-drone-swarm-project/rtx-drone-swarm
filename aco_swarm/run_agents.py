# run_agents.py
import time
import logging
from stigmergy_engine import InMemoryPheromoneGrid, GridConfig
from drone_agent import DroneAgent

logging.basicConfig(level=logging.INFO)

# ── Configure the grid ─────────────────────────────
grid_config = GridConfig(
    lat_min=37.427,  # example coordinates (UCI campus)
    lat_max=37.431,
    lon_min=-122.173,
    lon_max=-122.169,
    rows=50,
    cols=50,
)
grid = InMemoryPheromoneGrid(grid_config)
grid.start_evaporation()

# ── Create agents ──────────────────────────────────
# TCP ports: 5760, 5762, 5764, … (SITL default when --count N)
agents = [
    DroneAgent(drone_id=i, connection=f"tcp:127.0.0.1:{5760 + i*2}", grid=grid)
    for i in range(15)
]

# ── Connect all agents ─────────────────────────────
for agent in agents:
    try:
        agent.connect(timeout=60)  # waits for heartbeat
        agent.start()
        print(f"[Drone {agent.drone_id}] Started")
    except Exception as e:
        print(f"[Drone {agent.drone_id}] FAILED to connect: {e}")

# ── Keep the script alive ─────────────────────────
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Stopping agents…")
    for agent in agents:
        agent.stop()
    grid.stop_evaporation()
