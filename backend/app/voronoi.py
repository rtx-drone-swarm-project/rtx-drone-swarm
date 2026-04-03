"""
Voronoi/Lloyd coverage algorithm for the backend simulation.

Works directly in lat/lon degree space — no SITL, MAVLink, or NED conversion
required. This is a pure math module used by simulation_loop in main.py.
"""

import numpy as np


def build_search_grid(bounds: dict, n: int = 15) -> np.ndarray:
    """
    Build an n×n grid of [lat, lon] points covering the mission bounds.

    Returns shape (n*n, 2) array of [lat, lon] points.
    """
    lats = np.linspace(bounds["min_lat"], bounds["max_lat"], n)
    lons = np.linspace(bounds["min_lon"], bounds["max_lon"], n)
    ll, lo = np.meshgrid(lats, lons)
    return np.column_stack([ll.ravel(), lo.ravel()])


def lloyd_step(grid_points: np.ndarray, centroids: np.ndarray):
    """
    One iteration of Lloyd's algorithm in 2D lat/lon space.

    Args:
        grid_points: (M, 2) array of [lat, lon] search-area points.
        centroids:   (k, 2) array of current drone positions [lat, lon].

    Returns:
        new_centroids: (k, 2) array — Voronoi centroid for each drone.
        labels:        (M,) int array — which drone each grid point belongs to.
    """
    k = len(centroids)
    # distances[i, j] = distance from grid point i to centroid j
    distances = np.linalg.norm(grid_points[:, np.newaxis] - centroids, axis=2)
    labels = np.argmin(distances, axis=1)

    new_centroids = []
    for i in range(k):
        cluster_pts = grid_points[labels == i]
        if len(cluster_pts) > 0:
            new_centroids.append(cluster_pts.mean(axis=0))
        else:
            # Empty cluster: keep the current centroid
            new_centroids.append(centroids[i])

    return np.array(new_centroids), labels
