import asyncio
from fastapi.testclient import TestClient
from app import app
from app.main import missions_db, simulation_loop, manager, _sync_mission_drones_with_sitl, sitl_bridge
import app.main as main_module

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


def test_simulation_completes_when_progress_reaches_100():
    mission_id = "sim-progress-complete"
    missions_db[mission_id] = {
        "id": mission_id,
        "name": "Progress Completion Test",
        "status": "running",
        "progress": 99.7,
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
        "targets": [],
        "hikers": [],
    }

    async def no_op_broadcast(_message):
        return None

    original_broadcast = manager.broadcast
    manager.broadcast = no_op_broadcast
    try:
        asyncio.run(simulation_loop(mission_id))
        mission = missions_db[mission_id]
        assert mission["status"] == "complete"
        assert mission["progress"] == 100.0
    finally:
        manager.broadcast = original_broadcast
        missions_db.pop(mission_id, None)


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

    async def fake_run_dispatch(assignments, host, timeout_seconds, count=None):
        captured["assignments"] = assignments
        captured["host"] = host
        return [
            {
                "drone_id": "drone-alpha",
                "sysid": 1,
                "success": True,
                "message": "ok",
            }
        ]

    original_run_dispatch = main_module.run_dispatch_script
    main_module.run_dispatch_script = fake_run_dispatch

    try:
        create_response = client.post("/missions", json=mission_data)
        assert create_response.status_code == 200
        mission_id = create_response.json()["id"]

        start_response = client.post(f"/missions/{mission_id}/start")
        assert start_response.status_code == 200
        payload = start_response.json()
        assert payload["status"] == "running"
        assert payload["dispatch_results"] == [
            {
                "drone_id": "drone-alpha",
                "sysid": 1,
                "success": True,
                "message": "ok",
            }
        ]
        assert len(captured.get("assignments", [])) == 1
        assert captured["assignments"][0]["sysid"] == 1
    finally:
        main_module.run_dispatch_script = original_run_dispatch


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

    original_run_dispatch = main_module.run_dispatch_script
    main_module.run_dispatch_script = fake_run_dispatch

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
        main_module.run_dispatch_script = original_run_dispatch


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

    original_create_subprocess_exec = main_module.asyncio.create_subprocess_exec
    main_module.asyncio.create_subprocess_exec = fake_create_subprocess_exec

    try:
        results = asyncio.run(
            main_module.run_dispatch_script(
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
        main_module.asyncio.create_subprocess_exec = original_create_subprocess_exec


def test_run_dispatch_script_non_zero_exit_returns_failure_rows():
    class FailingProcess:
        def __init__(self):
            self.returncode = 1

        async def communicate(self):
            return b"", b"boom"

    async def fake_create_subprocess_exec(*_args, **_kwargs):
        return FailingProcess()

    original_create_subprocess_exec = main_module.asyncio.create_subprocess_exec
    main_module.asyncio.create_subprocess_exec = fake_create_subprocess_exec

    try:
        results = asyncio.run(
            main_module.run_dispatch_script(
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
        main_module.asyncio.create_subprocess_exec = original_create_subprocess_exec
