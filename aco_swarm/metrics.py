"""
metrics.py
----------
Live swarm performance metrics.
    - Coverage %     — fraction of total grid cells visited
    - Overlap %      — redundant visits across the swarm
    - Path Efficiency — how directly each drone moves through its zone
    - Utilization    — each drone's unique contribution to total coverage
"""

import math
import time
import numpy as np


class MetricsTracker:

    def __init__(self, planner, agents):
        self.planner    = planner
        self.agents     = agents
        self._start     = time.time()
        self._prev_pos  = {}
        self._dist      = {}

    def update_positions(self):
        for agent in self.agents:
            if agent.lat is None:
                continue
            did = agent.drone_id
            if did in self._prev_pos:
                dlat = agent.lat - self._prev_pos[did][0]
                dlon = agent.lon - self._prev_pos[did][1]
                dm   = math.sqrt(
                    (dlat * 111_111) ** 2 +
                    (dlon * 111_111 * math.cos(math.radians(agent.lat))) ** 2
                )
                self._dist[did] = self._dist.get(did, 0.0) + dm
            self._prev_pos[did] = (agent.lat, agent.lon)

    def coverage(self) -> float:
        snap = self.planner.pheromone.get_snapshot()
        return float(np.count_nonzero(snap)) / snap.size

    def overlap(self) -> float:
        snap      = self.planner.pheromone.get_snapshot()
        visited   = snap > 0
        threshold = self.planner.pheromone.config.deposit_strength * 1.5
        multi     = snap > threshold
        if not visited.any():
            return 0.0
        return float(multi.sum()) / float(visited.sum())

    def path_efficiency(self, agent) -> float:
        did = agent.drone_id
        if (agent.lat is None or did not in self._dist
                or self._dist[did] == 0
                or not hasattr(agent, "start_lat")
                or agent.start_lat is None):
            return 0.0
        dlat     = (agent.lat - agent.start_lat) * 111_111
        dlon     = (agent.lon - agent.start_lon) * 111_111 * math.cos(math.radians(agent.lat))
        straight = math.sqrt(dlat ** 2 + dlon ** 2)
        return min(1.0, straight / self._dist[did])

    def utilization(self, agent) -> float:
        if agent.territory is None or len(agent.territory) == 0:
            return 0.0
        visited_by_drone = sum(
            1 for pt in agent.territory
            if self.planner.pheromone.get_value(pt[0], pt[1]) > 0
        )
        total_visited = np.count_nonzero(self.planner.pheromone.get_snapshot())
        if total_visited == 0:
            return 0.0
        return visited_by_drone / total_visited

    def report(self):
        self.update_positions()
        elapsed = time.time() - self._start
        cov     = self.coverage()
        ovl     = self.overlap()

        print("\n" + "═" * 70)
        print(f"  SWARM METRICS  |  elapsed={elapsed:.0f}s  |  "
              f"coverage={cov:.1%}  |  overlap={ovl:.1%}")
        print("─" * 70)
        print(f"  {'Drone':<7} {'Position':<26} {'Dist(m)':<10} {'Efficiency':<13} {'Utilization'}")
        print("─" * 70)
        for agent in self.agents:
            if agent.lat is None:
                continue
            dist = self._dist.get(agent.drone_id, 0.0)
            eff  = self.path_efficiency(agent)
            util = self.utilization(agent)
            ter  = len(agent.territory) if agent.territory is not None else 0
            print(f"  D{agent.drone_id:<6} ({agent.lat:.5f},{agent.lon:.5f})  "
                  f"{dist:<10.1f} {eff:<13.1%} {util:.1%}  [{ter} cells]")
        print("═" * 70)