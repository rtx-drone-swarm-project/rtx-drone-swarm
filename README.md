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
./scripts/start_sitl_swarm.sh 15
```

3. In a second terminal, start the app stack:

```bash
docker compose up --build
```

## What You Should See

- Frontend: `http://localhost:5173`
- Backend health: `http://localhost:8000/health`
- SITL telemetry status: `http://localhost:8000/sitl/status`

When SITL is connected correctly, `/sitl/status` should report `connected_count > 0` and include live drone entries.

## Operational Notes

- `scripts/start_sitl_swarm.sh` expects a local ArduPilot checkout at `~/ardupilot` by default. Override with `ARDUPILOT_PATH=/path/to/ardupilot`.
- The default SITL telemetry ports are UDP `14550`, `14560`, `14570`, and so on.
- Docker publishes UDP `14550-14690` to the backend container so host SITL can stream telemetry into the app.
- Stop the swarm with `Ctrl+C` in the SITL terminal. If needed, kill remaining processes with `pkill -f arducopter` and `pkill -f mavproxy`.

## Repository Layout

- `frontend/` React + Leaflet mission UI
- `backend/` FastAPI mission, telemetry, and dispatch service
- `scripts/` SITL swarm launch and command helpers
- `docker-compose.yml` local app stack for frontend + backend

## More Detail

- [SITL quickstart and platform setup](docs/SITL_QUICKSTART.md)
- [Backend overview](backend/README.md)
