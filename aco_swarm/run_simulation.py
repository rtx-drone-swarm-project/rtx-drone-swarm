from stigmergy_engine import InMemoryPheromoneGrid, GridConfig
from voronoi_aco_hybrid import VoronoiACOPlanner, DroneState
import matplotlib.pyplot as plt

bounds = {
    "min_lat": 32.70, "max_lat": 32.75,
    "min_lon": -117.20, "max_lon": -117.15,
}

grid_config = GridConfig(
    lat_min=bounds["min_lat"], lat_max=bounds["max_lat"],
    lon_min=bounds["min_lon"], lon_max=bounds["max_lon"],
    rows=50, cols=50,
    evaporation_rate=0.97,
    tick_interval=1.0,
)

planner = VoronoiACOPlanner(bounds, grid_config, n_grid=15, lloyd_interval=10)

drones = [
    DroneState(id=0, lat=32.71, lon=-117.19),
    DroneState(id=1, lat=32.72, lon=-117.18),
    DroneState(id=2, lat=32.73, lon=-117.17),
]

for tick in range(50):
    waypoints = planner.step(drones)
    for drone, (lat, lon) in zip(drones, waypoints):
        print(f"  tick={tick:02d}  drone={drone.id}  → ({lat:.5f}, {lon:.5f})")
        # In real use, send MAVLink goto here; in sim, teleport the drone:
        drone.lat, drone.lon = lat, lon

    if tick % 10 == 0:
        snapshot = planner.pheromone.get_snapshot()
        plt.imshow(snapshot, origin="lower", cmap="hot")
        plt.title(f"Tick {tick}")
        plt.pause(0.1)
        plt.clf()