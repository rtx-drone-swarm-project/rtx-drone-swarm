"""Markdown report generation for persisted benchmark runs."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


BASELINE_ALGORITHMS = ("sweep", "voronoi", "vaco", "pso", "apf")


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


def _summarize(rows: list[dict[str, Any]]) -> dict[str, float | int | None]:
    trials = len(rows)
    successes = 0
    timeouts = 0
    partial_rates: list[float] = []
    first_find: list[float] = []
    coverage: list[float] = []
    targets_found_values: list[float] = []
    distance: list[float] = []

    for row in rows:
        found = _number(row.get("targets_found")) or 0.0
        total_targets = _number(row.get("targets_total")) or _number(row.get("target_count")) or 0.0
        if total_targets and found >= total_targets:
            successes += 1
        if row.get("status") == "timeout":
            timeouts += 1
        if total_targets:
            partial_rates.append(100.0 * found / total_targets)
        _append_number(first_find, row.get("first_find_seconds"))
        _append_number(coverage, row.get("coverage_pct"))
        _append_number(targets_found_values, row.get("targets_found"))
        _append_number(distance, row.get("total_distance_traveled_m"))

    return {
        "trials": trials,
        "success_rate_pct": 100.0 * successes / trials if trials else None,
        "timeout_rate_pct": 100.0 * timeouts / trials if trials else None,
        "partial_success_rate_pct": _mean(partial_rates),
        "mean_first_find_seconds": _mean(first_find),
        "mean_coverage_pct": _mean(coverage),
        "mean_targets_found": _mean(targets_found_values),
        "mean_distance_m": _mean(distance),
    }


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
