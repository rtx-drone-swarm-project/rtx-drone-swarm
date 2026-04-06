import asyncio
import logging
import math
import random
import time
from typing import Optional

import numpy as np
from pymavlink import mavutil

from app.missions import _sync_mission_drones_with_sitl, missions_db
from app.settings import DEFAULT_DISPATCH_ALT
from app.sitl import sitl_bridge
from app.voronoi import lloyd_step
from app.ws import manager


logger = logging.getLogger(__name__)
JITTER_DEG = 0.0001
SPEED = 0.001
DETECTION_RADIUS = 0.012
TARGET_STOP_RADIUS = 0.0005


async def _emit_target_found(mission: dict, target: dict, drone_id: Optional[str] = None):
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
    return next((t for t in mission.get("targets", []) if t["id"] == target_id), None)


def _find_drone(mission: dict, drone_id: Optional[str]) -> Optional[dict]:
    if not drone_id:
        return None
    return next((d for d in mission["drones"] if d["id"] == drone_id), None)


def _assign_confirmation_drone(mission: dict, target: dict, finder_drone: dict) -> Optional[dict]:
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


def _build_centroid_map(mission: dict) -> dict:
    centroid_map: dict = {}
    if "grid" not in mission:
        return centroid_map

    free_drones = [
        d
        for d in mission["drones"]
        if not d.get("assigned_target_id") and d.get("role") not in ["finder", "confirmer"]
    ]
    if not free_drones:
        return centroid_map

    grid_np = np.array(mission["grid"])
    pos_list = []
    for drone in free_drones:
        tlat = drone.get("target_lat")
        tlon = drone.get("target_lon")
        dlat = drone.get("lat", 0)
        dlon = drone.get("lon", 0)
        if tlat is not None and tlon is not None:
            dist_to_target = math.hypot(dlat - tlat, dlon - tlon)
            if dist_to_target > 0.005:
                pos_list.append([tlat, tlon])
            else:
                pos_list.append([dlat, dlon])
        else:
            pos_list.append([dlat, dlon])
    positions = np.array(pos_list)
    new_centroids, _ = lloyd_step(grid_np, positions)
    for drone, centroid in zip(free_drones, new_centroids):
        centroid_map[drone["id"]] = centroid
    return centroid_map


def _rearm_live_drones_if_needed(mission: dict, live_drone_ids: set[str]) -> None:
    if not live_drone_ids or mission.get("elapsed_seconds", 0) % 10 != 0:
        return

    live_states = sitl_bridge.get_states_by_sysid()
    now = time.time()
    for drone in mission["drones"]:
        sysid = drone.get("sysid")
        if not sysid or sitl_bridge.is_dispatching(sysid):
            continue
        last_arm = sitl_bridge._last_arm_time.get(sysid, 0)
        if now - last_arm < 20:
            continue
        state = live_states.get(sysid)
        if not state or not sitl_bridge.is_ready(sysid):
            continue
        conn = sitl_bridge._get_conn(sysid)
        conn_lock = sitl_bridge._get_conn_lock(sysid)
        if not conn or not conn_lock:
            continue
        if state.get("mode") != "GUIDED":
            logger.info("Re-arm: setting GUIDED for sysid=%s (currently %s)", sysid, state.get("mode"))
            with conn_lock:
                mode_map = conn.mode_mapping()
                conn.mav.set_mode_send(
                    sysid,
                    mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
                    mode_map.get("GUIDED", 4),
                )
        elif not state.get("armed"):
            logger.info("Re-arm: arming+takeoff sysid=%s", sysid)
            with conn_lock:
                conn.mav.command_long_send(
                    sysid,
                    conn.target_component,
                    mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                    0,
                    1,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                )
            sitl_bridge._last_arm_time[sysid] = now
            time.sleep(2.0)
            with conn_lock:
                conn.mav.command_long_send(
                    sysid,
                    conn.target_component,
                    mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    DEFAULT_DISPATCH_ALT,
                )


def _send_live_drone_gotos(mission: dict, live_drone_ids: set[str], centroid_map: dict) -> None:
    if not live_drone_ids:
        return

    airborne_states = sitl_bridge.get_states_by_sysid()
    goto_sent = 0
    for drone in mission["drones"]:
        if str(drone.get("id")) not in live_drone_ids:
            continue
        sysid = drone.get("sysid")
        if not sysid or sitl_bridge.is_dispatching(sysid):
            continue
        state = airborne_states.get(sysid, {})
        if not state.get("armed") or (state.get("alt") or 0) < 3.0:
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
        centroid = centroid_map.get(drone["id"])
        if centroid is not None:
            sitl_bridge.send_goto(sysid, float(centroid[0]), float(centroid[1]), DEFAULT_DISPATCH_ALT)
            goto_sent += 1

    if mission.get("elapsed_seconds", 0) % 10 == 0:
        logger.info("goto_loop: %d/%d drones got goto, centroids=%d", goto_sent, len(live_drone_ids), len(centroid_map))


async def _update_drones_for_tick(mission: dict, live_drone_ids: set[str], centroid_map: dict, bounds: dict) -> None:
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
                if not has_live_telemetry:
                    drone["lat"] = target["lat"]
                    drone["lon"] = target["lon"]
                drone["role"] = "finder"
                continue

            d_lat = target["lat"] - drone["lat"]
            d_lon = target["lon"] - drone["lon"]
            dist = math.hypot(d_lat, d_lon)
            if dist > TARGET_STOP_RADIUS and not has_live_telemetry:
                drone["lat"] += (d_lat / dist) * SPEED
                drone["lon"] += (d_lon / dist) * SPEED
                drone["lat"] += random.uniform(-JITTER_DEG / 2, JITTER_DEG / 2)
                drone["lon"] += random.uniform(-JITTER_DEG / 2, JITTER_DEG / 2)
                continue

            if target.get("status") in ["detected", "wandering"]:
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
        centroid = centroid_map.get(drone["id"])
        if centroid is not None and not has_live_telemetry:
            d_lat = centroid[0] - drone["lat"]
            d_lon = centroid[1] - drone["lon"]
            dist = math.hypot(d_lat, d_lon)
            if dist > TARGET_STOP_RADIUS:
                drone["lat"] += (d_lat / dist) * SPEED
                drone["lon"] += (d_lon / dist) * SPEED
                drone["lat"] += random.uniform(-JITTER_DEG / 2, JITTER_DEG / 2)
                drone["lon"] += random.uniform(-JITTER_DEG / 2, JITTER_DEG / 2)
            _bounce_entity(drone, bounds, d_lat, d_lon)
        elif not has_live_telemetry:
            if "vx" not in drone:
                angle = random.uniform(0, 2 * math.pi)
                drone["vx"] = SPEED * math.cos(angle)
                drone["vy"] = SPEED * math.sin(angle)
            drone["lat"] += drone["vx"]
            drone["lon"] += drone["vy"]
            _bounce_entity(drone, bounds, drone["vx"], drone["vy"])


def _update_targets_for_tick(mission: dict, bounds: dict) -> None:
    if "targets" not in mission:
        return

    for target in mission["targets"]:
        if target.get("status", "wandering") != "wandering":
            continue
        if "vx" not in target:
            angle = random.uniform(0, 2 * math.pi)
            target["vx"] = (SPEED / 2) * math.cos(angle)
            target["vy"] = (SPEED / 2) * math.sin(angle)
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
            target["status"] = "detected"
            target["assigned_drone_id"] = nearest_drone["id"]
            nearest_drone["assigned_target_id"] = target["id"]
            nearest_drone["role"] = None


async def _finalize_mission_progress(mission: dict) -> bool:
    all_targets_found = False
    if "targets" in mission and mission["targets"]:
        all_targets_found = all(t.get("status") == "found" for t in mission["targets"])
        if all_targets_found:
            mission["status"] = "complete"
            mission["progress"] = 100.0

    if mission.get("status") == "running" and mission["progress"] < 100.0:
        mission["progress"] += 0.75
    if mission["progress"] >= 100.0:
        mission["progress"] = 100.0
        if mission.get("status") == "running":
            if "targets" in mission:
                for target in mission["targets"]:
                    if target.get("status") == "found":
                        continue
                    target["status"] = "found"
                    assigned_drone_id = (
                        target.get("confirming_drone_id")
                        or target.get("finder_drone_id")
                        or target.get("assigned_drone_id")
                    )
                    for drone_id_key in ("confirming_drone_id", "finder_drone_id", "assigned_drone_id"):
                        drone = _find_drone(mission, target.get(drone_id_key))
                        if drone:
                            drone["assigned_target_id"] = None
                            drone["role"] = None
                    await _emit_target_found(mission, target, assigned_drone_id)
            mission["status"] = "complete"
            all_targets_found = True

    return all_targets_found


async def _broadcast_mission_tick(mission_id: str, mission: dict) -> None:
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
    if mission_id not in missions_db:
        return

    mission = missions_db[mission_id]
    mission.setdefault("_found_target_ids", [])
    mission.setdefault("elapsed_seconds", 0)

    while mission["status"] == "running":
        mission["elapsed_seconds"] = mission.get("elapsed_seconds", 0) + 1
        bounds = mission["bounds"]
        live_drone_ids = _sync_mission_drones_with_sitl(mission)
        centroid_map = _build_centroid_map(mission)

        _rearm_live_drones_if_needed(mission, live_drone_ids)
        _send_live_drone_gotos(mission, live_drone_ids, centroid_map)
        await _update_drones_for_tick(mission, live_drone_ids, centroid_map, bounds)
        _update_targets_for_tick(mission, bounds)
        all_targets_found = await _finalize_mission_progress(mission)
        await _broadcast_mission_tick(mission_id, mission)

        if all_targets_found:
            break

        await asyncio.sleep(1.0)
