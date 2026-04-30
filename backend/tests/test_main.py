import asyncio
from fastapi.testclient import TestClient
from app import app
from app.main import missions_db, simulation_loop, manager, _sync_mission_drones_with_sitl, sitl_bridge
import app.main as main_module
import app.routes.missions as missions_routes
import app.simulation as simulation_module

client = TestClient(app)

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
    assert start_data["status"] == "running"
    
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
    assert stop_data["status"] == "stopped"

    # Test stopping a non-existent mission
    invalid_stop_response = client.post("/missions/invalid_id/stop")
    assert invalid_stop_response.status_code == 404
    assert invalid_stop_response.json() == {"detail": "Mission not found"}
    
    # Test stopping an already stopped mission
    second_stop_response = client.post(f"/missions/{mission_id}/stop")
    assert second_stop_response.status_code == 400
    assert second_stop_response.json() == {"detail": "Mission is already stopped or complete"}


def test_simulation_emits_target_found_and_completes_mission():
    mission_id = "sim-target-found"
    missions_db[mission_id] = {
        "id": mission_id,
        "name": "Simulation Event Test",
        "status": "running",
        "progress": 0.0,
        "elapsed_seconds": 0,
        "bounds": {
            "min_lat": 34.0,
            "max_lat": 35.0,
            "min_lon": -118.0,
            "max_lon": -117.0,
        },
        "drones": [
            {
                "id": "drone1",
                "lat": 34.5,
                "lon": -117.5,
                "assigned_target_id": "tgt-1",
            }
        ],
        "targets": [
            {
                "id": "tgt-1",
                "lat": 34.5,
                "lon": -117.5,
                "status": "detected",
                "assigned_drone_id": "drone1",
            }
        ],
        "hikers": [],
    }

    captured = []

    async def fake_broadcast(message):
        captured.append(message)

    original_broadcast = manager.broadcast
    manager.broadcast = fake_broadcast
    try:
        asyncio.run(simulation_loop(mission_id))
        mission = missions_db[mission_id]
        assert mission["status"] == "complete"
        assert mission["progress"] == 100.0
    finally:
        manager.broadcast = original_broadcast
        missions_db.pop(mission_id, None)

    target_found_messages = [m for m in captured if m.get("type") == "target_found"]
    assert len(target_found_messages) == 1
    target_found = target_found_messages[0]
    assert target_found["target_id"] == "tgt-1"
    assert target_found["drone_id"] == "drone1"
    assert target_found["lat"] == 34.5
    assert target_found["lon"] == -117.5
    assert isinstance(target_found["found_at"], int)


def test_simulation_progress_only_advances_when_targets_are_found():
    mission_id = "sim-progress-from-found-targets"
    missions_db[mission_id] = {
        "id": mission_id,
        "name": "Progress From Found Targets Test",
        "status": "running",
        "progress": 0.0,
        "elapsed_seconds": 0,
        "bounds": {
            "min_lat": 34.0,
            "max_lat": 35.0,
            "min_lon": -118.0,
            "max_lon": -117.0,
        },
        "drones": [
            {
                "id": "drone1",
                "lat": 34.5,
                "lon": -117.5,
            }
        ],
        "targets": [
            {"id": "t1", "lat": 34.5, "lon": -117.5, "status": "found"},
            {"id": "t2", "lat": 34.6, "lon": -117.4, "status": "wandering"},
        ],
        "hikers": [],
    }

    async def no_op_broadcast(_message):
        return None

    original_broadcast = manager.broadcast
    manager.broadcast = no_op_broadcast
    try:
        mission = missions_db[mission_id]
        all_targets_found = asyncio.run(simulation_module._finalize_mission_progress(mission))
        assert all_targets_found is False
        assert mission["status"] == "running"
        assert mission["progress"] == 50.0
    finally:
        manager.broadcast = original_broadcast
        missions_db.pop(mission_id, None)


def test_target_detection_uses_expanded_radius_before_icons_overlap():
    mission = {
        "bounds": {
            "min_lat": 34.0,
            "max_lat": 35.0,
            "min_lon": -118.0,
            "max_lon": -117.0,
        },
        "drones": [
            {
                "id": "drone1",
                "lat": 34.5,
                "lon": -117.5,
            }
        ],
        "targets": [
            {
                "id": "t1",
                "lat": 34.5012,
                "lon": -117.5,
                "status": "wandering",
                "vx": 0,
                "vy": 0,
            }
        ],
    }

    simulation_module._update_targets_for_tick(
        mission,
        mission["bounds"],
    )

    target = mission["targets"][0]
    drone = mission["drones"][0]
    assert simulation_module.DETECTION_RADIUS >= 0.0012
    assert target["status"] == "detected"
    assert target["assigned_drone_id"] == "drone1"
    assert drone["assigned_target_id"] == "t1"


def test_simulation_completes_when_all_targets_are_found():
    mission_id = "sim-complete-all-targets-found"
    missions_db[mission_id] = {
        "id": mission_id,
        "name": "All Targets Found Completion Test",
        "status": "running",
        "progress": 0.0,
        "elapsed_seconds": 0,
        "bounds": {
            "min_lat": 34.0,
            "max_lat": 35.0,
            "min_lon": -118.0,
            "max_lon": -117.0,
        },
        "drones": [
            {
                "id": "drone1",
                "lat": 34.5,
                "lon": -117.5,
            }
        ],
        "targets": [
            {"id": "t1", "lat": 34.5, "lon": -117.5, "status": "found"},
            {"id": "t2", "lat": 34.6, "lon": -117.4, "status": "found"},
        ],
        "hikers": [],
    }

    async def no_op_broadcast(_message):
        return None

    original_broadcast = manager.broadcast
    manager.broadcast = no_op_broadcast
    try:
        mission = missions_db[mission_id]
        all_targets_found = asyncio.run(simulation_module._finalize_mission_progress(mission))
        assert all_targets_found is True
        assert mission["status"] == "complete"
        assert mission["progress"] == 100.0
    finally:
        manager.broadcast = original_broadcast
        missions_db.pop(mission_id, None)


def test_simulation_uses_voronoi_centroid_for_unassigned_simulated_drones():
    mission_id = "sim-voronoi-motion"
    missions_db[mission_id] = {
        "id": mission_id,
        "name": "Voronoi Motion Test",
        "status": "running",
        "progress": 0.0,
        "elapsed_seconds": 0,
        "bounds": {
            "min_lat": 0.0,
            "max_lat": 1.0,
            "min_lon": 0.0,
            "max_lon": 1.0,
        },
        "grid": [[0.8, 0.8], [0.9, 0.9]],
        "drones": [
            {
                "id": "drone1",
                "lat": 0.1,
                "lon": 0.1,
            }
        ],
        "targets": [],
        "hikers": [],
    }

    async def stop_after_first_telemetry(message):
        if message.get("type") == "telemetry":
            missions_db[mission_id]["status"] = "stopped"

    original_broadcast = manager.broadcast
    original_get_states = sitl_bridge.get_states_by_sysid
    manager.broadcast = stop_after_first_telemetry
    sitl_bridge.get_states_by_sysid = lambda: {}

    try:
        asyncio.run(simulation_loop(mission_id))
        drone = missions_db[mission_id]["drones"][0]
    finally:
        manager.broadcast = original_broadcast
        sitl_bridge.get_states_by_sysid = original_get_states
        missions_db.pop(mission_id, None)

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
        assert payload["status"] == "running"
        import time; time.sleep(0.3)
        assert len(captured.get("assignments", [])) == 1
        assert captured["assignments"][0]["sysid"] == 1
    finally:
        missions_routes.run_direct_dispatch = original_run_direct


def test_sync_mission_drones_with_sitl_uses_live_positions():
    mission = {
        "drones": [
            {
                "id": "drone-1",
                "lat": 1.0,
                "lon": 2.0,
            }
        ]
    }

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
    drone = mission["drones"][0]
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

    import app.dispatch as dispatch_module

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

    import app.dispatch as dispatch_module

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
    import app.sitl as sitl_module

    class FakeDrone:
        def __init__(self):
            self.sysid = 7
            self.state = {"mode": "GUIDED", "armed": False, "rel_alt": 0.0}
            self.arm_called = False
            self.takeoff_called = False
            self.goto_called = False

        def arm(self):
            self.arm_called = True

        def takeoff(self, _alt):
            self.takeoff_called = True

        def goto(self, _lat, _lon, _alt):
            self.goto_called = True

        def get_state(self):
            return self.state

    bridge = sitl_module.SITLTelemetryBridge()
    fake_drone = FakeDrone()
    bridge.swarm.drones = [fake_drone]

    original_wait = sitl_module._wait_for_condition
    sitl_module._wait_for_condition = lambda *_args, **_kwargs: False
    try:
        result = bridge.dispatch_drone(sysid=7, lat=34.5, lon=-117.5, alt=30.0, drone_id="drone-7")
    finally:
        sitl_module._wait_for_condition = original_wait

    assert result["success"] is False
    assert "never reported armed state" in result["message"]
    assert fake_drone.arm_called is True
    assert fake_drone.takeoff_called is False
    assert fake_drone.goto_called is False


def test_drone_eof_handler_marks_connection_disconnected():
    import app.connect_swarm as connect_swarm_module

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
    import app.sitl as sitl_module

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

    mission = {
        "elapsed_seconds": 10,
        "drones": [
            {
                "id": "drone-1",
                "sysid": 1,
                "lat": 34.5,
                "lon": -117.5,
                "alt": 0.0,
            }
        ],
    }

    try:
        with caplog.at_level("INFO"):
            simulation_module._send_live_drone_gotos(mission, {"drone-1"}, {})
    finally:
        sitl_bridge.get_states_by_sysid = original_get_states
        sitl_bridge.is_dispatching = original_is_dispatching

    assert "goto_loop: 0/1 drones got goto" in caplog.text
    assert "blocked airborne=1" in caplog.text


def test_get_states_by_sysid_triggers_reconnect_for_stale_links():
    import app.sitl as sitl_module

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
    mission = {
        "drones": [
            {"id": "drone-a", "sysid": 7},
            {"id": "drone-b"},
            {"id": "drone-c", "sysid": "3"},
        ]
    }

    mapping = main_module._mission_drone_to_sysid_map(mission)

    assert mapping == {
        "drone-a": 7,
        "drone-b": 2,
        "drone-c": 3,
    }
    assert mission["drones"][1]["sysid"] == 2


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
    assert payload["status"] == "running"
    assert "targets_total" in payload
    assert "targets_found" in payload
    assert "found_at_seconds" in payload
    assert isinstance(payload["found_at_seconds"], list)


def test_metrics_endpoint_returns_404_for_missing_mission():
    response = client.get("/missions/nonexistent-id/metrics")
    assert response.status_code == 404


def test_emit_target_found_stores_found_at_on_target():
    mission_id = "emit-found-at-test"
    missions_db[mission_id] = {
        "id": mission_id,
        "status": "running",
        "elapsed_seconds": 42,
        "_found_target_ids": [],
        "bounds": {"min_lat": 34.0, "max_lat": 35.0, "min_lon": -118.0, "max_lon": -117.0},
        "drones": [],
        "targets": [],
    }
    target = {"id": "tgt-x", "lat": 34.5, "lon": -117.5, "status": "detected"}

    async def fake_broadcast(_message):
        pass

    original_broadcast = manager.broadcast
    manager.broadcast = fake_broadcast
    try:
        asyncio.run(simulation_module._emit_target_found(missions_db[mission_id], target))
    finally:
        manager.broadcast = original_broadcast
        missions_db.pop(mission_id, None)

    assert target["found_at"] == 42


def test_finalize_mission_stores_completion_elapsed_seconds():
    mission = {
        "status": "running",
        "progress": 0.0,
        "elapsed_seconds": 77,
        "targets": [
            {"id": "t1", "status": "found"},
            {"id": "t2", "status": "found"},
        ],
    }

    async def run():
        return await simulation_module._finalize_mission_progress(mission)

    result = asyncio.run(run())
    assert result is True
    assert mission["status"] == "complete"
    assert mission["completion_elapsed_seconds"] == 77


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
