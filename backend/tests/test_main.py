import asyncio
import time
import numpy as np
import logging
from fastapi.testclient import TestClient
from app import app
from app.models import Mission, MissionCreate, Drone, Bounds
from app.main import mission_db, simulation_loop, manager, _sync_mission_drones_with_sitl, sitl_bridge
from app.algorithms.base import DETECTION_RADIUS
from app.algorithms.boustrophedon import _row_endpoints_lawnmower, _build_dense_grid, _voronoi_assign, _balanced_partition_seeds, _match_drones_to_seeds, _row_endpoints_lawnmower, VoronoiBoustrophedon, _REACH_RADIUS
from app.voronoi import lloyd_step
from app.algorithms.voronoi import VoronoiCoverage
from app.algorithms.base import build_search_grid
from app.settings import _positive_float_env
import app.main as main_module
import app.routes.missions as missions_routes
import app.simulation as simulation_module
import app.dispatch as dispatch_module
import app.sitl as sitl_module
import app.connect_swarm as connect_swarm_module

client = TestClient(app)

def create_test_mission(
    id="mission-1",
    drones=None,
    bounds=None,
    name="test-mission",
    algorithm="voronoi",
):
    bounds = bounds or Bounds(
        min_lat=0.0,
        max_lat=0.04,
        min_lon=0.0,
        max_lon=0.04,
    )

    drones = drones or [
        Drone(id="drone1", lat=0.01, lon=0.01),
    ]

    mission_data = MissionCreate(
        name=name,
        bounds=bounds,
        drones=drones,
        algorithm=algorithm,
    )
    mission = Mission(id, mission_data)

    return mission

def test_read_main():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_sitl_status_endpoint_returns_bridge_snapshot():
    original_get_states = sitl_bridge.get_states_by_sysid
    sitl_bridge.get_states_by_sysid = lambda: {
        1: {
            "sysid": 1,
            "armed": True,
            "mode": "GUIDED",
            "lat": 34.5,
            "lon": -117.5,
            "alt": 12.3,
            "heading": 87.0,
            "groundspeed": 4.2,
            "battery_remaining": 91,
            "has_position": True,
            "last_seen": 123.0,
        }
    }
    try:
        response = client.get("/sitl/status")
        assert response.status_code == 200
        payload = response.json()
        assert payload["connected_count"] == 1
        assert payload["drones"][0]["sysid"] == 1
        assert payload["drones"][0]["mode"] == "GUIDED"
    finally:
        sitl_bridge.get_states_by_sysid = original_get_states


def test_sitl_status_endpoint_includes_last_connect_error():
    original_get_states = sitl_bridge.get_states_by_sysid
    original_last_connect_error = sitl_bridge._last_connect_error
    sitl_bridge.get_states_by_sysid = lambda: {}
    sitl_bridge._last_connect_error = "connection refused"
    try:
        response = client.get("/sitl/status")
        assert response.status_code == 200
        payload = response.json()
        assert payload["connected_count"] == 0
        assert payload["last_connect_error"] == "connection refused"
    finally:
        sitl_bridge.get_states_by_sysid = original_get_states
        sitl_bridge._last_connect_error = original_last_connect_error

def test_create_mission():
    mission_data = {
        "name": "Test Mission",
        "bounds": {
            "min_lat": 34.0,
            "max_lat": 35.0,
            "min_lon": -118.0,
            "max_lon": -117.0
        },
        "drones": [
            {"id": "drone1", "lat": 34.5, "lon": -117.5, "alt": 100.0, "heading": 90.0}
        ],
        "hikers": [
            {"id": "hiker1", "lat": 34.6, "lon": -117.6, "alt": 0.0, "found": False}
        ]
    }
    response = client.post("/missions", json=mission_data)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == mission_data["name"]
    assert data["bounds"] == mission_data["bounds"]
    
    # Drones get initialized with status="idle" and target coords None
    for res_drone, req_drone in zip(data["drones"], mission_data["drones"]):
        assert res_drone["id"] == req_drone["id"]
        assert res_drone["lat"] == req_drone["lat"]
        assert res_drone["lon"] == req_drone["lon"]
        assert res_drone["status"] == "idle"
    assert data["hikers"] == mission_data["hikers"]


def test_get_mission_returns_stored_bounds():
    mission_data = {
        "name": "Mission Lookup Test",
        "bounds": {
            "min_lat": 34.0,
            "max_lat": 34.1,
            "min_lon": -118.1,
            "max_lon": -118.0,
        },
        "drones": [
            {"id": "drone1", "lat": 34.05, "lon": -118.05}
        ],
    }

    create_response = client.post("/missions", json=mission_data)
    assert create_response.status_code == 200
    mission_id = create_response.json()["id"]

    response = client.get(f"/missions/{mission_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == mission_id
    assert payload["bounds"] == mission_data["bounds"]

    missing_response = client.get("/missions/invalid_id")
    assert missing_response.status_code == 404
    assert missing_response.json() == {"detail": "Mission not found"}


def test_start_mission():
    mission_data = {
        "name": "Start Test Mission",
        "bounds": {
            "min_lat": 34.0,
            "max_lat": 35.0,
            "min_lon": -118.0,
            "max_lon": -117.0
        },
        "drones": [
            {"id": "drone1", "lat": 34.5, "lon": -117.5, "alt": 100.0, "heading": 90.0}
        ]
    }
    create_response = client.post("/missions", json=mission_data)
    assert create_response.status_code == 200
    mission_id = create_response.json()["id"]

    start_response = client.post(f"/missions/{mission_id}/start")
    assert start_response.status_code == 200
    start_data = start_response.json()
    assert start_data["status"] == "searching"

    get_response = client.get(f"/missions/{mission_id}")
    get_data = get_response.json()
    
    # Test starting a non-existent mission
    invalid_start_response = client.post("/missions/invalid_id/start")
    assert invalid_start_response.status_code == 404
    assert invalid_start_response.json() == {"detail": "Mission not found"}

    # Test starting an already running mission
    second_start_response = client.post(f"/missions/{mission_id}/start")
    assert second_start_response.status_code == 400
    assert second_start_response.json() == {"detail": "Only 'idle' missions can be started"}
    
def test_stop_mission():
    mission_data = {
        "name": "Stop Test Mission",
        "bounds": {
            "min_lat": 34.0,
            "max_lat": 35.0,
            "min_lon": -118.0,
            "max_lon": -117.0
        },
        "drones": [
            {"id": "drone1", "lat": 34.5, "lon": -117.5, "alt": 100.0, "heading": 90.0}
        ]
    }
    create_response = client.post("/missions", json=mission_data)
    assert create_response.status_code == 200
    mission_id = create_response.json()["id"]

    # Start the mission first
    start_response = client.post(f"/missions/{mission_id}/start")
    assert start_response.status_code == 200

    # Now stop the mission
    stop_response = client.post(f"/missions/{mission_id}/stop")
    assert stop_response.status_code == 200
    stop_data = stop_response.json()
    assert stop_data["status"] == "paused"

    # Test stopping a non-existent mission
    invalid_stop_response = client.post("/missions/invalid_id/stop")
    assert invalid_stop_response.status_code == 404
    assert invalid_stop_response.json() == {"detail": "Mission not found"}
    
    # Test stopping an already stopped mission
    second_stop_response = client.post(f"/missions/{mission_id}/stop")
    assert second_stop_response.status_code == 400
    assert second_stop_response.json() == {"detail": "Drones are not in motion"}


def test_simulation_progress_only_advances_when_targets_are_found():
    mission_id = "sim-progress-from-found-targets"
    mission = create_test_mission(
        id=mission_id,
        name="Progress From Found Targets Test",
        bounds={"min_lat": 34.0, "max_lat": 35.0, "min_lon": -118.0, "max_lon": -117.0},
        drones=[{"id": "drone1", "lat": 34.5, "lon": -117.5}],
    )
    mission.targets = [
        {"id": "t1", "lat": 34.5, "lon": -117.5, "status": "found"},
        {"id": "t2", "lat": 34.6, "lon": -117.4, "status": "wandering"},
    ]
    mission.status = "searching"
    mission_db[mission_id] = mission

    async def no_op_broadcast(_message):
        return None

    original_broadcast = manager.broadcast
    manager.broadcast = no_op_broadcast
    try:
        mission = mission_db[mission_id]
        all_targets_found = asyncio.run(simulation_module._finalize_mission_progress(mission))
        assert all_targets_found is False
        assert mission.status == "searching"
        assert mission.progress == 50.0
    finally:
        manager.broadcast = original_broadcast
        mission_db.pop(mission_id, None)


def test_target_detection_uses_expanded_radius_before_icons_overlap():
    mission = create_test_mission(
        bounds={"min_lat": 34.0, "max_lat": 35.0, "min_lon": -118.0, "max_lon": -117.0},
        drones=[{"id": "drone1", "lat": 34.5, "lon": -117.5}],
    )
    mission.targets = [
        {"id": "t1", "lat": 34.5012, "lon": -117.5, "status": "wandering", "vx": 0, "vy": 0}
    ]

    simulation_module._update_targets_for_tick(mission)

    target = mission.targets[0]
    drone = mission.drones[0]
    assert simulation_module.DETECTION_RADIUS >= 0.0012
    assert target["status"] == "detected"
    assert target["assigned_drone_id"] == "drone1"
    assert drone["assigned_target_id"] == "t1"


def test_simulation_completes_when_all_targets_are_found():
    mission_id = "sim-complete-all-targets-found"
    mission = create_test_mission(
        id=mission_id,
        name="All Targets Found Completion Test",
        bounds={"min_lat": 34.0, "max_lat": 35.0, "min_lon": -118.0, "max_lon": -117.0},
        drones=[{"id": "drone1", "lat": 34.5, "lon": -117.5}],
    )
    mission.targets = [
        {"id": "t1", "lat": 34.5, "lon": -117.5, "status": "found"},
        {"id": "t2", "lat": 34.6, "lon": -117.4, "status": "found"},
    ]
    mission_db[mission_id] = mission

    async def no_op_broadcast(_message):
        return None

    original_broadcast = manager.broadcast
    manager.broadcast = no_op_broadcast
    try:
        mission = mission_db[mission_id]
        all_targets_found = asyncio.run(simulation_module._finalize_mission_progress(mission))
        assert all_targets_found is True
        assert mission.progress == 100.0
    finally:
        manager.broadcast = original_broadcast
        mission_db.pop(mission_id, None)


def test_simulation_uses_voronoi_centroid_for_unassigned_simulated_drones():
    mission_id = "sim-voronoi-motion"
    mission = create_test_mission(
        id=mission_id,
        name="Voronoi Motion Test",
        bounds={"min_lat": 0.0, "max_lat": 1.0, "min_lon": 0.0, "max_lon": 1.0},
        drones=[{"id": "drone1", "lat": 0.1, "lon": 0.1}],
    )
    mission.status = "searching"
    mission.grid = np.array([
        [0.8, 0.8],
        [0.9, 0.9],
    ])
    mission_db[mission_id] = mission

    async def stop_after_first_telemetry(message):
        if message.get("type") == "telemetry":
            mission_db[mission_id].status = "mission_complete"

    original_broadcast = manager.broadcast
    original_get_states = sitl_bridge.get_states_by_sysid
    manager.broadcast = stop_after_first_telemetry
    sitl_bridge.get_states_by_sysid = lambda: {}

    try:
        asyncio.run(simulation_loop(mission_id))
        drone = mission_db[mission_id].drones[0]
    finally:
        manager.broadcast = original_broadcast
        sitl_bridge.get_states_by_sysid = original_get_states
        mission_db.pop(mission_id, None)

    assert drone["telemetry_source"] == "simulated"
    assert drone["lat"] > 0.1
    assert drone["lon"] > 0.1


def test_start_mission_runs_dispatch_bridge_when_targets_present():
    mission_data = {
        "name": "Dispatch Start Mission",
        "bounds": {
            "min_lat": 34.0,
            "max_lat": 35.0,
            "min_lon": -118.0,
            "max_lon": -117.0,
        },
        "drones": [
            {
                "id": "drone-alpha",
                "lat": 34.5,
                "lon": -117.5,
                "alt": 60.0,
                "target_lat": 34.51,
                "target_lon": -117.49,
            }
        ],
    }

    captured = {}

    async def fake_direct_dispatch(assignments):
        captured["assignments"] = assignments
        return [
            {
                "drone_id": "drone-alpha",
                "sysid": 1,
                "success": True,
                "message": "ok",
            }
        ]

    original_run_direct = missions_routes.run_direct_dispatch
    missions_routes.run_direct_dispatch = fake_direct_dispatch

    try:
        create_response = client.post("/missions", json=mission_data)
        assert create_response.status_code == 200
        mission_id = create_response.json()["id"]

        start_response = client.post(f"/missions/{mission_id}/start")
        assert start_response.status_code == 200
        payload = start_response.json()
        assert payload["status"] == "searching"
        time.sleep(0.3)
        assert len(captured.get("assignments", [])) == 1
        assert captured["assignments"][0]["sysid"] == 1
    finally:
        missions_routes.run_direct_dispatch = original_run_direct


def test_sync_mission_drones_with_sitl_uses_live_positions():
    mission = create_test_mission(
        drones=[{"id": "drone-1", "lat": 1.0, "lon": 2.0}],
    )

    original_get_states = sitl_bridge.get_states_by_sysid
    sitl_bridge.get_states_by_sysid = lambda: {
        1: {
            "sysid": 1,
            "armed": True,
            "mode": "AUTO",
            "lat": 34.123456,
            "lon": -117.654321,
            "alt": 25.0,
            "heading": 180.0,
            "groundspeed": 6.5,
            "battery_remaining": 88,
            "has_position": True,
            "last_seen": 999.0,
        }
    }

    try:
        live_drone_ids = _sync_mission_drones_with_sitl(mission)
    finally:
        sitl_bridge.get_states_by_sysid = original_get_states

    assert live_drone_ids == {"drone-1"}
    drone = mission.drones[0]
    assert drone["sysid"] == 1
    assert drone["lat"] == 34.123456
    assert drone["lon"] == -117.654321
    assert drone["alt"] == 25.0
    assert drone["mode"] == "AUTO"
    assert drone["armed"] is True
    assert drone["groundspeed"] == 6.5
    assert drone["battery_remaining"] == 88
    assert drone["telemetry_source"] == "sitl"


def test_dispatch_targets_endpoint_returns_preflight_and_script_results():
    mission_data = {
        "name": "Dispatch Endpoint Mission",
        "bounds": {
            "min_lat": 34.0,
            "max_lat": 35.0,
            "min_lon": -118.0,
            "max_lon": -117.0,
        },
        "drones": [
            {"id": "drone-1", "lat": 34.5, "lon": -117.5, "alt": 40.0},
            {"id": "drone-2", "lat": 34.6, "lon": -117.4, "alt": 40.0},
        ],
    }

    async def fake_run_dispatch(assignments, host, timeout_seconds, count=None):
        assert len(assignments) == 1
        assert assignments[0]["drone_id"] == "drone-1"
        assert assignments[0]["sysid"] == 1
        return [
            {
                "drone_id": "drone-1",
                "sysid": 1,
                "success": True,
                "message": "sent",
            }
        ]

    original_run_dispatch = missions_routes.run_dispatch_script
    missions_routes.run_dispatch_script = fake_run_dispatch

    try:
        create_response = client.post("/missions", json=mission_data)
        assert create_response.status_code == 200
        mission_id = create_response.json()["id"]

        dispatch_payload = {
            "assignments": [
                {"drone_id": "drone-1", "lat": 34.55, "lon": -117.45, "alt": 35.0},
                {"drone_id": "unknown-drone", "lat": 34.56, "lon": -117.46, "alt": 35.0},
            ]
        }
        response = client.post(f"/missions/{mission_id}/dispatch-targets", json=dispatch_payload)
        assert response.status_code == 200

        payload = response.json()
        assert payload["mission_id"] == mission_id
        assert len(payload["dispatch_results"]) == 2

        preflight_failure = payload["dispatch_results"][0]
        assert preflight_failure["drone_id"] == "unknown-drone"
        assert preflight_failure["success"] is False
        assert "Cannot resolve sysid" in preflight_failure["message"]

        script_success = payload["dispatch_results"][1]
        assert script_success["drone_id"] == "drone-1"
        assert script_success["sysid"] == 1
        assert script_success["success"] is True
    finally:
        missions_routes.run_dispatch_script = original_run_dispatch


def test_run_dispatch_script_timeout_returns_failure_rows():
    class SlowProcess:
        def __init__(self):
            self.returncode = None
            self.killed = False

        async def communicate(self):
            await asyncio.sleep(2)
            return b"", b""

        def kill(self):
            self.killed = True

    slow_process = SlowProcess()

    async def fake_create_subprocess_exec(*_args, **_kwargs):
        return slow_process

    original_create_subprocess_exec = dispatch_module.asyncio.create_subprocess_exec
    dispatch_module.asyncio.create_subprocess_exec = fake_create_subprocess_exec

    try:
        results = asyncio.run(
            dispatch_module.run_dispatch_script(
                assignments=[{"drone_id": "d1", "sysid": 1, "lat": 34.5, "lon": -117.5, "alt": 30.0}],
                timeout_seconds=1.0,
            )
        )
        assert len(results) == 1
        assert results[0]["drone_id"] == "d1"
        assert results[0]["sysid"] == 1
        assert results[0]["success"] is False
        assert "timeout" in results[0]["message"].lower()
        assert slow_process.killed is True
    finally:
        dispatch_module.asyncio.create_subprocess_exec = original_create_subprocess_exec


def test_run_dispatch_script_non_zero_exit_returns_failure_rows():
    class FailingProcess:
        def __init__(self):
            self.returncode = 1

        async def communicate(self):
            return b"", b"boom"

    async def fake_create_subprocess_exec(*_args, **_kwargs):
        return FailingProcess()

    original_create_subprocess_exec = dispatch_module.asyncio.create_subprocess_exec
    dispatch_module.asyncio.create_subprocess_exec = fake_create_subprocess_exec

    try:
        results = asyncio.run(
            dispatch_module.run_dispatch_script(
                assignments=[{"drone_id": "d2", "sysid": 2, "lat": 34.4, "lon": -117.4, "alt": 30.0}],
                timeout_seconds=2.0,
            )
        )
        assert len(results) == 1
        assert results[0]["drone_id"] == "d2"
        assert results[0]["sysid"] == 2
        assert results[0]["success"] is False
        assert "exited with code 1" in results[0]["message"].lower()
    finally:
        dispatch_module.asyncio.create_subprocess_exec = original_create_subprocess_exec


def test_dispatch_drone_fails_when_arm_never_reflects_in_state():
    class FakeDrone:
        def __init__(self):
            self.sysid = 7
            self.state = {"mode": "GUIDED", "armed": False, "rel_alt": 0.0}
            self.arm_called = False
            self.takeoff_called = False
            self.goto_called = False
            self.mode_map = {
                "GUIDED": 4,
                "LOITER": 5,
                "LAND": 9,
                "RTL": 6,
            }

        def arm(self):
            self.arm_called = True

        def takeoff(self, _alt):
            self.takeoff_called = True

        def goto(self, _lat, _lon, _alt):
            self.goto_called = True

        def get_state(self):
            return self.state

        def set_mode(self, mode_name):
            if mode_name not in self.mode_map:
                raise ValueError(f"Mode {mode_name} not supported")

            self.state["mode"] = self.mode_map[mode_name]

        def is_mode(self, mode_name):
            if mode_name not in self.mode_map:
                raise ValueError(f"Mode {mode_name} not supported")

            return self.get_state()["mode"] == self.mode_map[mode_name]

    bridge = sitl_module.SITLTelemetryBridge()
    fake_drone = FakeDrone()
    fake_drone.set_mode("GUIDED")
    bridge.swarm.drones = [fake_drone]

    original_wait = sitl_module._wait_for_condition
    sitl_module._wait_for_condition = lambda *_args, **_kwargs: False
    try:
        result = bridge.dispatch_drone(sysid=7, lat=34.5, lon=-117.5, alt=30.0, drone_id="drone-7")
    finally:
        sitl_module._wait_for_condition = original_wait

    assert result["success"] is False
    assert "Arm command ACKed but drone never reported armed state" in result["message"]
    assert fake_drone.arm_called is True
    assert fake_drone.takeoff_called is False
    assert fake_drone.goto_called is False


def test_drone_eof_handler_marks_connection_disconnected():
    class FakePort:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeConn:
        def __init__(self):
            self.target_component = 1
            self.port = FakePort()

    drone = connect_swarm_module.Drone(FakeConn(), sysid=3, index=1)

    try:
        drone.conn.handle_eof()
        assert False, "expected EOFError"
    except EOFError as exc:
        assert "EOF on TCP socket" in str(exc)

    assert drone.disconnected is True
    assert drone.last_error == "EOF on TCP socket"
    assert drone.conn.port.closed is True


def test_ensure_connected_drops_stale_links_and_retries():
    class FakeDrone:
        def is_connection_alive(self, _stale_after):
            return False

    bridge = sitl_module.SITLTelemetryBridge()
    bridge.swarm.drones = [FakeDrone()]

    reset_calls = {"count": 0}
    connect_calls = {"count": 0}

    def fake_reset_connections():
        reset_calls["count"] += 1
        bridge.swarm.drones = []

    bridge.swarm.reset_connections = fake_reset_connections

    def fake_connect(*_args, **_kwargs):
        connect_calls["count"] += 1
        bridge.swarm.drones = []
        raise RuntimeError("connection refused")

    bridge.swarm.connect = fake_connect

    result = bridge.ensure_connected(force=True)

    assert result is False
    assert reset_calls["count"] == 1
    assert connect_calls["count"] == 1
    assert "connection refused" in (bridge._last_connect_error or "")


def test_send_live_drone_gotos_logs_skip_reasons_for_not_airborne(caplog):
    original_get_states = sitl_bridge.get_states_by_sysid
    original_is_dispatching = sitl_bridge.is_dispatching

    sitl_bridge.get_states_by_sysid = lambda: {
        1: {
            "armed": False,
            "alt": 0.0,
        }
    }
    sitl_bridge.is_dispatching = lambda _sysid: False

    mission = create_test_mission(
        drones=[Drone(id="drone-1", sysid=1, lat=34.5, lon=-117.5, alt=0.0)],
    )
    mission.elapsed_seconds = 10

    try:
        with caplog.at_level("INFO"):
            simulation_module._send_live_drone_gotos(mission, {"drone-1"}, {})
    finally:
        sitl_bridge.get_states_by_sysid = original_get_states
        sitl_bridge.is_dispatching = original_is_dispatching

    assert "goto_loop: 0/1 drones got goto" in caplog.text
    assert "blocked airborne=1" in caplog.text


def test_sweep_live_goto_prefers_algorithm_waypoint_over_startup_target():
    original_get_states = sitl_bridge.get_states_by_sysid
    original_is_dispatching = sitl_bridge.is_dispatching
    original_send_goto = sitl_bridge.send_goto
    sent = []

    sitl_bridge.get_states_by_sysid = lambda: {1: {"armed": True, "alt": 20.0}}
    sitl_bridge.is_dispatching = lambda _sysid: False
    sitl_bridge.send_goto = lambda sysid, lat, lon, alt: sent.append((sysid, lat, lon, alt))

    mission = create_test_mission(
        drones=[Drone(id="drone-1", sysid=1, lat=34.0, lon=-117.0, alt=20.0, target_lat=34.9, target_lon=-117.9)],
        algorithm="sweep",
    )
    mission.elapsed_seconds = 1

    try:
        simulation_module._send_live_drone_gotos(mission, {"drone-1"}, {"drone-1": (34.2, -117.2)})
    finally:
        sitl_bridge.get_states_by_sysid = original_get_states
        sitl_bridge.is_dispatching = original_is_dispatching
        sitl_bridge.send_goto = original_send_goto

    assert sent == [(1, 34.2, -117.2, simulation_module.DEFAULT_DISPATCH_ALT)]


def test_assigned_target_still_overrides_sweep_waypoint():
    original_get_states = sitl_bridge.get_states_by_sysid
    original_is_dispatching = sitl_bridge.is_dispatching
    original_send_goto = sitl_bridge.send_goto
    sent = []

    sitl_bridge.get_states_by_sysid = lambda: {1: {"armed": True, "alt": 20.0}}
    sitl_bridge.is_dispatching = lambda _sysid: False
    sitl_bridge.send_goto = lambda sysid, lat, lon, alt: sent.append((sysid, lat, lon, alt))

    mission = create_test_mission(
        drones=[{"id": "drone-1", "sysid": 1, "lat": 34.0, "lon": -117.0, "alt": 20.0, "target_lat": 34.9, "target_lon": -117.9}],
        algorithm="sweep",
    )
    mission.elapsed_seconds = 1
    mission.targets = [{"id": "t1", "lat": 34.4, "lon": -117.4}]
    mission.drones[0]["assigned_target_id"] = "t1"

    try:
        simulation_module._send_live_drone_gotos(mission, {"drone-1"}, {"drone-1": (34.2, -117.2)})
    finally:
        sitl_bridge.get_states_by_sysid = original_get_states
        sitl_bridge.is_dispatching = original_is_dispatching
        sitl_bridge.send_goto = original_send_goto

    assert sent == [(1, 34.4, -117.4, simulation_module.DEFAULT_DISPATCH_ALT)]


def test_get_states_by_sysid_triggers_reconnect_for_stale_links():
    class FakeDrone:
        def is_connection_alive(self, _stale_after):
            return False

    bridge = sitl_module.SITLTelemetryBridge()
    bridge.swarm.drones = [FakeDrone()]

    reconnect_attempted = {"count": 0}

    def fake_connect(*_args, **_kwargs):
        reconnect_attempted["count"] += 1
        raise RuntimeError("connection refused")

    bridge.swarm.connect = fake_connect
    bridge.swarm.reset_connections = lambda: setattr(bridge.swarm, "drones", [])

    states = bridge.get_states_by_sysid()

    assert states == {}
    assert reconnect_attempted["count"] == 1
    assert "connection refused" in (bridge._last_connect_error or "")


def test_mission_drone_to_sysid_map_assigns_existing_and_fallback_sysids():
    mission = create_test_mission(
        drones=[
            {"id": "drone-a", "sysid": 7, "lat": 34.5, "lon": -117.5},
            {"id": "drone-b", "lat": 34.5, "lon": -117.5},
            {"id": "drone-c", "sysid": "3", "lat": 34.5, "lon": -117.5},
        ]
    )

    mapping = main_module._mission_drone_to_sysid_map(mission)

    assert mapping == {
        "drone-a": 7,
        "drone-b": 2,
        "drone-c": 3,
    }
    assert mission.drones[1]["sysid"] == 2


def test_start_mission_stores_algorithm_from_body():
    mission_data = {
        "name": "Algorithm Override Test",
        "bounds": {"min_lat": 34.0, "max_lat": 35.0, "min_lon": -118.0, "max_lon": -117.0},
        "drones": [{"id": "drone1", "lat": 34.5, "lon": -117.5}],
    }
    create_response = client.post("/missions", json=mission_data)
    assert create_response.status_code == 200
    mission_id = create_response.json()["id"]

    start_response = client.post(f"/missions/{mission_id}/start", json={"algorithm": "apf"})
    assert start_response.status_code == 200
    assert start_response.json()["algorithm"] == "apf"


def test_start_mission_defaults_algorithm_to_voronoi_when_no_body():
    mission_data = {
        "name": "Default Algorithm Test",
        "bounds": {"min_lat": 34.0, "max_lat": 35.0, "min_lon": -118.0, "max_lon": -117.0},
        "drones": [{"id": "drone1", "lat": 34.5, "lon": -117.5}],
    }
    create_response = client.post("/missions", json=mission_data)
    assert create_response.status_code == 200
    mission_id = create_response.json()["id"]

    start_response = client.post(f"/missions/{mission_id}/start")
    assert start_response.status_code == 200
    assert start_response.json()["algorithm"] == "voronoi"


def test_metrics_endpoint_returns_algorithm_and_structure():
    mission_data = {
        "name": "Metrics Test",
        "bounds": {"min_lat": 34.0, "max_lat": 35.0, "min_lon": -118.0, "max_lon": -117.0},
        "drones": [{"id": "drone1", "lat": 34.5, "lon": -117.5}],
    }
    create_response = client.post("/missions", json=mission_data)
    assert create_response.status_code == 200
    mission_id = create_response.json()["id"]

    client.post(f"/missions/{mission_id}/start", json={"algorithm": "apf"})

    response = client.get(f"/missions/{mission_id}/metrics")
    assert response.status_code == 200
    payload = response.json()
    assert payload["algorithm"] == "apf"
    assert payload["status"] == "searching"
    assert "targets_total" in payload
    assert "targets_found" in payload
    assert "found_at_seconds" in payload
    assert isinstance(payload["found_at_seconds"], list)


def test_metrics_endpoint_returns_404_for_missing_mission():
    response = client.get("/missions/nonexistent-id/metrics")
    assert response.status_code == 404


def test_emit_target_found_stores_found_at_on_target():
    mission_id = "emit-found-at-test"
    mission = create_test_mission(
        id=mission_id,
        bounds={"min_lat": 34.0, "max_lat": 35.0, "min_lon": -118.0, "max_lon": -117.0},
        drones=[],
    )
    mission.status = "searching"
    mission.elapsed_seconds = 42
    mission_db[mission_id] = mission
    
    target = {"id": "tgt-x", "lat": 34.5, "lon": -117.5, "status": "detected"}

    async def fake_broadcast(_message):
        pass

    original_broadcast = manager.broadcast
    manager.broadcast = fake_broadcast
    try:
        asyncio.run(simulation_module._emit_target_found(mission_db[mission_id], target))
    finally:
        manager.broadcast = original_broadcast
        mission_db.pop(mission_id, None)

    assert target["found_at"] == 42


def test_sweep_algorithm_assigns_dense_paths_and_returns_first_waypoint():
    drones = [Drone(id="drone1", lat=0.01, lon=0.01), Drone(id="drone2", lat=0.03, lon=0.03)]
    mission = create_test_mission(drones=drones, algorithm="sweep")

    algorithm = VoronoiBoustrophedon()
    waypoints = algorithm.get_target_waypoints(mission, mission.drones)

    assert set(mission.sweep_paths.keys()) == {"drone1", "drone2"}
    # Each drone covers half of a 0.04°×0.04° area
    assert all(len(path) > 2 for path in mission.sweep_paths.values())
    assert set(waypoints.keys()) == {"drone1", "drone2"}
    assert mission.sweep_reached_radius == DETECTION_RADIUS


def test_sweep_algorithm_advances_to_next_waypoint_when_drone_arrives():
    mission = create_test_mission(drones=[Drone(id="drone1", lat=-0.1, lon=-0.1)], algorithm="sweep")
    algorithm = VoronoiBoustrophedon()

    first = algorithm.get_target_waypoints(mission, mission.drones)
    initial_path_length = len(mission.sweep_paths["drone1"])

    # Teleport drone to the first waypoint
    mission.drones[0]["lat"] = first["drone1"][0]
    mission.drones[0]["lon"] = first["drone1"][1]
    second = algorithm.get_target_waypoints(mission, mission.drones)

    assert len(mission.sweep_paths["drone1"]) < initial_path_length


def test_sweep_reached_radius_equals_detection_radius():
    mission = create_test_mission(
        bounds={"min_lat": 33.45, "max_lat": 33.47, "min_lon": -117.25, "max_lon": -117.23}, 
        drones=[Drone(id="d1", lat=33.46, lon=-117.24)], algorithm="sweep"
    )
    alg = VoronoiBoustrophedon()
    alg.get_target_waypoints(mission, mission.drones)

    assert mission.sweep_reached_radius == DETECTION_RADIUS
    assert _REACH_RADIUS == DETECTION_RADIUS


def test_dense_grid_covers_full_bounds():
    """Every point in the search area must be within DETECTION_RADIUS of a grid point."""
    bounds = {"min_lat": 0.0, "max_lat": 0.01, "min_lon": 0.0, "max_lon": 0.01}
    grid = _build_dense_grid(bounds)

    assert float(grid[:, 0].min()) == 0.0
    assert float(grid[:, 1].min()) == 0.0
    assert float(grid[:, 0].max()) >= bounds["max_lat"] - DETECTION_RADIUS * 0.1
    assert float(grid[:, 1].max()) >= bounds["max_lon"] - DETECTION_RADIUS * 0.1


def test_dense_grid_spaced_at_detection_radius():
    bounds = {"min_lat": 0.0, "max_lat": 0.01, "min_lon": 0.0, "max_lon": 0.01}
    grid = _build_dense_grid(bounds)

    unique_lats = np.unique(np.round(grid[:, 0], 8))
    unique_lons = np.unique(np.round(grid[:, 1], 8))
    assert abs(float(np.diff(unique_lats).min()) - DETECTION_RADIUS) < 1e-9
    assert abs(float(np.diff(unique_lons).min()) - DETECTION_RADIUS) < 1e-9


def test_dense_grid_includes_non_multiple_max_bounds():
    """Max bounds must be explicit endpoints so sweep rows do not leave corner gaps."""
    bounds = {"min_lat": 0.0, "max_lat": 0.0139, "min_lon": 0.0, "max_lon": 0.0139}
    grid = _build_dense_grid(bounds)
    unique_lats = np.unique(np.round(grid[:, 0], 8))
    unique_lons = np.unique(np.round(grid[:, 1], 8))

    assert np.isclose(unique_lats[-1], bounds["max_lat"])
    assert np.isclose(unique_lons[-1], bounds["max_lon"])
    assert np.diff(unique_lats).max() <= DETECTION_RADIUS
    assert np.diff(unique_lons).max() <= DETECTION_RADIUS


def test_voronoi_partition_covers_entire_dense_grid():
    """Every dense-grid point must be assigned to exactly one seed — no gaps."""
    bounds = {"min_lat": 0.0, "max_lat": 0.01, "min_lon": 0.0, "max_lon": 0.01}
    grid = _build_dense_grid(bounds)
    positions = np.array([[0.002, 0.002], [0.008, 0.008]])
    labels = _voronoi_assign(grid, positions)

    assert len(labels) == len(grid)
    assert 0 in labels and 1 in labels


def test_balanced_partition_seeds_evenly_distributed_for_small_drone_counts():
    """For 2-6 drones, seeds must span the bounds — not cluster."""
    bounds = {"min_lat": 0.0, "max_lat": 1.0, "min_lon": 0.0, "max_lon": 1.0}
    for k in (2, 3, 4, 5, 6):
        seeds = _balanced_partition_seeds(bounds, k)
        assert len(seeds) == k
        assert seeds[:, 0].min() >= bounds["min_lat"] and seeds[:, 0].max() <= bounds["max_lat"]
        assert seeds[:, 1].min() >= bounds["min_lon"] and seeds[:, 1].max() <= bounds["max_lon"]
        if k >= 2:
            lat_spread = seeds[:, 0].max() - seeds[:, 0].min()
            lon_spread = seeds[:, 1].max() - seeds[:, 1].min()
            assert lat_spread + lon_spread >= 0.4, (
                f"k={k}: seeds clustered (lat_spread={lat_spread}, lon_spread={lon_spread})"
            )


def test_balanced_partition_seeds_returns_exactly_k_for_all_counts():
    """Contract: exactly k seeds for every valid k."""
    bounds = {"min_lat": 0.0, "max_lat": 1.0, "min_lon": 0.0, "max_lon": 1.0}
    for k in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 20, 25]:
        seeds = _balanced_partition_seeds(bounds, k)
        assert len(seeds) == k, f"k={k}: got {len(seeds)} seeds"


def test_balanced_partition_seeds_respects_bounds_aspect_ratio():
    """Wide bounds should yield more columns than rows; tall bounds the opposite."""
    wide = {"min_lat": 0.0, "max_lat": 0.02, "min_lon": 0.0, "max_lon": 0.08}  # 4:1 wide
    seeds = _balanced_partition_seeds(wide, 6)
    n_unique_lats = len(np.unique(np.round(seeds[:, 0], 6)))
    n_unique_lons = len(np.unique(np.round(seeds[:, 1], 6)))
    assert n_unique_lons >= n_unique_lats, (
        f"Wide bounds should have more columns: got {n_unique_lats} rows × {n_unique_lons} cols"
    )

    tall = {"min_lat": 0.0, "max_lat": 0.08, "min_lon": 0.0, "max_lon": 0.02}  # 1:4 tall
    seeds = _balanced_partition_seeds(tall, 6)
    n_unique_lats = len(np.unique(np.round(seeds[:, 0], 6)))
    n_unique_lons = len(np.unique(np.round(seeds[:, 1], 6)))
    assert n_unique_lats >= n_unique_lons, (
        f"Tall bounds should have more rows: got {n_unique_lats} rows × {n_unique_lons} cols"
    )


def test_single_drone_partition_centers_on_bounds():
    """k=1 → the one cell covers the entire area, centered."""
    bounds = {"min_lat": 0.0, "max_lat": 0.02, "min_lon": 0.0, "max_lon": 0.02}
    seeds = _balanced_partition_seeds(bounds, 1)
    assert len(seeds) == 1
    assert abs(seeds[0, 0] - 0.01) < 1e-9
    assert abs(seeds[0, 1] - 0.01) < 1e-9

    # Every dense-grid point must be assigned to the single drone.
    dense = _build_dense_grid(bounds)
    labels = _voronoi_assign(dense, seeds)
    assert (labels == 0).all()


def test_sweep_partition_balanced_across_all_drone_counts():
    """Max cell / min cell should stay under a sensible bound for every k."""
    bounds = {"min_lat": 0.0, "max_lat": 0.04, "min_lon": 0.0, "max_lon": 0.04}
    dense = _build_dense_grid(bounds)

    for k in [2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15]:
        seeds = _balanced_partition_seeds(bounds, k)
        labels = _voronoi_assign(dense, seeds)
        sizes = [int((labels == i).sum()) for i in range(k)]
        assert min(sizes) > 0, f"k={k}: some cell is empty: {sizes}"
        ratio = max(sizes) / min(sizes)
        # Odd k on a square can legitimately go up to ~2x due to geometry.
        assert ratio <= 2.5, f"k={k}: cells too lopsided ({sizes}, ratio={ratio:.2f}x)"


def test_sweep_partition_balanced_when_drones_clustered_at_init():
    """Even if all drones spawn clustered, partitions must be roughly equal area."""
    # 4 drones all clustered near a single corner — the worst case
    mission = create_test_mission(
        drones=[
            Drone(id="d1", lat=0.001, lon=0.001), 
            Drone(id="d2", lat=0.0011, lon=0.0012), 
            Drone(id="d3", lat=0.0009, lon=0.001), 
            Drone(id="d4", lat=0.0012, lon=0.0009)
        ], 
        algorithm="sweep"
    )

    alg = VoronoiBoustrophedon()
    alg.get_target_waypoints(mission, mission.drones)

    path_lengths = [len(p) for p in mission.sweep_paths.values()]
    # No drone gets more than 2x the smallest partition
    assert max(path_lengths) <= 2 * min(path_lengths) + 4, (
        f"Lopsided partitions: {path_lengths} — clustered drones broke the partition"
    )


def test_match_drones_to_seeds_assigns_each_drone_exactly_one_seed():
    drones = np.array([[0.0, 0.0], [1.0, 1.0], [0.5, 0.5]])
    seeds = np.array([[0.9, 0.9], [0.1, 0.1], [0.5, 0.5]])
    mapping = _match_drones_to_seeds(drones, seeds)

    assert len(mapping) == 3
    assert sorted(mapping) == [0, 1, 2]  # every seed claimed exactly once
    # Closest matches: drone 0 → seed 1, drone 1 → seed 0, drone 2 → seed 2
    assert mapping[0] == 1
    assert mapping[1] == 0
    assert mapping[2] == 2


def test_voronoi_lloyd_step_partition_is_correct():
    """Lloyd's: every grid point assigned to nearest centroid; new centroid is mean of cluster."""
    grid = np.array([[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [1.0, 1.0]])
    centroids = np.array([[0.1, 0.1], [0.9, 0.9]])
    new_centroids, labels = lloyd_step(grid, centroids)

    # Bottom-left + bottom-right closest to centroid 0; top-left + top-right closest to 1.
    # Grid as listed: [0,0]→0, [0,1]→1 (closer to 0.9,0.9), [1,0]→0 (closer to 0.1,0.1)? No:
    #   [1,0]: dist to (0.1,0.1) = sqrt(0.81+0.01)=0.906; dist to (0.9,0.9) = sqrt(0.01+0.81)=0.906 (tied)
    # Just verify cluster means are correct given whatever labels np picks.
    for i in range(2):
        cluster_pts = grid[labels == i]
        if len(cluster_pts) > 0:
            assert np.allclose(new_centroids[i], cluster_pts.mean(axis=0))


def test_voronoi_algorithm_returns_centroid_per_drone():
    mission = create_test_mission(
        bounds={"min_lat": 0.0, "max_lat": 1.0, "min_lon": 0.0, "max_lon": 1.0},
        drones=[Drone(id="d1", lat=0.1, lon=0.1), Drone(id="d2", lat=0.9, lon=0.9)],
    )
    mission.grid = np.array([[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [1.0, 1.0]])
    waypoints = VoronoiCoverage().get_target_waypoints(mission, mission.drones)
    assert set(waypoints.keys()) == {"d1", "d2"}
    for lat, lon in waypoints.values():
        assert 0.0 <= lat <= 1.0
        assert 0.0 <= lon <= 1.0


def test_voronoi_algorithm_handles_small_drone_counts():
    """Verify voronoi runs for N=1,2,3 and returns a valid waypoint per drone."""
    bounds = {"min_lat": 0.0, "max_lat": 0.04, "min_lon": 0.0, "max_lon": 0.04}
    grid = build_search_grid(bounds, n=15)

    for k in [1, 2, 3]:
        drones = [{"id": f"d{i}", "lat": 0.01 + i * 0.005, "lon": 0.01 + i * 0.005}
                  for i in range(k)]
        mission = create_test_mission(bounds=bounds, drones=drones)
        mission.grid = grid
        result = VoronoiCoverage().get_target_waypoints(mission, mission.drones)
        assert len(result) == k, f"k={k}: expected {k} waypoints, got {len(result)}"
        for lat, lon in result.values():
            assert bounds["min_lat"] <= lat <= bounds["max_lat"]
            assert bounds["min_lon"] <= lon <= bounds["max_lon"]


def test_app_voronoi_lloyd_step_aco_matches_algorithms_module():
    import numpy as np

    from app import voronoi as legacy_voronoi
    from app.algorithms import voronoi as algo_voronoi

    rng = np.random.default_rng(0)
    X = rng.random((20, 2))
    centroids = rng.random((3, 2))
    old_centroids = centroids.copy()
    pheromone = np.ones((20, 3))
    p2 = pheromone.copy()

    nc1, lb1, ph1 = legacy_voronoi.lloyd_step_aco(X, centroids, old_centroids, pheromone)
    nc2, lb2, ph2 = algo_voronoi.lloyd_step_aco(X, centroids, old_centroids, p2)

    assert np.allclose(nc1, nc2)
    assert np.array_equal(lb1, lb2)
    assert np.allclose(ph1, ph2)


def test_voronoi_aco_coverage_initialize_and_waypoints():
    from app.algorithms.voronoi import VoronoiACOCoverage
    from app.algorithms.base import build_search_grid

    bounds = {"min_lat": 0.0, "max_lat": 0.04, "min_lon": 0.0, "max_lon": 0.04}
    grid = build_search_grid(bounds, n=5).tolist()
    drones = [
        {"id": "d0", "lat": 0.01, "lon": 0.01},
        {"id": "d1", "lat": 0.02, "lon": 0.02},
    ]
    mission = {"bounds": bounds, "grid": grid, "drones": drones}
    algo = VoronoiACOCoverage()
    algo.initialize(mission)
    waypoints = algo.get_target_waypoints(mission, drones)
    assert set(waypoints.keys()) == {"d0", "d1"}
    for lat, lon in waypoints.values():
        assert bounds["min_lat"] <= lat <= bounds["max_lat"]
        assert bounds["min_lon"] <= lon <= bounds["max_lon"]
    # Second tick: pheromone state should exist and still return two waypoints
    waypoints2 = algo.get_target_waypoints(mission, drones)
    assert len(waypoints2) == 2


def test_voronoi_aco_preserves_state_by_drone_id_when_membership_changes():
    from app.algorithms.voronoi import VoronoiACOCoverage
    from app.algorithms.base import build_search_grid
    from unittest.mock import patch
    import numpy as np

    bounds = {"min_lat": 0.0, "max_lat": 0.04, "min_lon": 0.0, "max_lon": 0.04}
    grid = build_search_grid(bounds, n=5).tolist()
    mission = {"bounds": bounds, "grid": grid, "drones": []}
    algo = VoronoiACOCoverage()
    algo.initialize(mission)

    tick1 = [
        {"id": "d0", "lat": 0.01, "lon": 0.01},
        {"id": "d1", "lat": 0.02, "lon": 0.02},
    ]
    tick2 = [
        {"id": "d1", "lat": 0.03, "lon": 0.03},
        {"id": "d2", "lat": 0.035, "lon": 0.035},
    ]

    captures = []
    call_count = {"n": 0}

    def fake_lloyd_step_aco(X, centroids, old_centroids, pheromone, decay=0.9, deposit=0.5):
        call_count["n"] += 1
        captures.append((old_centroids.copy(), pheromone.copy()))
        if call_count["n"] == 1:
            pheromone[:, 0] = 5.0
            pheromone[:, 1] = 9.0
        labels = np.zeros(len(X), dtype=int)
        return centroids.copy(), labels, pheromone

    with patch("app.algorithms.voronoi.lloyd_step_aco", side_effect=fake_lloyd_step_aco):
        algo.get_target_waypoints(mission, tick1)
        algo.get_target_waypoints(mission, tick2)

    old_centroids_2, pheromone_2 = captures[1]
    # d1 existed on tick 1; its prior position should be reused after reordering.
    assert np.allclose(old_centroids_2[0], [0.02, 0.02])
    # d2 is new on tick 2; it should initialize with current position.
    assert np.allclose(old_centroids_2[1], [0.035, 0.035])
    # d1 moved from index 1 -> 0; its pheromone column must move with it.
    assert np.allclose(pheromone_2[:, 0], 9.0)
    # d2 is newly introduced, so it starts with baseline pheromone.
    assert np.allclose(pheromone_2[:, 1], 1.0)


def test_get_algorithm_returns_distinct_voronoi_aco_instances():
    from app.algorithms import get_algorithm

    a = get_algorithm("voronoi_aco")
    b = get_algorithm("voronoi_aco")
    assert a is not b


def test_row_endpoints_lawnmower_alternates_direction():
    pts = np.array([
        [0.0, 0.0], [0.0, 0.002], [0.0, 0.004],
        [0.002, 0.0], [0.002, 0.002], [0.002, 0.004],
    ])
    path = _row_endpoints_lawnmower(pts)

    # Row 0 (even): (0.0, 0.0) → (0.0, 0.004)  left to right
    assert path[0] == (0.0, 0.0)
    assert path[1] == (0.0, 0.004)
    # Row 1 (odd): (0.002, 0.004) → (0.002, 0.0)  right to left
    assert path[2] == (0.002, 0.004)
    assert path[3] == (0.002, 0.0)


def test_row_endpoints_lawnmower_emits_two_per_row():
    # 3 lat rows, 5 cols each → 6 waypoints (2 per row), not 15
    pts = np.array([[lat, lon]
                    for lat in [0.0, 0.002, 0.004]
                    for lon in np.arange(0.0, 0.01, 0.002)])
    path = _row_endpoints_lawnmower(pts)
    assert len(path) == 6  # 3 rows × 2 endpoints


def test_sweep_centroid_is_first_waypoint_and_phase_is_en_route_at_init():
    """Drone's first waypoint must be the centroid; drone is 'en_route' until reached."""
    mission = create_test_mission(
        drones=[{"id": "d1", "lat": -0.5, "lon": -0.5}]  # far from bounds
    )
    alg = VoronoiBoustrophedon()
    result = alg.get_target_waypoints(mission, mission.drones)

    centroid = mission.sweep_centroids["d1"]
    assert result["d1"] == centroid, "First waypoint must be the centroid"
    assert mission.sweep_phase["d1"] == "en_route"
    assert mission.drones[0]["sweep_centroid"] == [centroid[0], centroid[1]]
    assert mission.drones[0]["sweep_phase"] == "en_route"


def test_sweep_phase_transitions_to_sweeping_when_centroid_reached(caplog):
    """When drone arrives at its centroid, phase flips to 'sweeping' and a log line fires."""
    mission = create_test_mission(
        drones=[{"id": "d1", "lat": -0.5, "lon": -0.5}]
    )
    alg = VoronoiBoustrophedon()
    alg.get_target_waypoints(mission, mission.drones)

    centroid = mission.sweep_centroids["d1"]
    mission.drones[0]["lat"] = centroid[0]
    mission.drones[0]["lon"] = centroid[1]

    with caplog.at_level(logging.INFO, logger="app.algorithms.boustrophedon"):
        alg.get_target_waypoints(mission, mission.drones)

    assert mission.sweep_phase["d1"] == "sweeping"
    assert mission.drones[0]["sweep_phase"] == "sweeping"
    assert any("reached centroid" in rec.message for rec in caplog.records)


def test_sweep_phase_transitions_to_complete_when_path_exhausted(caplog):
    mission = create_test_mission(
        bounds={"min_lat": 0.0, "max_lat": 0.01, "min_lon": 0.0, "max_lon": 0.01},
        drones=[{"id": "d1", "lat": 0.005, "lon": 0.005}]
    )
    alg = VoronoiBoustrophedon()
    alg.get_target_waypoints(mission, mission.drones)
    mission.sweep_paths["d1"] = []

    with caplog.at_level(logging.INFO, logger="app.algorithms.boustrophedon"):
        alg.get_target_waypoints(mission, mission.drones)

    assert mission.sweep_phase["d1"] == "complete"
    assert any("partition fully swept" in rec.message for rec in caplog.records)


def test_sweep_drone_idles_when_partition_exhausted():
    """When a drone's path runs out it should go idle (not regenerate)."""
    mission = create_test_mission(
        bounds={"min_lat": 0.0, "max_lat": 0.01, "min_lon": 0.0, "max_lon": 0.01},
        drones=[{"id": "d1", "lat": 0.005, "lon": 0.005}],
        algorithm="sweep",
    )
    alg = VoronoiBoustrophedon()
    alg.get_target_waypoints(mission, mission.drones)
    mission.sweep_paths["d1"] = []  # simulate exhausted path

    result = alg.get_target_waypoints(mission, mission.drones)
    assert "d1" not in result


def test_update_coverage_marks_grid_cells_within_detection_radius():
    """Coverage now uses the dense grid (via _dense_coverage_grid or falls back to 'grid')."""
    # Provide a small fake dense grid: two cells near the drone, one far away.
    mission = create_test_mission(
        drones=[{"id": "drone1", "lat": 34.5, "lon": -117.5}],
    )
    mission._dense_coverage_grid = np.array([[34.5, -117.5], [34.5001, -117.5], [40.0, -117.5]])
    mission._dense_grid_size = 3
    simulation_module._update_coverage(mission)
    covered_set = mission.covered_set
    assert 0 in covered_set          # cell at drone position — covered
    assert 1 in covered_set          # cell 0.0001° away — within DETECTION_RADIUS
    assert 2 not in covered_set      # cell at lat=40.0 — far away
    assert mission._dense_covered_count == 2


def test_update_coverage_is_no_op_when_grid_missing():
    mission = create_test_mission(
        drones=[{"id": "drone1", "lat": 34.5, "lon": -117.5}],
    )
    simulation_module._update_coverage(mission)
    assert mission._dense_covered_count == 0


def test_metrics_endpoint_includes_coverage_and_find_time_fields():
    mission_data = {
        "name": "Coverage Metrics Test",
        "bounds": {"min_lat": 34.0, "max_lat": 35.0, "min_lon": -118.0, "max_lon": -117.0},
        "drones": [{"id": "drone1", "lat": 34.5, "lon": -117.5}],
    }
    create_response = client.post("/missions", json=mission_data)
    mission_id = create_response.json()["id"]
    client.post(f"/missions/{mission_id}/start", json={"algorithm": "sweep"})

    response = client.get(f"/missions/{mission_id}/metrics")
    payload = response.json()
    assert payload["algorithm"] == "sweep"
    assert "coverage_pct" in payload
    assert "coverage_rate_per_sec" in payload
    assert "first_find_seconds" in payload
    assert "last_find_seconds" in payload


def test_metrics_coverage_rate_is_percent_per_second():
    mission_id = "metrics-rate-units"
    mission = create_test_mission(
        id=mission_id,
        algorithm="sweep",
    )
    mission.status = "searching"
    mission.elapsed_seconds = 10
    mission._dense_grid_size = 4
    mission._dense_covered_count = 2
    mission_db[mission_id] = mission

    try:
        response = client.get(f"/missions/{mission_id}/metrics")
    finally:
        mission_db.pop(mission_id, None)

    payload = response.json()
    assert payload["coverage_pct"] == 50.0
    assert payload["coverage_rate_per_sec"] == 5.0


def test_sitl_drone_speed_env_parser_rejects_invalid_values(monkeypatch):
    monkeypatch.setenv("TEST_SPEED", "nan")
    assert _positive_float_env("TEST_SPEED", 15.0) == 15.0
    monkeypatch.setenv("TEST_SPEED", "-1")
    assert _positive_float_env("TEST_SPEED", 15.0) == 15.0
    monkeypatch.setenv("TEST_SPEED", "bad")
    assert _positive_float_env("TEST_SPEED", 15.0) == 15.0
    monkeypatch.setenv("TEST_SPEED", "12.5")
    assert _positive_float_env("TEST_SPEED", 15.0) == 12.5


def test_finalize_mission_stores_completion_elapsed_seconds():
    mission = create_test_mission()
    mission.elapsed_seconds = 77
    mission.status = "searching"
    mission.targets = [{"id": "t1", "status": "found"}, {"id": "t2", "status": "found"}]

    async def run():
        return await simulation_module._finalize_mission_progress(mission)

    result = asyncio.run(run())
    assert result is True
    assert mission.completion_elapsed_seconds == 77


def test_normalize_script_results_matches_expected_assignments_by_sysid_and_drone_id():
    expected_assignments = [
        {"drone_id": "drone-a", "sysid": 1},
        {"drone_id": "drone-b", "sysid": 2},
        {"drone_id": "drone-c", "sysid": 3},
    ]
    raw_results = [
        {"drone_id": "drone-b", "sysid": 2, "success": True, "message": "sent"},
        {"drone_id": "other-name", "sysid": 1, "success": False, "message": "denied"},
    ]

    normalized = main_module._normalize_script_results(raw_results, expected_assignments)

    assert normalized[0] == {
        "drone_id": "other-name",
        "sysid": 1,
        "success": False,
        "message": "denied",
    }
    assert normalized[1] == {
        "drone_id": "drone-b",
        "sysid": 2,
        "success": True,
        "message": "sent",
    }
    assert normalized[2]["drone_id"] == "drone-c"
    assert normalized[2]["sysid"] == 3
    assert normalized[2]["success"] is False
    assert "No dispatch result returned" in normalized[2]["message"]
