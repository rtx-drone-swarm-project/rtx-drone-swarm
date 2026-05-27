"""Markdown report generation for persisted benchmark runs."""

from __future__ import annotations

import csv
import io
import math
from collections import defaultdict
from typing import Any


BASELINE_ALGORITHMS = ("sweep", "voronoi", "vaco", "pso", "apf")
MOVING_PROFILES = {"corridor_route", "wandering_hikers", "moving_edge_escape", "diverging_group"}

SUMMARY_FIELDS = [
    "algorithm",
    "trials",
    "success_rate_pct",
    "partial_success_rate_pct",
    "timeout_rate_pct",
    "total_missed_hikers",
    "mean_targets_found",
    "median_first_find_seconds",
    "p90_first_find_seconds",
    "mean_first_find_seconds",
    "mean_last_find_seconds",
    "mean_coverage_pct",
    "mean_redundant_coverage_pct",
    "mean_coverage_per_drone_second",
    "mean_drone_seconds_total",
    "mean_search_effort_per_find",
    "mean_distance_per_find_m",
    "t50_coverage_reach_pct",
    "mean_t50_coverage_seconds",
    "t80_coverage_reach_pct",
    "mean_t80_coverage_seconds",
    "t95_coverage_reach_pct",
    "mean_t95_coverage_seconds",
]


def build_benchmark_markdown_report(run: dict[str, Any]) -> str:
    """Create a portable Markdown summary from a decoded benchmark run."""
    request = run.get("request") or {}
    trials = run.get("trials") or []
    by_algorithm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trial in trials:
        by_algorithm[str(trial.get("algorithm", ""))].append(trial)

    algorithms = _ordered_algorithms(by_algorithm.keys(), request.get("algorithms"))
    lines = [
        f"# Metrics Report: {run.get('run_id', 'unknown')}",
        "",
        "## Run Metadata",
        "",
        f"- Status: `{run.get('status', 'unknown')}`",
        f"- Created: {run.get('created_at') or '-'}",
        f"- Completed: {run.get('completed_at') or '-'}",
        f"- Scenario profile: `{request.get('scenario_profile', 'uniform_random')}`",
        f"- Iterations: {request.get('iterations', '-')}",
        f"- Drones: {request.get('drone_count', '-')}",
        f"- Targets: {request.get('target_count', '-')}",
        f"- Timeout seconds: {request.get('timeout_seconds', '-')}",
        f"- Completed trials: {run.get('completed_trials', 0)} / {run.get('total_trials', 0)}",
        "",
        "## Algorithm Summary",
        "",
        "| Algorithm | Trials | Success % | Timeout % | Partial Success % | Mean First Find | Mean Coverage % | Mean Targets Found | Mean Distance m |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    summaries = {algorithm: _summarize(rows) for algorithm, rows in by_algorithm.items()}
    for algorithm in algorithms:
        summary = summaries.get(algorithm, {})
        lines.append(
            f"| `{algorithm}` "
            f"| {summary.get('trials', 0)} "
            f"| {_fmt(summary.get('success_rate_pct'))} "
            f"| {_fmt(summary.get('timeout_rate_pct'))} "
            f"| {_fmt(summary.get('partial_success_rate_pct'))} "
            f"| {_fmt(summary.get('mean_first_find_seconds'), 's')} "
            f"| {_fmt(summary.get('mean_coverage_pct'))} "
            f"| {_fmt(summary.get('mean_targets_found'), suffix='', digits=2)} "
            f"| {_fmt(summary.get('mean_distance_m'), suffix='m', digits=1)} |"
        )

    lines.extend([
        "",
        "## PMV Comparison",
        "",
    ])
    pmv = summaries.get("pmv")
    if pmv is None:
        lines.append("- `pmv` was not included in this run.")
    else:
        baselines = [algorithm for algorithm in BASELINE_ALGORITHMS if algorithm in summaries]
        if not baselines:
            lines.append("- No configured baseline algorithms were included with `pmv`.")
        for baseline in baselines:
            other = summaries[baseline]
            lines.append(
                f"- `pmv` vs `{baseline}`: "
                f"success {_delta(pmv, other, 'success_rate_pct', 'pp')}, "
                f"coverage {_delta(pmv, other, 'mean_coverage_pct', 'pp')}, "
                f"targets found {_delta(pmv, other, 'mean_targets_found', '')}, "
                f"mean first find {_delta(pmv, other, 'mean_first_find_seconds', 's', lower_is_better=True)}."
            )

    lines.extend([
        "",
        "## Caveats",
        "",
        "- Trials are paired by scenario seed within each iteration.",
        "- First-find averages ignore trials where no hiker was found.",
        "- PMV benchmark priors are profile-based; hidden target positions are not passed to PMV.",
        "- Use the raw CSV export for spreadsheet-level inspection.",
        "",
    ])
    return "\n".join(lines)


def build_benchmark_report(run: dict[str, Any]) -> dict[str, Any]:
    """Return chart-ready Metrics report data from raw persisted trial rows."""
    request = run.get("request") or {}
    trials = run.get("trials") or []
    by_algorithm = _group_by_algorithm(trials)
    algorithms = _ordered_algorithms(by_algorithm.keys(), request.get("algorithms"))
    summaries = {algorithm: _summarize(rows) for algorithm, rows in by_algorithm.items()}
    summary_rows = [
        {"algorithm": algorithm, **summaries.get(algorithm, {"trials": 0})}
        for algorithm in algorithms
    ]

    scenario_profiles = sorted({
        str(trial.get("scenario_profile") or request.get("scenario_profile") or "uniform_random")
        for trial in trials
    })
    bounds = _first_bounds(trials, request)

    return {
        "run_id": run.get("run_id"),
        "status": run.get("status", "unknown"),
        "created_at": run.get("created_at"),
        "completed_at": run.get("completed_at"),
        "completed_trials": run.get("completed_trials", 0),
        "total_trials": run.get("total_trials", 0),
        "request": request,
        "metadata": {
            "scenario_profiles": scenario_profiles,
            "movement_mix": _movement_mix(scenario_profiles),
            "bounds": bounds,
            "bounds_area_km2": _bounds_area_km2(bounds) if bounds else None,
            "drone_count": _first_number(trials, "drone_count") or request.get("drone_count"),
            "target_count": _first_number(trials, "target_count") or request.get("target_count"),
            "timeout_seconds": _first_number(trials, "timeout_seconds") or request.get("timeout_seconds"),
            "notes": [
                "Trials are paired by scenario seed within each Metrics run.",
                "Near-live charts update after each headless trial row is persisted.",
                "Per-tick coverage and per-hiker find-time arrays are not persisted yet; charts use final trial rows and first/last/average find fields.",
                "PMV benchmark priors are profile-based; hidden target positions are not passed to PMV.",
            ],
        },
        "summary": summary_rows,
        "series": {
            "success_rate_pct": _bar_series(summary_rows, "success_rate_pct"),
            "partial_success_rate_pct": _bar_series(summary_rows, "partial_success_rate_pct"),
            "mean_coverage_pct": _bar_series(summary_rows, "mean_coverage_pct"),
            "median_first_find_seconds": _bar_series(summary_rows, "median_first_find_seconds"),
            "mean_distance_per_find_m": _bar_series(summary_rows, "mean_distance_per_find_m"),
            "coverage_efficiency": _bar_series(summary_rows, "mean_coverage_per_drone_second"),
            "coverage_milestones": [
                {
                    "algorithm": row["algorithm"],
                    "t50_seconds": row.get("mean_t50_coverage_seconds"),
                    "t50_reach_pct": row.get("t50_coverage_reach_pct"),
                    "t80_seconds": row.get("mean_t80_coverage_seconds"),
                    "t80_reach_pct": row.get("t80_coverage_reach_pct"),
                    "t95_seconds": row.get("mean_t95_coverage_seconds"),
                    "t95_reach_pct": row.get("t95_coverage_reach_pct"),
                }
                for row in summary_rows
            ],
            "coverage_vs_targets": _coverage_vs_targets(trials),
            "find_time_distribution": _find_time_distribution(by_algorithm, algorithms),
            "scenario_profile_success": _scenario_profile_success(trials, algorithms),
        },
        "outliers": _outlier_trials(trials),
    }


def build_benchmark_summary_csv(run: dict[str, Any]) -> str:
    """Export one run's computed summary rows as CSV."""
    report = build_benchmark_report(run)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=SUMMARY_FIELDS)
    writer.writeheader()
    for row in report["summary"]:
        writer.writerow({field: row.get(field) for field in SUMMARY_FIELDS})
    return output.getvalue()


def _summarize(rows: list[dict[str, Any]]) -> dict[str, float | int | None]:
    trials = len(rows)
    successes = 0
    timeouts = 0
    missed_hikers = 0
    partial_rates: list[float] = []
    first_find: list[float] = []
    last_find: list[float] = []
    coverage: list[float] = []
    redundant_coverage: list[float] = []
    coverage_efficiency: list[float] = []
    targets_found_values: list[float] = []
    distance: list[float] = []
    drone_seconds: list[float] = []
    search_effort_per_find: list[float] = []
    distance_per_find: list[float] = []
    coverage_milestones = {
        50: {"reached": 0, "times": []},
        80: {"reached": 0, "times": []},
        95: {"reached": 0, "times": []},
    }

    for row in rows:
        found = _number(row.get("targets_found")) or 0.0
        total_targets = _number(row.get("targets_total")) or _number(row.get("target_count")) or 0.0
        if total_targets and found >= total_targets:
            successes += 1
        if row.get("status") == "timeout":
            timeouts += 1
        if total_targets:
            partial_rates.append(100.0 * found / total_targets)
            missed_hikers += max(int(total_targets - found), 0)
        _append_number(first_find, row.get("first_find_seconds"))
        _append_number(last_find, row.get("last_find_seconds"))
        _append_number(coverage, row.get("coverage_pct"))
        _append_number(redundant_coverage, row.get("redundant_coverage_pct"))
        _append_number(coverage_efficiency, row.get("coverage_per_drone_second"))
        _append_number(targets_found_values, row.get("targets_found"))
        _append_number(distance, row.get("total_distance_traveled_m"))
        elapsed = _number(row.get("elapsed_seconds"))
        drone_count = _number(row.get("drone_count"))
        total_distance = _number(row.get("total_distance_traveled_m"))
        if elapsed is not None and drone_count is not None:
            effort = elapsed * drone_count
            drone_seconds.append(effort)
            search_effort_per_find.append(effort / max(found, 1.0))
        if total_distance is not None:
            distance_per_find.append(total_distance / max(found, 1.0))
        for threshold in (50, 80, 95):
            value = _number(row.get(f"time_to_{threshold}_coverage"))
            if value and value > 0:
                coverage_milestones[threshold]["reached"] += 1
                coverage_milestones[threshold]["times"].append(value)

    return {
        "trials": trials,
        "success_rate_pct": 100.0 * successes / trials if trials else None,
        "timeout_rate_pct": 100.0 * timeouts / trials if trials else None,
        "partial_success_rate_pct": _mean(partial_rates),
        "total_missed_hikers": missed_hikers,
        "mean_first_find_seconds": _mean(first_find),
        "median_first_find_seconds": _percentile(first_find, 50),
        "p90_first_find_seconds": _percentile(first_find, 90),
        "mean_last_find_seconds": _mean(last_find),
        "mean_coverage_pct": _mean(coverage),
        "mean_redundant_coverage_pct": _mean(redundant_coverage),
        "mean_coverage_per_drone_second": _mean(coverage_efficiency),
        "mean_targets_found": _mean(targets_found_values),
        "mean_distance_m": _mean(distance),
        "mean_drone_seconds_total": _mean(drone_seconds),
        "mean_search_effort_per_find": _mean(search_effort_per_find),
        "mean_distance_per_find_m": _mean(distance_per_find),
        "t50_coverage_reach_pct": _reach_pct(coverage_milestones[50]["reached"], trials),
        "mean_t50_coverage_seconds": _mean(coverage_milestones[50]["times"]),
        "t80_coverage_reach_pct": _reach_pct(coverage_milestones[80]["reached"], trials),
        "mean_t80_coverage_seconds": _mean(coverage_milestones[80]["times"]),
        "t95_coverage_reach_pct": _reach_pct(coverage_milestones[95]["reached"], trials),
        "mean_t95_coverage_seconds": _mean(coverage_milestones[95]["times"]),
    }


def _group_by_algorithm(trials: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trial in trials:
        algorithm = str(trial.get("algorithm", ""))
        if algorithm:
            grouped[algorithm].append(trial)
    return grouped


def _bar_series(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return [{"algorithm": row["algorithm"], "value": row.get(key)} for row in rows]


def _coverage_vs_targets(trials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for trial in trials:
        found = _number(trial.get("targets_found")) or 0.0
        total = _number(trial.get("targets_total")) or _number(trial.get("target_count")) or 0.0
        if not total:
            continue
        points.append({
            "algorithm": trial.get("algorithm"),
            "scenario_profile": trial.get("scenario_profile"),
            "coverage_pct": _number(trial.get("coverage_pct")),
            "targets_found_pct": 100.0 * found / total,
            "iteration": trial.get("iteration"),
        })
    return points


def _find_time_distribution(
    by_algorithm: dict[str, list[dict[str, Any]]],
    algorithms: list[str],
) -> list[dict[str, Any]]:
    series: list[dict[str, Any]] = []
    for algorithm in algorithms:
        values = [
            value
            for row in by_algorithm.get(algorithm, [])
            if (value := _number(row.get("first_find_seconds"))) is not None
        ]
        series.append({
            "algorithm": algorithm,
            "count": len(values),
            "min": min(values) if values else None,
            "p25": _percentile(values, 25),
            "median": _percentile(values, 50),
            "p75": _percentile(values, 75),
            "p90": _percentile(values, 90),
            "max": max(values) if values else None,
        })
    return series


def _scenario_profile_success(trials: list[dict[str, Any]], algorithms: list[str]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for trial in trials:
        key = (str(trial.get("scenario_profile") or "uniform_random"), str(trial.get("algorithm") or ""))
        buckets[key].append(trial)

    rows: list[dict[str, Any]] = []
    profiles = sorted({profile for profile, _ in buckets})
    for profile in profiles:
        for algorithm in algorithms:
            bucket = buckets.get((profile, algorithm), [])
            if not bucket:
                continue
            summary = _summarize(bucket)
            rows.append({
                "scenario_profile": profile,
                "algorithm": algorithm,
                "trials": len(bucket),
                "success_rate_pct": summary["success_rate_pct"],
                "partial_success_rate_pct": summary["partial_success_rate_pct"],
                "mean_coverage_pct": summary["mean_coverage_pct"],
            })
    return rows


def _outlier_trials(trials: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    def score(row: dict[str, Any]) -> tuple[float, float, float]:
        total = _number(row.get("targets_total")) or _number(row.get("target_count")) or 0.0
        found = _number(row.get("targets_found")) or 0.0
        missed = max(total - found, 0.0)
        elapsed = _number(row.get("elapsed_seconds")) or 0.0
        coverage = _number(row.get("coverage_pct")) or 0.0
        return missed, elapsed, -coverage

    sorted_trials = sorted(trials, key=score, reverse=True)
    fields = [
        "algorithm",
        "iteration",
        "scenario_seed",
        "scenario_profile",
        "status",
        "targets_found",
        "targets_total",
        "coverage_pct",
        "first_find_seconds",
        "last_find_seconds",
        "elapsed_seconds",
    ]
    return [{field: trial.get(field) for field in fields} for trial in sorted_trials[:limit]]


def _ordered_algorithms(algorithms: Any, requested: Any) -> list[str]:
    present = {str(algorithm) for algorithm in algorithms if str(algorithm)}
    ordered: list[str] = []
    if isinstance(requested, list):
        ordered.extend(str(algorithm) for algorithm in requested if str(algorithm) in present)
    for algorithm in sorted(present):
        if algorithm not in ordered:
            ordered.append(algorithm)
    return ordered


def _append_number(bucket: list[float], value: Any) -> None:
    number = _number(value)
    if number is not None:
        bucket.append(number)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * percentile / 100.0
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return sorted_values[int(rank)]
    weight = rank - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _reach_pct(reached: int, trials: int) -> float | None:
    return 100.0 * reached / trials if trials else None


def _first_bounds(trials: list[dict[str, Any]], request: dict[str, Any]) -> dict[str, float] | None:
    for trial in trials:
        bounds = trial.get("bounds")
        if isinstance(bounds, dict) and bounds:
            return bounds
    bounds = request.get("bounds")
    return bounds if isinstance(bounds, dict) and bounds else None


def _first_number(trials: list[dict[str, Any]], field: str) -> float | None:
    for trial in trials:
        value = _number(trial.get(field))
        if value is not None:
            return value
    return None


def _movement_mix(profiles: list[str]) -> dict[str, int]:
    moving = sum(1 for profile in profiles if profile in MOVING_PROFILES)
    return {"moving_profiles": moving, "stationary_profiles": max(len(profiles) - moving, 0)}


def _bounds_area_km2(bounds: dict[str, float]) -> float | None:
    try:
        min_lat = float(bounds["min_lat"])
        max_lat = float(bounds["max_lat"])
        min_lon = float(bounds["min_lon"])
        max_lon = float(bounds["max_lon"])
    except (KeyError, TypeError, ValueError):
        return None
    mean_lat_rad = math.radians((min_lat + max_lat) / 2.0)
    height_km = abs(max_lat - min_lat) * 111.32
    width_km = abs(max_lon - min_lon) * 111.32 * math.cos(mean_lat_rad)
    return height_km * width_km


def _fmt(value: Any, suffix: str = "%", *, digits: int = 1) -> str:
    number = _number(value)
    if number is None:
        return "-"
    return f"{number:.{digits}f}{suffix}"


def _delta(
    left: dict[str, Any],
    right: dict[str, Any],
    key: str,
    suffix: str,
    *,
    lower_is_better: bool = False,
) -> str:
    left_value = _number(left.get(key))
    right_value = _number(right.get(key))
    if left_value is None or right_value is None:
        return "-"
    diff = left_value - right_value
    direction = "better" if (diff < 0 if lower_is_better else diff > 0) else "worse"
    if abs(diff) < 1e-9:
        direction = "even"
    unit = suffix if suffix else ""
    return f"{diff:+.1f}{unit} ({direction})"
