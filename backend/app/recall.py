"""Helpers for sending mission recall commands to live SITL drones."""

import logging
from typing import List

from app.missions import Mission, _coerce_sysid
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
    logger.info("Recall invoked. Returning drones to stored home, then landing and disarming")

    results = []
    for drone in getattr(mission, "drones", []):
        drone_id = drone.get("id")
        sysid = _coerce_sysid(drone.get("sysid"))

        if sysid is None:
            logger.warning("Skipping drone %s due to invalid sysid", drone_id)
            results.append({
                "drone_id": drone_id,
                "sysid": None,
                "success": False,
                "message": "Invalid sysid",
            })
            continue

        result = sitl_bridge.recall_drone(sysid=sysid, drone_id=str(drone_id))
        results.append(result)

    # logger.info("Recall results: %s", results)
    return results
