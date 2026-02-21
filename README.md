# RTX – AI-Based Drone Swarm in Search and Rescue

## Team
- Louie Gutierrez
- Madison Lin (team lead)
- Kaydee Reyes
- Lawrence Tam
- Ian Tang

## Sponsor
Sponsor: RTX  
Sponsor Liaisons: Simon Wong, Alex Joseph  
Faculty Advisor: Prof. Gago-Masague


# ArduPilot SITL Windows Setup:
- Website Instructions - https://ardupilot.org/dev/docs/sitl-on-windows-wsl.html

## Prerequisites:
### Install WSL
Open PowerShell as Administrator and run:

```powershell
wsl --install
```
After Reboot, Ubuntu should ask you to create a username and password

ONLY IF UBUNTU DOES NOT INSTALL AUTOMATICALLY run:
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
If you want to use VSCode with WSL follow this link: https://ardupilot.org/dev/docs/editing-the-code-with-vscode.html#editing-the-code-with-vscode

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
