from scripts.swarm_command import connect_all, send_command
from pymavlink import mavutil

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
        alt = msg.relative_alt / 1000.0  # mm → meters

        locations.append((lat, lon, alt))

    return locations

def send_location(conn, north, east, down):
    """
    Move vehicle by a local NED offset (meters) once using COMMAND_LONG.
    """
    send_command(conn, mavutil.mavlink.MAV_CMD_DO_REPOSITION, p1=north, p2=east, p3=down)
