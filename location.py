from scripts.swarm_command import connect_all, send_command
from pymavlink import mavutil
import requests
import pyned2lla
import math
import time
import numpy as np

# Conversion constants
D2R = math.pi / 180.0
R2D = 180.0 / math.pi

def get_drones_locations(conns):
    """
    Connect to multiple drones and return their GPS locations.
    """
    locations = []

    for _, conn in conns:
        # Request GPS position
        send_command(conn, mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE, 0, p1=mavutil.mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT)

        msg = conn.recv_match(type='GLOBAL_POSITION_INT', blocking=True)

        lat = msg.lat / 1e7
        lon = msg.lon / 1e7
        alt = msg.alt / 1e3

        locations.append((lat, lon, alt))

    return np.array(locations)

# Not used 
def send_location(conn, lat, lon, rel_alt):
    """
    Move vehicle to a specific lat/lon at a relative altitude using COMMAND_LONG.
    """
    send_command(conn, mavutil.mavlink.MAV_CMD_DO_REPOSITION, conn.target_system, p1=-1, p2=1, p5=lat, p6=lon, p7=rel_alt)

def get_elevation_open(lat, lon):
    url = f"https://api.opentopodata.org/v1/srtm90m?locations={lat},{lon}"
    r = requests.get(url).json()
    return r["results"][0]["elevation"]

if __name__ == "__main__":
    conns = connect_all()
    initial_locations = get_drones_locations(conns)
    print(initial_locations)
    
    for i, (_, conn) in enumerate(conns):
        # assume ready to move for now
        (lat0, lon0, alt0) = initial_locations[i] # get location of drone
        (north, east, down) = 1334.3, -2543.6, 0
        (lat, lon, alt) = pyned2lla.ned2lla(lat0 * D2R, lon0 * D2R, alt0, north, east, down, pyned2lla.wgs84()) # convert to lat/lon
        send_location(conn, lat, lon, 100) # send command to move drone to new location (relative altitude)

    time.sleep(10) # wait for drones to move
    
    after_locations = get_drones_locations(conns)
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