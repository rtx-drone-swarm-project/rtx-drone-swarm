"""SQLite persistence for algorithm benchmark runs and trial rows."""

from __future__ import annotations

import csv
import io
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.settings import BENCHMARK_DB_PATH


DB_PATH = BENCHMARK_DB_PATH

METRIC_FIELDS = [
    "first_find_seconds",
    "avg_find_seconds",
    "last_find_seconds",
    "completion_elapsed_seconds",
    "coverage_pct",
    "miss_pct",
    "redundant_coverage_pct",
    "coverage_per_drone_second",
    "hiker_find_rate",
    "total_distance_traveled_m",
    "avg_distance_per_drone_m",
    "max_distance_single_drone_m",
    "time_to_50_coverage",
    "time_to_80_coverage",
    "time_to_95_coverage",
    "targets_found",
]

TRIAL_COLUMNS = [
    "run_id",
    "algorithm",
    "iteration",
    "scenario_seed",
    "bounds_json",
    "drone_count",
    "target_count",
    "timeout_seconds",
    "elapsed_seconds",
    *METRIC_FIELDS,
    "targets_total",
    "status",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create benchmark tables if this server has not run benchmarks before."""
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS benchmark_runs (
                run_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                total_trials INTEGER NOT NULL,
                completed_trials INTEGER NOT NULL DEFAULT 0,
                request_json TEXT NOT NULL,
                summary_json TEXT,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS benchmark_trials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                algorithm TEXT NOT NULL,
                iteration INTEGER NOT NULL,
                scenario_seed INTEGER NOT NULL,
                bounds_json TEXT NOT NULL,
                drone_count INTEGER NOT NULL,
                target_count INTEGER NOT NULL,
                timeout_seconds INTEGER NOT NULL,
                elapsed_seconds INTEGER NOT NULL,
                first_find_seconds REAL,
                avg_find_seconds REAL,
                last_find_seconds REAL,
                completion_elapsed_seconds REAL,
                coverage_pct REAL NOT NULL,
                miss_pct REAL NOT NULL,
                redundant_coverage_pct REAL NOT NULL,
                coverage_per_drone_second REAL NOT NULL,
                hiker_find_rate REAL NOT NULL,
                total_distance_traveled_m REAL NOT NULL,
                avg_distance_per_drone_m REAL NOT NULL,
                max_distance_single_drone_m REAL NOT NULL,
                time_to_50_coverage REAL,
                time_to_80_coverage REAL,
                time_to_95_coverage REAL,
                targets_found INTEGER NOT NULL,
                targets_total INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES benchmark_runs(run_id)
            );

            CREATE INDEX IF NOT EXISTS idx_benchmark_trials_run
            ON benchmark_trials(run_id, algorithm);
            """
        )


def create_run(run_id: str, request_payload: dict[str, Any], total_trials: int) -> dict[str, Any]:
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO benchmark_runs
            (run_id, status, created_at, total_trials, completed_trials, request_json)
            VALUES (?, 'running', ?, ?, 0, ?)
            """,
            (run_id, _now_iso(), total_trials, json.dumps(request_payload, sort_keys=True)),
        )
    return get_run(run_id) or {}


def insert_trial(row: dict[str, Any]) -> None:
    init_db()
    values = []
    for column in TRIAL_COLUMNS:
        value = row.get(column)
        if column == "bounds_json" and isinstance(value, dict):
            value = json.dumps(value, sort_keys=True)
        values.append(value)

    placeholders = ", ".join("?" for _ in TRIAL_COLUMNS)
    with _connect() as conn:
        conn.execute(
            f"""
            INSERT INTO benchmark_trials
            ({", ".join(TRIAL_COLUMNS)}, created_at)
            VALUES ({placeholders}, ?)
            """,
            [*values, _now_iso()],
        )
        conn.execute(
            """
            UPDATE benchmark_runs
            SET completed_trials = completed_trials + 1
            WHERE run_id = ?
            """,
            (row["run_id"],),
        )


def finish_run(run_id: str, status: str, summary: dict[str, Any] | None = None, error: str | None = None) -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE benchmark_runs
            SET status = ?, completed_at = ?, summary_json = ?, error = ?
            WHERE run_id = ?
            """,
            (
                status,
                _now_iso(),
                json.dumps(summary or {}, sort_keys=True),
                error,
                run_id,
            ),
        )


def list_runs(limit: int = 25) -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT run_id, status, created_at, completed_at, total_trials,
                   completed_trials, request_json, summary_json, error
            FROM benchmark_runs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_decode_run(row) for row in rows]


def get_run(run_id: str) -> dict[str, Any] | None:
    init_db()
    with _connect() as conn:
        run_row = conn.execute(
            """
            SELECT run_id, status, created_at, completed_at, total_trials,
                   completed_trials, request_json, summary_json, error
            FROM benchmark_runs
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        if run_row is None:
            return None
        trials = conn.execute(
            """
            SELECT *
            FROM benchmark_trials
            WHERE run_id = ?
            ORDER BY algorithm, iteration
            """,
            (run_id,),
        ).fetchall()

    decoded = _decode_run(run_row)
    decoded["trials"] = [_decode_trial(row) for row in trials]
    decoded["summary"] = aggregate_trials(decoded["trials"])
    return decoded


def aggregate_trials(trials: list[dict[str, Any]]) -> dict[str, Any]:
    """Return per-algorithm mean/min/max/stddev summaries for stored trials."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for trial in trials:
        grouped.setdefault(str(trial["algorithm"]), []).append(trial)

    summary: dict[str, Any] = {}
    for algorithm, rows in grouped.items():
        metrics: dict[str, Any] = {"count": len(rows)}
        for field in METRIC_FIELDS:
            values = [float(row[field]) for row in rows if row.get(field) is not None]
            if not values:
                metrics[field] = {"mean": None, "min": None, "max": None, "stddev": None}
                continue
            mean = sum(values) / len(values)
            variance = sum((value - mean) ** 2 for value in values) / len(values)
            metrics[field] = {
                "mean": round(mean, 3),
                "min": round(min(values), 3),
                "max": round(max(values), 3),
                "stddev": round(math.sqrt(variance), 3),
            }
        summary[algorithm] = metrics
    return summary


def export_trials_csv(run_id: str | None = None) -> str:
    init_db()
    query = "SELECT * FROM benchmark_trials"
    params: tuple[Any, ...] = ()
    if run_id:
        query += " WHERE run_id = ?"
        params = (run_id,)
    query += " ORDER BY created_at DESC, run_id, algorithm, iteration"

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()

    output = io.StringIO()
    fieldnames = ["id", *TRIAL_COLUMNS, "created_at"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row[key] for key in fieldnames})
    return output.getvalue()


def _decode_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _decode_run(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "run_id": row["run_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
        "total_trials": row["total_trials"],
        "completed_trials": row["completed_trials"],
        "request": _decode_json(row["request_json"], {}),
        "summary": _decode_json(row["summary_json"], {}),
        "error": row["error"],
    }


def _decode_trial(row: sqlite3.Row) -> dict[str, Any]:
    decoded = {column: row[column] for column in row.keys()}
    decoded["bounds"] = _decode_json(decoded.pop("bounds_json", None), {})
    return decoded
