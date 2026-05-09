"""
validation_protocol.py
-----------------------
When a drone reports a PENDING target, this module:

  1. Finds the nearest drone that did NOT make the original sighting
     and is not already on a validation mission.
  2. Temporarily overrides that drone's ACO navigation to fly toward
     the target coordinates (validation_goto).
  3. If the drone confirms (TargetManager transitions to CONFIRMED),
     the override is cleared and normal ACO resumes.
  4. If the validation window expires (TargetManager resets to UNDETECTED),
     the override is cleared and normal ACO resumes.

Integration
-----------
  protocol = ValidationProtocol(target_manager, agents, planner)

  # Inside _lloyd_loop or swarm_main main loop, after check_detection:
  protocol.on_detection(target)

The per-drone override is stored as agent._validation_target — a (lat, lon)
tuple or None. drone_agent.py checks this before calling ACO for its waypoint.

No new threads are spawned — the protocol runs on the existing Lloyd loop
thread and clears overrides synchronously once confirmation is observed.
"""

import math
import logging
import time
import threading
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from drone_agent import DroneAgent
    from voronoi_aco_hybrid import VoronoiACOPlanner

from target_manager import TargetManager, Target, TargetState

log = logging.getLogger(__name__)


def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6_371_000
    import math
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(phi1) * math.cos(phi2)
         * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class ValidationProtocol:
    """
    Coordinates validation missions when a target moves to PENDING state.

    Parameters
    ----------
    target_manager : TargetManager instance
    agents         : list of DroneAgent instances
    planner        : VoronoiACOPlanner (used to deposit pheromone on confirmation)
    pheromone_boost: how much pheromone to deposit on confirmation
                     (large value → other drones avoid the confirmed site)
    """

    def __init__(
        self,
        target_manager:  TargetManager,
        agents:          List["DroneAgent"],
        planner:         "VoronoiACOPlanner",
        pheromone_boost: float = 50.0,
    ):
        self._mgr     = target_manager
        self._agents  = agents
        self._planner = planner
        self._boost   = pheromone_boost
        self._lock    = threading.Lock()

        # Maps target_id → drone_id currently on validation mission
        self._active_missions: dict = {}

        # Start the monitor loop (checks for confirmation / expiry)
        t = threading.Thread(
            target=self._monitor_loop, daemon=True, name="validation-monitor"
        )
        t.start()
        log.info("[ValidationProtocol] ready")

    # ── Called immediately when a drone reports a PENDING detection ───────────

    def on_detection(self, target: Target):
        """
        React to a new PENDING target.
        Selects the best available validator and issues a navigation override.
        """
        if target.state != TargetState.PENDING:
            return

        with self._lock:
            if target.target_id in self._active_missions:
                return   # already dispatched

            validator = self._select_validator(
                target=target,
                exclude_drone=target.detected_by,
            )
            if validator is None:
                log.warning(
                    f"[ValidationProtocol] No available validator for T{target.target_id}"
                )
                return

            self._active_missions[target.target_id] = validator.drone_id
            validator._validation_target = (target.lat, target.lon)
            log.warning(
                f"[ValidationProtocol] 🚁 Dispatching Drone {validator.drone_id + 1} "
                f"→ T{target.target_id} at ({target.lat:.5f},{target.lon:.5f})"
            )

    # ── Monitor loop — runs every 3 s ─────────────────────────────────────────

    def _monitor_loop(self):
        while True:
            time.sleep(3)
            self._check_resolutions()

    def _check_resolutions(self):
        """Clear navigation overrides for missions that have resolved."""
        with self._lock:
            resolved = []
            for target_id, drone_id in self._active_missions.items():
                target = self._mgr._targets.get(target_id)
                if target is None:
                    resolved.append(target_id)
                    continue

                if target.state == TargetState.CONFIRMED:
                    self._on_confirmed(target, drone_id)
                    resolved.append(target_id)

                elif target.state == TargetState.UNDETECTED:
                    # Window expired — TargetManager already reset it
                    self._clear_override(drone_id)
                    log.info(
                        f"[ValidationProtocol] Drone {drone_id + 1} released "
                        f"(T{target_id} expired)"
                    )
                    resolved.append(target_id)

            for tid in resolved:
                self._active_missions.pop(tid, None)

    def _on_confirmed(self, target: Target, validator_drone_id: int):
        """
        React to a confirmed find:
          - Clear the validator's navigation override
          - Deposit a large pheromone spike at the target location
            (deters re-visits; keeps the rest of the swarm productive)
          - Optionally log a visual marker to .agent_state.npy via planner state
        """
        self._clear_override(validator_drone_id)
        also_clear = target.detected_by
        if also_clear is not None:
            self._clear_override(also_clear)

        # Pheromone spike — large deposit discourages further visits
        for _ in range(int(self._boost)):
            self._planner.pheromone.deposit(target.lat, target.lon, strength=1.0)

        # Also saturate a small ring around the site (3×3 neighbourhood)
        # so adjacent cells are also deprioritised — keeps the swarm moving
        # to genuinely unsearched ground rather than orbiting the find.
        for dlat in (-0.0003, 0, 0.0003):
            for dlon in (-0.0003, 0, 0.0003):
                if dlat == 0 and dlon == 0:
                    continue
                self._planner.pheromone.deposit(
                    target.lat + dlat,
                    target.lon + dlon,
                    strength=self._boost * 0.4,
                )

        log.warning(
            f"[ValidationProtocol] 📍 CONFIRMED T{target.target_id} — "
            f"pheromone spike deposited | "
            f"{self._mgr.summary()}"
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _select_validator(
        self,
        target:        Target,
        exclude_drone: Optional[int],
    ) -> Optional["DroneAgent"]:
        """
        Return the nearest drone that:
          - is not the detecting drone
          - has a known GPS position
          - is not already on a validation mission
          - is in ACO phase (airborne, has territory)
        Ties broken by distance.
        """
        busy_drone_ids = set(self._active_missions.values())
        candidates = []
        for agent in self._agents:
            if agent.drone_id == exclude_drone:
                continue
            if agent.drone_id in busy_drone_ids:
                continue
            if agent.lat is None or agent.lon is None:
                continue
            if not getattr(agent, "airborne", False):
                continue
            dist = _haversine_m(agent.lat, agent.lon, target.lat, target.lon)
            candidates.append((dist, agent))

        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    def _clear_override(self, drone_id: int):
        for agent in self._agents:
            if agent.drone_id == drone_id:
                agent._validation_target = None
                log.info(
                    f"[ValidationProtocol] Drone {drone_id + 1} override cleared "
                    "— resuming ACO"
                )
                return