from typing import List, Dict, Tuple
import numpy as np
import math
from app.models import Mission

# Distance (degrees) within which a drone detects a target.
# Algorithms use this for sweep row density.  simulation.py imports from here
# so both always use the same value.
DETECTION_RADIUS = 0.002

def build_search_grid(bounds: dict, n: int = 15) -> np.ndarray:
    """
    Build an n×n grid of [lat, lon] points covering the mission bounds.
    Returns shape (n*n, 2) array of [lat, lon] points.
    Used by Voronoi/APF algorithms and as the legacy coverage grid.
    """
    lats = np.linspace(bounds["min_lat"], bounds["max_lat"], n)
    lons = np.linspace(bounds["min_lon"], bounds["max_lon"], n)
    ll, lo = np.meshgrid(lats, lons)
    return np.column_stack([ll.ravel(), lo.ravel()])


def build_dense_coverage_grid(bounds: dict) -> np.ndarray:
    """Dense grid at DETECTION_RADIUS spacing for accurate area-coverage measurement.

    Each cell represents a DETECTION_RADIUS × DETECTION_RADIUS patch of ground.
    Coverage % = (cells visited within DETECTION_RADIUS of any drone) / total cells.
    This is far more accurate than the sparse 15×15 grid, whose checkpoints are
    ~0.007° apart — 3.5× DETECTION_RADIUS — so the sweep algorithm can cover 100%
    of the area while marking only ~15% on the old metric.

    The max bound is always included as an explicit endpoint so non-multiple
    search areas (e.g. 0.0139° wide) do not leave a gap at the far edge.
    """
    def _axis(min_val: float, max_val: float) -> np.ndarray:
        pts = np.arange(min_val, max_val, DETECTION_RADIUS)
        if len(pts) == 0 or not np.isclose(pts[-1], max_val):
            pts = np.append(pts, max_val)
        return pts

    lats = _axis(bounds["min_lat"], bounds["max_lat"])
    lons = _axis(bounds["min_lon"], bounds["max_lon"])
    ll, lo = np.meshgrid(lats, lons)
    return np.column_stack([ll.ravel(), lo.ravel()])

class BaseSearchAlgorithm:
    def initialize(self, mission: Mission) -> None:
        """Run once when the mission starts (generate grids or waypoints)"""
        pass

    def get_target_waypoints(self, mission: Mission, free_drones: List[dict]) -> Dict[str, Tuple[float, float]]:
        """Run every simulation tick to get the next target coordinate for each free drone."""
        raise NotImplementedError("Every algorithm must implement get_target_waypoints()")