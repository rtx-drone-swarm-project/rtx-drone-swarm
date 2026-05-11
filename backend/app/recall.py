"""Helpers for sending mission recall commands to live SITL drones."""

import logging
from typing import List

from app.missions import _build_recall_assignments, _coerce_sysid
from app.models import Mission
from app.sitl import sitl_bridge


logger = logging.getLogger(__name__)

def check_recall_completion() -> bool:
    states = sitl_bridge.get_states_by_sysid()
    if not states:
        return False
    return all(
        state.get("armed") is False and float(state.get("alt") or 0.0) <= 0.1
        for state in states.values()
    )

def run_direct_recall(mission: Mission) -> List[dict]:
    """Recall drones directly through the in-process SITL bridge."""
    logger.info("Recall invoked. Returning drones to mission home formation, then landing and disarming")

    results = []
    assignments = _build_recall_assignments(mission)
    if not assignments:
        logger.warning("Recall skipped because mission home is unavailable")
        for drone in getattr(mission, "drones", []):
            results.append(
                {
                    "drone_id": drone.get("id"),
                    "sysid": _coerce_sysid(drone.get("sysid")),
                    "success": False,
                    "message": "Mission home unavailable for recall",
                }
            )
        return results

    for assignment in assignments:
        drone_id = assignment.get("drone_id")
        sysid = _coerce_sysid(assignment.get("sysid"))

        if sysid is None:
            logger.warning("Skipping drone %s due to invalid sysid", drone_id)
            results.append({
                "drone_id": drone_id,
                "sysid": None,
                "success": False,
                "message": "Invalid sysid",
            })
            continue

        result = sitl_bridge.recall_drone(
            sysid=sysid,
            drone_id=str(drone_id),
            target_lat=float(assignment["lat"]),
            target_lon=float(assignment["lon"]),
        )
        results.append(result)
    return results
