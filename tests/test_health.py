"""Tests for /api/v1/health and /api/v1/health/test-ai endpoints."""
import pytest
from fastapi.testclient import TestClient
from governiq.main import app

client = TestClient(app)


def test_health_endpoint_returns_expected_structure():
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["status"] in ("ok", "warning", "error")
    assert "subsystems" in data
    for key in ("ai_model", "storage", "manifests", "app"):
        assert key in data["subsystems"]
        sub = data["subsystems"][key]
        assert "status" in sub
        assert sub["status"] in ("ok", "warning", "failing")
        assert "message" in sub
    assert "advisories" in data


def test_health_app_subsystem_always_ok():
    resp = client.get("/api/v1/health")
    data = resp.json()
    assert data["subsystems"]["app"]["status"] == "ok"


def test_health_no_technical_jargon_in_messages():
    resp = client.get("/api/v1/health")
    data = resp.json()
    for key, sub in data["subsystems"].items():
        msg = sub["message"]
        assert "Exception" not in msg
        assert "Traceback" not in msg
        assert "localhost:" not in msg or key == "ai_model"


def test_test_ai_endpoint_returns_status():
    """POST /api/v1/health/test-ai must return ok or failing."""
    payload = {
        "provider": "lmstudio",
        "url": "http://localhost:9999",  # nothing running here
        "api_key": ""
    }
    resp = client.post("/api/v1/health/test-ai", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["status"] in ("ok", "failing")
    assert "message" in data
