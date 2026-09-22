from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_returns_project_info():
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert "project" in body
    assert "version" in body


def test_health_endpoint_reports_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
