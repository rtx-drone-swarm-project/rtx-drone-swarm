from fastapi.testclient import TestClient
from app import app

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