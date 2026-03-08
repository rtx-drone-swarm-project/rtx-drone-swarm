import time
import numpy as np
import location
import pyned2lla
import math

D2R = math.pi / 180.0
R2D = 180.0 / math.pi

def compare_centroids(old_centroids, new_centroids, epsilon=0.1):
    """
    Compares two sets of centroids and returns True if they are close enough.
    """
    return np.max(np.linalg.norm(old_centroids - new_centroids, axis=1)) < epsilon

def lloyd_step(X, centroids):
    """
    Performs one iteration of Lloyd's algorithm.
    """
    k = len(centroids) # number of centroids

    distances = np.linalg.norm(X[:, np.newaxis] - centroids, axis=2) # compute distances from points to centroids
    labels = np.argmin(distances, axis=1) # assign points to nearest centroid

    new_centroids = []

    for i in range(k): # compute new centroid for each
        cluster_points = X[labels == i]

        if len(cluster_points) > 0: # if cluster has points, move towards mean, else random point in subregion
            target = cluster_points.mean(axis=0)
        else:
            target = X[np.random.randint(0, len(X))]

        new_centroids.append(target)

    new_centroids = np.array(new_centroids)
    
    return new_centroids, labels

def run_lloyd(X, drones, lat, lon, n_iters=100, epsilon=0.1):
    """
    Runs Lloyd until convergence (centroid movement < epsilon) or max iterations.
    """
    for _ in range(n_iters):
        centroids = location.get_drones_locations(drones)[:, :2] # initial centroids from drone locations
        for i in range(len(centroids)):
            centroids[i] = pyned2lla.lla2ned(lat*D2R, lon*D2R, 0, centroids[i][0]*D2R, centroids[i][1]*D2R, 0, pyned2lla.wgs84())[:2] # convert to NED coordinates
        new_centroids, labels = lloyd_step(X, centroids)

        # Check convergence
        if compare_centroids(centroids, new_centroids, epsilon):
            break

        # print("Centroids:", centroids)
        # print("New centroids:", new_centroids)
        
        for i in range(len(centroids)):
            centroids[i] = pyned2lla.ned2lla(lat*D2R, lon*D2R, 0, new_centroids[i][0], new_centroids[i][1], 0, pyned2lla.wgs84())[:2] # convert back to lat/lon

        centroids *= R2D # convert to degrees
        
        location.send_location(drones, centroids[:, 0], centroids[:, 1], [50]*len(centroids)) # send new centroids as target locations to drones
        time.sleep(10)

    return centroids, labels

if __name__ == "__main__":
    from scripts.connect_swarm import Swarm
    # start swarm
    swarm = Swarm()

    swarm.connect(count=5) # number of drones

    swarm.set_mode_all("GUIDED")
    time.sleep(3)

    swarm.arm_all()

    swarm.takeoff_all(40)

    time.sleep(30)

    # generate full map
    full_width=100
    full_height=100
    sub_x_min=50
    sub_x_max=90
    sub_y_min=50
    sub_y_max=90

    x_coords = np.arange(full_width)
    y_coords = np.arange(full_height)

    xx, yy = np.meshgrid(x_coords, y_coords)
    full_X = np.column_stack([xx.ravel(), yy.ravel()])

    # subregion to search
    # mask = (
    #     (full_X[:, 0] >= sub_x_min) & (full_X[:, 0] < sub_x_max) &
    #     (full_X[:, 1] >= sub_y_min) & (full_X[:, 1] < sub_y_max)
    # )

    # X = full_X[mask]

    full_X *= 10 # scale, default unit is meters

    centroids, labels = run_lloyd(full_X, swarm.drones, lat=-35.363, lon=149.165, n_iters=100, epsilon=0.1)