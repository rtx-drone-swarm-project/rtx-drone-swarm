"""
SAR Drone Grid Partitioning — ACO / Stigmergy Algorithm
========================================================
100 km² search area · 20×20 grid (each cell = 0.25 km²)

Usage:
    python sar_aco.py                  # default 15 drones
    python sar_aco.py --drones 6       # custom drone count
    python sar_aco.py --drones 5 --seed 42  # reproducible run
"""

import argparse
import random
import math
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import ListedColormap
from collections import deque

# ─── Config ──────────────────────────────────────────────────────────────────
GRID_SIZE        = 40          # 20×20 = 400 cells
AREA_KM2         = 100.0
CELL_KM2         = AREA_KM2 / (GRID_SIZE * GRID_SIZE)   # 0.25 km² per cell

# ACO hyperparameters
EVAPORATION_RATE = 0.02   # pheromone decay per iteration
DEPOSIT_AMOUNT   = 0.8    # pheromone added when a cell is claimed
ALPHA            = 1.0    # pheromone-repulsion weight
BETA             = 1.5    # priority (heuristic) weight
BALANCE_WEIGHT   = 0.5    # how hard drones throttle when over-size
MAX_ITERATIONS   = 100

# ─── Colors ───────────────────────────────────────────────────────────────────
DRONE_COLORS = [
    "#d83636", "#f27929", "#d8b113", "#cdf23c", "#6cd824",
    "#15f215", "#36d877", "#29f2ca", "#13b1d8", "#3c85f2",
    "#2424d8", "#6d15f2", "#b836d8", "#f229ca", "#d81362",
]


# ─── Grid Cell ────────────────────────────────────────────────────────────────
class Cell:
    __slots__ = ("r", "c", "drone", "pheromone", "priority")

    def __init__(self, r, c):
        self.r         = r
        self.c         = c
        self.drone     = -1
        self.pheromone = 0.0
        self.priority  = random.random()


def make_grid():
    return [[Cell(r, c) for c in range(GRID_SIZE)] for r in range(GRID_SIZE)]


def neighbors(grid, r, c):
    for dr, dc in ((-1,0),(1,0),(0,-1),(0,1)):
        nr, nc = r+dr, c+dc
        if 0 <= nr < GRID_SIZE and 0 <= nc < GRID_SIZE:
            yield grid[nr][nc]


def spread_bases(num_drones):
    """Spread drone bases evenly in a ring around the centre."""
    bases = []
    for i in range(num_drones):
        angle = 2 * math.pi * i / num_drones
        r = int(round(GRID_SIZE/2 + (GRID_SIZE * 0.35) * math.cos(angle)))
        c = int(round(GRID_SIZE/2 + (GRID_SIZE * 0.35) * math.sin(angle)))
        bases.append((max(0, min(GRID_SIZE-1, r)),
                      max(0, min(GRID_SIZE-1, c))))
    return bases


# ─── ACO Partitioner ─────────────────────────────────────────────────────────
def aco_partition(num_drones, seed=None):
    """
    Stigmergy-based ACO area partitioning.

    Each drone expands from its base by BFS-like frontier growth.
    Claim probability = priority^β × (1 - pheromone)^α × balance_factor.
    Pheromone evaporates each iteration (stigmergy = indirect communication).
    Load-balancing factor slows drones that already own too many cells.

    Returns:
        grid    — 2D list of Cell objects (.drone assigned 0..n-1)
        bases   — list of (r, c) starting positions
        history — [(iteration, cells_covered), …] for convergence plot
    """
    if seed is not None:
        random.seed(seed)

    grid   = make_grid()
    bases  = spread_bases(num_drones)
    history = []
    ideal   = GRID_SIZE * GRID_SIZE / num_drones   # target cells per drone

    # Seed base cells
    for di, (r, c) in enumerate(bases):
        grid[r][c].drone     = di
        grid[r][c].pheromone = 1.0

    # BFS frontiers  &  cell-count cache
    frontiers    = [deque([(r, c)]) for r, c in bases]
    drone_counts = [1] * num_drones

    for iteration in range(MAX_ITERATIONS):

        # 1. Pheromone evaporation
        for row in grid:
            for cell in row:
                cell.pheromone *= (1.0 - EVAPORATION_RATE)

        # 2. Frontier expansion
        new_frontiers = [deque() for _ in range(num_drones)]

        for di, frontier in enumerate(frontiers):
            # Balance factor: throttle drones that are already oversized
            balance = max(0.05, 1.0 - (drone_counts[di] / ideal) * BALANCE_WEIGHT)
            visited = set()

            for (r, c) in frontier:
                for nb in neighbors(grid, r, c):
                    if nb.drone != -1 or (nb.r, nb.c) in visited:
                        continue

                    score = (nb.priority ** BETA) * ((1.0 - nb.pheromone) ** ALPHA) * balance

                    if score > random.random() * 0.55:
                        nb.drone     = di
                        nb.pheromone = min(1.0, nb.pheromone + DEPOSIT_AMOUNT)
                        drone_counts[di] += 1
                        new_frontiers[di].append((nb.r, nb.c))
                        visited.add((nb.r, nb.c))

        # Keep last frontier if drone couldn't expand (avoid stalling)
        for di in range(num_drones):
            if not new_frontiers[di]:
                new_frontiers[di] = frontiers[di]
        frontiers = new_frontiers

        covered = sum(drone_counts)
        history.append((iteration + 1, covered))

        if covered >= GRID_SIZE * GRID_SIZE:
            print(f"  ✓ Full coverage at iteration {iteration+1}")
            break

    # 3. BFS flood-fill for any remaining unassigned cells
    changed = True
    while changed:
        changed = False
        for row in grid:
            for cell in row:
                if cell.drone == -1:
                    for nb in neighbors(grid, cell.r, cell.c):
                        if nb.drone != -1:
                            cell.drone = nb.drone
                            changed = True
                            break

    return grid, bases, history


# ─── Statistics ───────────────────────────────────────────────────────────────
def compute_stats(grid, num_drones):
    stats = []
    for di in range(num_drones):
        cells = [cell for row in grid for cell in row if cell.drone == di]
        stats.append({
            "drone":        di + 1,
            "cells":        len(cells),
            "area_km2":     len(cells) * CELL_KM2,
            "avg_priority": float(np.mean([c.priority for c in cells])) if cells else 0.0,
        })
    areas = [s["cells"] for s in stats]
    cv    = float(np.std(areas) / np.mean(areas) * 100)
    return stats, cv


# ─── Visualization ────────────────────────────────────────────────────────────
def visualize(grid, bases, history, num_drones):
    fig = plt.figure(figsize=(16, 10), facecolor="#0a0a1a")
    fig.suptitle("SAR Drone Grid — ACO Stigmergy Partitioning",
                 color="white", fontsize=15, fontweight="bold", y=0.98)

    gs = fig.add_gridspec(2, 3, width_ratios=[2.2, 1, 1],
                          hspace=0.35, wspace=0.3,
                          left=0.04, right=0.97, top=0.93, bottom=0.06)

    ax_main  = fig.add_subplot(gs[:, 0])
    ax_pher  = fig.add_subplot(gs[0, 1])
    ax_prio  = fig.add_subplot(gs[1, 1])
    ax_conv  = fig.add_subplot(gs[0, 2])
    ax_stats = fig.add_subplot(gs[1, 2])

    bg = "#0d0d1f"
    for ax in [ax_main, ax_pher, ax_prio, ax_conv, ax_stats]:
        ax.set_facecolor(bg)
        for spine in ax.spines.values():
            spine.set_edgecolor("#334")

    # ── Main partition map ────────────────────────────────────────────────────
    drone_map = np.array([[cell.drone for cell in row] for row in grid])
    cmap = ListedColormap(DRONE_COLORS[:num_drones])
    ax_main.imshow(drone_map, cmap=cmap, vmin=0, vmax=num_drones - 1,
                   interpolation="nearest", origin="upper")

    for i in range(GRID_SIZE + 1):
        ax_main.axhline(i - 0.5, color="#0a0a1a", lw=0.4)
        ax_main.axvline(i - 0.5, color="#0a0a1a", lw=0.4)

    for di, (r, c) in enumerate(bases):
        color = DRONE_COLORS[di % len(DRONE_COLORS)]
        ax_main.plot(c, r, "w*", markersize=13, zorder=5)
        ax_main.text(c, r, str(di + 1), ha="center", va="center",
                     fontsize=7, fontweight="bold", color="#000", zorder=6)

    patches = [mpatches.Patch(color=DRONE_COLORS[i], label=f"Drone {i+1}")
               for i in range(num_drones)]
    ax_main.legend(handles=patches, loc="upper right", fontsize=7,
                   facecolor="#111", edgecolor="#334", labelcolor="white", framealpha=0.85)

    ax_main.set_title("Zone Partition Map", color="white", fontsize=11, pad=6)
    ax_main.set_xlabel("Column (km)", color="#888", fontsize=8)
    ax_main.set_ylabel("Row (km)", color="#888", fontsize=8)
    ax_main.tick_params(colors="#555", labelsize=7)

    ticks = list(range(0, GRID_SIZE, 4))
    km_labels = [f"{t * math.sqrt(CELL_KM2):.1f}" for t in ticks]
    ax_main.set_xticks(ticks); ax_main.set_xticklabels(km_labels)
    ax_main.set_yticks(ticks); ax_main.set_yticklabels(km_labels)

    # ── Pheromone map ─────────────────────────────────────────────────────────
    pher_map = np.array([[cell.pheromone for cell in row] for row in grid])
    im_p = ax_pher.imshow(pher_map, cmap="plasma", vmin=0, vmax=1,
                          interpolation="bilinear", origin="upper")
    ax_pher.set_title("Pheromone Density", color="white", fontsize=9, pad=4)
    ax_pher.tick_params(colors="#555", labelsize=6)
    plt.colorbar(im_p, ax=ax_pher, fraction=0.046, pad=0.04).ax.tick_params(colors="#888", labelsize=6)

    # ── Priority / heat map ───────────────────────────────────────────────────
    prio_map = np.array([[cell.priority for cell in row] for row in grid])
    im_q = ax_prio.imshow(prio_map, cmap="YlOrRd", vmin=0, vmax=1,
                          interpolation="bilinear", origin="upper")
    ax_prio.set_title("Victim Probability Heat", color="white", fontsize=9, pad=4)
    ax_prio.tick_params(colors="#555", labelsize=6)
    plt.colorbar(im_q, ax=ax_prio, fraction=0.046, pad=0.04).ax.tick_params(colors="#888", labelsize=6)

    # ── Convergence curve ─────────────────────────────────────────────────────
    total = GRID_SIZE * GRID_SIZE
    iters, covered = zip(*history) if history else ([0], [0])
    ax_conv.plot(iters, [c / total * 100 for c in covered], color="#00e5ff", lw=2)
    ax_conv.fill_between(iters, [c / total * 100 for c in covered], alpha=0.15, color="#00e5ff")
    ax_conv.axhline(100, color="#ffffff22", lw=0.8, ls="--")
    ax_conv.set_title("ACO Convergence", color="white", fontsize=9, pad=4)
    ax_conv.set_xlabel("Iteration", color="#888", fontsize=7)
    ax_conv.set_ylabel("Coverage %", color="#888", fontsize=7)
    ax_conv.tick_params(colors="#555", labelsize=7)
    ax_conv.set_ylim(0, 105)
    ax_conv.grid(color="#ffffff0a", lw=0.5)

    # ── Zone stats bar chart ──────────────────────────────────────────────────
    stats, cv = compute_stats(grid, num_drones)
    drone_ids = [s["drone"]    for s in stats]
    areas     = [s["area_km2"] for s in stats]
    colors    = [DRONE_COLORS[i] for i in range(num_drones)]
    bars = ax_stats.bar(drone_ids, areas, color=colors, edgecolor="#0a0a1a", width=0.6)
    for bar, area in zip(bars, areas):
        ax_stats.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.2,
                      f"{area:.1f}", ha="center", va="bottom", color="white", fontsize=6.5)
    ideal_area = AREA_KM2 / num_drones
    ax_stats.axhline(ideal_area, color="#ffffff55", lw=1, ls="--",
                     label=f"Ideal ({ideal_area:.1f} km²)")
    ax_stats.set_title(f"Zone Areas  [CV={cv:.1f}%]", color="white", fontsize=9, pad=4)
    ax_stats.set_xlabel("Drone ID", color="#888", fontsize=7)
    ax_stats.set_ylabel("Area (km²)", color="#888", fontsize=7)
    ax_stats.tick_params(colors="#555", labelsize=7)
    ax_stats.legend(fontsize=6.5, facecolor="#111", edgecolor="#334", labelcolor="white")
    ax_stats.grid(axis="y", color="#ffffff0a", lw=0.5)

    plt.savefig("sar_aco_result.png", dpi=150, bbox_inches="tight", facecolor="#0a0a1a")
    print("  ✓ Plot saved → sar_aco_result.png")
    plt.show()


# ─── CLI entry point ──────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="SAR Drone ACO Partitioner")
    parser.add_argument("--drones", type=int, default=15, help="Number of drones (2–10)")
    parser.add_argument("--seed",   type=int, default=None, help="Random seed")
    args = parser.parse_args()

    num_drones = max(2, min(15, args.drones))

    print(f"\n{'─'*52}")
    print(f"  SAR-ACO Partitioner")
    print(f"  Grid  : {GRID_SIZE}×{GRID_SIZE} = {GRID_SIZE*GRID_SIZE} cells  |  {AREA_KM2} km²")
    print(f"  Cell  : {CELL_KM2:.2f} km²  |  Drones: {num_drones}  |  Seed: {args.seed}")
    print(f"{'─'*52}\n")

    print("Running ACO partitioning …")
    grid, bases, history = aco_partition(num_drones, seed=args.seed)

    stats, cv = compute_stats(grid, num_drones)
    print(f"\n{'─'*52}")
    print(f"  {'Drone':<8} {'Cells':<8} {'Area (km²)':<14} {'Avg Priority'}")
    print(f"{'─'*52}")
    for s in stats:
        bar = "█" * int(s["cells"] / (GRID_SIZE * GRID_SIZE / num_drones) * 10)
        print(f"  {s['drone']:<8} {s['cells']:<8} {s['area_km2']:<14.2f} {s['avg_priority']:.3f}  {bar}")
    print(f"{'─'*52}")
    print(f"  Balance CV = {cv:.1f}%  (lower = more balanced)\n")

    print("Rendering visualisation …")
    visualize(grid, bases, history, num_drones)


if __name__ == "__main__":
    main()