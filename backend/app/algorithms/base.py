from typing import List, Dict, Tuple
import numpy as np
import math

def build_search_grid(bounds: dict, n: int = 15) -> np.ndarray:
    """
    Build an n×n grid of [lat, lon] points covering the mission bounds.
    Returns shape (n*n, 2) array of [lat, lon] points.
    """
    lats = np.linspace(bounds["min_lat"], bounds["max_lat"], n)
    lons = np.linspace(bounds["min_lon"], bounds["max_lon"], n)
    ll, lo = np.meshgrid(lats, lons)
    return np.column_stack([ll.ravel(), lo.ravel()])

class BaseSearchAlgorithm:
    def initialize(self, mission: dict) -> None:
        """Run once when the mission starts (generate grids or waypoints)"""
        pass

    def get_target_waypoints(self, mission: dict, free_drones: List[dict]) -> Dict[str, Tuple[float, float]]:
        """Run every simulation tick to get the next target coordinate for each free drone."""
        raise NotImplementedError("Every algorithm must implement get_target_waypoints()")