# SITL Quickstart

This guide contains the detailed setup and runbook notes for ArduPilot SITL. Use it if you need to build the simulator for the first time, run the project outside Docker, or troubleshoot host/container networking.

## Supported Demo Flow

The primary demo path for this repo is:

1. Build ArduPilot SITL on the host machine.
2. Copy `.env.example` to `.env`.
3. Start the app stack, including SITL:

```bash
docker compose up --build
```

If you only need to rebuild the frontend and backend images, run:

```bash
docker compose build
```

4. Verify telemetry:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/sitl/status
```

Expected result:
- `/health` returns `{"ok": true}`
- `/sitl/status` reports `connected_count > 0`

## Recommended Startup

Use Docker Compose as the default local startup path. Compose now starts a dedicated `sitl` service that runs `scripts/launch_sitl.sh` inside a container and mounts your host ArduPilot checkout at runtime. Configure host-specific values such as `ARDUPILOT_PATH` in a repo-local `.env` file.

## General Prerequisites

- Docker Engine 24+ with the Docker Compose V2 plugin (`docker compose`), or Docker Desktop 4+ on macOS/Windows.
- A full ArduPilot checkout on the host machine. The SITL Docker image does not bundle ArduPilot; Compose bind-mounts your host `ARDUPILOT_PATH` into the container at `/ardupilot`.
- `ARDUPILOT_PATH` must point to the ArduPilot repository root, not `ArduCopter` or another subdirectory. The path is valid when this command succeeds:

```bash
test -f "$ARDUPILOT_PATH/Tools/autotest/sim_vehicle.py"
```

For native host runs without Docker, install the platform-specific packages below plus the SITL Python helpers (`MAVProxy`, `empy==3.3.4`, `future`, and `pyserial`) in the Python environment used to run ArduPilot.

## Ubuntu / Linux Setup

Official reference: [ArduPilot Linux setup](https://ardupilot.org/dev/docs/building-setup-linux.html)

### 1. Install host packages

```bash
sudo apt update
sudo apt install -y git build-essential python3-pip
```

### 2. Clone this repo

```bash
git clone https://github.com/rtx-drone-swarm-project/rtx-drone-swarm.git
cd rtx-drone-swarm
```

### 3. Clone ArduPilot

```bash
cd ~
git clone --recurse-submodules https://github.com/ArduPilot/ardupilot.git
cd ardupilot
git submodule update --init --recursive
```

### 4. Install ArduPilot dependencies

```bash
Tools/environment_install/install-prereqs-ubuntu.sh -y
source ~/.profile
```

### 5. Install native SITL helpers and repo dependencies

```bash
python3 -m pip install MAVProxy empy==3.3.4 future pyserial
cd ~/rtx-drone-swarm
python3 -m pip install -r requirements.txt
python3 -m pip install -r backend/requirements.txt
```

On Ubuntu releases that block system-wide Python installs, use a virtual environment or append `--break-system-packages` to the `python3 -m pip install ...` commands.

### 6. Build SITL

```bash
cd ~/ardupilot
./waf configure --board sitl
./waf copter
```

### 7. Configure this repo

```bash
cd ~/rtx-drone-swarm
cp .env.example .env
```

Set `ARDUPILOT_PATH` in `.env` to your ArduPilot checkout, for example:

```bash
ARDUPILOT_PATH=/home/your-user/ardupilot
```

Verify it points to the ArduPilot root:

```bash
set -a
source .env
set +a
test -f "$ARDUPILOT_PATH/Tools/autotest/sim_vehicle.py"
```

You can now run the default Docker Compose flow or use the host-only run mode below.

## macOS Setup

Official references:
- https://ardupilot.org/dev/docs/building-setup-mac.html
- https://ardupilot.org/dev/docs/SITL-setup-landingpage.html

### 1. Install Xcode Command Line Tools

```bash
xcode-select --install
```

### 2. Install Homebrew

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 3. Clone ArduPilot

```bash
cd ~
git clone --recurse-submodules https://github.com/ArduPilot/ardupilot.git
cd ardupilot
```

### 4. Install ArduPilot dependencies

Recommended:

```bash
sh ./Tools/environment_install/install-prereqs-mac.sh
```

Reload your shell after the script finishes:

```bash
source ~/.zshrc
```

Manual fallback:

```bash
brew update
brew install genromfs gcc-arm-none-eabi gawk
pip3 install pyserial future empy==3.3.4
```

### 5. Build SITL

```bash
./waf configure --board sitl
./waf copter
```

### 6. Install MAVProxy and repo dependencies

```bash
brew install readline
pip3 install MAVProxy future pyserial empy==3.3.4
cd <repo-root>
pip3 install -r requirements.txt
pip3 install -r backend/requirements.txt
```

### 7. Test single-vehicle SITL

```bash
cd ~/ardupilot/ArduCopter
../Tools/autotest/sim_vehicle.py -v ArduCopter -f quad --map --console
```

In the MAVProxy console:

```bash
mode guided
arm throttle
takeoff 40
```

Land with:

```bash
mode rtl
```

## Windows / WSL Setup

Official reference:
- https://ardupilot.org/dev/docs/sitl-on-windows-wsl.html

### 1. Install WSL

Run in PowerShell as Administrator:

```powershell
wsl --install
```

If Ubuntu does not install automatically:

```powershell
wsl --install -d Ubuntu
```

### 2. Install Git inside WSL

```bash
sudo apt-get update
sudo apt-get install -y git gitk git-gui build-essential python3-pip
```

### 3. Clone this repo

```bash
git clone https://github.com/rtx-drone-swarm-project/rtx-drone-swarm.git
cd rtx-drone-swarm
```

### 4. Clone ArduPilot

```bash
cd ~
git clone --recurse-submodules https://github.com/ArduPilot/ardupilot.git
cd ardupilot
git submodule update --init --recursive
```

### 5. Install ArduPilot dependencies

```bash
Tools/environment_install/install-prereqs-ubuntu.sh -y
source ~/.profile
```

### 6. Install MAVProxy and repo dependencies

```bash
python3 -m pip install MAVProxy empy==3.3.4 future gnureadline pyserial
cd ~/rtx-drone-swarm
python3 -m pip install -r requirements.txt
python3 -m pip install -r backend/requirements.txt
```

On Ubuntu releases that block system-wide Python installs, use a virtual environment or append `--break-system-packages` to the `python3 -m pip install ...` commands.

### 7. Test single-vehicle SITL

```bash
cd ~/ardupilot/ArduCopter
../Tools/autotest/sim_vehicle.py --map --console
```

In the MAVProxy console:

```bash
mode guided
arm throttle
takeoff 40
```

Land with:

```bash
mode rtl
```

## Swarm Commands

Start the default 15-drone swarm:

```bash
./scripts/launch_sitl.sh 15
```

Start with a custom parameter file:

```bash
./scripts/launch_sitl.sh 15 ./scripts/sitl_params.param
```

In another terminal, send commands:

```bash
python3 scripts/swarm_command.py status
python3 scripts/swarm_command.py arm
python3 scripts/swarm_command.py takeoff 5
python3 scripts/swarm_command.py hover
```

## Alternative Run Modes

### Host SITL + host backend

Use this when you want to run the system without Docker or when you want the simplest setup for telemetry debugging. This path uses three terminal windows.

1a. Verify `ARDUPILOT_PATH` points to the ArduPilot repo root:

```bash
set -a
source .env
set +a
test -f "$ARDUPILOT_PATH/Tools/autotest/sim_vehicle.py"
```

1b. Start SITL:

```bash
./scripts/launch_sitl.sh
```

2. Start the backend (override `SITL_HOST` — `.env` defaults to `sitl` for Docker):

```bash
SITL_HOST=127.0.0.1 PYTHONPATH=backend uvicorn app.main:app --host 0.0.0.0 --port 8000
```

3. Start the frontend separately (`VITE_API_PORT` must match the backend port):

```bash
cd frontend
npm install
VITE_API_PORT=8000 npm run dev
```

4. Verify:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/sitl/status
```

**Host-only build check (no Docker):** from the repo root after the Ubuntu steps above:

```bash
python3 -m pip install -r requirements.txt -r backend/requirements.txt
cd backend && pytest tests/ -q
cd ../frontend && npm ci && npm test -- --run && npm run build
```

ArduPilot SITL must be built on the host (`./waf configure --board sitl && ./waf copter` in `$ARDUPILOT_PATH`) before `./scripts/launch_sitl.sh` will start vehicles.

### Docker Compose SITL + Docker backend

This is the default containerized flow. Compose starts a separate `sitl` service, and the backend reaches it over the internal Docker network using the hostname `sitl`.

1. Create `.env` and set `ARDUPILOT_PATH`:

```bash
cp .env.example .env
```

2. Start the stack:

```bash
docker compose up --build
```

3. Verify telemetry:

```bash
curl http://localhost:8000/sitl/status
```

Expected result:
- `connected_count > 0`
- live drone entries with `lat`, `lon`, `alt`, `mode`, and `armed`

### Multi-host deployment

If SITL and the backend run on different machines, set `SITL_HOST` for the backend to a host or DNS name that exposes the TCP SITL ports.

## Troubleshooting

- **After Docker Compose SITL, host `./scripts/launch_sitl.sh` or `./waf copter` fails** — the `sitl` service bind-mounts your host `ARDUPILOT_PATH` and `sim_vehicle.py` reconfigures/rebuilds SITL inside the container. That invalidates the host WAF cache (`invalid lock file`, `run "waf configure" first`). On the host: `cd "$ARDUPILOT_PATH" && rm -f .lock-waf_* && ./waf configure --board sitl && ./waf copter`, then retry. Expect a multi-minute rebuild. To avoid ping-ponging, use either Docker Compose or host-native SITL for a given work session, not both against the same checkout without rebuilding.
- **Host backend shows `Temporary failure in name resolution` for `tcp://sitl:5760`** — `.env` sets `SITL_HOST=sitl` for Compose. For host-native runs, start the backend with `SITL_HOST=127.0.0.1` (see [Host SITL + host backend](#host-sitl--host-backend)).
- If `launch_sitl.sh` says ArduPilot is missing, check `ARDUPILOT_PATH` in `.env` or clone ArduPilot locally first.
- If the `sitl` service reports `./Tools/autotest/sim_vehicle.py: No such file or directory`, confirm `ARDUPILOT_PATH` points to the ArduPilot repo root and that `test -f "$ARDUPILOT_PATH/Tools/autotest/sim_vehicle.py"` succeeds on the host.
- If native `launch_sitl.sh` reports `[Errno 2] No such file or directory: 'mavproxy.py'`, install MAVProxy in the Python environment used by ArduPilot: `python3 -m pip install MAVProxy`.
- If `/sitl/status` shows `connected_count: 0`, confirm SITL is still running and that TCP ports `5760`, `5770`, `5780`, and so on are reachable from the backend.
- If Docker is part of your flow, make sure Docker Engine or Docker Desktop is running before `docker compose up --build`, and confirm `docker compose version` works.
- If the `sitl` service exits immediately, confirm `ARDUPILOT_PATH` in `.env` points to a valid local ArduPilot checkout that has already been built for SITL.
- If you recently pulled repo changes, rerun `docker compose up --build` so stale images do not keep older startup behavior.
- If you changed a Dockerfile and want fresh images without starting containers yet, run `docker compose build`.
- If port `8000` or `5173` is already in use, adjust the host port mappings in `docker-compose.yml`.
