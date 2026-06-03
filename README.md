# RTX: AI-Based Drone Swarm for Search and Rescue

RTX is a capstone prototype for coordinating a simulated multi-drone swarm in search-and-rescue scenarios. The system combines ArduPilot SITL drones, a FastAPI mission and telemetry service, and a React map UI so teams can launch a mission, observe live drone state, and test swarm behavior without physical hardware.

## Why It Matters

This prototype demonstrates how a coordinated drone swarm could help search teams cover large areas faster, monitor vehicle state in real time, and evaluate mission behavior safely in simulation before field deployment.

**Stack**
- ArduPilot SITL for simulated drones
- FastAPI backend for mission control, telemetry, and dispatch
- React + Leaflet frontend for mission planning and visualization

**Sponsor**
- RTX
- Sponsor liaisons: Simon Wong, Alex Joseph
- Faculty advisor: Prof. Gago-Masague

**Team**
- Madison Lin (Team Lead)
- Kaydee Reyes
- Lawrence Tam
- Ian Tang
- Louie Gutierrez

## Prerequisites

The preferred local demo path uses Docker Compose, but the SITL simulator still depends on a full ArduPilot checkout on the host machine.

- Git to clone this repository:

```bash
git clone https://github.com/rtx-drone-swarm-project/rtx-drone-swarm.git
cd rtx-drone-swarm
```

- Docker Engine 24+ with Docker Compose V2 (`docker compose`), or Docker Desktop 4+ on macOS/Windows.
- A full ArduPilot checkout built for SITL. `ARDUPILOT_PATH` must point to the ArduPilot repository root, the directory that contains `Tools/autotest/sim_vehicle.py`.
- For native Ubuntu/Linux setup without Docker, install system build tools and Python package tooling:

```bash
sudo apt update
sudo apt install -y build-essential python3-pip
python3 -m pip install MAVProxy empy==3.3.4 future pyserial
```

If Ubuntu blocks system-wide Python installs, use a virtual environment or rerun the `pip` command with `--break-system-packages`.

## First-Time Setup

1a. If ArduPilot SITL is not installed and built yet, follow [docs/SITL_QUICKSTART.md](docs/SITL_QUICKSTART.md) first.

1b. Copy the local environment template:

```bash
cp .env.example .env
```

2. Edit `.env` and set `ARDUPILOT_PATH` to your local ArduPilot checkout.

3. Verify the path points to the ArduPilot repo root:

```bash
set -a
source .env
set +a
test -f "$ARDUPILOT_PATH/Tools/autotest/sim_vehicle.py"
```

## Run the Demo

These commands assume ArduPilot SITL is already installed and built on the host machine. Docker reads repo-local settings from `.env`, including the ArduPilot path mounted into the SITL service. If you still need to install ArduPilot, follow the one-time setup guide in [docs/SITL_QUICKSTART.md](docs/SITL_QUICKSTART.md).

1. Optional: install repo Python dependencies for host helper scripts and local backend runs. Docker-only runs install service dependencies during image builds.

```bash
pip3 install -r requirements.txt
pip3 install -r backend/requirements.txt
```

2. Create `.env` from the example and set your local paths:

```bash
cp .env.example .env
```

Set `ARDUPILOT_PATH` in `.env` to your local ArduPilot checkout, then start the full stack:

```bash
docker compose up --build
```

If you want to change the published frontend or backend ports, edit `FRONTEND_PORT` and `BACKEND_PORT` in `.env`.

If you only want to refresh the Docker images, run:

```bash
docker compose build
```

To run without Docker, use the host-only path in [docs/SITL_QUICKSTART.md](docs/SITL_QUICKSTART.md#host-sitl--host-backend).

## What You Should See

- Frontend: `http://localhost:5173`
- Dedicated Metrics page: `http://localhost:5173/metrics`
- Backend health: `http://localhost:8000/health`
- SITL telemetry status: `http://localhost:8000/sitl/status`

When SITL is connected correctly, `/sitl/status` should report `connected_count > 0` and include live drone entries. If SITL is still booting, the backend will stay up and `last_connect_error` will explain the current connection failure.

## Operational Notes

- **Docker and host-native SITL share your host ArduPilot checkout** — Compose bind-mounts `ARDUPILOT_PATH`. The `sitl` container runs `waf configure` + `waf copter` on that tree; switching back to `./scripts/launch_sitl.sh` on the host usually requires `rm -f .lock-waf_*` and a host `./waf configure --board sitl && ./waf copter` first. See [docs/SITL_QUICKSTART.md](docs/SITL_QUICKSTART.md#troubleshooting).
- **Host-native backend** — if `.env` sets `SITL_HOST=sitl` (for Compose), override with `SITL_HOST=127.0.0.1` when running `uvicorn` on the host; see [Host SITL + host backend](docs/SITL_QUICKSTART.md#host-sitl--host-backend).
- `scripts/launch_sitl.sh` remains the underlying SITL launcher, but Docker Compose now starts it in a dedicated `sitl` service.
- Algorithm metrics history is stored locally in `backend/data/benchmarks.db`; the database file is gitignored, and CSV plus Markdown report exports are available from the Metrics panel. The backend keeps `/benchmark` routes for compatibility.
- The dedicated Metrics page (`/metrics`) can launch paired runs across multiple scenario profiles with shared parameters, load persisted run history, import raw Metrics CSVs, and export combined CSVs or SVG charts.
- Run Metrics headless (CLI sweeps, scripted scenarios, multi-scale studies) using `python -m app.benchmark_cli`
- `docker compose up --build` builds the backend, frontend, and SITL images.
- Use `docker compose up -d --build` if you want the app stack to keep running in the background.
- Compose auto-loads `.env` from the repo root; use `.env.example` as the template.
- The SITL service bind-mounts your local ArduPilot checkout from `ARDUPILOT_PATH` into `/ardupilot`; Compose will fail fast if that variable is missing.
- The backend connects to the SITL service over the Compose network using the hostname `sitl`.
- Stop the swarm with `Ctrl+C` in the SITL terminal. If needed, kill remaining processes with `pkill -f arducopter` and `pkill -f mavproxy`.

## Repository Layout

- `frontend/` React + Leaflet mission UI
- `backend/` FastAPI mission, telemetry, and dispatch service
- `scripts/` SITL swarm launch and command helpers
- `docker-compose.yml` local app stack for frontend + backend + SITL

## More Detail

- [SITL quickstart and platform setup](docs/SITL_QUICKSTART.md)
- [Backend overview](backend/README.md)
