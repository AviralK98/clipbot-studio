"""YouTube upload rejections: an exhausted allowance defers, other 400s report Google's reason."""

from types import SimpleNamespace

import httpx
import pytest
import respx
from clipbot.config import get_settings
from clipbot.errors import Blocked, Deferred
from clipbot.integrations.social import YouTubeProvider
from clipbot.storage import LocalStorage

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"


def credentials(monkeypatch):
    for name in ["youtube_client_id", "youtube_client_secret", "youtube_refresh_token"]:
        monkeypatch.setattr(get_settings(), name, "contract-test-value")
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(200, json={"access_token": "contract-test-token"})
    )


def clip_on_disk(name):
    file = LocalStorage().path(f"clips/{name}.mp4")
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(b"12345678")
    return SimpleNamespace(
        storage_key=f"clips/{name}.mp4",
        metadata_json={"youtube": {"title": "Owned clip", "description": "Description", "hashtags": []}},
    )


def rejection(reason, message):
    return {"error": {"code": 400, "message": message, "errors": [{"reason": reason, "message": message}]}}


@respx.mock
async def test_exhausted_upload_allowance_defers_and_stays_retryable(monkeypatch):
    credentials(monkeypatch)
    init = respx.post(UPLOAD_URL).mock(
        return_value=httpx.Response(
            400,
            json=rejection(
                "uploadLimitExceeded", "The user has exceeded the number of videos they may upload."
            ),
        )
    )
    post = SimpleNamespace(remote_state={})

    def persist(state):
        post.remote_state = dict(state)

    with pytest.raises(Deferred) as caught:
        await YouTubeProvider().publish(clip_on_disk("allowance"), post, persist)

    # Deferred keeps the job queued (jobs.execute re-queues and refunds the attempt).
    assert caught.value.seconds >= 3600
    assert "uploadLimitExceeded" in str(caught.value)
    assert "exceeded the number of videos" in str(caught.value)
    # A later retry must be able to initiate a fresh upload session.
    assert post.remote_state["init_attempted"] is False
    assert init.call_count == 1


@respx.mock
async def test_other_rejection_reports_google_reason(monkeypatch):
    credentials(monkeypatch)
    respx.post(UPLOAD_URL).mock(
        return_value=httpx.Response(400, json=rejection("invalidTitle", "Invalid video title."))
    )
    post = SimpleNamespace(remote_state={})

    with pytest.raises(Blocked) as caught:
        await YouTubeProvider().publish(clip_on_disk("title"), post, lambda state: None)

    message = str(caught.value)
    assert "HTTP 400" in message
    assert "invalidTitle" in message
    assert "Invalid video title." in message


@respx.mock
async def test_rejection_without_json_body_still_reports_status(monkeypatch):
    credentials(monkeypatch)
    respx.post(UPLOAD_URL).mock(return_value=httpx.Response(400, text="not json"))
    post = SimpleNamespace(remote_state={})

    with pytest.raises(Blocked, match="HTTP 400"):
        await YouTubeProvider().publish(clip_on_disk("nojson"), post, lambda state: None)
