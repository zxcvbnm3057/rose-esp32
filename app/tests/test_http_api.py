"""API smoke tests."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.src.main import create_app


def test_health_endpoint_exposes_registered_features() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/app/health")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "ac_ir_control" in data["features"]
    assert any(item["url"] == "/app/ac/ir/control" for item in data["http_triggers"])


def test_http_trigger_invalid_parameters_return_503() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post("/app/ac/ir/control", json={"room": "living_room", "mode": "invalid"})
    assert response.status_code == 503
