"""
visualiser.py
-------------
Real-time stigmergy swarm visualiser.

Shows:
  - Pheromone heatmap (purple = low, yellow = high)
  - Red dots for each active drone
  - Drone trails (fading white)
  - Live stats (airborne count, tick rate)

Reads directly from the shared InMemoryPheromoneGrid and DroneAgent list.
Run from swarm_main.py by passing agents + grid after takeoff.

Usage (standalone test):
  python3 visualiser.py

Usage (from swarm_main.py):
  from visualiser import SwarmVisualiser
  vis = SwarmVisualiser(grid, agents)
  vis.start()   # non-blocking, runs in its own thread
  ...
  vis.stop()
"""

import threading
import time
import math
from collections import deque
from typing import List, Optional

import numpy as np
import matplotlib
matplotlib.use("MacOSX")  # native macOS backend, no Tk/wx needed
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.animation import FuncAnimation

from stigmergy_engine import InMemoryPheromoneGrid
from drone_agent import DroneAgent

TRAIL_LEN    = 40     # positions to keep per drone
REFRESH_MS   = 500    # animation interval in milliseconds
DOT_SIZE     = 80     # scatter marker size
TRAIL_ALPHA  = 0.35


class SwarmVisualiser:
    def __init__(self, grid: InMemoryPheromoneGrid, agents: List[DroneAgent]):
        self.grid    = grid
        self.agents  = agents
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._trails = {a.drone_id: deque(maxlen=TRAIL_LEN) for a in agents}

    # ── Public API ───────────────────────────────────────────────────

    def start(self):
        """Start the visualiser in a background thread."""
        self._running = True
        self._thread  = threading.Thread(
            target=self._run, daemon=True, name="visualiser"
        )
        self._thread.start()

    def stop(self):
        self._running = False

    # ── Internal ─────────────────────────────────────────────────────

    def _run(self):
        cfg = self.grid.config

        fig, ax = plt.subplots(figsize=(8, 8))
        fig.patch.set_facecolor("#0d0d0d")
        ax.set_facecolor("#0d0d0d")
        ax.set_title("Stigmergy Swarm", color="white", fontsize=13)
        ax.tick_params(colors="white")
        for spine in ax.spines.values():
            spine.set_edgecolor("#444")

        # Axis labels in relative metres from grid centre
        cx = (cfg.lon_min + cfg.lon_max) / 2
        cy = (cfg.lat_min + cfg.lat_max) / 2
        def lon_to_m(lon): return (lon - cx) * 111_111 * math.cos(math.radians(cy))
        def lat_to_m(lat): return (lat - cy) * 111_111

        grid_w_m = lon_to_m(cfg.lon_max)
        grid_h_m = lat_to_m(cfg.lat_max)
        ax.set_xlim(-grid_w_m, grid_w_m)
        ax.set_ylim(-grid_h_m, grid_h_m)
        ax.set_xlabel("metres (E/W)", color="#aaa")
        ax.set_ylabel("metres (N/S)", color="#aaa")

        # Pheromone heatmap
        snapshot  = self.grid.get_snapshot()
        img_extent = [-grid_w_m, grid_w_m, -grid_h_m, grid_h_m]
        heatmap = ax.imshow(
            snapshot,
            origin="lower",
            extent=img_extent,
            cmap="plasma",
            alpha=0.75,
            aspect="auto",
            vmin=0, vmax=5,
        )
        cbar = fig.colorbar(heatmap, ax=ax, fraction=0.03, pad=0.02)
        cbar.set_label("Pheromone", color="white")
        cbar.ax.yaxis.set_tick_params(color="white")
        plt.setp(cbar.ax.yaxis.get_ticklabels(), color="white")

        # Drone dots
        scatter = ax.scatter([], [], s=DOT_SIZE, c="red", zorder=5,
                             edgecolors="white", linewidths=0.5)

        # Trail lines — one per drone
        trail_lines = {}
        for agent in self.agents:
            line, = ax.plot([], [], color="white", alpha=TRAIL_ALPHA,
                            linewidth=0.8, zorder=4)
            trail_lines[agent.drone_id] = line

        # Stats text
        stats_text = ax.text(
            0.02, 0.97, "", transform=ax.transAxes,
            color="white", fontsize=9, va="top",
            fontfamily="monospace",
        )

        def update(_frame):
            if not self._running:
                return

            # Update heatmap
            snap = self.grid.get_snapshot()
            heatmap.set_data(snap)
            heatmap.set_clim(vmin=0, vmax=max(snap.max(), 1))

            # Update drone positions
            xs, ys = [], []
            airborne = 0
            for agent in self.agents:
                if agent.lat is None or agent.lon is None:
                    continue
                airborne += 1
                mx = lon_to_m(agent.lon)
                my = lat_to_m(agent.lat)
                xs.append(mx)
                ys.append(my)
                self._trails[agent.drone_id].append((mx, my))

                trail = self._trails[agent.drone_id]
                if len(trail) >= 2:
                    tx, ty = zip(*trail)
                    trail_lines[agent.drone_id].set_data(tx, ty)

            scatter.set_offsets(np.c_[xs, ys] if xs else np.empty((0, 2)))

            stats_text.set_text(
                f"Airborne : {airborne}/{len(self.agents)}\n"
                f"Max pher : {snap.max():.2f}\n"
                f"Mean pher: {snap.mean():.4f}"
            )

        anim = FuncAnimation(fig, update, interval=REFRESH_MS, cache_frame_data=False)
        plt.tight_layout()
        plt.show()


# ── Minimal standalone test (no SITL needed) ─────────────────────────
if __name__ == "__main__":
    from stigmergy_engine import GridConfig

    home_lat, home_lon = -35.363262, 149.165237
    span = 0.004
    cfg  = GridConfig(
        lat_min=home_lat - span, lat_max=home_lat + span,
        lon_min=home_lon - span, lon_max=home_lon + span,
        rows=40, cols=40,
        evaporation_rate=0.97,
        deposit_strength=1.0,
        tick_interval=1.0,
    )
    grid = InMemoryPheromoneGrid(cfg)
    grid.start_evaporation()

    # Fake agents that wander randomly for testing
    import random, types
    agents = []
    for i in range(15):
        a = types.SimpleNamespace()
        a.drone_id = i
        a.lat = home_lat + random.uniform(-span * 0.8, span * 0.8)
        a.lon = home_lon + random.uniform(-span * 0.8, span * 0.8)
        agents.append(a)

    def _wander():
        while True:
            for a in agents:
                a.lat += random.uniform(-0.0001, 0.0001)
                a.lon += random.uniform(-0.0001, 0.0001)
                grid.deposit(a.lat, a.lon)
            time.sleep(0.5)

    threading.Thread(target=_wander, daemon=True).start()

    vis = SwarmVisualiser(grid, agents)
    vis._run()   # blocking in __main__