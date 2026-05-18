"""
stigmergy_engine.py
-------------------
Pheromone grid for the drone swarm.
Backend-agnostic: InMemoryPheromoneGrid uses numpy.
Swap for RedisPheromoneGrid (stub below) to go distributed —
no other file needs to change.
"""

import numpy as np
import threading
import time
import random
from dataclasses import dataclass
from typing import Tuple, Optional, List


@dataclass
class GridConfig:
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    rows: int               = 50
    cols: int               = 50
    evaporation_rate: float = 0.97   # multiplied every tick
    deposit_strength: float = 1.0
    tick_interval: float    = 1.0    # seconds


class InMemoryPheromoneGrid:
    """
    Thread-safe in-memory pheromone grid.

    TO SWAP FOR REDIS — implement the same six methods in RedisPheromoneGrid:
        deposit, get_value, get_gradient, get_snapshot,
        start_evaporation, stop_evaporation
    Then change one line in swarm_main.py. Nothing else changes.
    """

    def __init__(self, config: GridConfig):
        self.config   = config
        self.grid     = np.zeros((config.rows, config.cols), dtype=np.float32)
        self._lock    = threading.Lock()
        self._running = False

    # ── Coordinate helpers ──────────────────────────────────────────

    def world_to_grid(self, lat: float, lon: float) -> Tuple[int, int]:
        cfg = self.config
        row = int((lat - cfg.lat_min) / (cfg.lat_max - cfg.lat_min) * (cfg.rows - 1))
        col = int((lon - cfg.lon_min) / (cfg.lon_max - cfg.lon_min) * (cfg.cols - 1))
        return max(0, min(cfg.rows - 1, row)), max(0, min(cfg.cols - 1, col))

    def grid_to_world(self, row: int, col: int) -> Tuple[float, float]:
        cfg = self.config
        lat = cfg.lat_min + (row / (cfg.rows - 1)) * (cfg.lat_max - cfg.lat_min)
        lon = cfg.lon_min + (col / (cfg.cols - 1)) * (cfg.lon_max - cfg.lon_min)
        return lat, lon

    # ── Core operations ─────────────────────────────────────────────

    def deposit(self, lat: float, lon: float, strength: Optional[float] = None):
        s = strength if strength is not None else self.config.deposit_strength
        row, col = self.world_to_grid(lat, lon)
        with self._lock:
            self.grid[row, col] += s

    def get_value(self, lat: float, lon: float) -> float:
        row, col = self.world_to_grid(lat, lon)
        with self._lock:
            return float(self.grid[row, col])

    def get_gradient(self, lat: float, lon: float, radius: int = 2) -> Tuple[float, float]:
        """
        Return the least-visited neighbour cell within `radius` steps.

        Tie-breaking: when multiple cells share the minimum pheromone value
        (common at startup when the grid is all zeros), pick randomly among
        them rather than defaulting to the current cell — this ensures drones
        move immediately instead of sending a goto to their own position.
        """
        row, col = self.world_to_grid(lat, lon)
        cfg      = self.config

        with self._lock:
            best_val:   float               = float('inf')
            candidates: List[Tuple[int,int]] = []

            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    if dr == 0 and dc == 0:
                        continue
                    r = max(0, min(cfg.rows - 1, row + dr))
                    c = max(0, min(cfg.cols - 1, col + dc))
                    v = float(self.grid[r, c])
                    if v < best_val:
                        best_val   = v
                        candidates = [(r, c)]
                    elif v == best_val:
                        candidates.append((r, c))

            best_cell = random.choice(candidates) if candidates else (row, col)

        return self.grid_to_world(*best_cell)

    def get_snapshot(self) -> np.ndarray:
        with self._lock:
            return self.grid.copy()

    # ── Evaporation loop ────────────────────────────────────────────

    def start_evaporation(self):
        self._running = True
        threading.Thread(target=self._evaporate_loop, daemon=True).start()

    def stop_evaporation(self):
        self._running = False

    def _evaporate_loop(self):
        while self._running:
            time.sleep(self.config.tick_interval)
            self.tick()

    def tick(self):
        """Apply one deterministic evaporation step."""
        with self._lock:
            self.grid *= self.config.evaporation_rate

    def deposit_path(
        self,
        lat0: float, lon0: float,
        lat1: float, lon1: float,
        steps: int = 4,
    ):
        """
        Deposit pheromone at `steps` evenly-spaced points between two positions.
        Call this with (prev_lat, prev_lon, curr_lat, curr_lon) each tick.
        """
        for i in range(steps + 1):
            t = i / steps
            self.deposit(lat0 + t * (lat1 - lat0), lon0 + t * (lon1 - lon0))

    def reset(self):
        """Zero out the pheromone grid (called after Lloyd repartition)."""
        with self._lock:
            self.grid[:] = 0.0


# ── Redis stub ──────────────────────────────────────────────────────

class RedisPheromoneGrid:
    """
    Drop-in replacement for InMemoryPheromoneGrid using Redis.
    Implement these methods and swap in swarm_main.py — nothing else changes.

    Hints:
      - deposit      → HINCRBYFLOAT  (atomic per-cell increment)
      - evaporation  → Lua script that multiplies all hash fields atomically
      - get_snapshot → HGETALL + reshape to numpy array
    """
    def __init__(self, config: GridConfig, redis_url: str = "redis://localhost:6379"):
        raise NotImplementedError("Implement RedisPheromoneGrid to go distributed.")

    def world_to_grid(self, lat, lon): ...
    def grid_to_world(self, row, col): ...
    def deposit(self, lat, lon, strength=None): ...
    def get_value(self, lat, lon): ...
    def get_gradient(self, lat, lon, radius=2): ...
    def get_snapshot(self): ...
    def start_evaporation(self): ...
    def stop_evaporation(self): ...
