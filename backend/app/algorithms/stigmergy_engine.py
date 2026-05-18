"""
stigmergy_engine.py
-------------------
Pheromone grid for the drone swarm with enhanced features:
- Seeded randomness for reproducible testing
- Improved gradient calculation with exploration bonus
- Heat map generation for visualization
- Thread-safe operations with deterministic tick()

Backend-agnostic: InMemoryPheromoneGrid uses numpy.
Swap for RedisPheromoneGrid to go distributed.
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
    exploration_bonus: float = 0.5    # Bias toward unexplored cells


class InMemoryPheromoneGrid:
    """
    Thread-safe in-memory pheromone grid with enhanced ACO features.

    Key improvements:
    - Seeded RNG for reproducible testing
    - Exploration bonus to prevent premature convergence
    - Heat map export for visualization
    - Deterministic tick() separate from async evaporation loop
    """

    def __init__(self, config: GridConfig, seed: Optional[int] = None):
        self.config   = config
        self.grid     = np.zeros((config.rows, config.cols), dtype=np.float32)
        self._lock    = threading.Lock()
        self._running = False
        self._rng     = random.Random(seed)  # Seeded for reproducibility
        self._tick_count = 0

    # ══════════════════════════════════════════════════════════════
    # COORDINATE HELPERS
    # ══════════════════════════════════════════════════════════════

    def world_to_grid(self, lat: float, lon: float) -> Tuple[int, int]:
        """Convert GPS coordinates to grid indices."""
        cfg = self.config
        row = int((lat - cfg.lat_min) / (cfg.lat_max - cfg.lat_min) * (cfg.rows - 1))
        col = int((lon - cfg.lon_min) / (cfg.lon_max - cfg.lon_min) * (cfg.cols - 1))
        return max(0, min(cfg.rows - 1, row)), max(0, min(cfg.cols - 1, col))

    def grid_to_world(self, row: int, col: int) -> Tuple[float, float]:
        """Convert grid indices to GPS coordinates."""
        cfg = self.config
        lat = cfg.lat_min + (row / (cfg.rows - 1)) * (cfg.lat_max - cfg.lat_min)
        lon = cfg.lon_min + (col / (cfg.cols - 1)) * (cfg.lon_max - cfg.lon_min)
        return lat, lon

    # ══════════════════════════════════════════════════════════════
    # CORE OPERATIONS
    # ══════════════════════════════════════════════════════════════

    def deposit(self, lat: float, lon: float, strength: Optional[float] = None):
        """Deposit pheromone at a GPS location."""
        s = strength if strength is not None else self.config.deposit_strength
        row, col = self.world_to_grid(lat, lon)
        with self._lock:
            self.grid[row, col] += s

    def get_value(self, lat: float, lon: float) -> float:
        """Get pheromone concentration at a GPS location."""
        row, col = self.world_to_grid(lat, lon)
        with self._lock:
            return float(self.grid[row, col])

    def get_gradient(
        self, 
        lat: float, 
        lon: float, 
        radius: int = 3,
        rng: Optional[random.Random] = None
    ) -> Tuple[float, float]:
        """
        Return the GPS coordinates of the least-visited neighbor cell.
        
        Enhanced with:
        - Exploration bonus: slightly prefer completely unvisited cells
        - Seeded randomness: use mission RNG if provided for reproducibility
        - Larger default radius: 3 cells instead of 2 for better exploration
        
        Args:
            lat: Current latitude
            lon: Current longitude
            radius: Search radius in grid cells (default 3)
            rng: Optional seeded random number generator
            
        Returns:
            (target_lat, target_lon) tuple for least-visited neighbor
        """
        row, col = self.world_to_grid(lat, lon)
        cfg = self.config
        rng = rng if rng is not None else self._rng

        with self._lock:
            best_score: float = float('inf')
            candidates: List[Tuple[int, int]] = []

            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    # Skip the current cell
                    if dr == 0 and dc == 0:
                        continue
                    
                    r = max(0, min(cfg.rows - 1, row + dr))
                    c = max(0, min(cfg.cols - 1, col + dc))
                    
                    pheromone = float(self.grid[r, c])
                    
                    # Exploration bonus: unvisited cells get a small advantage
                    exploration_bonus = 0 if pheromone > 0.01 else -cfg.exploration_bonus
                    score = pheromone + exploration_bonus
                    
                    if score < best_score:
                        best_score = score
                        candidates = [(r, c)]
                    elif score == best_score:
                        candidates.append((r, c))

            # Seeded random choice for reproducibility
            if candidates:
                best_cell = rng.choice(candidates)
            else:
                # Fallback to current position if no candidates found
                best_cell = (row, col)

        return self.grid_to_world(*best_cell)

    def get_snapshot(self) -> np.ndarray:
        """Get a copy of the current pheromone grid for visualization."""
        with self._lock:
            return self.grid.copy()
    
    def get_heatmap(self) -> np.ndarray:
        """
        Get a normalized heatmap of the pheromone grid (0-1 range).
        Useful for visualization and debugging.
        """
        with self._lock:
            snapshot = self.grid.copy()
            max_val = snapshot.max()
            if max_val > 0:
                return snapshot / max_val
            return snapshot

    # ══════════════════════════════════════════════════════════════
    # EVAPORATION SYSTEM
    # ══════════════════════════════════════════════════════════════

    def start_evaporation(self):
        """Start the background evaporation thread."""
        if self._running:
            return
        self._running = True
        threading.Thread(target=self._evaporate_loop, daemon=True).start()

    def stop_evaporation(self):
        """Stop the background evaporation thread."""
        self._running = False

    def _evaporate_loop(self):
        """Background thread that calls tick() at regular intervals."""
        while self._running:
            time.sleep(self.config.tick_interval)
            self.tick()

    def tick(self):
        """
        Apply one deterministic evaporation step.
        Can be called manually for deterministic testing,
        or automatically by the background thread.
        """
        with self._lock:
            self.grid *= self.config.evaporation_rate
            self._tick_count += 1

    # ══════════════════════════════════════════════════════════════
    # BATCH OPERATIONS
    # ══════════════════════════════════════════════════════════════

    def deposit_path(
        self,
        lat0: float, lon0: float,
        lat1: float, lon1: float,
        steps: int = 4,
    ):
        """
        Deposit pheromone along a path at evenly-spaced points.
        Call with (prev_lat, prev_lon, curr_lat, curr_lon) each tick.
        
        Args:
            lat0, lon0: Starting GPS coordinates
            lat1, lon1: Ending GPS coordinates
            steps: Number of interpolation points (default 4)
        """
        for i in range(steps + 1):
            t = i / steps
            self.deposit(
                lat0 + t * (lat1 - lat0),
                lon0 + t * (lon1 - lon0)
            )

    def deposit_area(self, lat: float, lon: float, radius: int = 1):
        """
        Deposit pheromone in a circular area around a GPS location.
        Useful for marking confirmed target locations.
        
        Args:
            lat, lon: Center GPS coordinates
            radius: Radius in grid cells
        """
        row, col = self.world_to_grid(lat, lon)
        cfg = self.config
        
        with self._lock:
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    if dr*dr + dc*dc <= radius*radius:
                        r = max(0, min(cfg.rows - 1, row + dr))
                        c = max(0, min(cfg.cols - 1, col + dc))
                        self.grid[r, c] += cfg.deposit_strength

    def reset(self):
        """
        Zero out the pheromone grid.
        Called after Lloyd repartition to start fresh exploration.
        """
        with self._lock:
            self.grid[:] = 0.0
            self._tick_count = 0

    # ══════════════════════════════════════════════════════════════
    # STATISTICS & DEBUGGING
    # ══════════════════════════════════════════════════════════════

    def get_statistics(self) -> dict:
        """Get statistical summary of the pheromone grid."""
        with self._lock:
            return {
                "tick_count": self._tick_count,
                "total_pheromone": float(self.grid.sum()),
                "max_concentration": float(self.grid.max()),
                "mean_concentration": float(self.grid.mean()),
                "visited_cells": int((self.grid > 0.01).sum()),
                "total_cells": self.grid.size,
                "coverage_percent": float((self.grid > 0.01).sum() / self.grid.size * 100),
            }


# ══════════════════════════════════════════════════════════════════
# REDIS STUB (For Future Distributed Implementation)
# ══════════════════════════════════════════════════════════════════

class RedisPheromoneGrid:
    """
    Drop-in replacement for InMemoryPheromoneGrid using Redis.
    Implement these methods and swap — nothing else changes.

    Implementation hints:
      - Use Redis hashes: key = "phero_grid", field = "{row}:{col}"
      - deposit      → HINCRBYFLOAT (atomic increment)
      - evaporation  → Lua script that multiplies all hash fields
      - get_snapshot → HGETALL + reshape to numpy array
      - tick_count   → separate Redis key for synchronization
    """
    
    def __init__(
        self, 
        config: GridConfig, 
        redis_url: str = "redis://localhost:6379",
        seed: Optional[int] = None
    ):
        raise NotImplementedError("Implement RedisPheromoneGrid for distributed swarms.")

    def world_to_grid(self, lat, lon): ...
    def grid_to_world(self, row, col): ...
    def deposit(self, lat, lon, strength=None): ...
    def get_value(self, lat, lon): ...
    def get_gradient(self, lat, lon, radius=3, rng=None): ...
    def get_snapshot(self): ...
    def get_heatmap(self): ...
    def start_evaporation(self): ...
    def stop_evaporation(self): ...
    def tick(self): ...
    def deposit_path(self, lat0, lon0, lat1, lon1, steps=4): ...
    def deposit_area(self, lat, lon, radius=1): ...
    def reset(self): ...
    def get_statistics(self): ...