import os
import tempfile
from datetime import datetime
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


@pytest.fixture
def live(monkeypatch):
    """Live (non-demo) mode with placeholder YouTube credentials; pair with respx mocks."""
    from clipbot.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "demo_mode", False)
    for name in ("youtube_client_id", "youtube_client_secret", "youtube_refresh_token"):
        monkeypatch.setattr(settings, name, "contract-test-value")


@pytest.fixture
def published(live):
    """One real (non-demo) clip published to YouTube as video EdJ1Ebbaedg, with its video file."""
    from clipbot.db import transaction
    from clipbot.models import (
        Clip,
        ProviderProject,
        PublishedPost,
        ScheduledPost,
        SocialAccount,
        Source,
        SourceVideo,
    )
    from clipbot.storage import LocalStorage

    published_at = datetime(2026, 9, 18, 3, 24)
    storage_key = "clips/published-test-clip.mp4"
    media = LocalStorage().path(storage_key)
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"\x00\x00\x00\x18ftypmp42 stand-in clip bytes")
    with transaction() as db:
        source = Source(
            name="Owned show",
            url="https://example.com/show",
            kind="manual",
            authorization_type="owner",
            authorized_platforms=["youtube"],
        )
        db.add(source)
        db.flush()
        video = SourceVideo(
            source_id=source.id,
            external_id="ep-1",
            title="Episode",
            url="https://example.com/ep.mp4",
            duration=600,
            status="complete",
        )
        db.add(video)
        db.flush()
        project = ProviderProject(
            source_video_id=video.id, provider="vizard", external_id="p-1", status="complete"
        )
        db.add(project)
        db.flush()
        clip = Clip(
            source_video_id=video.id,
            provider_project_id=project.id,
            provider="vizard",
            external_id="c-1",
            title="Finally Guessing The Character!",
            transcript="Yes. Am I Apu? __silence Yes! Good job.",
            duration=33,
            status="published",
            storage_key=storage_key,
        )
        account = SocialAccount(platform="youtube", name="Melancholy", external_id="@m")
        db.add_all([clip, account])
        db.flush()
        post = ScheduledPost(
            clip_id=clip.id,
            account_id=account.id,
            platform="youtube",
            scheduled_at=published_at,
            status="published",
        )
        db.add(post)
        db.flush()
        db.add(
            PublishedPost(
                scheduled_post_id=post.id,
                clip_id=clip.id,
                platform="youtube",
                external_id="EdJ1Ebbaedg",
                url="https://youtu.be/EdJ1Ebbaedg",
                published_at=published_at,
            )
        )
    return {"video_id": "EdJ1Ebbaedg", "clip_id": clip.id, "media": media}


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
