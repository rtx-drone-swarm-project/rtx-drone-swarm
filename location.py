from scripts.swarm_command import connect_all, send_command
from pymavlink import mavutil
import requests
import pyned2lla
import math
import numpy as np

# Conversion constants
D2R = math.pi / 180.0
R2D = 180.0 / math.pi

def get_drones_locations():
    """
    Connect to multiple drones and return their GPS locations.
    """
    locations = []
    conns = connect_all()

    for conn in conns:
        # Request GPS position
        send_command(conn, mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE, p1=mavutil.mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT)

        msg = conn.recv_match(type='GLOBAL_POSITION_INT', blocking=True)

        lat = msg.lat / 1e7
        lon = msg.lon / 1e7

        locations.append((lat, lon))

    return np.array(locations)

def send_location(conn, north, east, down):
    """
    Move vehicle by a local NED offset (meters) once using COMMAND_LONG.
    """
    send_command(conn, mavutil.mavlink.MAV_CMD_DO_REPOSITION, p1=north, p2=east, p3=down)

def get_elevation_open(lat, lon):
    url = f"https://api.opentopodata.org/v1/srtm90m?locations={lat},{lon}"
    r = requests.get(url).json()
    return r["results"][0]["elevation"]

if __name__ == "__main__":
    # Define the origin point (reference location) in degrees
    (lat0, lon0, alt0) = 44.532, -72.782, 1699

    # Define the NED coordinates (relative to the origin) in meters
    (north, east, down) = 1334.3, -2543.6, 359.64

    # Perform the conversion (inputs for lat/lon must be radians)
    (lat, lon, alt) = pyned2lla.ned2lla(lat0 * D2R, lon0 * D2R, alt0, north, east, down, pyned2lla.wgs84())

    # Print results in degrees
    print((lat * R2D, lon * R2D, alt))
