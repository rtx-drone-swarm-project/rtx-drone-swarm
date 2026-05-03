"""
FastAPI entry: wires routers, SITL bridge lifespan, and re-exports symbols
tests and route helpers expect on ``app.main``.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.dispatch import run_direct_dispatch, run_dispatch_script
from app.missions import (
    missions_db,
    _mission_drone_to_sysid_map,
    _normalize_script_results,
    _sync_mission_drones_with_sitl,
)
from app.settings import DEFAULT_DISPATCH_HOST, DEFAULT_DISPATCH_TIMEOUT_SECONDS
from app.simulation import simulation_loop
from app.sitl import idle_sitl_telemetry_loop, sitl_bridge
from app.ws import manager
from app.benchmark_db import init_db

from app.routes import algorithms, benchmark, health, missions, sitl as sitl_routes, ws as ws_routes

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start background SITL telemetry on startup and stop it during shutdown."""
    init_db()
    sitl_bridge.start()
    idle_task = asyncio.create_task(idle_sitl_telemetry_loop())
    try:
        yield
    finally:
        idle_task.cancel()
        try:
            await idle_task
        except asyncio.CancelledError:
            pass
        sitl_bridge.stop()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(algorithms.router)
app.include_router(missions.router)
app.include_router(benchmark.router)
app.include_router(ws_routes.router)
app.include_router(sitl_routes.router)
