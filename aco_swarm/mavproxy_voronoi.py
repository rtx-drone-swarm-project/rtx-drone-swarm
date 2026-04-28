"""
mavproxy_voronoi.py
-------------------
MAVProxy module that overlays Voronoi partition polygons on the map.

SEARCH ADDITIONS:
  - Confirmed targets rendered as filled circles with "T{id}" labels
  - Pending targets rendered as dashed circles (awaiting corroboration)
  - Detection radius ring shown around each pending target
  - Validation drone gets a dashed line drawn to its target
  - All search overlays keyed as "search_*" for clean removal on reset

UPDATED FOR 15 DRONES:
  - Expanded COLORS array from 12 to 15 unique colors
  - All drones get unique colors (no wrapping)
"""

import numpy as np
import os
import time
from MAVProxy.modules.lib import mp_module
from MAVProxy.modules.mavproxy_map import mp_slipmap
from scipy.spatial import ConvexHull


def _resolve_state_file() -> str:
    explicit = os.environ.get("SWARM_STATE_FILE", "").strip()
    if explicit:
        return explicit
    pypath = os.environ.get("PYTHONPATH", "")
    for entry in pypath.split(":"):
        entry = entry.strip()
        if entry and os.path.exists(os.path.join(entry, "mavproxy_voronoi.py")):
            return os.path.join(entry, ".agent_state.npy")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), ".agent_state.npy")


COLORS = [
    (230, 25,  75),   # red      - D0
    (60,  180, 75),   # green    - D1
    (67,  99,  216),  # blue     - D2
    (245, 130, 49),   # orange   - D3
    (145, 30,  180),  # purple   - D4
    (66,  212, 244),  # cyan     - D5
    (240, 50,  230),  # magenta  - D6
    (191, 239, 69),   # lime     - D7
    (250, 190, 212),  # pink     - D8
    (70,  153, 144),  # teal     - D9
    (220, 190, 255),  # lavender - D10
    (154, 99,  36),   # brown    - D11
    (255, 225, 25),   # yellow   - D12
    (0,   130, 200),  # steel    - D13
    (128, 128, 0),    # olive    - D14
]

# Search overlay colors — fixed, not drone-indexed
COLOR_CONFIRMED = (255, 50,  50)    # bright red fill
COLOR_PENDING   = (255, 200, 0)     # amber for unconfirmed
COLOR_RADIUS    = (255, 200, 0)     # amber ring matches pending
COLOR_VALDRONE  = (255, 255, 255)   # white line to validator target

# Detection radius in metres — must match --detection-radius in swarm_main.py.
# Used to draw the proximity ring around pending targets on the map.
# If you change --detection-radius at runtime, update this constant too.
DETECTION_RADIUS_M = 30.0

# How many seconds of no file updates before we clear all overlays.
STALE_THRESHOLD_S = 8.0


def _circle_polygon(lat: float, lon: float, radius_m: float, n_pts: int = 36):
    """
    Return a list of (lat, lon) tuples approximating a circle of radius_m
    metres centred on (lat, lon).  Uses equirectangular approximation —
    accurate enough for the small radii (~30-500 m) used here.
    """
    import math
    lat_per_m = 1.0 / 111_111.0
    lon_per_m = 1.0 / (111_111.0 * math.cos(math.radians(lat)))
    pts = []
    for i in range(n_pts + 1):          # +1 closes the ring
        angle = 2 * math.pi * i / n_pts
        pts.append((
            lat + radius_m * math.sin(angle) * lat_per_m,
            lon + radius_m * math.cos(angle) * lon_per_m,
        ))
    return pts


class VoronoiModule(mp_module.MPModule):
    def __init__(self, mpstate):
        super().__init__(mpstate, "voronoi", "Voronoi partition overlay")
        self._poll_interval = 2.0
        self._last_poll     = 0
        self._last_mtime    = 0
        self._last_seen     = 0.0
        self._state_file    = None
        self._tick          = 0
        self._cleared       = False
        print("[voronoi] loaded ✓")

    def _get_state_file(self) -> str:
        if self._state_file is None:
            self._state_file = _resolve_state_file()
            print(f"[voronoi] STATE_FILE → {self._state_file}")
        return self._state_file

    def _get_map(self):
        m = self.module("map")
        if m is None or not hasattr(m, "map"):
            return None
        return m

    def _clear_overlays(self, map_module):
        """Remove all voronoi and search overlay objects."""
        try:
            keys = list(map_module.map.objects.keys())
            for k in keys:
                if k.startswith("voronoi_") or k.startswith("search_"):
                    map_module.map.remove_object(k)
        except Exception:
            pass

    def _suppress_arrows(self, map_module):
        try:
            for k in list(map_module.map.objects.keys()):
                if any(x in k.lower() for x in ("arrow", "heading", "velocity")):
                    map_module.map.remove_object(k)
        except Exception:
            pass

    def _add_object(self, map_module, obj_id, obj_type, *args, **kwargs):
        """
        Try adding a SlipPolygon or SlipLabel.
        Falls back without 'layer' kwarg for older MAVProxy versions.
        """
        for try_kwargs in [kwargs, {k: v for k, v in kwargs.items() if k != "layer"}]:
            try:
                if obj_type == "polygon":
                    map_module.map.add_object(
                        mp_slipmap.SlipPolygon(obj_id, *args, **try_kwargs))
                else:
                    map_module.map.add_object(
                        mp_slipmap.SlipLabel(obj_id, *args, **try_kwargs))
                return True
            except TypeError:
                continue
            except Exception as e:
                print(f"[voronoi] add_object {obj_id} error: {e}")
                return False
        return False

    # ── Main loop ─────────────────────────────────────────────────────
    def idle_task(self):
        try:
            self._idle_inner()
        except Exception as e:
            print(f"[voronoi] idle_task error: {type(e).__name__}: {e}")

    def _idle_inner(self):
        now = time.time()
        if now - self._last_poll < self._poll_interval:
            return
        self._last_poll = now
        self._tick += 1

        state_file = self._get_state_file()
        map_module = self._get_map()

        if map_module is not None:
            self._suppress_arrows(map_module)

        if not os.path.exists(state_file):
            if map_module is not None and not self._cleared:
                self._clear_overlays(map_module)
                self._cleared = True
                print("[voronoi] state file absent — overlays cleared")
            return

        mtime = os.path.getmtime(state_file)

        if self._last_seen > 0 and (now - self._last_seen) > STALE_THRESHOLD_S:
            if map_module is not None and not self._cleared:
                self._clear_overlays(map_module)
                self._cleared = True
                print("[voronoi] stale state — overlays cleared")

        if mtime == self._last_mtime:
            return
        self._last_mtime = mtime
        self._last_seen  = now
        self._cleared    = False

        # ── Load ──────────────────────────────────────────────────────
        try:
            state             = np.load(state_file, allow_pickle=True).item()
            agents            = state.get("agents", [])
            confirmed_targets = state.get("confirmed_targets", [])
            pending_targets   = state.get("pending_targets", [])
            all_targets       = state.get("all_targets", [])
        except Exception as e:
            print(f"[voronoi] load error: {e}")
            return

        if map_module is None:
            return

        # ── Draw drone territories and trails ─────────────────────────
        for a in agents:
            drone_id        = a["id"]
            territory       = a.get("territory", [])
            path            = a.get("path", [])
            on_validation   = a.get("on_validation", False)
            color           = COLORS[drone_id % len(COLORS)]

            # Zone polygon (convex hull of territory points)
            if len(territory) >= 3:
                pts = np.array(territory)
                try:
                    hull    = ConvexHull(pts)
                    verts   = pts[hull.vertices]
                    verts   = np.vstack([verts, verts[0]])
                    polygon = [(float(p[0]), float(p[1])) for p in verts]
                except Exception:
                    polygon = [(float(p[0]), float(p[1])) for p in pts]

                self._add_object(map_module,
                    f"voronoi_zone_{drone_id}", "polygon",
                    polygon, layer="voronoi", linewidth=2, colour=color)

                cx = float(pts[:, 0].mean())
                cy = float(pts[:, 1].mean())
                self._add_object(map_module,
                    f"voronoi_label_{drone_id}", "label",
                    (cx, cy), f"D{drone_id + 1}", layer="voronoi", colour=color)

            # Flight trail — thicker and dashed when on validation mission
            if len(path) >= 2:
                trail = [(float(p[0]), float(p[1])) for p in path]
                lw    = 2 if on_validation else 1
                self._add_object(map_module,
                    f"voronoi_trail_{drone_id}", "polygon",
                    trail, layer="voronoi", linewidth=lw, colour=color)

        # ── Draw search overlays ──────────────────────────────────────
        self._draw_search_overlays(
            map_module, confirmed_targets, pending_targets, agents, all_targets
        )

    def _draw_search_overlays(
        self,
        map_module,
        confirmed_targets,
        pending_targets,
        agents,
        all_targets=None,
    ):
        """
        Render all search-related map objects.

        Confirmed targets:
          - Bright red outer ring (15 m radius, 3 px)
          - Bright red inner dot (6 m radius, 6 px) — gives filled appearance
          - Cross hairlines at exact GPS coordinate
          - "T{id} ✓" label offset north

        Pending targets (PENDING state — sighted, awaiting corroboration):
          - Amber dashed ring at detection radius
          - "T{id} ?" label
          - White dashed line from the validating drone to the sighting

        Confirmed targets supersede pending — if a target appears in both
        lists (race condition between state writes), confirmed wins.
        """
        import math

        confirmed_ids = {t["id"] for t in confirmed_targets}

        # Build a quick lookup: drone_id → current (lat, lon)
        drone_pos = {}
        for a in agents:
            path = a.get("path", [])
            if path:
                drone_pos[a["id"]] = (float(path[-1][0]), float(path[-1][1]))

        # ── Confirmed targets ─────────────────────────────────────────
        for t in confirmed_targets:
            tid = t["id"]
            lat = float(t["lat"])
            lon = float(t["lon"])

            # Outer ring
            outer = _circle_polygon(lat, lon, radius_m=15.0, n_pts=24)
            self._add_object(map_module,
                f"search_confirmed_ring_{tid}", "polygon",
                outer, layer="search", linewidth=3, colour=COLOR_CONFIRMED)

            # Inner dot (tight polygon for filled look)
            inner = _circle_polygon(lat, lon, radius_m=6.0, n_pts=16)
            self._add_object(map_module,
                f"search_confirmed_dot_{tid}", "polygon",
                inner, layer="search", linewidth=6, colour=COLOR_CONFIRMED)

            # Crosshair at exact coordinate
            dlat = 10.0 / 111_111.0
            dlon = 10.0 / (111_111.0 * math.cos(math.radians(lat)))
            self._add_object(map_module,
                f"search_confirmed_hbar_{tid}", "polygon",
                [(lat, lon - dlon), (lat, lon + dlon)],
                layer="search", linewidth=3, colour=COLOR_CONFIRMED)
            self._add_object(map_module,
                f"search_confirmed_vbar_{tid}", "polygon",
                [(lat - dlat, lon), (lat + dlat, lon)],
                layer="search", linewidth=3, colour=COLOR_CONFIRMED)

            # Label offset 20 m north
            label_lat = lat + 20.0 / 111_111.0
            self._add_object(map_module,
                f"search_confirmed_label_{tid}", "label",
                (label_lat, lon),
                f"T{tid} \u2713",
                layer="search", colour=COLOR_CONFIRMED)

            # Remove any stale pending overlay for this target
            for suffix in ("ring", "label", "valdrone_line"):
                try:
                    map_module.map.remove_object(f"search_pending_{suffix}_{tid}")
                except Exception:
                    pass

        # ── Pending targets ───────────────────────────────────────────
        for t in pending_targets:
            tid = t["id"]
            if tid in confirmed_ids:
                continue   # already confirmed — confirmed overlay takes priority

            lat          = float(t["lat"])
            lon          = float(t["lon"])
            detected_by  = t.get("detected_by")

            # Detection-radius ring (amber)
            ring = _circle_polygon(lat, lon,
                                   radius_m=DETECTION_RADIUS_M, n_pts=36)
            self._add_object(map_module,
                f"search_pending_ring_{tid}", "polygon",
                ring, layer="search", linewidth=2, colour=COLOR_PENDING)

            # Label at sighting coordinates
            label_lat = lat + 15.0 / 111_111.0
            self._add_object(map_module,
                f"search_pending_label_{tid}", "label",
                (label_lat, lon),
                f"T{tid} ?",
                layer="search", colour=COLOR_PENDING)

            # Line from validating drone to sighting
            # The validator is whichever drone is on_validation=True and
            # is NOT the detecting drone.
            for a in agents:
                if not a.get("on_validation", False):
                    continue
                if a["id"] == detected_by:
                    continue   # this is the detector, not the validator
                val_pos = drone_pos.get(a["id"])
                if val_pos is None:
                    continue
                line = [val_pos, (lat, lon)]
                self._add_object(map_module,
                    f"search_pending_valdrone_line_{tid}", "polygon",
                    line, layer="search", linewidth=2,
                    colour=COLOR_VALDRONE)
                break   # only one validator per target
        
        # ── All targets (persistent baseline overlay) ──────────────────────
        if not all_targets:
            return
        confirmed_ids = {t["id"] for t in confirmed_targets}
        pending_ids   = {t["id"] for t in pending_targets}

        for t in all_targets:
            tid   = t["id"]
            lat   = float(t["lat"])
            lon   = float(t["lon"])
            state = t.get("state", "UNDETECTED")

            # Skip if already drawn by confirmed/pending blocks above
            if state == "CONFIRMED" or tid in confirmed_ids:
                continue
            if state == "PENDING" or tid in pending_ids:
                continue

            # Undetected: yellow crosshair + small ring (40m so it's visible)
            COLOR_UNDETECTED = (255, 255, 0)

            ring = _circle_polygon(lat, lon, radius_m=40.0, n_pts=24)
            self._add_object(map_module,
                f"search_undetected_ring_{tid}", "polygon",
                ring, layer="search", linewidth=2, colour=COLOR_UNDETECTED)

            dlat = 15.0 / 111_111.0
            dlon = 15.0 / (111_111.0 * math.cos(math.radians(lat)))
            self._add_object(map_module,
                f"search_undetected_hbar_{tid}", "polygon",
                [(lat, lon - dlon), (lat, lon + dlon)],
                layer="search", linewidth=3, colour=COLOR_UNDETECTED)
            self._add_object(map_module,
                f"search_undetected_vbar_{tid}", "polygon",
                [(lat - dlat, lon), (lat + dlat, lon)],
                layer="search", linewidth=3, colour=COLOR_UNDETECTED)

            label_lat = lat + 25.0 / 111_111.0
            self._add_object(map_module,
                f"search_undetected_label_{tid}", "label",
                (label_lat, lon),
                f"T{tid}",
                layer="search", colour=COLOR_UNDETECTED)


def init(mpstate):
    return VoronoiModule(mpstate)