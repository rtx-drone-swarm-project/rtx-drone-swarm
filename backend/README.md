# Backend Overview

This backend is the control layer for the drone-swarm demo. It exposes mission APIs over FastAPI, streams telemetry to the frontend over WebSockets, mirrors live ArduPilot SITL state into mission data, and runs the simulation loop that assigns coverage areas, moves simulated entities, and dispatches live drones.

## Runtime Flow

The backend has three main jobs:

1. Accept mission requests over REST.
2. Keep live telemetry available through the SITL bridge and WebSocket broadcasts.
3. Advance missions over time through the simulation loop.

At runtime the flow looks like this:

- `app/main.py` starts FastAPI, mounts routes, initializes benchmark storage, starts the SITL telemetry bridge, and launches idle telemetry broadcasting.
- `app/routes/algorithms.py` exposes dynamically discovered search algorithms for frontend controls.
- `app/routes/missions.py` creates missions, starts them, and triggers background dispatch plus `simulation_loop`.
- `app/routes/benchmark.py` starts headless algorithm comparisons, reads persisted benchmark history, and exports trial rows as CSV.
- `app/benchmark.py` runs paired algorithm scenarios without SITL commands or per-tick broadcasts.
- `app/benchmark_db.py` owns the SQLite schema and query helpers for `backend/data/benchmarks.db`.
- `app/sitl.py` maintains MAVLink TCP connections to SITL drones, tracks readiness and flight state, and sends direct dispatch or goto commands.
- `app/simulation.py` runs the mission tick loop: it syncs live drone telemetry, computes centroid coverage, moves drones and targets, detects findings, derives progress from found targets, and broadcasts mission state.
- `app/ws.py` broadcasts telemetry and mission updates to the frontend over `WS /ws`.

## File Map

### Core app modules

| Path | Responsibility |
|------|----------------|
| `app/main.py` | FastAPI app wiring, CORS setup, lifespan hooks, and symbol re-exports used by tests. |
| `app/settings.py` | Shared constants, helper script paths, SITL host/port defaults, dispatch defaults, and concurrency limits. |
| `app/models.py` | Pydantic request/response models for missions, benchmarks, and dispatch payloads. |
| `app/algorithms/__init__.py` | Dynamic algorithm discovery and registry used by missions, benchmarks, and UI metadata. |
| `app/benchmark.py` | Headless paired-scenario benchmark runner for algorithm comparison. |
| `app/benchmark_db.py` | SQLite schema, persistence helpers, aggregation, and CSV export. |
| `app/missions.py` | Mission-state helpers: sysid resolution, script result normalization, coverage-point assignment, SITL sync, and dispatch preflight shaping. |
| `app/dispatch.py` | Dispatch execution helpers. Supports either direct in-process dispatch through `sitl_bridge` or the external `scripts/swarm_command.py` helper. |
| `app/sitl.py` | `SITLTelemetryBridge`, telemetry cache, readiness polling, direct MAVLink dispatch flow, idle telemetry broadcasting, and frontend-facing SITL snapshots. |
| `app/simulation.py` | Mission tick loop, centroid assignment, target movement, detection/confirmation flow, re-arm logic, and broadcast updates. |
| `app/voronoi.py` | Search-grid generation and one Lloyd relaxation step used to spread drones across the mission area. |
| `app/ws.py` | WebSocket connection manager and broadcast helper. |

### Route modules

| Path | Responsibility |
|------|----------------|
| `app/routes/algorithms.py` | Discovered search algorithm metadata endpoint. |
| `app/routes/health.py` | Lightweight liveness endpoint. |
| `app/routes/benchmark.py` | Metrics compatibility start/history/detail/export endpoints. |
| `app/routes/missions.py` | Mission create/read/start/dispatch/stop/delete endpoints. |
| `app/routes/sitl.py` | SITL bridge inspection and manual dispatch smoke-test endpoints. |
| `app/routes/ws.py` | Telemetry WebSocket endpoint for browser clients. |

## API Surface

### REST endpoints

| Route | Purpose |
|------|---------|
| `GET /health` | Returns `{"ok": true}` when the backend is up. |
| `GET /algorithms` | Returns discovered algorithm keys, labels, descriptions, modules, and class names. |
| `POST /missions` | Creates an in-memory mission from bounds, drones, and optional hikers. |
| `GET /missions/{mission_id}` | Returns the stored mission object. |
| `POST /missions/{mission_id}/start` | Marks a mission running, seeds targets and grid points, optionally starts SITL, and launches simulation plus startup dispatch. |
| `GET /missions/{mission_id}/metrics` | Returns mission coverage and target-find metrics. |
| `POST /missions/{mission_id}/dispatch-targets` | Dispatches specific drones to explicit coordinates through the helper-script flow. |
| `POST /missions/{mission_id}/stop` | Marks a mission stopped and broadcasts the state change. |
| `DELETE /missions/{mission_id}` | Removes a mission from the in-memory store. |
| `GET /sitl/status` | Returns bridge config plus the latest cached state for each connected drone. |
| `POST /sitl/test-dispatch/{sysid}` | Runs a direct dispatch against one connected drone for smoke testing. |
| `POST /benchmark` | Starts a background headless benchmark and returns a persisted `run_id`. |
| `GET /benchmark/runs` | Lists recent benchmark runs. |
| `GET /benchmark/scenarios` | Lists Metrics scenario profiles for the UI selector. |
| `GET /benchmark/{run_id}` | Returns one run, raw trials, and aggregate metric summaries. |
| `GET /benchmark/export?run_id=...` | Exports one benchmark run as CSV. Full local export requires explicit `?all_runs=true`. |

### WebSocket endpoint

| Route | Purpose |
|------|---------|
| `WS /ws` | Pushes telemetry, mission progress, target-found events, and mission status updates to connected clients. |

## Key Functions

These are the functions worth reading first if you need to change behavior.

### Mission lifecycle

- `app/routes/missions.py:start_mission`
  Creates the runtime mission state: initializes progress, creates targets, builds the grid, prepares initial dispatch assignments, launches the simulation task, and optionally kicks off background dispatch.
- `app/routes/missions.py:dispatch_targets`
  Normalizes a dispatch request against mission state, resolves sysids, and runs the helper-script dispatch path.
- `app/missions.py:_prepare_dispatch_assignments`
  Converts API assignments into validated dispatch rows and returns preflight failures for unresolved drones.

### SITL and dispatch

- `app/sitl.py:SITLTelemetryBridge._run`
  Background thread that attempts connections and continuously drains MAVLink messages into the cached state map.
- `app/sitl.py:SITLTelemetryBridge.dispatch_drone`
  The direct dispatch sequence: wait for readiness, set GUIDED, arm, take off, and send a goto target.
- `app/sitl.py:SITLTelemetryBridge.send_goto`
  Lightweight goto command used after a drone is already airborne.
- `app/dispatch.py:run_dispatch_script`
  Shells out to `scripts/swarm_command.py`, then normalizes whatever JSON results the script returns.
- `app/dispatch.py:run_direct_dispatch`
  Uses a bounded thread pool to dispatch multiple drones directly through the in-process SITL bridge.

### Simulation

- `app/simulation.py:simulation_loop`
  Main mission loop. Each tick syncs telemetry, computes centroids, re-arms drones if needed, pushes gotos, moves targets and simulated drones, recalculates progress from found targets, and broadcasts state.
- `app/simulation.py:_build_centroid_map`
  Uses Lloyd relaxation to spread free drones across the search area.
- `app/simulation.py:_update_targets_for_tick`
  Moves wandering targets and assigns a nearby drone when one detects a target.
- `app/simulation.py:_finalize_mission_progress`
  Derives progress from the number of found targets and completes the mission once every target is found.

### Algorithms

- `app/algorithms/__init__.py:discover_algorithms`
  Imports modules in `backend/app/algorithms/` and registers concrete `BaseSearchAlgorithm` subclasses. Set `algorithm_key`, `display_name`, `description`, and `display_order` on the class for stable API keys and clean UI labels.
- `app/routes/algorithms.py:get_algorithms`
  Feeds the Actions panel, Metrics panel, status labels, and summary labels. Frontend algorithm controls should consume this endpoint rather than maintaining a second hardcoded list.

## State and Data Ownership

- Mission state lives in the in-memory `missions_db` dictionary in `app/missions.py`.
- Metrics trial history lives in local SQLite at `backend/data/benchmarks.db`; that file is ignored by git. The backend route/table names still use `benchmark` for compatibility.
- Metrics runs left `running` by a backend restart are marked `failed` on startup so the UI does not poll stale jobs forever.
- Live drone telemetry lives in the bridge cache inside `app/sitl.py`.
- During each simulation tick, live SITL state is copied into the mission's drone list so the frontend receives one coherent mission view.
- The backend does not currently persist missions to a database; a restart clears mission state. Metrics history persists locally unless `backend/data/benchmarks.db` is deleted.

## Local Run and Verification

From the repo root, the simplest backend-only run path is:

```bash
pip3 install -r requirements.txt
pip3 install -r backend/requirements.txt
PYTHONPATH=backend uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Quick checks:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/sitl/status
```

If SITL is running and connected, `/sitl/status` should report `connected_count > 0`.

## Tests

Run the backend test suite from the repo root:

```bash
cd backend
pytest tests/
```

The tests in `tests/test_main.py` cover health, mission lifecycle endpoints, SITL status behavior, and major simulation flows. Algorithm-specific tests such as `tests/test_pmv.py` exercise newer search logic and deterministic benchmark behavior.
