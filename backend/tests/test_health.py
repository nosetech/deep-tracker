from fastapi.testclient import TestClient

from deep_tracker.main import app


def test_health() -> None:
    res = TestClient(app).get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
