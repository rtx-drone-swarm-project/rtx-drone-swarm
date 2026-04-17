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
pip3 install pyserial future empy
```

### 5. Build SITL

```bash
./waf configure --board sitl
./waf copter
```

### 6. Install MAVProxy and repo dependencies

```bash
brew install readline
pip3 install MAVProxy future pyserial empy
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
sudo apt-get install git
sudo apt-get install gitk git-gui
```

### 3. Clone ArduPilot

```bash
git clone --recurse-submodules https://github.com/ArduPilot/ardupilot.git
cd ardupilot
```

### 4. Install ArduPilot dependencies

```bash
Tools/environment_install/install-prereqs-ubuntu.sh -y
source ~/.profile
```

### 5. Install MAVProxy and repo dependencies

```bash
pip install MAVProxy future gnureadline
cd <repo-root>
pip install -r requirements.txt
pip install -r backend/requirements.txt
```

### 6. Test single-vehicle SITL

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

Use this when you want the simplest setup for telemetry debugging.

1. Start SITL:

```bash
./scripts/launch_sitl.sh
```

2. Start the backend:

```bash
PYTHONPATH=backend uvicorn app.main:app --host 0.0.0.0 --port 8000
```

3. Optionally start the frontend separately:

```bash
cd frontend
npm install
npm run dev
```

4. Verify:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/sitl/status
```

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

- If `launch_sitl.sh` says ArduPilot is missing, check `ARDUPILOT_PATH` in `.env` or clone ArduPilot locally first.
- If `/sitl/status` shows `connected_count: 0`, confirm SITL is still running and that TCP ports `5760`, `5770`, `5780`, and so on are reachable from the backend.
- If Docker is part of your flow, make sure Docker Desktop is running before `docker compose up --build`.
- If the `sitl` service exits immediately, confirm `ARDUPILOT_PATH` in `.env` points to a valid local ArduPilot checkout that has already been built for SITL.
- If you changed a Dockerfile and want fresh images without starting containers yet, run `docker compose build`.
- If port `8000` or `5173` is already in use, adjust the host port mappings in `docker-compose.yml`.
