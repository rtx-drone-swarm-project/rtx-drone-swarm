from scripts.connect_swarm import Swarm
from pymavlink import mavutil
import requests
import pyned2lla
import math
import time
import numpy as np

# Conversion constants
D2R = math.pi / 180.0
R2D = 180.0 / math.pi

def get_drones_locations(drones):
    """
    Connect to multiple drones and return their GPS locations.
    """
    locations = [[0,0,0]] * len(drones)

    for i, drone in enumerate(drones):
        # Request GPS position
        params = [0]*7
        params[0] = mavutil.mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT
        drone.send_command(command=mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE, params=params)

        msg = drone.conn.recv_match(type='GLOBAL_POSITION_INT', blocking=True)

        lat = msg.lat / 1e7
        lon = msg.lon / 1e7
        alt = msg.alt / 1e3

        locations[i] = [lat, lon, alt]
    return np.array(locations)

def send_location(drones, lats, lons, rel_alts):
    """
    Move vehicle to a specific lat/lon at a relative altitude using COMMAND_LONG.
    """
    for i, drone in enumerate(drones):
        drone.goto(lats[i], lons[i], rel_alts[i])

def get_elevation_open(lat, lon):
    url = f"https://api.opentopodata.org/v1/srtm90m?locations={lat},{lon}"
    r = requests.get(url).json()
    return r["results"][0]["elevation"]

if __name__ == "__main__":
    swarm = Swarm()

    swarm.connect(count=12)

    swarm.set_mode_all("GUIDED")
    time.sleep(3)

    swarm.arm_all()

    swarm.takeoff_all(40)

    time.sleep(30)

    initial_locations = get_drones_locations(swarm.drones)
    print(initial_locations)
    
    lats, lons, alts = [], [], []
    for i, drone in enumerate(swarm.drones):
        # assume ready to move for now
        (lat0, lon0, alt0) = initial_locations[i] # get location of drone
        (north, east, down) = 1334.3, -2543.6, 0
        (lat, lon, alt) = pyned2lla.ned2lla(lat0 * D2R, lon0 * D2R, alt0, north, east, down, pyned2lla.wgs84()) # convert to lat/lon
        lats.append(lat)
        lons.append(lon)
        alts.append(alt)

    send_location(swarm.drones, lats, lons, alts) # send command to move drone to new location (relative altitude)

    time.sleep(10) # wait for drones to move
    
    after_locations = get_drones_locations(swarm.drones)
    (initial_lat, initial_lon, initial_alt) = initial_locations[0]
    print(after_locations - initial_locations)
    
    
    
    # Define the origin point (reference location) in degrees
    #(lat0, lon0, alt0) = -35.363, 149.165, 1699

    # Define the NED coordinates (relative to the origin) in meters
    #(north, east, down) = 1334.3, -2543.6, 0

    # Perform the conversion (inputs for lat/lon must be radians)
    #(lat, lon, alt) = pyned2lla.ned2lla(lat0 * D2R, lon0 * D2R, alt0, north, east, down, pyned2lla.wgs84())
    #(north_back, east_back, down_back) = pyned2lla.lla2ned(lat0*D2R, lon0*D2R, alt0, lat, lon, alt, pyned2lla.wgs84())
    
    # Print results
    #print((lat * R2D, lon * R2D, alt))
    #print((north_back, east_back, down_back)) # should be similar to (north, east, down)
    #print(get_elevation_open(lat * R2D, lon * R2D))