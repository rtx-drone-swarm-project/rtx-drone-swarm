import numpy as np

def compare_centroids(old_centroids, new_centroids, epsilon=0.1):
    """
    Compares two sets of centroids and returns True if they are close enough.
    """
    return np.max(np.linalg.norm(old_centroids - new_centroids, axis=1)) < epsilon

def sample_get_centroids(centroids, new_centroids, alpha=0.2):
    """
    Sample function to move centroids towards new centroids by a fraction alpha. Placeholder for simulator API call.
    """
    return centroids + alpha * (new_centroids - centroids)

def lloyd_step(X, centroids, alpha=0.2):
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

    # if compare_centroids(centroids, new_centroids, epsilon=0.5):  # check for convergence
    #     return centroids, labels    
    
    centroids = sample_get_centroids(centroids, new_centroids, alpha) # smooth movement towards new centroids

    return centroids, labels

def run_lloyd(X, centroids, n_iters=100, alpha=0.2, epsilon=0.1):
    """
    Runs Lloyd until convergence (centroid movement < epsilon) or max iterations.
    """
    for _ in range(n_iters):
        new_centroids, labels = lloyd_step(X, centroids, alpha)
        # Check convergence
        if compare_centroids(centroids, new_centroids, epsilon):
            print(_)
            break

        centroids = new_centroids

    return centroids, labels