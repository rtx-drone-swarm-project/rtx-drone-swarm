# RTX – AI-Based Drone Swarm in Search and Rescue

A capstone prototype for coordinating and monitoring a simulated multi-drone “swarm” for search-and-rescue scenarios.
We will use **ArduPilot SITL** (simulated autopilots), a **web UI** for mission input/visualization, and a **backend service** to connect UI and swarm control (in progress)

## Team
- Madison Lin (team lead)
- Kaydee Reyes
- Lawrence Tam
- Ian Tang
- Louie Gutierrez

## Sponsor
Sponsor: RTX  
Sponsor Liaisons: Simon Wong, Alex Joseph  
Faculty Advisor: Prof. Gago-Masague


# ArduPilot SITL macOS Setup

- **Official docs:** [Building setup (MacOSX)](https://ardupilot.org/dev/docs/building-setup-mac.html) and [SITL setup landing page](https://ardupilot.org/dev/docs/SITL-setup-landingpage.html).
- **To run this project’s swarm:** do the setup below, then clone this repo and follow **Quickstart** from the repo root (use `./scripts/start_sitl_swarm.sh 15`). Also install MAVProxy and script deps (see below).

## Prerequisites

### 1. Xcode Command Line Tools

```bash
xcode-select --install
```

### 2. Homebrew

Install [Homebrew](https://brew.sh/) if needed:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 3. Clone ArduPilot

```bash
cd ~
git clone --recurse-submodules https://github.com/ArduPilot/ardupilot.git
cd ardupilot
```

### 4. Install ArduPilot dependencies (recommended)

From the `ardupilot` directory:

```bash
sh ./Tools/environment_install/install-prereqs-mac.sh
```

Then reload your shell (or run `source ~/.zshrc` or `source ~/.bash_profile`).

**Manual alternative** (if the script fails): install build tools and Python deps:

```bash
brew update
brew install genromfs gcc-arm-none-eabi gawk
# Python deps (use pip3 if you use Python 3 by default)
pip3 install pyserial future empy
```

### 5. Build ArduPilot SITL

From the `ardupilot` directory, configure and build (see [BUILD.md](https://github.com/ArduPilot/ardupilot/blob/master/BUILD.md) in that repo):

```bash
./waf configure --board sitl
./waf copter
```

### 6. MAVProxy and project Python deps

MAVProxy is required for the swarm script. On macOS you can use `readline` from Homebrew:

```bash
brew install readline
pip3 install MAVProxy future pyserial empy
```

If you prefer the same deps as Linux: `pip3 install MAVProxy future gnureadline` (may need `brew install readline` first).

From **this project’s repo root**, install script/backend deps:

```bash
pip3 install -r requirements.txt
pip3 install -r backend/requirements.txt
```

## Testing SITL (single copter)

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

To land: `mode rtl` or `mode land`.

---

# ArduPilot SITL Windows Setup
- Website Instructions - https://ardupilot.org/dev/docs/sitl-on-windows-wsl.html  
- **To run this project’s swarm:** do the setup below in WSL, then clone this repo and follow **Quickstart** from the repo root (use `./scripts/start_sitl_swarm.sh 15` in WSL). Also install MAVProxy: `pip install MAVProxy future gnureadline`.

## Prerequisites:
### Install WSL
Open PowerShell as Administrator and run:

```powershell
wsl --install
```
After Reboot, Ubuntu should ask you to create a username and password

**ONLY IF UBUNTU DOES NOT INSTALL AUTOMATICALLY** run:
```powershell
wsl --install -d Ubuntu
```

## Steps:
### Get Git on WSL
```powershell
sudo apt-get update

sudo apt-get install git

sudo apt-get install gitk git-gui
```

### Clone ArduPilot Repo
```powershell
git clone --recurse-submodules https://github.com/ArduPilot/ardupilot.git
cd ardupilot
```

### Install ArduPilot Dependencies
```powershell
Tools/environment_install/install-prereqs-ubuntu.sh -y
```

### Reload WSL Terminal or Run:
```powershell
source ~/.profile
```

## Testing SITL:
If you want to use VSCode with WSL follow this [link](https://ardupilot.org/dev/docs/editing-the-code-with-vscode.html#editing-the-code-with-vscode)

Navigate to one of the vehicle directories (in this case Copter) and call sim_vehicle.py to start SITL.
```powershell
cd ~/ardupilot/ArduCopter
../Tools/autotest/sim_vehicle.py --map --console
```

Send commands to SITL from the command prompt and observe the results on the map. You should see the altitude increase on the console
```powershell
mode guided
arm throttle
takeoff 40
```

When you’re ready to land you can set the mode to RTL (or LAND).
```powershell
mode rtl
```

---

## Quickstart (See something running)

**Prerequisites for the swarm:** ArduPilot must be built and on your machine (see **ArduPilot SITL macOS Setup** or **ArduPilot SITL Windows Setup** above, or [ArduPilot dev docs](https://ardupilot.org/dev/index.html) for Linux). You also need **MAVProxy** and its deps (`pip install MAVProxy future gnureadline` on Linux/WSL; on macOS see the macOS section). Install script deps from the repo root: `pip install -r requirements.txt`. All commands below are from the **repo root**.

### 1) Run a SITL swarm (n drones)
In a terminal, start the swarm and leave it running:
```bash
./scripts/start_sitl_swarm.sh 15   # 15 for this project; use any number
```

### 2) In another terminal: send swarm commands
```bash
python3 scripts/swarm_command.py status   # confirm all drones are visible
python3 scripts/swarm_command.py arm
python3 scripts/swarm_command.py takeoff 5
python3 scripts/swarm_command.py hover
# python3 scripts/swarm_command.py land   # when done
```
See `scripts/swarm_command.py` for more commands (disarm, rtl, etc.).

**Stop the swarm:** In the terminal where the swarm is running, press **Ctrl+C**. To kill from elsewhere: `pkill -f arducopter; pkill -f mavproxy`.

### 3) (Optional) Run the web app
```bash
docker compose up --build
```
- Frontend: http://localhost:5173  
- Backend: http://localhost:8000/health

## Repository Structure
- `frontend/` - React + leaflet UI
- `backend/` - FastAPI backend (currently /health, MAVLink)
- `scripts/` - Current SITL swarm launcher utilizing MAVLink command tools
- `docker-compose.yml` - local dev stack