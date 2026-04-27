"""
mavproxy_voronoi.py
-------------------
MAVProxy module that overlays Voronoi partition polygons on the map.
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
        if not entry:
            continue
        if os.path.exists(os.path.join(entry, "mavproxy_voronoi.py")):
            return os.path.join(entry, ".agent_state.npy")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), ".agent_state.npy")


COLORS = [
    (230, 25,  75),
    (60,  180, 75),
    (67,  99,  216),
    (245, 130, 49),
    (145, 30,  180),
    (66,  212, 244),
    (240, 50,  230),
    (191, 239, 69),
    (250, 190, 212),
    (70,  153, 144),
    (220, 190, 255),
    (154, 99,  36),
]


class VoronoiModule(mp_module.MPModule):
    def __init__(self, mpstate):
        super().__init__(mpstate, "voronoi", "Voronoi partition overlay")
        self._last_mtime    = 0
        self._poll_interval = 2.0
        self._last_poll     = 0
        self._state_file    = None
        self._draw_count    = 0   # total successful polygon draws
        self._diag_ticks    = 0   # counts idle_task calls for periodic diag
        print("[voronoi] loaded ✓")

    def _get_state_file(self) -> str:
        if self._state_file is None:
            self._state_file = _resolve_state_file()
            print(f"[voronoi] STATE_FILE resolved → {self._state_file}")
        return self._state_file

    def idle_task(self):
        now = time.time()
        if now - self._last_poll < self._poll_interval:
            return
        self._last_poll = now
        self._diag_ticks += 1

        state_file = self._get_state_file()

        # ── Suppress heading/velocity arrows ─────────────────────────
        map_module = self.module("map")
        if map_module is not None:
            for obj_key in list(map_module.map.objects.keys()):
                if any(k in obj_key.lower() for k in ("arrow", "heading", "velocity")):
                    map_module.map.remove_object(obj_key)

        # ── Every 10 ticks (~20s) print a heartbeat ───────────────────
        if self._diag_ticks % 10 == 1:
            exists = os.path.exists(state_file)
            print(f"[voronoi] tick={self._diag_ticks} file_exists={exists} "
                  f"draws_so_far={self._draw_count}")

        if not os.path.exists(state_file):
            return

        mtime = os.path.getmtime(state_file)
        if mtime == self._last_mtime:
            return
        self._last_mtime = mtime

        # ── Load state ────────────────────────────────────────────────
        try:
            raw   = np.load(state_file, allow_pickle=True)
            state = raw.item()
        except Exception as e:
            print(f"[voronoi] load error: {e}")
            return

        agents = state.get("agents", [])
        if self._diag_ticks <= 3 or self._diag_ticks % 10 == 1:
            print(f"[voronoi] loaded state: {len(agents)} agents")
            for a in agents:
                print(f"  drone {a['id']}: "
                      f"territory={len(a.get('territory',[]))} pts, "
                      f"path={len(a.get('path',[]))} pts")

        map_module = self.module("map")
        if map_module is None:
            print("[voronoi] WARNING: map module is None — cannot draw")
            return

        # ── Check map object ──────────────────────────────────────────
        if not hasattr(map_module, "map"):
            print(f"[voronoi] WARNING: map_module has no .map attr. "
                  f"attrs={[x for x in dir(map_module) if not x.startswith('_')]}")
            return

        tick_draws = 0

        for a in agents:
            drone_id  = a["id"]
            territory = a.get("territory", [])
            path      = a.get("path", [])
            color     = COLORS[drone_id % len(COLORS)]

            # ── Voronoi zone polygon ───────────────────────────────────
            if len(territory) >= 3:
                pts = np.array(territory)
                try:
                    hull    = ConvexHull(pts)
                    verts   = pts[hull.vertices]
                    verts   = np.vstack([verts, verts[0]])
                    polygon = [(float(p[0]), float(p[1])) for p in verts]
                except Exception as e:
                    if self._diag_ticks <= 3:
                        print(f"[voronoi] ConvexHull failed drone {drone_id}: {e}")
                    polygon = [(float(p[0]), float(p[1])) for p in pts]

                try:
                    map_module.map.add_object(
                        mp_slipmap.SlipPolygon(
                            f"voronoi_zone_{drone_id}",
                            polygon,
                            layer="voronoi",
                            linewidth=2,
                            colour=color,
                        )
                    )
                    tick_draws += 1
                except Exception as e:
                    print(f"[voronoi] add_object (polygon) failed drone {drone_id}: {e}")

                # Label at centroid
                centroid_lat = float(pts[:, 0].mean())
                centroid_lon = float(pts[:, 1].mean())
                try:
                    map_module.map.add_object(
                        mp_slipmap.SlipLabel(
                            f"voronoi_label_{drone_id}",
                            (centroid_lat, centroid_lon),
                            f"D{drone_id}",
                            layer="voronoi",
                            colour=color,
                        )
                    )
                except Exception as e:
                    print(f"[voronoi] add_object (label) failed drone {drone_id}: {e}")

            elif len(territory) > 0 and self._diag_ticks <= 3:
                print(f"[voronoi] drone {drone_id} only {len(territory)} territory pts — skipping polygon")

            # ── Flight trail ──────────────────────────────────────────
            if len(path) >= 2:
                trail = [(float(p[0]), float(p[1])) for p in path]
                try:
                    map_module.map.add_object(
                        mp_slipmap.SlipPolygon(
                            f"voronoi_trail_{drone_id}",
                            trail,
                            layer="voronoi",
                            linewidth=1,
                            colour=color,
                        )
                    )
                    tick_draws += 1
                except Exception as e:
                    print(f"[voronoi] add_object (trail) failed drone {drone_id}: {e}")

        self._draw_count += tick_draws
        if tick_draws > 0 and self._diag_ticks <= 5:
            print(f"[voronoi] drew {tick_draws} objects this tick "
                  f"(total={self._draw_count})")


def init(mpstate):
    return VoronoiModule(mpstate)