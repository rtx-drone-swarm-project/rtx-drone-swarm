"""Helpers for sending mission recall commands to live SITL drones."""

import logging
import sys
from typing import List, Optional

from app.missions import _coerce_sysid
from app.sitl import sitl_bridge


logger = logging.getLogger(__name__)

def check_recall_completion() -> bool:
    states = sitl_bridge.get_states_by_sysid()
    return all(
        (not s.get("armed")) and (s.get("altitude", 0) < 0.5)
        for s in states.values()
    )

def run_direct_recall(mission: dict) -> List[dict]:
    """Recall drones directly through the in-process SITL bridge."""
    logger.info("Recall invoked. Executing swarm mode set to RTL")

    results = []
    for drone in mission.get("drones", []):
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

    logger.info("Recall results: %s", results)
    return results
