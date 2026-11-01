from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ecu_list() -> None:
    response = client.get("/api/ecus")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) >= 4
    assert any(item["ecu_id"] == "engine" for item in payload)


def test_toggle_ecu() -> None:
    response = client.post("/api/ecus/engine/toggle")
    assert response.status_code == 200
    assert "enabled" in response.json()


def test_dashboard_endpoint() -> None:
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    payload = response.json()
    assert "stats" in payload
    assert "ecus" in payload
