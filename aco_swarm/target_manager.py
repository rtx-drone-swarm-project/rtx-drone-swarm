"""
target_manager.py
-----------------
Target registry for SAR swarm simulation.

Each target has three possible states:
  UNDETECTED  — not yet seen by any drone
  PENDING     — one drone has reported a sighting; awaiting corroboration
  CONFIRMED   — a second independent drone verified within the time window
  EXPIRED     — PENDING window timed out without corroboration (→ UNDETECTED)

Usage:
    mgr = TargetManager(targets=[(-35.362, 149.166), (-35.365, 149.163)])
    # In drone detection loop:
    hit = mgr.check_detection(drone_id=2, lat=agent.lat, lon=agent.lon)
    if hit:
        log.info(f"Drone 2 detected target {hit.target_id}")

Coordinates are (lat, lon) tuples matching the swarm grid.
Detection radius defaults to 30 m (≈0.00027°).
Validation window defaults to 60 s.
"""

import time
import math
import logging
import threading
import csv
import os
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Tuple, Dict

log = logging.getLogger(__name__)


# ── Target state ──────────────────────────────────────────────────────────────

class TargetState(Enum):
    UNDETECTED = auto()
    PENDING    = auto()
    CONFIRMED  = auto()
    EXPIRED    = auto()


@dataclass
class Target:
    target_id:      int
    lat:            float
    lon:            float
    state:          TargetState = TargetState.UNDETECTED

    # PENDING metadata
    detected_by:    Optional[int]   = None   # drone_id of first detector
    detected_at:    Optional[float] = None   # wall-clock time

    # CONFIRMED metadata
    confirmed_by:   Optional[int]   = None   # drone_id of validator
    confirmed_at:   Optional[float] = None


# ── Haversine (local copy avoids circular import with drone_agent) ─────────────

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi       = math.radians(lat2 - lat1)
    dlambda    = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── TargetManager ─────────────────────────────────────────────────────────────

class TargetManager:
    """
    Thread-safe target registry.

    Parameters
    ----------
    targets          : list of (lat, lon) tuples — known target positions
    detection_radius : metres within which a drone detects a target
    validation_window: seconds a PENDING sighting stays open for corroboration
    csv_path         : if set, confirmed finds are appended to this CSV file
    """

    def __init__(
        self,
        targets:           List[Tuple[float, float]],
        detection_radius:  float = 30.0,
        validation_window: float = 60.0,
        csv_path:          Optional[str] = None,
    ):
        self._lock    = threading.Lock()
        self._radius  = detection_radius
        self._window  = validation_window
        self._csv     = csv_path

        self._targets: Dict[int, Target] = {
            i: Target(target_id=i, lat=lat, lon=lon)
            for i, (lat, lon) in enumerate(targets)
        }

        if csv_path:
            self._init_csv(csv_path)

        # Start the expiry watchdog
        t = threading.Thread(target=self._expiry_loop, daemon=True, name="target-expiry")
        t.start()

        log.info(
            f"[TargetManager] {len(self._targets)} targets loaded | "
            f"radius={detection_radius}m | window={validation_window}s"
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def check_detection(
        self,
        drone_id: int,
        lat:      float,
        lon:      float,
    ) -> Optional[Target]:
        """
        Call from each drone's navigation loop.

        Returns the Target if a meaningful state change occurred:
          - UNDETECTED → PENDING   (first detection)
          - PENDING    → CONFIRMED (validation by a different drone)
        Returns None if nothing changed (already confirmed, same drone, etc.)
        """
        with self._lock:
            for target in self._targets.values():
                if target.state in (TargetState.CONFIRMED, TargetState.EXPIRED):
                    continue

                dist = _haversine_m(lat, lon, target.lat, target.lon)
                if dist > self._radius:
                    continue

                if target.state == TargetState.UNDETECTED:
                    target.state       = TargetState.PENDING
                    target.detected_by = drone_id
                    target.detected_at = time.time()
                    log.warning(
                        f"[TargetManager] 🔍 PENDING  T{target.target_id} — "
                        f"Drone {drone_id + 1} at ({lat:.5f},{lon:.5f}) "
                        f"dist={dist:.1f}m"
                    )
                    return target

                if target.state == TargetState.PENDING:
                    if drone_id == target.detected_by:
                        # Same drone overflying — doesn't count as validation
                        continue
                    target.state        = TargetState.CONFIRMED
                    target.confirmed_by = drone_id
                    target.confirmed_at = time.time()
                    elapsed = target.confirmed_at - target.detected_at
                    log.warning(
                        f"[TargetManager] ✅ CONFIRMED T{target.target_id} — "
                        f"Drone {drone_id + 1} validated in {elapsed:.1f}s"
                    )
                    if self._csv:
                        self._write_csv(target)
                    return target

        return None

    def get_pending_targets(self) -> List[Target]:
        """Return all targets currently awaiting validation."""
        with self._lock:
            return [t for t in self._targets.values() if t.state == TargetState.PENDING]

    def get_confirmed_targets(self) -> List[Target]:
        """Return all confirmed targets."""
        with self._lock:
            return [t for t in self._targets.values() if t.state == TargetState.CONFIRMED]

    def summary(self) -> str:
        with self._lock:
            counts = {s: 0 for s in TargetState}
            for t in self._targets.values():
                counts[t.state] += 1
        return (
            f"Targets: {counts[TargetState.UNDETECTED]} undetected | "
            f"{counts[TargetState.PENDING]} pending | "
            f"{counts[TargetState.CONFIRMED]} confirmed | "
            f"{counts[TargetState.EXPIRED]} expired"
        )

    # ── Expiry watchdog ───────────────────────────────────────────────────────

    def _expiry_loop(self):
        while True:
            time.sleep(5)
            now = time.time()
            with self._lock:
                for target in self._targets.values():
                    if target.state != TargetState.PENDING:
                        continue
                    age = now - (target.detected_at or now)
                    if age > self._window:
                        target.state = TargetState.UNDETECTED   # reset — retryable
                        log.warning(
                            f"[TargetManager] ⏰ EXPIRED  T{target.target_id} — "
                            f"no validator in {self._window:.0f}s — reset to UNDETECTED"
                        )

    # ── CSV logging ───────────────────────────────────────────────────────────

    def _init_csv(self, path: str):
        with open(path, "w", newline="") as f:
            csv.writer(f).writerow([
                "target_id", "lat", "lon",
                "detected_by", "detected_at",
                "confirmed_by", "confirmed_at",
                "validation_time_s",
            ])
        log.info(f"[TargetManager] CSV → {path}")

    def _write_csv(self, target: Target):
        if not self._csv:
            return
        vtime = (
            (target.confirmed_at - target.detected_at)
            if target.confirmed_at and target.detected_at
            else None
        )
        with open(self._csv, "a", newline="") as f:
            csv.writer(f).writerow([
                target.target_id,
                f"{target.lat:.7f}", f"{target.lon:.7f}",
                target.detected_by, f"{target.detected_at:.2f}",
                target.confirmed_by, f"{target.confirmed_at:.2f}",
                f"{vtime:.2f}" if vtime else "",
            ])