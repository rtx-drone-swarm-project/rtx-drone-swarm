"""Routes for inspecting the SITL bridge and manually testing dispatch."""

import asyncio

from fastapi import APIRouter, HTTPException

from app.sitl import sitl_bridge


router = APIRouter()


@router.post("/sitl/test-dispatch/{sysid}")
async def test_dispatch_single(sysid: int, alt: float = 30.0):
    """Dispatch a connected SITL drone to its current coordinates for smoke testing."""
    states = sitl_bridge.get_states_by_sysid()
    state = states.get(sysid)
    if state is None:
        raise HTTPException(status_code=404, detail=f"sysid {sysid} not connected")

    lat = state.get("lat", 0.0)
    lon = state.get("lon", 0.0)
    conn = sitl_bridge._get_conn(sysid)
    conn_info = (
        {
            "address": getattr(conn, "address", None),
            "target_system": getattr(conn, "target_system", None),
            "prearm_ok": state.get("prearm_ok"),
            "ekf_ok": state.get("ekf_ok"),
        }
        if conn
        else None
    )
    result = await asyncio.to_thread(sitl_bridge.dispatch_drone, sysid, lat, lon, alt, str(sysid))
    post_state = sitl_bridge.get_states_by_sysid().get(sysid, {})
    result["conn_info"] = conn_info
    result["post_state"] = {k: post_state.get(k) for k in ("armed", "mode")}
    return result


@router.get("/sitl/status")
def sitl_status():
    """Return the bridge configuration plus the latest telemetry snapshot per drone."""
    states = sorted(sitl_bridge.get_states_by_sysid().values(), key=lambda row: row["sysid"])
    return {
        "host": sitl_bridge.host,
        "base_port": sitl_bridge.base_port,
        "port_step": sitl_bridge.port_step,
        "configured_count": sitl_bridge.count,
        "connected_count": len(states),
        "last_connect_error": sitl_bridge._last_connect_error,
        "drones": states,
    }
