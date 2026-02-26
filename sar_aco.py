import random
import math
from collections import deque
import numpy as np

GRID_SIZE = 40  # 40x40 cells

class Cell:
    __slots__ = ("r", "c", "drone", "pheromone", "priority")
    def __init__(self, r, c):
        self.r = r
        self.c = c
        self.drone = -1
        self.pheromone = 0.0
        self.priority = random.random()

def make_grid():
    return [[Cell(r, c) for c in range(GRID_SIZE)] for r in range(GRID_SIZE)]

def neighbors(grid, r, c):
    for dr, dc in ((-1,0),(1,0),(0,-1),(0,1)):
        nr, nc = r+dr, c+dc
        if 0 <= nr < GRID_SIZE and 0 <= nc < GRID_SIZE:
            yield grid[nr][nc]

def spread_bases(num_drones):
    bases = []
    for i in range(num_drones):
        angle = 2 * math.pi * i / num_drones
        r = int(round(GRID_SIZE/2 + (GRID_SIZE * 0.35) * math.cos(angle)))
        c = int(round(GRID_SIZE/2 + (GRID_SIZE * 0.35) * math.sin(angle)))
        bases.append((max(0, min(GRID_SIZE-1, r)), max(0, min(GRID_SIZE-1, c))))
    return bases

def aco_partition(num_drones, seed=None, iterations=5, alpha=1.0, beta=2.0, evap=0.3):
    """
    ACO-based area partitioning for SAR drone swarms.

    Each drone expands from its base using ant-colony style pheromone attraction,
    weighted by cell priority (simulated urgency/heat map). After BFS seeding,
    multiple ACO iterations refine borders by having ants re-claim high-priority
    unclaimed or low-pheromone contested cells.

    Returns:
        grid   : 2D list of Cell objects, each with .drone assigned
        bases  : list of (r, c) base positions per drone
        history: list of dicts recording pheromone state per iteration
    """
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)

    grid = make_grid()
    bases = spread_bases(num_drones)
    history = []

    # --- Phase 1: BFS flood-fill from bases to give each drone a seed region ---
    queues = [deque() for _ in range(num_drones)]
    for drone_id, (br, bc) in enumerate(bases):
        cell = grid[br][bc]
        cell.drone = drone_id
        cell.pheromone = 1.0
        queues[drone_id].append(cell)

    total_cells = GRID_SIZE * GRID_SIZE
    assigned = num_drones  # bases already assigned

    # Round-robin BFS so territories grow evenly
    while assigned < total_cells:
        progress = False
        for drone_id in range(num_drones):
            if not queues[drone_id]:
                continue
            cell = queues[drone_id].popleft()
            for nb in neighbors(grid, cell.r, cell.c):
                if nb.drone == -1:
                    nb.drone = drone_id
                    nb.pheromone = cell.pheromone * 0.95
                    queues[drone_id].append(nb)
                    assigned += 1
                    progress = True
        if not progress:
            break

    # Catch any remaining unassigned cells (shouldn't happen but safety net)
    for row in grid:
        for cell in row:
            if cell.drone == -1:
                best_nb = None
                for nb in neighbors(grid, cell.r, cell.c):
                    if nb.drone != -1:
                        best_nb = nb
                        break
                cell.drone = best_nb.drone if best_nb else 0

    # --- Phase 2: ACO refinement iterations ---
    # Each iteration: ants walk from bases, deposit pheromone on high-priority
    # cells, and contested border cells can be re-assigned to stronger colonies.

    ANTS_PER_DRONE = 8
    WALK_STEPS = 20

    for iteration in range(iterations):
        # Evaporate pheromones
        for row in grid:
            for cell in row:
                cell.pheromone *= (1.0 - evap)

        # Each drone sends ants out from its base
        for drone_id, (br, bc) in enumerate(bases):
            for _ in range(ANTS_PER_DRONE):
                r, c = br, bc
                for _step in range(WALK_STEPS):
                    nbs = list(neighbors(grid, r, c))
                    if not nbs:
                        break

                    # Score each neighbor: prefer same-drone, high priority, high pheromone
                    scores = []
                    for nb in nbs:
                        tau = max(nb.pheromone, 1e-6) ** alpha
                        eta = nb.priority ** beta
                        # Penalty for crossing into another drone's territory
                        territory_bonus = 1.5 if nb.drone == drone_id else 0.5
                        scores.append(tau * eta * territory_bonus)

                    total = sum(scores)
                    probs = [s / total for s in scores]
                    chosen = random.choices(nbs, weights=probs, k=1)[0]

                    # Deposit pheromone
                    chosen.pheromone += chosen.priority

                    # Re-assign if this ant's pheromone dominates
                    if chosen.drone != drone_id:
                        # Check if this drone's pheromone is stronger at this cell
                        # (simple: re-assign if visiting drone's base is closer)
                        base_r, base_c = br, bc
                        current_base_r, current_base_c = bases[chosen.drone]
                        dist_visitor = math.hypot(chosen.r - base_r, chosen.c - base_c)
                        dist_owner   = math.hypot(chosen.r - current_base_r, chosen.c - current_base_c)
                        if chosen.pheromone > 1.2 and dist_visitor < dist_owner:
                            chosen.drone = drone_id

                    r, c = chosen.r, chosen.c

        # Record pheromone snapshot for history
        snapshot = np.array([[grid[r][c].pheromone for c in range(GRID_SIZE)]
                              for r in range(GRID_SIZE)])
        history.append({"iteration": iteration, "pheromone_map": snapshot})

    # --- Phase 3: Ensure contiguity — re-flood isolated cells back to nearest drone ---
    _fix_contiguity(grid, bases, num_drones)

    return grid, bases, history


def _fix_contiguity(grid, bases, num_drones):
    """
    BFS from each base to reclaim isolated cells that got flipped to wrong drone
    during ACO refinement. Ensures each drone's territory stays connected.
    """
    # Build reachability map from each base
    visited = [[False]*GRID_SIZE for _ in range(GRID_SIZE)]
    queue = deque()

    for drone_id, (br, bc) in enumerate(bases):
        queue.append((br, bc, drone_id))

    while queue:
        r, c, drone_id = queue.popleft()
        if visited[r][c]:
            continue
        visited[r][c] = True
        cell = grid[r][c]
        if cell.drone != drone_id:
            continue
        for nb in neighbors(grid, r, c):
            if not visited[nb.r][nb.c] and nb.drone == drone_id:
                queue.append((nb.r, nb.c, drone_id))

    # Any unvisited cell is isolated — reassign to closest base
    for row in grid:
        for cell in row:
            if not visited[cell.r][cell.c]:
                best_drone, best_dist = 0, float("inf")
                for drone_id, (br, bc) in enumerate(bases):
                    d = math.hypot(cell.r - br, cell.c - bc)
                    if d < best_dist:
                        best_dist = d
                        best_drone = drone_id
                cell.drone = best_drone