"""
mavproxy_voronoi.py
-------------------
MAVProxy module that overlays Voronoi partition polygons on the map.

Load with:
    mavproxy.py ... --load-module voronoi

Or from MAVProxy console:
    module load voronoi
"""

import numpy as np
import os
import time
from MAVProxy.modules.lib import mp_module
from MAVProxy.modules.mavproxy_map import mp_slipmap

STATE_FILE = os.path.join(os.path.dirname(__file__), ".agent_state.npy")

COLORS = [
    (230, 25,  75),   # red
    (60,  180, 75),   # green
    (67,  99,  216),  # blue
    (245, 130, 49),   # orange
    (145, 30,  180),  # purple
    (66,  212, 244),  # cyan
    (240, 50,  230),  # magenta
    (191, 239, 69),   # lime
    (250, 190, 212),  # pink
    (70,  153, 144),  # teal
    (220, 190, 255),  # lavender
    (154, 99,  36),   # brown
]


class VoronoiModule(mp_module.MPModule):
    def __init__(self, mpstate):
        super().__init__(mpstate, "voronoi", "Voronoi partition overlay")
        self._last_mtime = 0
        self._poll_interval = 2.0
        self._last_poll = 0
        print("[voronoi] Voronoi partition overlay loaded ✓")

    def idle_task(self):
        now = time.time()
        if now - self._last_poll < self._poll_interval:
            return
        self._last_poll = now

        if not os.path.exists(STATE_FILE):
            return

        mtime = os.path.getmtime(STATE_FILE)
        if mtime == self._last_mtime:
            return
        self._last_mtime = mtime

        try:
            state  = np.load(STATE_FILE, allow_pickle=True).item()
            agents = state.get("agents", [])
        except Exception:
            return

        map_module = self.module("map")
        if map_module is None:
            return

        for a in agents:
            drone_id  = a["id"]
            territory = a.get("territory", [])
            color     = COLORS[drone_id % len(COLORS)]

            if len(territory) == 0:
                continue

            pts = np.array(territory)

            try:
                from scipy.spatial import ConvexHull
                if len(pts) < 3:
                    polygon = [(float(pts[0][0]), float(pts[0][1]))]
                else:
                    hull  = ConvexHull(pts)
                    verts = pts[hull.vertices]
                    verts = np.vstack([verts, verts[0]])
                    polygon = [(float(p[0]), float(p[1])) for p in verts]
            except Exception:
                polygon = [(float(p[0]), float(p[1])) for p in pts]

            map_module.map.add_object(
                mp_slipmap.SlipPolygon(
                    f"voronoi_zone_{drone_id}",
                    polygon,
                    layer="voronoi",
                    linewidth=2,
                    colour=color,
                )
            )

            centroid_lat = float(pts[:, 0].mean())
            centroid_lon = float(pts[:, 1].mean())
            map_module.map.add_object(
                mp_slipmap.SlipLabel(
                    f"voronoi_label_{drone_id}",
                    (centroid_lat, centroid_lon),
                    f"D{drone_id}",
                    layer="voronoi",
                    colour=color,
                )
            )


def init(mpstate):
    return VoronoiModule(mpstate)