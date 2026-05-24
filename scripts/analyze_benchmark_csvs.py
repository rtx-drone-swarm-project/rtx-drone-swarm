"""Analyze benchmark CSV exports and generate split CSVs, SVG charts, and Markdown.

Usage:
    python scripts/analyze_benchmark_csvs.py backend/data/metrics_runs/<run-dir>
"""

from __future__ import annotations

import argparse
import csv
import html
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


ALGORITHM_ORDER = ["voronoi", "voronoi_aco", "vaco", "apf", "sweep", "pso", "pmv"]
RAW_PREFIX = "raw_"

STATIONARY_PROFILES = {
    "uniform_random",
    "clustered_targets",
    "edge_targets",
    "split_clusters",
    "clustered_drones",
}
MOVING_PROFILES = {
    "wandering_hikers",
    "corridor_route",
    "moving_edge_escape",
    "diverging_group",
}
PAIRED_REFERENCE_ALGORITHM = "pmv"
COVERAGE_MILESTONES = (50, 80, 95)


def _read_rows(input_dir: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(input_dir.glob(f"{RAW_PREFIX}*.csv")):
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                row.setdefault("source_csv", path.name)
                if not row.get("scenario_profile"):
                    row["scenario_profile"] = path.stem.removeprefix(RAW_PREFIX)
                rows.append(row)
    if not rows:
        raise SystemExit(f"No raw CSVs found in {input_dir}")
    return rows


def _float(row: dict[str, str], key: str) -> float | None:
    value = row.get(key)
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if math.isnan(parsed):
        return None
    return parsed


def _mean(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _percentile(values: list[float], p: int) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    idx = max(0, math.ceil(p / 100 * len(sorted_values)) - 1)
    return sorted_values[idx]


def _fmt(value: float | None, digits: int = 1, suffix: str = "") -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}{suffix}"


def _milestone_reach_rate(rows: list[dict[str, str]], key: str) -> tuple[float | None, float | None]:
    """Return (reach_rate_pct, mean_seconds_for_trials_that_reached) for a coverage milestone."""
    total = len(rows)
    if not total:
        return None, None
    reached: list[float] = []
    for row in rows:
        value = _float(row, key)
        if value is None or value <= 0:
            continue
        reached.append(value)
    reach_rate = 100.0 * len(reached) / total
    return reach_rate, _mean(reached)


def _drone_count(row: dict[str, str]) -> float:
    value = _float(row, "drone_count")
    return value or 0.0


def _elapsed_or_timeout_seconds(row: dict[str, str]) -> float:
    value = _float(row, "elapsed_seconds")
    if value:
        return value
    timeout = _float(row, "timeout_seconds")
    return timeout or 0.0


def _group_rows(rows: list[dict[str, str]], *keys: str) -> dict[tuple[str, ...], list[dict[str, str]]]:
    grouped: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row.get(key, "") for key in keys)].append(row)
    return dict(grouped)


def _summarize(rows: list[dict[str, str]]) -> dict[str, float | int | None]:
    total = len(rows)
    successes = 0
    timeouts = 0
    partial_rates: list[float] = []
    first_find: list[float] = []
    coverage: list[float] = []
    redundant_coverage: list[float] = []
    distance: list[float] = []
    targets_found: list[float] = []
    coverage_efficiency: list[float] = []
    drone_seconds_total: list[float] = []
    search_effort_per_find: list[float] = []
    distance_per_find: list[float] = []

    for row in rows:
        found = _float(row, "targets_found") or 0.0
        total_targets = _float(row, "targets_total") or _float(row, "target_count") or 0.0
        if total_targets and found >= total_targets:
            successes += 1
        if row.get("status") == "timeout":
            timeouts += 1
        if total_targets:
            partial_rates.append(100.0 * found / total_targets)
        for key, bucket in [
            ("first_find_seconds", first_find),
            ("coverage_pct", coverage),
            ("redundant_coverage_pct", redundant_coverage),
            ("total_distance_traveled_m", distance),
            ("targets_found", targets_found),
            ("coverage_per_drone_second", coverage_efficiency),
        ]:
            value = _float(row, key)
            if value is not None:
                bucket.append(value)

        drones = _drone_count(row)
        elapsed = _elapsed_or_timeout_seconds(row)
        if drones > 0 and elapsed > 0:
            ds_total = drones * elapsed
            drone_seconds_total.append(ds_total)
            # search_effort / distance per find use found = 0 as "effort spent for nothing".
            denom = found if found and found > 0 else 1.0
            search_effort_per_find.append(ds_total / denom)
            row_distance = _float(row, "total_distance_traveled_m")
            if row_distance is not None:
                distance_per_find.append(row_distance / denom)

    milestones: dict[str, float | None] = {}
    for pct in COVERAGE_MILESTONES:
        rate, mean_seconds = _milestone_reach_rate(rows, f"time_to_{pct}_coverage")
        milestones[f"reach_{pct}_coverage_pct"] = rate
        milestones[f"mean_time_to_{pct}_coverage"] = mean_seconds

    summary: dict[str, float | int | None] = {
        "trials": total,
        "success_rate_pct": 100.0 * successes / total if total else None,
        "timeout_rate_pct": 100.0 * timeouts / total if total else None,
        "partial_success_rate_pct": _mean(partial_rates),
        "mean_first_find_seconds": _mean(first_find),
        "median_first_find_seconds": _median(first_find),
        "p90_first_find_seconds": _percentile(first_find, 90),
        "mean_coverage_pct": _mean(coverage),
        "mean_redundant_coverage_pct": _mean(redundant_coverage),
        "mean_distance_m": _mean(distance),
        "mean_targets_found": _mean(targets_found),
        "mean_coverage_per_drone_second": _mean(coverage_efficiency),
        "mean_drone_seconds_total": _mean(drone_seconds_total),
        "mean_search_effort_per_find": _mean(search_effort_per_find),
        "mean_distance_per_find_m": _mean(distance_per_find),
    }
    summary.update(milestones)
    return summary


def _ordered_algorithms(rows: list[dict[str, str]]) -> list[str]:
    present = {row.get("algorithm", "") for row in rows}
    ordered = [algorithm for algorithm in ALGORITHM_ORDER if algorithm in present]
    ordered.extend(sorted(present - set(ordered)))
    return ordered


def _write_splits(rows: list[dict[str, str]], input_dir: Path) -> None:
    split_root = input_dir / "splits"
    grouped = _group_rows(rows, "scenario_profile", "algorithm")
    for (scenario, algorithm), group in grouped.items():
        out_dir = split_root / scenario
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{algorithm}.csv"
        fieldnames = list(group[0].keys())
        with out_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(group)


def _bar_svg(title: str, values: list[tuple[str, float | None]], out_path: Path, unit: str = "") -> None:
    width = 920
    height = 420
    margin_left = 80
    margin_bottom = 84
    margin_top = 52
    chart_width = width - margin_left - 32
    chart_height = height - margin_top - margin_bottom
    finite_values = [value for _, value in values if value is not None]
    max_value = max(finite_values) if finite_values else 1.0
    max_value = max(max_value, 1.0)
    bar_gap = 14
    bar_width = max(28, (chart_width - bar_gap * (len(values) + 1)) / max(len(values), 1))
    palette = ["#2563eb", "#16a34a", "#f97316", "#9333ea", "#dc2626", "#0f766e", "#64748b"]

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{margin_left}" y="30" font-family="Arial" font-size="20" font-weight="700">{html.escape(title)}</text>',
        f'<line x1="{margin_left}" y1="{margin_top + chart_height}" x2="{width - 24}" y2="{margin_top + chart_height}" stroke="#334155"/>',
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + chart_height}" stroke="#334155"/>',
    ]
    for tick in range(0, 5):
        frac = tick / 4
        y = margin_top + chart_height - frac * chart_height
        label = max_value * frac
        parts.append(f'<line x1="{margin_left - 4}" y1="{y:.1f}" x2="{width - 24}" y2="{y:.1f}" stroke="#e2e8f0"/>')
        parts.append(f'<text x="{margin_left - 10}" y="{y + 4:.1f}" text-anchor="end" font-family="Arial" font-size="12" fill="#475569">{label:.0f}{html.escape(unit)}</text>')

    for idx, (label, value) in enumerate(values):
        x = margin_left + bar_gap + idx * (bar_width + bar_gap)
        safe_value = value or 0.0
        bar_height = chart_height * safe_value / max_value
        y = margin_top + chart_height - bar_height
        color = palette[idx % len(palette)]
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_height:.1f}" fill="{color}" rx="2"/>')
        parts.append(f'<text x="{x + bar_width / 2:.1f}" y="{y - 6:.1f}" text-anchor="middle" font-family="Arial" font-size="12" fill="#0f172a">{safe_value:.1f}{html.escape(unit)}</text>')
        parts.append(f'<text x="{x + bar_width / 2:.1f}" y="{height - 42}" text-anchor="middle" font-family="Arial" font-size="12" fill="#0f172a" transform="rotate(-25 {x + bar_width / 2:.1f},{height - 42})">{html.escape(label)}</text>')

    parts.append("</svg>\n")
    out_path.write_text("\n".join(parts))


def _write_graphs(rows: list[dict[str, str]], input_dir: Path) -> None:
    graphs_dir = input_dir / "graphs"
    graphs_dir.mkdir(parents=True, exist_ok=True)
    scenarios = sorted({row.get("scenario_profile", "") for row in rows})
    metric_specs = [
        ("success_rate_pct", "Success rate", "%"),
        ("mean_first_find_seconds", "Mean first-find time", "s"),
        ("median_first_find_seconds", "Median first-find time", "s"),
        ("p90_first_find_seconds", "P90 first-find time", "s"),
        ("mean_coverage_pct", "Mean final coverage", "%"),
        ("mean_distance_m", "Mean total distance", "m"),
        ("timeout_rate_pct", "Timeout rate", "%"),
    ]

    for scenario in scenarios:
        scenario_rows = [row for row in rows if row.get("scenario_profile") == scenario]
        by_algorithm = _group_rows(scenario_rows, "algorithm")
        summaries = {key[0]: _summarize(group) for key, group in by_algorithm.items()}
        for metric, label, unit in metric_specs:
            values = [
                (algorithm, summaries[algorithm].get(metric))
                for algorithm in _ordered_algorithms(scenario_rows)
            ]
            _bar_svg(
                f"{scenario}: {label}",
                [(label, float(value) if value is not None else None) for label, value in values],
                graphs_dir / f"{scenario}_{metric}.svg",
                unit,
            )

    overall_by_algorithm = _group_rows(rows, "algorithm")
    overall_summaries = {key[0]: _summarize(group) for key, group in overall_by_algorithm.items()}
    for metric, label, unit in metric_specs:
        values = [
            (algorithm, overall_summaries[algorithm].get(metric))
            for algorithm in _ordered_algorithms(rows)
        ]
        _bar_svg(
            f"overall: {label}",
            [(label, float(value) if value is not None else None) for label, value in values],
            graphs_dir / f"overall_{metric}.svg",
            unit,
        )


def _rank(summary: dict[str, dict[str, Any]], metric: str, reverse: bool) -> str:
    candidates = [
        (algorithm, values.get(metric))
        for algorithm, values in summary.items()
        if values.get(metric) is not None
    ]
    if not candidates:
        return "-"
    candidates.sort(key=lambda item: float(item[1]), reverse=reverse)
    return str(candidates[0][0])


def _write_analysis(rows: list[dict[str, str]], input_dir: Path) -> None:
    scenarios = sorted({row.get("scenario_profile", "") for row in rows})
    algorithms = _ordered_algorithms(rows)
    lines = [
        "# Benchmark Analysis",
        "",
        f"Raw trials analyzed: {len(rows)}",
        f"Scenarios: {', '.join(scenarios)}",
        f"Algorithms: {', '.join(algorithms)}",
        "",
        "## Overall Summary",
        "",
    ]

    overall = {
        key[0]: _summarize(group)
        for key, group in _group_rows(rows, "algorithm").items()
    }
    lines.extend(_summary_table(overall, algorithms))
    lines.extend([
        "",
        "## Scenario Summaries",
        "",
    ])
    for scenario in scenarios:
        scenario_rows = [row for row in rows if row.get("scenario_profile") == scenario]
        summary = {
            key[0]: _summarize(group)
            for key, group in _group_rows(scenario_rows, "algorithm").items()
        }
        lines.append(f"### {scenario}")
        lines.append("")
        lines.extend(_summary_table(summary, algorithms))
        lines.append("")
        lines.append(f"- Best success rate: `{_rank(summary, 'success_rate_pct', True)}`.")
        lines.append(f"- Fastest mean first find: `{_rank(summary, 'mean_first_find_seconds', False)}`.")
        lines.append(f"- Highest mean coverage: `{_rank(summary, 'mean_coverage_pct', True)}`.")
        lines.append(f"- Lowest mean distance: `{_rank(summary, 'mean_distance_m', False)}`.")
        lines.append("")

    stationary = [row for row in rows if row.get("scenario_profile") in STATIONARY_PROFILES]
    moving = [row for row in rows if row.get("scenario_profile") in MOVING_PROFILES]

    lines.extend(_effort_section(rows, algorithms))
    lines.extend(_coverage_milestone_section(rows, algorithms))
    lines.extend(_stationary_vs_moving_section(stationary, moving, algorithms))
    lines.extend(_paired_section(rows, algorithms))

    lines.extend([
        "## Algorithm Notes",
        "",
    ])
    for algorithm in algorithms:
        all_rows = [row for row in rows if row.get("algorithm") == algorithm]
        stat_rows = [row for row in stationary if row.get("algorithm") == algorithm]
        moving_rows = [row for row in moving if row.get("algorithm") == algorithm]
        all_summary = _summarize(all_rows)
        stat_summary = _summarize(stat_rows) if stat_rows else {}
        moving_summary = _summarize(moving_rows) if moving_rows else {}
        lines.append(f"### {algorithm}")
        lines.append("")
        lines.append(
            "- Overall: "
            f"success {_fmt(all_summary.get('success_rate_pct'), 1, '%')}, "
            f"timeout {_fmt(all_summary.get('timeout_rate_pct'), 1, '%')}, "
            f"mean first find {_fmt(all_summary.get('mean_first_find_seconds'), 1, 's')}, "
            f"coverage {_fmt(all_summary.get('mean_coverage_pct'), 1, '%')}, "
            f"distance {_fmt(all_summary.get('mean_distance_m'), 1, 'm')}."
        )
        if stat_rows and moving_rows:
            lines.append(
                "- Stationary vs moving: "
                f"stationary success {_fmt(stat_summary.get('success_rate_pct'), 1, '%')} / "
                f"moving success {_fmt(moving_summary.get('success_rate_pct'), 1, '%')}; "
                f"stationary first find {_fmt(stat_summary.get('mean_first_find_seconds'), 1, 's')} / "
                f"moving first find {_fmt(moving_summary.get('mean_first_find_seconds'), 1, 's')}."
            )
        lines.append("")

    lines.extend([
        "## Caveats",
        "",
        "- Results are paired by scenario seed inside each scenario CSV.",
        "- First-find averages ignore trials with no find; use success and timeout rates beside speed metrics.",
        "- Coverage milestone reach % is the share of trials that crossed the milestone before timeout; trials that never reached it are excluded from the mean time, not counted as zero.",
        "- `search_effort_per_find` and `distance_per_find_m` charge the full effort to trials that found nothing (denominator floored at 1 hiker), so high values indicate wasted effort, not missing data.",
        "- Generated SVG charts are in `graphs/`; per-algorithm CSV splits are in `splits/`.",
        "",
    ])
    (input_dir / "analysis.md").write_text("\n".join(lines))


def _effort_section(rows: list[dict[str, str]], algorithms: list[str]) -> list[str]:
    overall = {
        key[0]: _summarize(group)
        for key, group in _group_rows(rows, "algorithm").items()
    }
    lines = [
        "## SAR Effort and Efficiency",
        "",
        "Coverage-per-drone-second is the cleanest cross-scale efficiency metric; effort/distance per find penalize trials that found nothing.",
        "",
        "| Algorithm | Cov %/drone-sec ×1k | Drone-seconds total | Effort per find (drone-sec) | Distance per find (m) | Redundant cov % |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for algorithm in algorithms:
        values = overall.get(algorithm)
        if not values:
            continue
        cps = values.get("mean_coverage_per_drone_second")
        cps_scaled = cps * 1000 if cps is not None else None
        lines.append(
            f"| `{algorithm}` "
            f"| {_fmt(cps_scaled, 3)} "
            f"| {_fmt(values.get('mean_drone_seconds_total'), 0)} "
            f"| {_fmt(values.get('mean_search_effort_per_find'), 0)} "
            f"| {_fmt(values.get('mean_distance_per_find_m'), 0)} "
            f"| {_fmt(values.get('mean_redundant_coverage_pct'), 1)} |"
        )
    lines.append("")
    return lines


def _coverage_milestone_section(rows: list[dict[str, str]], algorithms: list[str]) -> list[str]:
    overall = {
        key[0]: _summarize(group)
        for key, group in _group_rows(rows, "algorithm").items()
    }
    lines = [
        "## Coverage Milestone Reach Rates",
        "",
        "Reach % is the share of trials that crossed the milestone within the timeout. Mean time is computed only over trials that reached it (so an algorithm with low reach % and small mean time was lucky, not fast).",
        "",
        "| Algorithm | Reach 50% | Mean t→50% | Reach 80% | Mean t→80% | Reach 95% | Mean t→95% |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for algorithm in algorithms:
        values = overall.get(algorithm)
        if not values:
            continue
        cells: list[str] = []
        for pct in COVERAGE_MILESTONES:
            reach = values.get(f"reach_{pct}_coverage_pct")
            mean_t = values.get(f"mean_time_to_{pct}_coverage")
            cells.append(_fmt(reach, 1, "%"))
            if reach in (None, 0) or mean_t in (None, 0):
                cells.append("did not reach")
            else:
                cells.append(_fmt(mean_t, 0, "s"))
        lines.append(f"| `{algorithm}` | " + " | ".join(cells) + " |")
    lines.append("")
    return lines


def _stationary_vs_moving_section(
    stationary: list[dict[str, str]],
    moving: list[dict[str, str]],
    algorithms: list[str],
) -> list[str]:
    lines = [
        "## Stationary vs Moving Profile Split",
        "",
        "Algorithms that win overall by being good only on moving profiles will look weak here; algorithms whose stationary value is competitive deserve to be the SAR default.",
        "",
        "| Algorithm | Stat Success % | Stat Coverage % | Stat Cov/drone-s ×1k | Moving Success % | Moving Coverage % | Moving Cov/drone-s ×1k |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    stat_groups = {
        key[0]: _summarize(group)
        for key, group in _group_rows(stationary, "algorithm").items()
    }
    move_groups = {
        key[0]: _summarize(group)
        for key, group in _group_rows(moving, "algorithm").items()
    }
    for algorithm in algorithms:
        st = stat_groups.get(algorithm, {})
        mv = move_groups.get(algorithm, {})
        if not st and not mv:
            continue
        st_cps = st.get("mean_coverage_per_drone_second")
        mv_cps = mv.get("mean_coverage_per_drone_second")
        lines.append(
            f"| `{algorithm}` "
            f"| {_fmt(st.get('success_rate_pct'), 1)} "
            f"| {_fmt(st.get('mean_coverage_pct'), 1)} "
            f"| {_fmt(st_cps * 1000 if st_cps is not None else None, 3)} "
            f"| {_fmt(mv.get('success_rate_pct'), 1)} "
            f"| {_fmt(mv.get('mean_coverage_pct'), 1)} "
            f"| {_fmt(mv_cps * 1000 if mv_cps is not None else None, 3)} |"
        )
    lines.append("")
    return lines


def _paired_section(rows: list[dict[str, str]], algorithms: list[str]) -> list[str]:
    pair_key = ("scenario_profile", "scenario_seed", "iteration")
    paired: dict[tuple[str, ...], dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        key = tuple(row.get(k, "") for k in pair_key)
        paired[key][row.get("algorithm", "")] = row

    if PAIRED_REFERENCE_ALGORITHM not in {row.get("algorithm") for row in rows}:
        return []

    lines = [
        f"## Paired Comparison vs `{PAIRED_REFERENCE_ALGORITHM}` (same seed/profile/iteration)",
        "",
        "Pairs where both algorithms ran on the exact same scenario instance. `pmv only` = pmv fully succeeded and the other did not; `other only` = the inverse; `both` = both fully succeeded; `neither` = both failed within timeout.",
        "",
        "| Algorithm | Paired trials | pmv only | other only | both | neither |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for algorithm in algorithms:
        if algorithm == PAIRED_REFERENCE_ALGORITHM:
            continue
        pmv_only = other_only = both = neither = 0
        total = 0
        for key, runs in paired.items():
            ref = runs.get(PAIRED_REFERENCE_ALGORITHM)
            other = runs.get(algorithm)
            if ref is None or other is None:
                continue
            total += 1
            ref_succ = _full_success(ref)
            other_succ = _full_success(other)
            if ref_succ and other_succ:
                both += 1
            elif ref_succ:
                pmv_only += 1
            elif other_succ:
                other_only += 1
            else:
                neither += 1
        if total == 0:
            continue
        lines.append(
            f"| `{algorithm}` "
            f"| {total} "
            f"| {pmv_only} ({100*pmv_only/total:.1f}%) "
            f"| {other_only} ({100*other_only/total:.1f}%) "
            f"| {both} ({100*both/total:.1f}%) "
            f"| {neither} ({100*neither/total:.1f}%) |"
        )
    lines.append("")
    return lines


def _full_success(row: dict[str, str]) -> bool:
    found = _float(row, "targets_found") or 0.0
    total = _float(row, "targets_total") or _float(row, "target_count") or 0.0
    return bool(total) and found >= total


def _summary_table(summary: dict[str, dict[str, Any]], algorithms: list[str]) -> list[str]:
    lines = [
        "| Algorithm | Trials | Success % | Timeout % | Mean first find | Median first find | P90 first find | Mean coverage % | Mean distance m | Mean targets found |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for algorithm in algorithms:
        values = summary.get(algorithm)
        if not values:
            continue
        lines.append(
            f"| `{algorithm}` "
            f"| {values['trials']} "
            f"| {_fmt(values.get('success_rate_pct'), 1)} "
            f"| {_fmt(values.get('timeout_rate_pct'), 1)} "
            f"| {_fmt(values.get('mean_first_find_seconds'), 1)} "
            f"| {_fmt(values.get('median_first_find_seconds'), 1)} "
            f"| {_fmt(values.get('p90_first_find_seconds'), 1)} "
            f"| {_fmt(values.get('mean_coverage_pct'), 1)} "
            f"| {_fmt(values.get('mean_distance_m'), 1)} "
            f"| {_fmt(values.get('mean_targets_found'), 2)} |"
        )
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze benchmark raw CSV exports.")
    parser.add_argument("input_dir", type=Path, help="Directory containing raw_<scenario>.csv files.")
    args = parser.parse_args()

    rows = _read_rows(args.input_dir)
    _write_splits(rows, args.input_dir)
    _write_graphs(rows, args.input_dir)
    _write_analysis(rows, args.input_dir)
    print(f"Analysis written to {args.input_dir / 'analysis.md'}")
    print(f"Graphs written to {args.input_dir / 'graphs'}")
    print(f"Split CSVs written to {args.input_dir / 'splits'}")


if __name__ == "__main__":
    main()
