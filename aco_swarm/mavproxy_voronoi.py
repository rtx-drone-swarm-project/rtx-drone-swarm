"""
mavproxy_voronoi.py
-------------------
MAVProxy module that overlays Voronoi partition polygons on the map.

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

# How many seconds of no file updates before we clear all overlays.
# swarm_main deletes the file on startup, so this also clears stale data
# from a previous run while the new swarm is initialising.
STALE_THRESHOLD_S = 8.0


class VoronoiModule(mp_module.MPModule):
    def __init__(self, mpstate):
        super().__init__(mpstate, "voronoi", "Voronoi partition overlay")
        self._poll_interval = 2.0
        self._last_poll     = 0
        self._last_mtime    = 0
        self._last_seen     = 0.0   # wall-clock time of last successful read
        self._state_file    = None
        self._tick          = 0
        self._cleared       = False  # True after we've wiped stale overlays
        print("[voronoi] loaded ✓")

    def _get_state_file(self) -> str:
        if self._state_file is None:
            self._state_file = _resolve_state_file()
            print(f"[voronoi] STATE_FILE → {self._state_file}")
        return self._state_file

    def _get_map(self):
        """Return map module if fully initialised, else None."""
        m = self.module("map")
        if m is None or not hasattr(m, "map"):
            return None
        return m

    def _clear_overlays(self, map_module):
        """Remove all voronoi overlay objects."""
        try:
            keys = list(map_module.map.objects.keys())
            for k in keys:
                if k.startswith("voronoi_"):
                    map_module.map.remove_object(k)
        except Exception:
            pass

    def _suppress_arrows(self, map_module):
        """Remove MAVProxy's built-in heading/velocity arrows."""
        try:
            for k in list(map_module.map.objects.keys()):
                if any(x in k.lower() for x in ("arrow", "heading", "velocity")):
                    map_module.map.remove_object(k)
        except Exception:
            pass

    def _add_object(self, map_module, obj_id, obj_type, *args, **kwargs):
        """
        Try adding a SlipPolygon or SlipLabel with layer= kwarg first,
        then fall back without it for older MAVProxy versions.
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

        # ── Suppress MAVProxy arrows (best-effort) ────────────────────
        if map_module is not None:
            self._suppress_arrows(map_module)

        # ── Handle missing/stale file ─────────────────────────────────
        if not os.path.exists(state_file):
            if map_module is not None and not self._cleared:
                self._clear_overlays(map_module)
                self._cleared = True
                print("[voronoi] state file absent — overlays cleared")
            return

        mtime = os.path.getmtime(state_file)

        # Clear stale overlays if file hasn't updated for STALE_THRESHOLD_S
        # (covers the window between swarm_main deleting the old file and
        # writing the first new one — mtime doesn't change in that gap)
        if self._last_seen > 0 and (now - self._last_seen) > STALE_THRESHOLD_S:
            if map_module is not None and not self._cleared:
                self._clear_overlays(map_module)
                self._cleared = True
                print("[voronoi] stale state — overlays cleared")

        if mtime == self._last_mtime:
            return
        self._last_mtime = mtime
        self._last_seen  = now
        self._cleared    = False   # new data — allow drawing again

        # ── Load ──────────────────────────────────────────────────────
        try:
            state  = np.load(state_file, allow_pickle=True).item()
            agents = state.get("agents", [])
        except Exception as e:
            print(f"[voronoi] load error: {e}")
            return

        if map_module is None:
            return

        # ── Draw each drone's territory and trail ─────────────────────
        for a in agents:
            drone_id  = a["id"]
            territory = a.get("territory", [])
            path      = a.get("path", [])
            color     = COLORS[drone_id % len(COLORS)]

            # Zone polygon
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

            # Flight trail
            if len(path) >= 2:
                trail = [(float(p[0]), float(p[1])) for p in path]
                self._add_object(map_module,
                    f"voronoi_trail_{drone_id}", "polygon",
                    trail, layer="voronoi", linewidth=1, colour=color)


def init(mpstate):
    return VoronoiModule(mpstate)