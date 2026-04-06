import asyncio
import concurrent.futures
import json
import logging
import sys
from typing import List, Optional

from app.missions import (
    _coerce_sysid,
    _dispatch_failure_row,
    _extract_result_payload,
    _normalize_script_results,
)
from app.settings import (
    DEFAULT_DISPATCH_HOST,
    DEFAULT_DISPATCH_TIMEOUT_SECONDS,
    SWARM_COMMAND_SCRIPT,
)
from app.sitl import sitl_bridge


logger = logging.getLogger(__name__)


async def run_dispatch_script(
    assignments: List[dict],
    host: str = DEFAULT_DISPATCH_HOST,
    timeout_seconds: float = DEFAULT_DISPATCH_TIMEOUT_SECONDS,
    count: Optional[int] = None,
) -> List[dict]:
    if not assignments:
        return []

    if not SWARM_COMMAND_SCRIPT.exists():
        return [
            _dispatch_failure_row(
                item.get("drone_id"),
                _coerce_sysid(item.get("sysid")),
                f"Dispatch script not found: {SWARM_COMMAND_SCRIPT}",
            )
            for item in assignments
        ]

    timeout_seconds = max(1.0, float(timeout_seconds))
    inferred_count = max((_coerce_sysid(item.get("sysid")) or 0 for item in assignments), default=0)
    selected_count = count if count is not None and count > 0 else max(inferred_count, len(assignments))
    command = [
        sys.executable,
        str(SWARM_COMMAND_SCRIPT),
        "dispatch-targets",
        "--host",
        host,
        "--count",
        str(selected_count),
        "--assignments-json",
        json.dumps(assignments),
    ]

    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        if process and process.returncode is None:
            process.kill()
            await process.communicate()
        return [
            _dispatch_failure_row(
                item.get("drone_id"),
                _coerce_sysid(item.get("sysid")),
                f"Dispatch timeout after {timeout_seconds:.1f}s",
            )
            for item in assignments
        ]
    except Exception as exc:
        return [
            _dispatch_failure_row(
                item.get("drone_id"),
                _coerce_sysid(item.get("sysid")),
                f"Dispatch execution error: {exc}",
            )
            for item in assignments
        ]

    stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
    parsed_results = _extract_result_payload(stdout_text)

    if process.returncode != 0:
        reason = f"Dispatch script exited with code {process.returncode}"
        if stderr_text:
            reason = f"{reason}: {stderr_text}"
        if parsed_results is None:
            return [
                _dispatch_failure_row(
                    item.get("drone_id"),
                    _coerce_sysid(item.get("sysid")),
                    reason,
                )
                for item in assignments
            ]
        normalized = _normalize_script_results(parsed_results, assignments)
        for row in normalized:
            if not row["success"] and not row["message"]:
                row["message"] = reason
        return normalized

    if parsed_results is None:
        reason = "Dispatch script did not return JSON results"
        if stderr_text:
            reason = f"{reason}: {stderr_text}"
        return [
            _dispatch_failure_row(
                item.get("drone_id"),
                _coerce_sysid(item.get("sysid")),
                reason,
            )
            for item in assignments
        ]

    return _normalize_script_results(parsed_results, assignments)


async def run_direct_dispatch(assignments: List[dict]) -> List[dict]:
    if not assignments:
        return []

    def _dispatch_one(item: dict) -> dict:
        sysid = _coerce_sysid(item.get("sysid"))
        if sysid is None:
            return _dispatch_failure_row(item.get("drone_id"), None, "Invalid sysid")
        return sitl_bridge.dispatch_drone(
            sysid=sysid,
            lat=float(item["lat"]),
            lon=float(item["lon"]),
            alt=float(item["alt"]),
            drone_id=item.get("drone_id"),
        )

    def _dispatch_all() -> List[dict]:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(assignments)) as pool:
            futures = [pool.submit(_dispatch_one, item) for item in assignments]
            return [f.result() for f in futures]

    return await asyncio.to_thread(_dispatch_all)
