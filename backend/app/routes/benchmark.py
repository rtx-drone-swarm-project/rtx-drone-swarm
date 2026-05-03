"""Benchmark routes for comparing algorithms across repeated headless trials."""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Response

from app.algorithms import list_algorithm_keys
from app.benchmark import make_run_id, run_benchmark_job, total_trials
from app.benchmark_db import create_run, export_trials_csv, get_run, list_runs
from app.models import BenchmarkRequest


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/benchmark", tags=["benchmark"])
_benchmark_tasks: set[asyncio.Task] = set()


@router.post("")
async def start_benchmark(request: BenchmarkRequest):
    """Start a background benchmark and return the persisted run record."""
    unknown = sorted(set(request.algorithms) - set(list_algorithm_keys()))
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown algorithm(s): {', '.join(unknown)}")

    run_id = make_run_id()
    run = await asyncio.to_thread(create_run, run_id, request.model_dump(), total_trials(request))
    task = asyncio.create_task(run_benchmark_job(run_id, request))
    _benchmark_tasks.add(task)

    def _log_failure(done: asyncio.Task) -> None:
        _benchmark_tasks.discard(done)
        try:
            done.result()
        except Exception:
            logger.exception("Benchmark run %s failed", run_id)

    task.add_done_callback(_log_failure)
    return run


@router.get("/runs")
def get_benchmark_runs():
    """List recent benchmark runs with progress and stored summaries."""
    return {"runs": list_runs()}


@router.get("/export")
def export_benchmarks(run_id: str | None = None, all_runs: bool = False):
    """Export benchmark trial rows as CSV for spreadsheet or notebook analysis."""
    if run_id is None and not all_runs:
        raise HTTPException(status_code=400, detail="Pass run_id, or all_runs=true for a full dev-only export")
    csv_text = export_trials_csv(run_id)
    filename = "benchmark_results.csv" if run_id is None else f"benchmark_{run_id}.csv"
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{run_id}")
def get_benchmark_run(run_id: str):
    """Return one benchmark run with raw trials and aggregate metric summaries."""
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Benchmark run not found")
    return run
