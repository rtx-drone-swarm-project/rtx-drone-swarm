from fastapi.testclient import TestClient

from app import app


client = TestClient(app)


def _create_mission_payload():
    return {
        "name": "Probability Grid Mission",
        "bounds": {
            "min_lat": 34.0,
            "max_lat": 34.1,
            "min_lon": -118.1,
            "max_lon": -118.0,
        },
        "drones": [
            {"id": "drone1", "lat": 34.05, "lon": -118.05},
            {"id": "drone2", "lat": 34.06, "lon": -118.04},
        ],
    }


def test_new_mission_starts_with_unconfirmed_setup_state():
    response = client.post("/missions", json=_create_mission_payload())

    assert response.status_code == 200
    payload = response.json()
    assert "probability_grid" in payload
    assert "grid_shape" in payload
    assert "operator_label_grid" in payload
    assert "searchable_mask" in payload
    assert "probability_grid_config" in payload
    assert payload["grid"] is None
    assert payload["grid_shape"] is None
    assert payload["operator_label_grid"] is None
    assert payload["searchable_mask"] is None
    assert payload["probability_grid"] is None
    assert payload["search_area_confirmed"] is False
    assert payload["probability_grid_confirmed"] is False
    assert payload["probability_grid_config"] == {
        "smoothing_passes": 1,
        "regions": [],
    }


def test_new_mission_keeps_grid_and_probability_map_uninitialized():
    response = client.post("/missions", json=_create_mission_payload())

    assert response.status_code == 200
    payload = response.json()
    assert payload["grid"] is None
    assert payload["probability_grid"] is None


def test_existing_mission_json_fields_are_preserved():
    response = client.post("/missions", json=_create_mission_payload())

    assert response.status_code == 200
    payload = response.json()
    expected_fields = {
        "id",
        "name",
        "status",
        "progress",
        "elapsed_seconds",
        "completion_elapsed_seconds",
        "algorithm",
        "bounds",
        "drones",
        "hikers",
        "targets",
        "grid",
        "grid_shape",
        "operator_label_grid",
        "searchable_mask",
        "probability_grid",
        "search_area_confirmed",
        "probability_grid_confirmed",
    }
    assert expected_fields.issubset(payload.keys())
