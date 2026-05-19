import math
from typing import Any

import numpy as np


DEFAULT_TARGET_CELL_SIZE_M = 100.0
MIN_GRID_ROWS = 5
MIN_GRID_COLS = 5
MAX_GRID_ROWS = 60
MAX_GRID_COLS = 60


def _validate_bounds(bounds: dict[str, Any]) -> dict[str, float]:
    required = {"min_lat", "max_lat", "min_lon", "max_lon"}
    missing = required - set(bounds.keys())
    if missing:
        raise ValueError(f"bounds missing required keys: {sorted(missing)}")

    min_lat = float(bounds["min_lat"])
    max_lat = float(bounds["max_lat"])
    min_lon = float(bounds["min_lon"])
    max_lon = float(bounds["max_lon"])

    values = np.array([min_lat, max_lat, min_lon, max_lon], dtype=float)
    if not np.all(np.isfinite(values)):
        raise ValueError("bounds values must be finite numbers")

    if min_lat >= max_lat:
        raise ValueError("bounds min_lat must be less than max_lat")
    if min_lon >= max_lon:
        raise ValueError("bounds min_lon must be less than max_lon")

    return {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
    }


def estimate_bounds_size_meters(bounds: dict[str, Any]) -> tuple[float, float]:
    """
    Estimate the physical height and width of a lat/lon rectangle in meters.

    Returns:
        (height_m, width_m)
    """
    b = _validate_bounds(bounds)

    mid_lat = (b["min_lat"] + b["max_lat"]) / 2.0

    meters_per_degree_lat = 111_320.0
    meters_per_degree_lon = 111_320.0 * math.cos(math.radians(mid_lat))

    height_m = abs(b["max_lat"] - b["min_lat"]) * meters_per_degree_lat
    width_m = abs(b["max_lon"] - b["min_lon"]) * meters_per_degree_lon

    return height_m, width_m


def choose_grid_shape(
    bounds: dict[str, Any],
    target_cell_size_m: float = DEFAULT_TARGET_CELL_SIZE_M,
    min_rows: int = MIN_GRID_ROWS,
    min_cols: int = MIN_GRID_COLS,
    max_rows: int = MAX_GRID_ROWS,
    max_cols: int = MAX_GRID_COLS,
) -> tuple[int, int]:
    """
    Choose a grid shape based on the physical size of the search area.

    A wide search area gets more columns.
    A tall search area gets more rows.
    """
    if target_cell_size_m <= 0:
        raise ValueError("target_cell_size_m must be positive")

    height_m, width_m = estimate_bounds_size_meters(bounds)

    rows = math.ceil(height_m / target_cell_size_m)
    cols = math.ceil(width_m / target_cell_size_m)

    rows = max(min_rows, min(rows, max_rows))
    cols = max(min_cols, min(cols, max_cols))

    return rows, cols


def build_search_grid(
    bounds: dict[str, Any],
    target_cell_size_m: float = DEFAULT_TARGET_CELL_SIZE_M,
    min_rows: int = MIN_GRID_ROWS,
    min_cols: int = MIN_GRID_COLS,
    max_rows: int = MAX_GRID_ROWS,
    max_cols: int = MAX_GRID_COLS,
) -> tuple[np.ndarray, tuple[int, int]]:
    """
    Build a flexible rectangular search grid from mission bounds.

    The search area is divided into rows x cols cells based on the target
    cell size in meters. The returned grid contains the center point of each
    cell as [lat, lon].

    Returns:
        search_grid:
            Shape (rows * cols, 2), flat array of [lat, lon] cell centers.

        grid_shape:
            Tuple (rows, cols). Use this for probability_grid,
            operator_label_grid, and searchable_mask.

    Flattening convention:
        flat_index = row * cols + col
        row = latitude direction
        col = longitude direction
    """
    b = _validate_bounds(bounds)

    rows, cols = choose_grid_shape(
        b,
        target_cell_size_m=target_cell_size_m,
        min_rows=min_rows,
        min_cols=min_cols,
        max_rows=max_rows,
        max_cols=max_cols,
    )

    lat_edges = np.linspace(b["min_lat"], b["max_lat"], rows + 1)
    lon_edges = np.linspace(b["min_lon"], b["max_lon"], cols + 1)

    lat_centers = (lat_edges[:-1] + lat_edges[1:]) / 2.0
    lon_centers = (lon_edges[:-1] + lon_edges[1:]) / 2.0

    lat_grid, lon_grid = np.meshgrid(lat_centers, lon_centers, indexing="ij")

    search_grid = np.column_stack([lat_grid.ravel(), lon_grid.ravel()])

    return search_grid, (rows, cols)