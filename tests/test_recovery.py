import hashlib
import hmac
import json
import time
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
import respx
from clipbot.ai import llm_provider
from clipbot.config import get_settings
from clipbot.db import Session, initialize, transaction
from clipbot.errors import Ambiguous, Blocked
from clipbot.integrations.clipping import clipping_provider
from clipbot.integrations.social import YouTubeProvider, publishing_provider
from clipbot.jobs import enqueue
from clipbot.models import (
    Clip,
    ProviderProject,
    PublishedPost,
    ScheduledPost,
    SocialAccount,
    SourceVideo,
    SystemJob,
    now,
)
from clipbot.storage import LocalStorage
from sqlalchemy import func, select

TINY_MP4 = b"\x00\x00\x00\x08ftyp"  # the smallest valid MP4 start: an empty ftyp box


def records(source):
    with transaction() as db:
        video = SourceVideo(
            source_id=source["id"],
            external_id="recovery-source",
            title="Owned recording",
            url="https://example.com/owned.mp4",
            duration=600,
            status="complete",
            demo=True,
        )
        db.add(video)
        db.flush()
        project = ProviderProject(
            source_video_id=video.id, provider="opus", external_id="opus-project", status="processing"
        )
        db.add(project)
        db.flush()
        clip = Clip(
            source_video_id=video.id,
            provider_project_id=project.id,
            provider="opus",
            external_id="clip-1",
            title="A tested moment",
            transcript="Authorized source transcript",
            duration=30,
            status="approved",
            overall_score=92,
            manually_approved=True,
            metadata_json={
                "youtube": {
                    "title": "A tested moment",
                    "description": "Description",
                    "hashtags": ["#Testing"],
                }
            },
            demo=True,
        )
        account = SocialAccount(platform="youtube", name="Recovery account", demo=True)
        db.add_all([clip, account])
        db.flush()
        post = ScheduledPost(
            clip_id=clip.id,
            account_id=account.id,
            platform="youtube",
            scheduled_at=now() - timedelta(minutes=10),
            status="needs_reconciliation",
            demo=True,
        )
        db.add(post)
        db.flush()
        job = enqueue(db, "publish", {"post_id": post.id}, f"publish:{post.id}")
        job.status = "needs_reconciliation"
        return video, project, clip, account, post


def signed_headers(body, salt="receipt-1", timestamp=None):
    return {
        "x-opus-salt": salt,
        "x-opus-timestamp": str(timestamp or int(time.time())),
        "x-opus-signature": hmac.new(
            b"webhook-test-secret", body + salt.encode(), hashlib.sha256
        ).hexdigest(),
        "Content-Type": "application/json",
    }


def test_password_rotation_revokes_existing_sessions(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_password", "changed-test-password")
    initialize()
    assert client.get("/api/studio").status_code == 401
    assert client.post("/api/auth/login", json={"password": "test-password"}).status_code == 401
    assert client.post("/api/auth/login", json={"password": "changed-test-password"}).status_code == 200
    assert client.get("/api/studio").status_code == 200


def test_demo_mode_blocks_live_adapters_even_with_keys(monkeypatch, client, source):
    monkeypatch.setattr(get_settings(), "vizard_api_key", "unused-key")
    for factory, args in [
        (clipping_provider, ("vizard",)),
        (publishing_provider, ("youtube",)),
        (llm_provider, ()),
    ]:
        with pytest.raises(Blocked, match="Live API calls"):
            factory(*args)
    assert source["demo"] is True
    assert (
        client.post("/api/accounts", json={"name": "Sample destination", "platform": "instagram"}).json()[
            "demo"
        ]
        is True
    )


def test_cannot_schedule_before_final_selection(client, source):
    video, _, clip, account, _ = records(source)
    with transaction() as db:
        db.get(SourceVideo, video.id).status = "processing"
    # A different account prevents an existing queue record from short-circuiting eligibility.
    dest = client.post("/api/accounts", json={"platform": "instagram", "name": "Other destination"}).json()
    response = client.post("/api/queue", json={"clip_id": clip.id, "account_id": dest["id"]})
    assert response.status_code == 409 and "both engines" in response.json()["detail"]


def test_signed_webhook_is_bound_to_project_and_idempotent(client, source, monkeypatch):
    monkeypatch.setattr(get_settings(), "opus_webhook_secret", "webhook-test-secret")
    _, project, _, _, _ = records(source)
    body = json.dumps({"projectId": "opus-project"}).encode()
    url = f"/api/webhooks/opus/{project.id}"
    assert client.post(url, content=body, headers=signed_headers(body)).status_code == 200
    assert client.post(url, content=body, headers=signed_headers(body)).json()["duplicate"] is True
    with Session() as db:
        assert db.get(ProviderProject, project.id).detail["completion_confirmed"] is True
        assert (
            db.scalar(
                select(func.count())
                .select_from(SystemJob)
                .where(SystemJob.idempotency_key == f"poll:{project.id}")
            )
            == 1
        )


@pytest.mark.parametrize("case", ["signature", "expired", "wrong_project"])
def test_webhook_rejects_invalid_or_mismatched_receipts(client, source, monkeypatch, case):
    monkeypatch.setattr(get_settings(), "opus_webhook_secret", "webhook-test-secret")
    _, project, _, _, _ = records(source)
    body = json.dumps({"projectId": "different" if case == "wrong_project" else "opus-project"}).encode()
    headers = signed_headers(body, timestamp=int(time.time()) - 600 if case == "expired" else None)
    if case == "signature":
        headers["x-opus-signature"] = "tampered"
    result = client.post(f"/api/webhooks/opus/{project.id}", content=body, headers=headers)
    assert result.status_code == (409 if case == "wrong_project" else 401)
    with Session() as db:
        assert not db.get(ProviderProject, project.id).detail.get("completion_confirmed")


def test_publication_reconciliation_records_once_without_upload(client, source):
    _, _, clip, _, post = records(source)
    body = {
        "external_id": "video-confirmed",
        "published_at": (now() - timedelta(minutes=5)).isoformat() + "Z",
        "publication_confirmed": True,
    }
    url = f"/api/queue/{post.id}/reconcile"
    first = client.post(url, json=body)
    assert first.status_code == 200, first.text
    assert client.post(url, json=body).json()["id"] == first.json()["id"]
    assert client.post(url, json={**body, "external_id": "another-video"}).status_code == 409
    with Session() as db:
        assert db.get(Clip, clip.id).status == "published"
        assert db.get(ScheduledPost, post.id).status == "published"
        assert (
            db.scalar(select(SystemJob).where(SystemJob.idempotency_key == f"publish:{post.id}")).status
            == "done"
        )
        assert db.scalar(select(func.count()).select_from(SystemJob).where(SystemJob.kind == "metrics")) == 5
        assert db.scalar(select(func.count()).select_from(PublishedPost)) == 1


def test_reconciliation_requires_explicit_confirmation_and_idle_worker(client, source):
    _, _, _, _, post = records(source)
    body = {
        "external_id": "video-confirmed",
        "published_at": now().isoformat() + "Z",
        "publication_confirmed": False,
    }
    url = f"/api/queue/{post.id}/reconcile"
    assert client.post(url, json=body).status_code == 422
    with transaction() as db:
        db.scalar(
            select(SystemJob).where(SystemJob.idempotency_key == f"publish:{post.id}")
        ).status = "running"
    assert client.post(url, json={**body, "publication_confirmed": True}).status_code == 409


@respx.mock
async def test_youtube_recovers_lost_final_response_without_second_upload(monkeypatch):
    for name in ["youtube_client_id", "youtube_client_secret", "youtube_refresh_token"]:
        monkeypatch.setattr(get_settings(), name, "contract-test-value")
    file = LocalStorage().path("clips/upload-test.mp4")
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(TINY_MP4)
    clip = SimpleNamespace(
        storage_key="clips/upload-test.mp4",
        metadata_json={"youtube": {"title": "Owned clip", "description": "A description", "hashtags": []}},
    )
    post = SimpleNamespace(remote_state={})

    def persist(state):
        post.remote_state = dict(state)

    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(200, json={"access_token": "contract-test-token"})
    )
    session = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=existing"
    init = respx.post("https://www.googleapis.com/upload/youtube/v3/videos").mock(
        return_value=httpx.Response(200, headers={"Location": session})
    )
    upload = respx.put(session).mock(
        side_effect=[
            httpx.Response(308),
            httpx.ReadTimeout("Lost final response"),
            httpx.Response(200, json={"id": "confirmed-id"}),
        ]
    )
    provider = YouTubeProvider()
    with pytest.raises(httpx.ReadTimeout):
        await provider.publish(clip, post, persist)
    assert post.remote_state["session_url"] == session
    result = await provider.publish(clip, post, persist)
    assert result.external_id == "confirmed-id" and init.call_count == 1
    assert upload.calls[0].request.headers["Content-Range"] == "bytes */8"
    assert upload.calls[1].request.content == TINY_MP4
    assert upload.calls[2].request.headers["Content-Range"] == "bytes */8"


@respx.mock
async def test_youtube_rejects_untrusted_session_location(monkeypatch):
    for name in ["youtube_client_id", "youtube_client_secret", "youtube_refresh_token"]:
        monkeypatch.setattr(get_settings(), name, "contract-test-value")
    file = LocalStorage().path("clips/location-test.mp4")
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(TINY_MP4)
    clip = SimpleNamespace(
        storage_key="clips/location-test.mp4",
        metadata_json={"youtube": {"title": "Owned clip", "description": "Description", "hashtags": []}},
    )
    post = SimpleNamespace(remote_state={})
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(200, json={"access_token": "test-token"})
    )
    respx.post("https://www.googleapis.com/upload/youtube/v3/videos").mock(
        return_value=httpx.Response(200, headers={"Location": "https://untrusted.example/upload"})
    )
    with pytest.raises(Ambiguous, match="Unexpected"):
        await YouTubeProvider().publish(clip, post, lambda state: None)


def test_cancelled_post_is_rescheduled_only_by_explicit_request(client, source):
    from clipbot.scheduling import schedule_clip

    _, _, clip, account, post = records(source)
    with transaction() as db:
        db.get(ScheduledPost, post.id).status = "failed"
        db.scalar(
            select(SystemJob).where(SystemJob.idempotency_key == f"publish:{post.id}")
        ).status = "blocked"
    assert client.post(f"/api/queue/{post.id}/cancel", json={}).status_code == 200
    with transaction() as db:
        assert schedule_clip(db, clip.id, account.id).status == "cancelled"
    result = client.post("/api/queue", json={"clip_id": clip.id, "account_id": account.id})
    assert result.status_code == 200 and result.json()["status"] == "scheduled"
    assert result.json()["id"] == post.id
    with Session() as db:
        assert (
            db.scalar(select(SystemJob).where(SystemJob.idempotency_key == f"publish:{post.id}")).status
            == "queued"
        )


def test_early_approval_cannot_skip_embeddings_or_final_dedup(client, source):
    video, _, clip, _, _ = records(source)
    with transaction() as db:
        db.get(SourceVideo, video.id).status = "processing"
        db.get(Clip, clip.id).status = "analyzing"
    result = client.post(f"/api/clips/{clip.id}/review",json={"action":"approve"})
    assert result.status_code == 409 and "final duplicate selection" in result.json()["detail"]
    with Session() as db:
        assert db.get(Clip, clip.id).status == "analyzing"
