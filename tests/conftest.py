import os
import tempfile
from pathlib import Path

import pytest

_testdir = tempfile.TemporaryDirectory(prefix="clipbot-tests-")
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(_testdir.name) / "test.db").as_posix()
os.environ["DEMO_MODE"] = "true"
os.environ["APP_ENV"] = "development"
os.environ["ADMIN_PASSWORD"] = "test-password"
os.environ["SESSION_SECRET"] = "test-session-secret-never-use-in-production"
os.environ["WEB_ORIGIN"] = "http://localhost:3000"
os.environ["STORAGE_ROOT"] = str(Path(_testdir.name) / "media")
os.environ["VIZARD_API_KEY"] = ""
os.environ["OPUS_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["API_TOKEN"] = ""

from clipbot.api import app, login_attempts  # noqa: E402
from clipbot.db import Base, engine, initialize  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(engine)
    initialize()
    login_attempts.clear()
    yield


@pytest.fixture
def client():
    with TestClient(app, headers={"Origin": "http://localhost:3000"}) as test:
        assert test.post("/api/auth/login", json={"password": "test-password"}).status_code == 200
        yield test


@pytest.fixture
def source(client):
    data = {
        "name": "Owned podcast",
        "url": "https://example.com/podcast.mp4",
        "kind": "manual",
        "authorization_type": "owner",
        "authorization_note": "I produced and own this recording.",
        "authorized_platforms": ["youtube", "instagram", "tiktok"],
        "category": "podcast",
    }
    response = client.post("/api/sources", json=data)
    assert response.status_code == 200
    return response.json()


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
