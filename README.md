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

## Run the Demo

These commands assume ArduPilot SITL is already installed and built on the host machine. If not, follow the one-time setup guide in [docs/SITL_QUICKSTART.md](docs/SITL_QUICKSTART.md).

1. Install repo Python dependencies:

```bash
pip3 install -r requirements.txt
```

2. Start the simulated swarm from the repo root:

```bash
./scripts/launch_sitl.sh
```

`launch_sitl.sh` is the main SITL launcher for this repo. By default it starts a 15-drone ArduCopter swarm and loads `scripts/sitl_params.param`. You can also pass an explicit drone count and param file:

```bash
./scripts/launch_sitl.sh 15
./scripts/launch_sitl.sh 15 ./scripts/sitl_params.param
```

3. In a second terminal, start the app stack:

```bash
docker compose up --build
```

If you only want to refresh the Docker images, run:

```bash
docker compose build
```

## What You Should See

- Frontend: `http://localhost:5173`
- Backend health: `http://localhost:8000/health`
- SITL telemetry status: `http://localhost:8000/sitl/status`

When SITL is connected correctly, `/sitl/status` should report `connected_count > 0` and include live drone entries. If SITL is still booting, the backend will stay up and `last_connect_error` will explain the current connection failure.

## Operational Notes

- `scripts/launch_sitl.sh` expects a local ArduPilot checkout at `~/ardupilot` by default. Override with `ARDUPILOT_PATH=/path/to/ardupilot`.
- `docker compose up --build` builds the backend from `backend/Dockerfile` and the frontend from `frontend/Dockerfile`.
- Use `docker compose up -d --build` if you want the app stack to keep running in the background.
- The backend connects directly to host SITL over TCP on ports `5762`, `5772`, `5782`, and so on.
- In Docker, the backend resolves the host via `host.docker.internal`.
- Stop the swarm with `Ctrl+C` in the SITL terminal. If needed, kill remaining processes with `pkill -f arducopter` and `pkill -f mavproxy`.

## Repository Layout

- `frontend/` React + Leaflet mission UI
- `backend/` FastAPI mission, telemetry, and dispatch service
- `scripts/` SITL swarm launch and command helpers
- `docker-compose.yml` local app stack for frontend + backend

## More Detail

- [SITL quickstart and platform setup](docs/SITL_QUICKSTART.md)
- [Backend overview](backend/README.md)
