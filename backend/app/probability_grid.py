"""Utilities for building a mission probability grid from operator labels."""

from __future__ import annotations

from typing import Literal

import numpy as np

RegionLabel = Literal[
    "very_unlikely",
    "unlikely",
    "normal",
    "likely",
    "very_likely",
    "excluded",
]

REGION_LABEL_CODES: dict[RegionLabel, int] = {
    "very_unlikely": 0,
    "unlikely": 1,
    "normal": 2,
    "likely": 3,
    "very_likely": 4,
    "excluded": 5,
}

REGION_CODE_MULTIPLIERS = np.array(
    [
        0.25,  # very_unlikely
        0.5,   # unlikely
        1.0,   # normal
        2.0,   # likely
        4.0,   # very_likely
        0.0,   # excluded
    ],
    dtype=float,
)

NORMAL_CODE = REGION_LABEL_CODES["normal"]
EXCLUDED_CODE = REGION_LABEL_CODES["excluded"]


def create_operator_label_grid(rows: int, cols: int) -> np.ndarray:
    """Create a label-code grid initialized to the normal region label."""
    return np.full((rows, cols), NORMAL_CODE, dtype=np.uint8)


def create_searchable_mask(rows: int, cols: int) -> np.ndarray:
    """Create a boolean searchable mask for the configured grid shape."""
    return np.ones((rows, cols), dtype=bool)


def _validate_grid_shape(grid_shape: tuple[int, int]) -> tuple[int, int]:
    if len(grid_shape) != 2:
        raise ValueError("grid_shape must be a 2-item tuple of (rows, cols)")
    rows, cols = grid_shape
    if rows <= 0 or cols <= 0:
        raise ValueError("grid_shape rows and cols must be positive")
    return rows, cols


def _operator_label_grid_to_multiplier_grid(operator_label_grid: np.ndarray) -> np.ndarray:
    labels = np.asarray(operator_label_grid)

    if labels.ndim != 2:
        raise ValueError("operator_label_grid must be a 2D grid")
    if not np.issubdtype(labels.dtype, np.integer):
        raise ValueError("operator_label_grid must contain integer label codes")
    if np.any(labels < 0) or np.any(labels >= len(REGION_CODE_MULTIPLIERS)):
        raise ValueError("operator_label_grid contains invalid label codes")

    return REGION_CODE_MULTIPLIERS[labels]


def apply_operator_label_grid(
    score_grid: np.ndarray,
    searchable_mask: np.ndarray,
    operator_label_grid: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply operator label weights and exclusions to the score grid."""
    scores = np.asarray(score_grid, dtype=float).copy()
    searchable = np.asarray(searchable_mask, dtype=bool).copy()
    labels = np.asarray(operator_label_grid, dtype=np.uint8)

    if scores.shape != searchable.shape or scores.shape != labels.shape:
        raise ValueError("score_grid, searchable_mask, and operator_label_grid must have the same shape")

    operator_multiplier_grid = _operator_label_grid_to_multiplier_grid(labels)

    searchable &= labels != EXCLUDED_CODE
    scores *= operator_multiplier_grid
    scores[~searchable] = 0.0

    return scores, searchable


def smooth_probability_grid(
    score_grid: np.ndarray,
    searchable_mask: np.ndarray,
    iterations: int,
) -> np.ndarray:
    """Smooth a score grid with local neighbor averaging while preserving exclusions."""
    if iterations < 0:
        raise ValueError("iterations must be non-negative")

    scores = np.asarray(score_grid, dtype=float).copy()
    searchable = np.asarray(searchable_mask, dtype=bool)

    if scores.shape != searchable.shape:
        raise ValueError("score_grid and searchable_mask must have the same shape")

    scores[~searchable] = 0.0
    if iterations == 0:
        return scores

    for _ in range(iterations):
        padded_scores = np.pad(scores, 1, mode="constant", constant_values=0.0)
        padded_mask = np.pad(searchable.astype(float), 1, mode="constant", constant_values=0.0)

        neighbor_sum = np.zeros_like(scores, dtype=float)
        neighbor_count = np.zeros_like(scores, dtype=float)

        for row_offset in range(3):
            for col_offset in range(3):
                neighbor_sum += padded_scores[
                    row_offset:row_offset + scores.shape[0],
                    col_offset:col_offset + scores.shape[1],
                ]
                neighbor_count += padded_mask[
                    row_offset:row_offset + scores.shape[0],
                    col_offset:col_offset + scores.shape[1],
                ]

        next_scores = np.zeros_like(scores, dtype=float)
        active_cells = searchable & (neighbor_count > 0)
        next_scores[active_cells] = neighbor_sum[active_cells] / neighbor_count[active_cells]
        scores = next_scores

    scores[~searchable] = 0.0
    return scores


def normalize_probability_grid(
    score_grid: np.ndarray,
    searchable_mask: np.ndarray,
) -> np.ndarray:
    """Normalize scores to probabilities across searchable cells."""
    scores = np.asarray(score_grid, dtype=float).copy()
    searchable = np.asarray(searchable_mask, dtype=bool)

    if scores.shape != searchable.shape:
        raise ValueError("score_grid and searchable_mask must have the same shape")

    scores[~searchable] = 0.0
    total = float(scores.sum())
    if total > 0.0:
        return scores / total

    if not np.any(searchable):
        return np.zeros_like(scores, dtype=float)

    normalized = np.zeros_like(scores, dtype=float)
    normalized[searchable] = 1.0 / float(np.count_nonzero(searchable))
    return normalized


def rectangle_bounds_to_grid_mask(
    search_grid: np.ndarray,
    grid_shape: tuple[int, int] | list[int],
    rect_bounds: dict,
) -> np.ndarray:
    """
    Map a lat/lon rectangle to a boolean mask over the discrete search grid.

    Assumes search_grid was built with the convention:
        search_grid shape = (rows * cols, 2)
        search_grid[:, 0] = latitude
        search_grid[:, 1] = longitude

    Assumes flattening order:
        flat_index = row * cols + col
        row = latitude index
        col = longitude index
    """
    required_keys = {"min_lat", "max_lat", "min_lon", "max_lon"}
    missing = required_keys - set(rect_bounds.keys())
    if missing:
        raise ValueError(f"rect_bounds missing required keys: {sorted(missing)}")

    rows, cols = _validate_grid_shape(tuple(grid_shape))
    flat_grid = np.asarray(search_grid, dtype=float)

    if flat_grid.shape != (rows * cols, 2):
        raise ValueError("search_grid must have shape (rows * cols, 2) matching grid_shape")

    lat_a = float(rect_bounds["min_lat"])
    lat_b = float(rect_bounds["max_lat"])
    lon_a = float(rect_bounds["min_lon"])
    lon_b = float(rect_bounds["max_lon"])

    values = np.array([lat_a, lat_b, lon_a, lon_b], dtype=float)
    if not np.all(np.isfinite(values)):
        raise ValueError("rect_bounds values must be finite numbers")

    min_lat = min(lat_a, lat_b)
    max_lat = max(lat_a, lat_b)
    min_lon = min(lon_a, lon_b)
    max_lon = max(lon_a, lon_b)

    lats = flat_grid[:, 0]
    lons = flat_grid[:, 1]

    grid_min_lat = float(np.min(lats))
    grid_max_lat = float(np.max(lats))
    grid_min_lon = float(np.min(lons))
    grid_max_lon = float(np.max(lons))

    intersects_grid = not (
        max_lat < grid_min_lat
        or min_lat > grid_max_lat
        or max_lon < grid_min_lon
        or min_lon > grid_max_lon
    )

    if not intersects_grid:
        return np.zeros((rows, cols), dtype=bool)

    matches = (
        (lats >= min_lat)
        & (lats <= max_lat)
        & (lons >= min_lon)
        & (lons <= max_lon)
    )

    return matches.reshape((rows, cols))


def build_probability_grid(
    grid_shape: tuple[int, int],
    operator_label_grid: np.ndarray | None = None,
    searchable_mask: np.ndarray | None = None,
    smoothing_iterations: int = 1,
) -> tuple[np.ndarray, np.ndarray]:
    """Build a 2D probability grid and the effective searchable mask."""
    rows, cols = _validate_grid_shape(grid_shape)

    labels = (
        create_operator_label_grid(rows, cols)
        if operator_label_grid is None
        else np.asarray(operator_label_grid, dtype=np.uint8).copy()
    )
    searchable = (
        create_searchable_mask(rows, cols)
        if searchable_mask is None
        else np.asarray(searchable_mask, dtype=bool).copy()
    )

    if labels.shape != (rows, cols):
        raise ValueError("operator_label_grid must match grid_shape")
    if searchable.shape != (rows, cols):
        raise ValueError("searchable_mask must match grid_shape")

    score_grid = np.ones((rows, cols), dtype=float)
    adjusted_scores, adjusted_searchable_mask = apply_operator_label_grid(
        score_grid=score_grid,
        searchable_mask=searchable,
        operator_label_grid=labels,
    )
    smoothed_scores = smooth_probability_grid(
        score_grid=adjusted_scores,
        searchable_mask=adjusted_searchable_mask,
        iterations=smoothing_iterations,
    )
    probability_grid = normalize_probability_grid(
        score_grid=smoothed_scores,
        searchable_mask=adjusted_searchable_mask,
    )
    return probability_grid, adjusted_searchable_mask
