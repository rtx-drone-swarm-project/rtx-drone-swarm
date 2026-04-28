"""Mission tick loop for search coverage, target detection, and frontend updates.

This module is responsible for the backend's time-based mission behavior after a
mission has been started. On each tick it:

- syncs live SITL telemetry into the mission drone list
- computes updated Voronoi/Lloyd coverage centroids for free drones
- sends goto commands to live drones that are airborne and available
- advances simulated drones and wandering targets
- promotes targets through detected -> confirming -> found states
- updates mission progress and broadcasts telemetry/status events
"""

import asyncio
import logging
import math
import random
import time
from typing import Optional

import numpy as np
from pymavlink import mavutil

from app.missions import _sync_mission_drones_with_sitl, missions_db
from app.settings import DEFAULT_DISPATCH_ALT, SLEEP_BETWEEN_DISPATCH_SECONDS
from app.sitl import sitl_bridge
#from app.voronoi import lloyd_step
from app.ws import manager
from app.algorithms import get_algorithm


logger = logging.getLogger(__name__)
# Small random perturbation keeps simulated movement from looking perfectly linear.
JITTER_DEG = 0.0001
# Degree-space speed used for simple simulated movement.
SPEED = 0.0005
# Distance threshold for a drone to "detect" a wandering target.
# About 200m at this latitude; large enough that detection does not require
# marker centers to visually overlap at the default map zoom.
DETECTION_RADIUS = 0.002
# Distance threshold for considering a drone close enough to stop moving toward a point.
TARGET_STOP_RADIUS = 0.00055


async def _emit_target_found(mission: dict, target: dict, drone_id: Optional[str] = None):
    """Broadcast a target-found event once per target id.

    Missions can reach the same "found" state through multiple branches, so this
    helper deduplicates the event before notifying connected clients.
    """
    found_ids = mission.setdefault("_found_target_ids", [])
    if target["id"] in found_ids:
        return
    found_ids.append(target["id"])
    await manager.broadcast(
        {
            "type": "target_found",
            "target_id": target["id"],
            "drone_id": drone_id,
            "lat": target["lat"],
            "lon": target["lon"],
            "found_at": mission.get("elapsed_seconds", 0),
        }
    )


def _bounce_entity(entity: dict, bounds: dict, vx: float, vy: float) -> None:
    """Clamp a moving entity to mission bounds and reflect its velocity at edges.

    The entity is modified in place. When it crosses a mission boundary, its
    position is snapped back inside the bounds and the offending velocity
    component is flipped.
    """
    if entity["lat"] < bounds["min_lat"]:
        entity["lat"] = bounds["min_lat"]
        entity["vx"] = abs(vx)
    elif entity["lat"] > bounds["max_lat"]:
        entity["lat"] = bounds["max_lat"]
        entity["vx"] = -abs(vx)
    if entity["lon"] < bounds["min_lon"]:
        entity["lon"] = bounds["min_lon"]
        entity["vy"] = abs(vy)
    elif entity["lon"] > bounds["max_lon"]:
        entity["lon"] = bounds["max_lon"]
        entity["vy"] = -abs(vy)


def _find_target(mission: dict, target_id: str) -> Optional[dict]:
    """Return the mission target with the requested id, if it exists."""
    return next((t for t in mission.get("targets", []) if t["id"] == target_id), None)


def _find_drone(mission: dict, drone_id: Optional[str]) -> Optional[dict]:
    """Return the mission drone with the requested id, if it exists."""
    if not drone_id:
        return None
    return next((d for d in mission["drones"] if d["id"] == drone_id), None)


def _assign_confirmation_drone(mission: dict, target: dict, finder_drone: dict) -> Optional[dict]:
    """Pick the closest available second drone to confirm a newly detected target.

    The first drone to reach a target becomes the finder. If another free drone
    is available, it is reassigned as the confirmer so the simulation can model
    a simple two-drone confirmation workflow.
    """
    finder_pos_lat = finder_drone["lat"]
    finder_pos_lon = finder_drone["lon"]
    candidates = [
        d
        for d in mission["drones"]
        if d["id"] != finder_drone["id"] and not d.get("assigned_target_id")
    ]
    if not candidates:
        return None
    confirmer = min(
        candidates,
        key=lambda d: math.hypot(d["lat"] - finder_pos_lat, d["lon"] - finder_pos_lon),
    )
    confirmer["assigned_target_id"] = target["id"]
    confirmer["role"] = "confirmer"
    target["confirming_drone_id"] = confirmer["id"]
    target["status"] = "confirming"
    return confirmer

def _send_live_drone_gotos(mission: dict, live_drone_ids: set[str], waypoint_map: dict) -> None:
    """Send goto commands to live drones toward targets, queued points, or centroids.

    Priority order is:
    1. actively assigned mission target
    2. previously queued `target_lat` / `target_lon`
    3. the latest free-search centroid
    """
    if not live_drone_ids:
        return

    airborne_states = sitl_bridge.get_states_by_sysid()
    goto_sent = 0
    skipped_not_dispatchable = 0
    skipped_not_airborne = 0
    skipped_no_destination = 0
    for drone in mission["drones"]:
        if str(drone.get("id")) not in live_drone_ids:
            continue
        sysid = drone.get("sysid")
        if not sysid or sitl_bridge.is_dispatching(sysid):
            skipped_not_dispatchable += 1
            continue
        state = airborne_states.get(sysid, {})
        # Some paths keep altitude on the mission drone record rather than the
        # latest SITL state, so use the higher of the two when deciding whether
        # the drone is safely airborne.
        rel_alt = max(float(state.get("alt") or 0), float(drone.get("alt") or 0))
        if not state.get("armed") or rel_alt < 3.0:
            skipped_not_airborne += 1
            continue
        target_id = drone.get("assigned_target_id")
        if target_id:
            target = _find_target(mission, target_id)
            if target:
                sitl_bridge.send_goto(sysid, target["lat"], target["lon"], DEFAULT_DISPATCH_ALT)
                goto_sent += 1
                continue
        tlat = drone.get("target_lat")
        tlon = drone.get("target_lon")
        dlat = drone.get("lat", 0)
        dlon = drone.get("lon", 0)
        still_enroute = tlat is not None and tlon is not None and math.hypot(dlat - tlat, dlon - tlon) > 0.005
        if still_enroute:
            sitl_bridge.send_goto(sysid, tlat, tlon, DEFAULT_DISPATCH_ALT)
            goto_sent += 1
            continue
        waypoint = waypoint_map.get(drone["id"])
        if waypoint is not None:
            sitl_bridge.send_goto(sysid, float(waypoint[0]), float(waypoint[1]), DEFAULT_DISPATCH_ALT)
            goto_sent += 1
            continue
        skipped_no_destination += 1

    if mission.get("elapsed_seconds", 0) % 10 == 0:
        logger.info(
            "goto_loop: %d/%d drones got goto, centroids=%d, blocked dispatching=%d, blocked airborne=%d, blocked destination=%d",
            goto_sent,
            len(live_drone_ids),
            len(waypoint_map),
            skipped_not_dispatchable,
            skipped_not_airborne,
            skipped_no_destination,
        )


async def _update_drones_for_tick(mission: dict, live_drone_ids: set[str], waypoint_map: dict, bounds: dict) -> None:
    """Advance drone state for one simulation tick using live or simulated movement.

    Live drones keep their position from SITL telemetry and mainly receive role
    and assignment updates here. Simulated drones are moved directly in mission
    state either toward an assigned target, toward a centroid, or with simple
    bounded wandering when they have no coverage point yet.
    """
    for drone in mission["drones"]:
        has_live_telemetry = str(drone.get("id")) in live_drone_ids
        target_id = drone.get("assigned_target_id")
        if target_id and "targets" in mission:
            target = _find_target(mission, target_id)
            if not target:
                drone["assigned_target_id"] = None
                drone["role"] = None
                continue

            if drone["id"] == target.get("finder_drone_id") and target.get("status") == "confirming":
                # The finder holds position on the detected target while the
                # confirmer closes in.
                if not has_live_telemetry:
                    drone["lat"] = target["lat"]
                    drone["lon"] = target["lon"]
                drone["role"] = "finder"
                continue

            d_lat = target["lat"] - drone["lat"]
            d_lon = target["lon"] - drone["lon"]
            dist = math.hypot(d_lat, d_lon)

            
            if dist > TARGET_STOP_RADIUS:
                
                '''if not has_live_telemetry:
                    drone["lat"] += (d_lat / dist) * SPEED
                    drone["lon"] += (d_lon / dist) * SPEED 
                    drone["lat"] += random.uniform(-JITTER_DEG / 2, JITTER_DEG / 2)        #ONLY FOR USING MOCK DATA, NOT NEEDED?
                    drone["lon"] += random.uniform(-JITTER_DEG / 2, JITTER_DEG / 2)'''
                    
                continue

            if target.get("status") in ["detected", "wandering"]:
                # First arrival upgrades the target to confirming and attempts
                # to recruit a second drone. If none is available, the finder
                # alone can complete the discovery.
                target["status"] = "confirming"
                target["finder_drone_id"] = drone["id"]
                drone["role"] = "finder"
                if not has_live_telemetry:
                    drone["lat"] = target["lat"]
                    drone["lon"] = target["lon"]
                _assign_confirmation_drone(mission, target, drone)
                if not target.get("confirming_drone_id"):
                    target["status"] = "found"
                    drone["assigned_target_id"] = None
                    drone["role"] = None
                    await _emit_target_found(mission, target, drone["id"])
            elif target.get("status") == "confirming":
                if drone["id"] == target.get("confirming_drone_id"):
                    # The confirmer reaching the target completes the two-drone
                    # confirmation workflow and frees both drones.
                    target["status"] = "found"
                    finder = _find_drone(mission, target.get("finder_drone_id"))
                    if finder:
                        finder["assigned_target_id"] = None
                        finder["role"] = None
                    drone["assigned_target_id"] = None
                    drone["role"] = None
                    await _emit_target_found(mission, target, drone["id"])
                elif drone["id"] == target.get("finder_drone_id") and not has_live_telemetry:
                    drone["lat"] = target["lat"]
                    drone["lon"] = target["lon"]
            continue

        if drone.get("role") not in ["finder", "confirmer"]:
            drone["role"] = None
        waypoint = waypoint_map.get(drone["id"])
        if waypoint is not None and not has_live_telemetry:
            # Free simulated drones drift toward their latest coverage centroid.
            d_lat = waypoint[0] - drone["lat"]
            d_lon = waypoint[1] - drone["lon"]
            dist = math.hypot(d_lat, d_lon)
            if dist > TARGET_STOP_RADIUS:
                drone["lat"] += (d_lat / dist) * SPEED
                drone["lon"] += (d_lon / dist) * SPEED
                drone["lat"] += random.uniform(-JITTER_DEG / 2, JITTER_DEG / 2)
                drone["lon"] += random.uniform(-JITTER_DEG / 2, JITTER_DEG / 2)
            _bounce_entity(drone, bounds, d_lat, d_lon)
        elif not has_live_telemetry:
            # If no centroid exists yet, fall back to bounded random wandering.
            if "vx" not in drone:
                angle = random.uniform(0, 2 * math.pi)
                drone["vx"] = SPEED * math.cos(angle)
                drone["vy"] = SPEED * math.sin(angle)
            drone["lat"] += drone["vx"]
            drone["lon"] += drone["vy"]
            _bounce_entity(drone, bounds, drone["vx"], drone["vy"])


def _update_targets_for_tick(mission: dict, bounds: dict) -> None:
    """Move wandering targets and assign a nearby drone when one detects them.

    Only targets still in the wandering state move on their own. Detection is a
    nearest-drone check against the current mission drone positions, whether
    those positions are live SITL telemetry or simulated motion.
    """
    if "targets" not in mission:
        return

    for target in mission["targets"]:
        if target.get("status", "wandering") != "wandering":
            continue
        if "vx" not in target:
            angle = random.uniform(0, 2 * math.pi)
            target["vx"] = SPEED / 2 * math.cos(angle)
            target["vy"] = SPEED / 2 * math.sin(angle)
        target["lat"] += target["vx"]
        target["lon"] += target["vy"]
        _bounce_entity(target, bounds, target["vx"], target["vy"])

        nearest_drone = None
        min_dist = float("inf")
        for drone in mission["drones"]:
            dist = math.hypot(drone["lat"] - target["lat"], drone["lon"] - target["lon"])
            if dist < min_dist:
                min_dist = dist
                nearest_drone = drone

        if min_dist < DETECTION_RADIUS and nearest_drone and not nearest_drone.get("assigned_target_id"):
            # Detection only assigns a drone; the actual confirmation/found flow
            # is handled in `_update_drones_for_tick`.
            target["status"] = "detected"
            target["assigned_drone_id"] = nearest_drone["id"]
            nearest_drone["assigned_target_id"] = target["id"]
            nearest_drone["role"] = None


async def _finalize_mission_progress(mission: dict) -> bool:
    """Advance mission progress and complete the mission when all targets are found.

    Progress is derived strictly from target state rather than elapsed time, so
    the frontend progress bar only advances when a target transitions to
    ``found``.
    """
    targets = mission.get("targets", [])
    if not targets:
        mission["progress"] = 0.0
        return False

    found_count = sum(1 for target in targets if target.get("status") == "found")
    total_targets = len(targets)
    mission["progress"] = round((found_count / total_targets) * 100.0, 1)

    all_targets_found = found_count == total_targets
    if all_targets_found:
        mission["status"] = "complete"
        mission["progress"] = 100.0

    return all_targets_found


async def _broadcast_mission_tick(mission_id: str, mission: dict) -> None:
    """Broadcast per-tick telemetry, progress, and target status updates."""
    await manager.broadcast({"type": "telemetry", "drones": mission["drones"]})
    await manager.broadcast({"type": "mission_progress", "progress": mission["progress"]})
    if "targets" in mission:
        await manager.broadcast(
            {
                "type": "mission_status",
                "mission_id": mission_id,
                "status": mission.get("status", "running"),
                "progress": mission["progress"],
                "targets": mission["targets"],
            }
        )


async def simulation_loop(mission_id: str):
    """Run the mission tick loop until the mission stops or reaches completion.

    Each iteration performs one full mission update cycle, then sleeps for the
    configured tick interval in `settings.py`.
    """
    if mission_id not in missions_db:
        return

    mission = missions_db[mission_id]
    mission.setdefault("_found_target_ids", [])
    mission.setdefault("elapsed_seconds", 0)


    while mission["status"] == "running":
        mission["elapsed_seconds"] = mission.get("elapsed_seconds", 0) + 1
        bounds = mission["bounds"]

        # Pull live SITL state into the mission before making any coverage or
        # targeting decisions for this tick.
        live_drone_ids = _sync_mission_drones_with_sitl(mission)

        free_drones = [
            d for d in mission["drones"]
            if not d.get("assigned_target_id") and d.get("role") not in ["finder", "confirmer"]
        ]

        #centroid_map =  await asyncio.to_thread(_build_centroid_map, mission) # DELETE THREAD IF NOT NECESSARY

        algorithm_name = mission.get("algorithm", "voronoi")
        active_strategy = get_algorithm(algorithm_name)
        waypoints_map = await asyncio.to_thread(active_strategy.get_target_waypoints, mission, free_drones)

        _send_live_drone_gotos(mission, live_drone_ids, waypoints_map)
        await _update_drones_for_tick(mission, live_drone_ids, waypoints_map, bounds)
        _update_targets_for_tick(mission, bounds)
        all_targets_found = await _finalize_mission_progress(mission)
        await _broadcast_mission_tick(mission_id, mission)

        if all_targets_found:
            break

        await asyncio.sleep(SLEEP_BETWEEN_DISPATCH_SECONDS)
        if mission["status"] != "running":
            break
