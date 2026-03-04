import asyncio
from fastapi.testclient import TestClient
from app import app
from app.main import missions_db, simulation_loop, manager

client = TestClient(app)

def test_read_main():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}

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
