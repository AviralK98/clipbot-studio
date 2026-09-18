from clipbot.api import app
from clipbot.db import Session
from clipbot.models import Source
from fastapi.testclient import TestClient


def test_authentication_required():
    with TestClient(app) as client:
        assert client.get("/api/studio").status_code == 401
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200


def test_csrf_protection(client):
    assert (
        client.patch(
            "/api/settings", json={"autopilot": False}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )


def test_login_rate_limit():
    with TestClient(app, headers={"Origin": "http://localhost:3000"}) as client:
        for _ in range(10):
            assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
        assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 429


def test_source_crud_and_authorization_history(client, source):
    row = {
        k: source[k]
        for k in [
            "name",
            "url",
            "kind",
            "authorization_type",
            "authorization_note",
            "authorized_platforms",
            "category",
            "enabled",
            "routing",
        ]
    }
    row["enabled"] = False
    assert client.put(f"/api/sources/{source['id']}", json=row).json()["enabled"] is False
    assert client.delete(f"/api/sources/{source['id']}").status_code == 200
    with Session() as db:
        assert db.get(Source, source["id"]).archived
        assert db.get(Source, source["id"]).authorization_note


def test_missing_authorization_rejected(client):
    assert (
        client.post(
            "/api/sources", json={"name": "No permission", "url": "https://example.com/x.mp4"}
        ).status_code
        == 422
    )


def test_video_ingestion_is_idempotent(client, source):
    payload = {
        "source_id": source["id"],
        "title": "Owned episode",
        "url": "https://example.com/ep.mp4",
        "duration": 600,
    }
    first = client.post("/api/videos", json=payload)
    second = client.post("/api/videos", json=payload)
    assert first.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_thresholds_and_timezone_validation(client):
    assert (
        client.patch(
            "/api/settings", json={"thresholds": {"priority": 70, "approved": 82, "reserve": 75}}
        ).status_code
        == 422
    )
    assert client.patch("/api/settings", json={"timezone": "Not/AZone"}).status_code == 422
    assert client.patch("/api/settings", json={"posting_times": ["25:00"]}).status_code == 422
    assert client.patch("/api/settings", json={"posting_times": []}).status_code == 422
    assert client.patch("/api/settings", json={"autopilot": False}).json()["autopilot"] is False


def test_private_urls_rejected(client, source):
    for url in [
        "http://127.0.0.1/file.mp4",
        "http://169.254.169.254/latest",
        "file:///etc/passwd",
        "http://localhost/video",
        "https://user:secret@example.com/video",
    ]:
        assert (
            client.post(
                "/api/videos", json={"source_id": source["id"], "title": "Bad", "url": url, "duration": 60}
            ).status_code
            == 422
        )


def test_secrets_absent_from_dashboard(client):
    data = client.get("/api/studio").text
    assert "test-password" not in data
    assert "test-session-secret" not in data
    assert "password_hash" not in data


def test_unknown_identifiers_return_404(client):
    assert client.get("/api/clips/does-not-exist").status_code == 404
    assert client.post("/api/jobs/does-not-exist/retry", json={}).status_code == 404
