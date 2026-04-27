from voronoi import *
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from functools import partial

def compute_pheromone_field(full_X, X, pheromone_matrix):
    # collapse centroid dimension → scalar per point
    intensity = pheromone_matrix.sum(axis=1)

    # normalize
    intensity = intensity / (intensity.max() + 1e-8)

    # map only where X exists
    field = np.zeros(len(full_X))

    # assume X is subset of full_X in same order mask
    field_indices = np.arange(len(full_X))[:len(X)]
    field[field_indices] = intensity

    return field

def update_coverage(centroids, X, coverage_grid, radius=5):
    """
    Marks grid cells as covered if they are within sensor radius
    of any centroid (drone position).
    """
    for c in centroids:
        dists = np.linalg.norm(X - c, axis=1)
        coverage_grid[dists <= radius] = 1

    return coverage_grid

def compute_coverage_stat(coverage_grid):
    return np.sum(coverage_grid) / len(coverage_grid)

# update function for animation
def update(frame):
    global centroids, old_centroids, pheromone_matrix, coverage_grid
    
    new_centroids, labels, pheromone_matrix = lloyd_step_aco(X, centroids, old_centroids, pheromone_matrix) # calls lloyd step to update centroids and labels

    old_centroids = centroids
    centroids = new_centroids
    
    coverage_grid = update_coverage(centroids, X, coverage_grid, radius=5)
    coverage_stat = compute_coverage_stat(coverage_grid)

    print(f"Coverage: {coverage_stat:.3f}")

    # scatter.set_array(labels) # updates scatter and centroids
    centroid_plot.set_offsets(centroids)
    field = pheromone_matrix.sum(axis=1)
    field = field / (field.max() + 1e-8)

    pheromone_scatter.set_array(
        np.pad(field, (0, len(full_X) - len(field)), mode='constant')
    )
    pheromone_scatter.set_alpha(0.7)


    time.sleep(0.3) # small delay for better visualization
    return scatter, centroid_plot, pheromone_scatter # returns updated scatter and centroid plot for animation

def grid_setup(full_width=100, full_height=100, sub_x_min=50, sub_x_max=90, sub_y_min=50, sub_y_max=90):
    # generate full map
    x_coords = np.arange(full_width)
    y_coords = np.arange(full_height)

    xx, yy = np.meshgrid(x_coords, y_coords)
    full_X = np.column_stack([xx.ravel(), yy.ravel()])

    # subregion to search
    mask = (
        (full_X[:, 0] >= sub_x_min) & (full_X[:, 0] < sub_x_max) &
        (full_X[:, 1] >= sub_y_min) & (full_X[:, 1] < sub_y_max)
    )

    X = full_X[mask]

    return X, full_X, sub_x_min, sub_x_max, sub_y_min, sub_y_max

def generate_random_centroids(k=15, full_width=100, full_height=100, sub_x_min=50, sub_x_max=90, sub_y_min=50, sub_y_max=90):
    centroids = []

    while len(centroids) < k:
        x = np.random.uniform(0, full_width) # generates random coordinate in map
        y = np.random.uniform(0, full_height)

        if not (sub_x_min <= x < sub_x_max and # checks outside subregion
                sub_y_min <= y < sub_y_max):
            centroids.append([x, y])

    return np.array(centroids)

def plot_setup(full_X, X, sub_x_min, sub_x_max, sub_y_min, sub_y_max, centroids, full_width=100, full_height=100):
    fig, ax = plt.subplots(figsize=(8, 8)) # plot setup

    #ax.scatter(full_X[:, 0], full_X[:, 1], # plot points in full map (for grid)
    #        c='lightgray', s=5)

    scatter = ax.scatter(X[:, 0], X[:, 1], # plot points in subregion (for grid)
                        s=10)

    scatter.set_cmap('tab20') # set colormap for clusters

    pheromone_scatter = ax.scatter(
        X[:, 0],
        X[:, 1],
        c='white',
        s=5,
        alpha=0.0,
        cmap='inferno',
        vmin=0.1, 
        vmax=1.0
    )

    centroid_plot = ax.scatter(centroids[:, 0], # plot centroids
                            centroids[:, 1],
                            c='black',
                            s=200,
                            marker='X')

    rect = plt.Rectangle((sub_x_min, sub_y_min), # rectangle for subregion
                        sub_x_max - sub_x_min - 1,
                        sub_y_max - sub_y_min - 1,
                        fill=False,
                        edgecolor='red',
                        linewidth=2)

    ax.add_patch(rect)

    ax.set_xlim(0, full_width)
    ax.set_ylim(0, full_height)
    ax.set_aspect('equal', adjustable='box')
    ax.set_title("Lloyd's Algorithm")

    return fig, ax, scatter, centroid_plot, pheromone_scatter

def run_animated(n_iters=100, fig=None):
    ani = FuncAnimation(fig, update, frames=n_iters, interval=200, repeat=False) # over time animation

    plt.show()

def run_final(X, centroids, n_iters=100, alpha=0.2, epsilon=0.1, centroid_plot=None):
    centroid_plot.remove() # remove centroid plot so no extra centroids show up

    centroids, labels = run_lloyd(X, centroids, n_iters=n_iters, alpha=alpha, epsilon=epsilon) # final run of lloyd without animation
    
    ax.scatter(
        X[:, 0],
        X[:, 1],
        c=labels, # color by assigned cluster
        s=10,
        cmap='tab20',
    )

    ax.scatter(centroids[:, 0], # plot centroids
                            centroids[:, 1],
                            c='black',
                            s=200,
                            marker='X')

    rect = plt.Rectangle((sub_x_min, sub_y_min), # rectangle for subregion again so it shows on top
                        sub_x_max - sub_x_min - 1,
                        sub_y_max - sub_y_min - 1,
                        fill=False,
                        edgecolor='red',
                        linewidth=2)

    ax.add_patch(rect)

    plt.show()

if __name__ == "__main__":
    X, full_X, sub_x_min, sub_x_max, sub_y_min, sub_y_max = grid_setup(sub_x_min=10, sub_x_max=90, sub_y_min=10, sub_y_max=90)

    # create initial centroids outside the subregion
    np.random.seed(42)
    centroids = generate_random_centroids(k=15, full_width=100, full_height=100, sub_x_min=sub_x_min, sub_x_max=sub_x_max, sub_y_min=sub_y_min, sub_y_max=sub_y_max)
    old_centroids = centroids
    pheromone_matrix = np.ones((len(X), len(centroids))) # initialize pheromone matrix for ACO

    fig, ax, scatter, centroid_plot, pheromone_scatter = plot_setup(full_X, X, sub_x_min, sub_x_max, sub_y_min, sub_y_max, centroids)
    coverage_grid = np.zeros(len(X), dtype=np.uint8)

    run_animated(n_iters=100, fig=fig)

    # run_final(X, centroids, n_iters=100, alpha=0.2, epsilon=0.1, centroid_plot=centroid_plot)
