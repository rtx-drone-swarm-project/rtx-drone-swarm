"""Scenario-shaped probability priors for PMV search.

The helpers in this module intentionally use only pre-launch context:
mission bounds, scenario profile names, and optional explicit SAR clues. The
benchmark runner must not pass hidden target samples or generation internals.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from app.algorithms.base import DETECTION_RADIUS


BOUNDARY_BAND_DEG = 4 * DETECTION_RADIUS
CORRIDOR_HALFWIDTH_DEG = 4 * DETECTION_RADIUS


def build_prior(
    bounds: dict[str, float],
    grid: np.ndarray,
    scenario_profile: str,
    scenario_params: dict[str, Any] | None = None,
) -> np.ndarray:
    """Return a normalized flat probability prior aligned with ``grid``.

    ``scenario_params`` is reserved for explicit SAR intelligence supplied by a
    caller, for example a last-known position. Benchmarks deliberately use the
    profile-only fallback so PMV does not receive hidden target locations.
    """
    grid_np = np.asarray(grid, dtype=float)
    if len(grid_np) == 0:
        return np.array([], dtype=float)

    scenario_params = scenario_params or {}
    clue_prior = _explicit_clue_prior(bounds, grid_np, scenario_params)
    if clue_prior is not None:
        return _normalize(clue_prior)

    if scenario_profile in {"edge_targets", "moving_edge_escape"}:
        return _normalize(_edge_prior(bounds, grid_np))
    if scenario_profile == "corridor_route":
        return _normalize(_corridor_prior(bounds, grid_np, scenario_params))
    if scenario_profile in {"clustered_targets", "diverging_group"}:
        return _normalize(_center_prior(bounds, grid_np))
    if scenario_profile == "split_clusters":
        return _normalize(_split_cluster_prior(bounds, grid_np))

    # uniform_random, clustered_drones, wandering_hikers, and unknown future
    # profiles fall back to the uninformative prior.
    return _normalize(np.ones(len(grid_np), dtype=float))


def _normalize(weights: np.ndarray) -> np.ndarray:
    weights = np.asarray(weights, dtype=float)
    weights = np.where(np.isfinite(weights) & (weights > 0), weights, 0.0)
    total = float(weights.sum())
    if total <= 0:
        if len(weights) == 0:
            return weights
        return np.ones(len(weights), dtype=float) / len(weights)
    return weights / total


def _explicit_clue_prior(
    bounds: dict[str, float],
    grid: np.ndarray,
    scenario_params: dict[str, Any],
) -> np.ndarray | None:
    centers: list[tuple[float, float]] = []

    last_known = scenario_params.get("last_known_position")
    if isinstance(last_known, dict) and {"lat", "lon"}.issubset(last_known):
        centers.append((float(last_known["lat"]), float(last_known["lon"])))

    raw_centers = scenario_params.get("cluster_centers")
    if isinstance(raw_centers, (list, tuple)):
        for raw in raw_centers:
            if isinstance(raw, dict) and {"lat", "lon"}.issubset(raw):
                centers.append((float(raw["lat"]), float(raw["lon"])))
            elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
                centers.append((float(raw[0]), float(raw[1])))

    if not centers:
        return None

    sigma = float(
        scenario_params.get(
            "sigma_deg",
            max(_lat_span(bounds), _lon_span(bounds), DETECTION_RADIUS) * 0.18,
        )
    )
    return _gaussian_mixture(grid, centers, max(sigma, DETECTION_RADIUS))


def _edge_prior(bounds: dict[str, float], grid: np.ndarray) -> np.ndarray:
    edge_distance = _distance_to_nearest_edge(bounds, grid)
    # A strong but not singular edge bias keeps a little mass in the interior.
    return 1.0 + 12.0 * np.exp(-edge_distance / max(BOUNDARY_BAND_DEG / 2.0, 1e-12))


def _corridor_prior(
    bounds: dict[str, float],
    grid: np.ndarray,
    scenario_params: dict[str, Any],
) -> np.ndarray:
    start = _point_param(scenario_params.get("corridor_start"))
    end = _point_param(scenario_params.get("corridor_end"))
    if start is None:
        start = (bounds["min_lat"], bounds["min_lon"])
    if end is None:
        end = (bounds["max_lat"], bounds["max_lon"])

    halfwidth = float(scenario_params.get("corridor_halfwidth_deg", CORRIDOR_HALFWIDTH_DEG))
    distances = _distance_to_segment(grid, start, end)
    return 0.05 + np.exp(-0.5 * (distances / max(halfwidth / 2.0, 1e-12)) ** 2)


def _center_prior(bounds: dict[str, float], grid: np.ndarray) -> np.ndarray:
    center = (
        (bounds["min_lat"] + bounds["max_lat"]) / 2.0,
        (bounds["min_lon"] + bounds["max_lon"]) / 2.0,
    )
    sigma = max(_lat_span(bounds), _lon_span(bounds), DETECTION_RADIUS) * 0.28
    return 0.15 + _gaussian_mixture(grid, [center], max(sigma, DETECTION_RADIUS))


def _split_cluster_prior(bounds: dict[str, float], grid: np.ndarray) -> np.ndarray:
    centers = [
        _near_corner(bounds, 1),
        _near_corner(bounds, 2),
    ]
    sigma = max(_lat_span(bounds), _lon_span(bounds), DETECTION_RADIUS) * 0.14
    return 0.05 + _gaussian_mixture(grid, centers, max(sigma, DETECTION_RADIUS))


def _gaussian_mixture(
    grid: np.ndarray,
    centers: list[tuple[float, float]],
    sigma: float,
) -> np.ndarray:
    weights = np.zeros(len(grid), dtype=float)
    for lat, lon in centers:
        dist_sq = (grid[:, 0] - lat) ** 2 + (grid[:, 1] - lon) ** 2
        weights += np.exp(-0.5 * dist_sq / (sigma ** 2))
    return weights


def _distance_to_nearest_edge(bounds: dict[str, float], grid: np.ndarray) -> np.ndarray:
    return np.minimum.reduce(
        [
            grid[:, 0] - bounds["min_lat"],
            bounds["max_lat"] - grid[:, 0],
            grid[:, 1] - bounds["min_lon"],
            bounds["max_lon"] - grid[:, 1],
        ]
    )


def _distance_to_segment(
    grid: np.ndarray,
    start: tuple[float, float],
    end: tuple[float, float],
) -> np.ndarray:
    start_np = np.asarray(start, dtype=float)
    end_np = np.asarray(end, dtype=float)
    segment = end_np - start_np
    denom = float(np.dot(segment, segment))
    if denom <= 1e-18:
        return np.linalg.norm(grid - start_np, axis=1)
    t = np.clip(((grid - start_np) @ segment) / denom, 0.0, 1.0)
    projection = start_np + t[:, np.newaxis] * segment
    return np.linalg.norm(grid - projection, axis=1)


def _point_param(raw: Any) -> tuple[float, float] | None:
    if isinstance(raw, dict) and {"lat", "lon"}.issubset(raw):
        return float(raw["lat"]), float(raw["lon"])
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        return float(raw[0]), float(raw[1])
    return None


def _lat_span(bounds: dict[str, float]) -> float:
    return max(float(bounds["max_lat"]) - float(bounds["min_lat"]), 1e-12)


def _lon_span(bounds: dict[str, float]) -> float:
    return max(float(bounds["max_lon"]) - float(bounds["min_lon"]), 1e-12)


def _near_corner(bounds: dict[str, float], corner_index: int) -> tuple[float, float]:
    corners = [
        (bounds["min_lat"], bounds["min_lon"]),
        (bounds["min_lat"], bounds["max_lon"]),
        (bounds["max_lat"], bounds["min_lon"]),
        (bounds["max_lat"], bounds["max_lon"]),
    ]
    lat, lon = corners[corner_index % len(corners)]
    inset_lat = _lat_span(bounds) * 0.08
    inset_lon = _lon_span(bounds) * 0.08
    return (
        lat + inset_lat if math.isclose(lat, bounds["min_lat"]) else lat - inset_lat,
        lon + inset_lon if math.isclose(lon, bounds["min_lon"]) else lon - inset_lon,
    )
