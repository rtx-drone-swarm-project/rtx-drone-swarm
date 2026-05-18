"""Headless benchmark CLI for algorithm comparison and PSO acceptance-criteria validation.

Usage (run from backend/):

    PYTHONPATH=. python -m app.benchmark_cli \\
        --algorithms pso,voronoi,voronoi_aco,sweep \\
        --iterations 50 \\
        --scenario-profile wandering_hikers \\
        --min-lat 33.45 --max-lat 33.55 \\
        --min-lon -117.25 --max-lon -117.15

Writes trial rows to the same backend/data/benchmarks.db used by the HTTP API.
Prints an ASCII summary table to stdout and exports a CSV for sharing.

Scenario profiles
-----------------
  uniform_random   — stationary targets, random placement (default)
  clustered_targets — stationary targets clustered in a random 30% sub-region
  wandering_hikers  — moving targets, random placement
  corridor_route    — moving targets placed along a diagonal band

PSO acceptance-criteria checks (printed when pso is one of the algorithms)
--------------------------------------------------------------------------
  AC#5: |pso.success_rate - voronoi.success_rate| ≤ 10 pp
        (meaningful on uniform_random and clustered_targets)
  AC#6: pso.avg_first_find_seconds ≤ voronoi_aco.avg_first_find_seconds
        (meaningful on wandering_hikers and corridor_route)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import random
import statistics
import sys
from pathlib import Path
from typing import Any

from app.algorithms import get_algorithm          # noqa: F401 — triggers registry import
from app.benchmark import SCENARIO_PROFILES, _build_scenario, make_run_id, run_headless_trial
from app.benchmark_db import (
    aggregate_trials,
    create_run,
    export_trials_csv,
    finish_run,
    init_db,
    insert_trial,
)

# ---------------------------------------------------------------------------
# Derived stats helpers
# ---------------------------------------------------------------------------

def _success_rate(trials: list[dict[str, Any]]) -> float | None:
    if not trials:
        return None
    successes = sum(
        1 for t in trials
        if t.get("targets_found") is not None
        and t.get("targets_total") is not None
        and int(t["targets_found"]) == int(t["targets_total"])
    )
    return round(100.0 * successes / len(trials), 1)


def _percentile(values: list[float], p: int) -> float | None:
    if not values:
        return None
    sorted_v = sorted(values)
    idx = max(0, math.ceil(p / 100 * len(sorted_v)) - 1)
    return round(sorted_v[idx], 1)


def _mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(statistics.mean(values), 1)


def _fmt(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value}{suffix}"


# ---------------------------------------------------------------------------
# Summary printing
# ---------------------------------------------------------------------------

def _print_summary(
    run_id: str,
    algorithms: list[str],
    trials: list[dict[str, Any]],
    scenario_profile: str,
    iterations: int,
) -> None:
    by_algo: dict[str, list[dict[str, Any]]] = {}
    for t in trials:
        by_algo.setdefault(str(t["algorithm"]), []).append(t)

    # Build rows
    rows: list[dict[str, Any]] = []
    for algo in algorithms:
        algo_trials = by_algo.get(algo, [])
        find_times = [
            float(t["first_find_seconds"])
            for t in algo_trials
            if t.get("first_find_seconds") is not None
        ]
        coverage_vals = [
            float(t["coverage_pct"])
            for t in algo_trials
            if t.get("coverage_pct") is not None
        ]
        distance_vals = [
            float(t["total_distance_traveled_m"])
            for t in algo_trials
            if t.get("total_distance_traveled_m") is not None
        ]
        rows.append({
            "algo": algo,
            "n": len(algo_trials),
            "success": _success_rate(algo_trials),
            "avg_first_find": _mean_or_none(find_times),
            "p90_first_find": _percentile(find_times, 90),
            "avg_coverage": _mean_or_none(coverage_vals),
            "avg_distance": _mean_or_none(distance_vals),
        })

    col_w = [16, 9, 12, 12, 12, 14, 7]
    header = ["Algorithm", "Success%", "AvgFirst(s)", "P90First(s)", "AvgCoverage%", "AvgDistance_m", "Trials"]
    sep = "  ".join("-" * w for w in col_w)

    print()
    print(f"=== Benchmark run {run_id} | profile={scenario_profile} | {iterations} iters ===")
    print()
    print("  ".join(h.ljust(w) for h, w in zip(header, col_w)))
    print(sep)
    for r in rows:
        cols = [
            r["algo"].ljust(col_w[0]),
            _fmt(r["success"], "%").ljust(col_w[1]),
            _fmt(r["avg_first_find"], "s").ljust(col_w[2]),
            _fmt(r["p90_first_find"], "s").ljust(col_w[3]),
            _fmt(r["avg_coverage"], "%").ljust(col_w[4]),
            _fmt(r["avg_distance"], "m").ljust(col_w[5]),
            str(r["n"]).ljust(col_w[6]),
        ]
        print("  ".join(cols))
    print()

    # AC checks (only meaningful if pso is in the run)
    if "pso" not in by_algo:
        return

    pso_row = next((r for r in rows if r["algo"] == "pso"), None)
    voronoi_row = next((r for r in rows if r["algo"] == "voronoi"), None)
    vaco_row = next((r for r in rows if r["algo"] == "voronoi_aco"), None)

    print("--- PSO Acceptance Criteria ---")
    if scenario_profile in ("uniform_random", "clustered_targets"):
        if pso_row and voronoi_row and pso_row["success"] is not None and voronoi_row["success"] is not None:
            diff = abs(pso_row["success"] - voronoi_row["success"])
            badge = "PASS" if diff <= 10.0 else "FAIL"
            print(f"  AC#5 (success_rate within 10pp of voronoi): {badge}"
                  f"  [pso={pso_row['success']}%  voronoi={voronoi_row['success']}%  diff={diff:.1f}pp]")
        else:
            print("  AC#5: insufficient data (need pso + voronoi in same run)")

    if scenario_profile in ("wandering_hikers", "corridor_route"):
        if pso_row and vaco_row and pso_row["avg_first_find"] is not None and vaco_row["avg_first_find"] is not None:
            badge = "PASS" if pso_row["avg_first_find"] <= vaco_row["avg_first_find"] else "FAIL"
            print(f"  AC#6 (pso first_find ≤ voronoi_aco first_find):  {badge}"
                  f"  [pso={pso_row['avg_first_find']}s  voronoi_aco={vaco_row['avg_first_find']}s]")
        elif pso_row and pso_row["avg_first_find"] is None:
            print("  AC#6: pso found no targets in any trial — FAIL (no finds)")
        else:
            print("  AC#6: need both pso and voronoi_aco in the same run for this check")
    print()


# ---------------------------------------------------------------------------
# Main async runner
# ---------------------------------------------------------------------------

async def _run(
    algorithms: list[str],
    iterations: int,
    scenario_profile: str,
    bounds: dict[str, float],
    drone_count: int,
    target_count: int,
    timeout_seconds: int,
    seed: int | None,
    output_csv: str | None,
    output_dir: str | None,
) -> None:
    if scenario_profile not in SCENARIO_PROFILES:
        print(f"Unknown scenario profile {scenario_profile!r}. "
              f"Choose from: {', '.join(SCENARIO_PROFILES)}", file=sys.stderr)
        sys.exit(1)

    base_seed = seed if seed is not None else random.SystemRandom().randint(1, 2_147_483_647)
    run_id = make_run_id()

    total = len(algorithms) * iterations
    request_payload = {
        "algorithms": algorithms,
        "iterations": iterations,
        "scenario_profile": scenario_profile,
        "bounds": bounds,
        "drone_count": drone_count,
        "target_count": target_count,
        "timeout_seconds": timeout_seconds,
        "seed": base_seed,
    }

    init_db()
    create_run(run_id, request_payload, total)

    print(f"Run ID: {run_id}")
    print(f"Profile: {scenario_profile}  |  Algorithms: {', '.join(algorithms)}"
          f"  |  Iterations: {iterations}  |  Seed: {base_seed}")
    print(f"Bounds: lat [{bounds['min_lat']}, {bounds['max_lat']}]  "
          f"lon [{bounds['min_lon']}, {bounds['max_lon']}]")
    print(f"Drones: {drone_count}  Targets: {target_count}  Timeout: {timeout_seconds}s")
    print()

    trials: list[dict[str, Any]] = []
    completed = 0

    try:
        for iteration in range(iterations):
            scenario_seed = base_seed + iteration
            scenario = _build_scenario(bounds, drone_count, target_count, scenario_seed, scenario_profile)
            for algo in algorithms:
                trial = await run_headless_trial(
                    run_id=run_id,
                    algorithm=algo,
                    iteration=iteration + 1,
                    scenario_seed=scenario_seed,
                    bounds=bounds,
                    drone_starts=scenario["drones"],
                    target_starts=scenario["targets"],
                    timeout_seconds=timeout_seconds,
                    scenario_profile=scenario_profile,
                    static_targets=not bool(scenario["targets_move"]),
                )
                insert_trial(trial)
                trials.append(trial)
                completed += 1
                # Progress indicator: print a dot every 10 trials
                if completed % 10 == 0 or completed == total:
                    pct = int(100 * completed / total)
                    print(f"  [{completed}/{total}] {pct}%", end="\r", flush=True)

        print()
        finish_run(run_id, "complete", summary=aggregate_trials(trials))

    except KeyboardInterrupt:
        print("\nInterrupted — saving partial results.")
        finish_run(run_id, "cancelled", summary=aggregate_trials(trials))

    except Exception as exc:
        finish_run(run_id, "failed", summary=aggregate_trials(trials), error=str(exc))
        raise

    _print_summary(run_id, algorithms, trials, scenario_profile, iterations)

    # CSV export
    if output_csv:
        csv_path = Path(output_csv)
    elif output_dir:
        csv_path = Path(output_dir) / f"raw_{scenario_profile}.csv"
    else:
        csv_path = Path(f"bench_{run_id}_{scenario_profile}.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_data = export_trials_csv(run_id)
    with open(csv_path, "w", newline="") as fh:
        fh.write(csv_data)
    print(f"CSV exported → {csv_path}")
    print()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.benchmark_cli",
        description="Headless algorithm benchmark runner with scenario-profile support.",
    )
    p.add_argument(
        "--algorithms",
        default="pso,voronoi,voronoi_aco,sweep",
        help="Comma-separated algorithm keys (default: pso,voronoi,voronoi_aco,sweep)",
    )
    p.add_argument(
        "--iterations",
        type=int,
        default=50,
        help="Number of paired iterations per algorithm (default: 50)",
    )
    p.add_argument(
        "--scenario-profile",
        default="uniform_random",
        choices=list(SCENARIO_PROFILES),
        help="Scenario profile for target/drone placement (default: uniform_random)",
    )
    p.add_argument("--min-lat", type=float, required=True)
    p.add_argument("--max-lat", type=float, required=True)
    p.add_argument("--min-lon", type=float, required=True)
    p.add_argument("--max-lon", type=float, required=True)
    p.add_argument(
        "--drones", type=int, default=4,
        help="Number of drones per trial (default: 4)",
    )
    p.add_argument(
        "--targets", type=int, default=3,
        help="Number of targets (hikers) per trial (default: 3)",
    )
    p.add_argument(
        "--timeout", type=int, default=300,
        help="Simulated seconds per trial before timeout (default: 300)",
    )
    p.add_argument(
        "--seed", type=int, default=None,
        help="Base RNG seed for reproducible runs (default: random)",
    )
    p.add_argument(
        "--output", default=None,
        help="CSV output file path (default: bench_<run_id>_<profile>.csv)",
    )
    p.add_argument(
        "--output-dir", default=None,
        help="Directory for raw_<scenario_profile>.csv output. Ignored when --output is set.",
    )
    p.add_argument(
        "--log-level",
        default="ERROR",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Python logging threshold for algorithm internals (default: ERROR).",
    )
    return p


def main() -> None:
    args = _build_parser().parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level))
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    algorithms = [a.strip() for a in args.algorithms.split(",") if a.strip()]
    if not algorithms:
        print("No algorithms specified.", file=sys.stderr)
        sys.exit(1)
    bounds = {
        "min_lat": args.min_lat,
        "max_lat": args.max_lat,
        "min_lon": args.min_lon,
        "max_lon": args.max_lon,
    }
    asyncio.run(
        _run(
            algorithms=algorithms,
            iterations=args.iterations,
            scenario_profile=args.scenario_profile,
            bounds=bounds,
            drone_count=args.drones,
            target_count=args.targets,
            timeout_seconds=args.timeout,
            seed=args.seed,
            output_csv=args.output,
            output_dir=args.output_dir,
        )
    )


if __name__ == "__main__":
    main()
