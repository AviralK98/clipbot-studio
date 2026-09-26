"""The dashboard's progress card, and one engine failing without holding up the other."""

import httpx
import pytest
import respx
from clipbot import pipeline
from clipbot.config import get_settings
from clipbot.db import Session, transaction
from clipbot.errors import Blocked
from clipbot.integrations import clipping
from clipbot.jobs import drain
from clipbot.models import (
    Clip,
    ProviderProject,
    SocialAccount,
    Source,
    SourceVideo,
    SystemJob,
    SystemState,
    now,
)
from clipbot.scheduling import can_publish
from clipbot.storage import LocalStorage
from sqlalchemy import select

OUT_OF_MINUTES = clipping.VIZARD_CODES[4007] + " (Vizard code 4007)"
TINY_MP4 = b"\x00\x00\x00\x08ftyp"


async def finish(client):
    await drain()
    with transaction() as db:
        for job in db.scalars(select(SystemJob).where(SystemJob.kind == "finalize")):
            job.due_at = now()
    await drain()


def progress(client):
    return client.get("/api/studio").json()["recent_videos"]


def vizard_runs_out_of_minutes(monkeypatch):
    working = clipping.DemoClippingProvider.get_status

    async def get_status(self, project_id):
        if self.provider == "vizard":
            raise Blocked(OUT_OF_MINUTES)
        return await working(self, project_id)

    monkeypatch.setattr(clipping.DemoClippingProvider, "get_status", get_status)


async def test_progress_follows_a_video_from_added_to_ready(client):
    video_id = client.post("/api/demo/seed", json={}).json()["source_video_id"]
    [added] = [v for v in progress(client) if v["id"] == video_id]
    assert added["stage"] == "sending" and added["clips"]["found"] == 0

    await finish(client)
    [done] = [v for v in progress(client) if v["id"] == video_id]
    assert done["stage"] == "done" and done["finished_at"]
    assert not any(e["needs_confirmation"] or e["confirmed"] for e in done["engines"])
    assert [(e["name"], e["status"], e["clips"]) for e in done["engines"]] == [
        ("OpusClip", "complete", 3),
        ("Vizard", "complete", 3),
    ]
    assert done["clips"] == {"found": 6, "scored": 6, "scoring": 0, "approved": 4, "review": 0, "rejected": 2}


async def test_failed_engine_does_not_hold_up_the_other(client, monkeypatch):
    vizard_runs_out_of_minutes(monkeypatch)
    video_id = client.post("/api/demo/seed", json={}).json()["source_video_id"]
    await finish(client)

    with Session() as db:
        vizard = db.scalar(
            select(ProviderProject).where(
                ProviderProject.source_video_id == video_id, ProviderProject.provider == "vizard"
            )
        )
        assert (vizard.status, vizard.error) == ("failed", OUT_OF_MINUTES)
        assert db.get(SourceVideo, video_id).status == "complete"
        clips = list(db.scalars(select(Clip).where(Clip.source_video_id == video_id)))
        assert {c.provider for c in clips} == {"opus"}
        assert all(c.status in {"approved", "reserve", "rejected"} for c in clips)

    [video] = [v for v in progress(client) if v["id"] == video_id]
    assert video["stage"] == "done"
    engines = {e["provider"]: e for e in video["engines"]}
    assert engines["vizard"]["status"] == "failed"
    assert "out of processing minutes" in engines["vizard"]["problem"]
    assert engines["opus"]["problem"] is None


async def test_retried_engine_adds_its_clips_without_undoing_decisions(client, monkeypatch):
    vizard_runs_out_of_minutes(monkeypatch)
    video_id = client.post("/api/demo/seed", json={}).json()["source_video_id"]
    await finish(client)
    with transaction() as db:
        decided = {c.id: c.status for c in db.scalars(select(Clip).where(Clip.source_video_id == video_id))}
        # The owner overrules one selection by hand before the retry.
        first = db.get(Clip, next(iter(decided)))
        first.status, first.manually_approved = "reserve", True
        decided[first.id] = "reserve"
        poll = db.scalar(select(SystemJob).where(SystemJob.kind == "poll", SystemJob.status == "blocked"))

    monkeypatch.undo()  # Vizard minutes topped up
    assert client.post(f"/api/jobs/{poll.id}/retry", json={}).status_code == 200
    await finish(client)

    with Session() as db:
        assert db.get(SourceVideo, video_id).status == "complete"
        clips = list(db.scalars(select(Clip).where(Clip.source_video_id == video_id)))
        assert {c.provider for c in clips} == {"opus", "vizard"}
        assert all(c.status in {"approved", "reserve", "rejected"} for c in clips)
        assert {c.id: c.status for c in clips if c.id in decided} == decided


async def test_setup_problems_show_on_the_engine(client, source, monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_mode", False)
    with transaction() as db:
        db.get(Source, source["id"]).demo = False
    client.post(
        "/api/videos",
        json={
            "source_id": source["id"],
            "title": "Episode",
            "url": "https://example.com/e.mp4",
            "duration": 600,
        },
    )
    await drain()
    [video] = progress(client)
    assert video["stage"] == "sending" and video["thumbnail"] == ""
    problems = {e["provider"]: e["problem"] for e in video["engines"]}
    assert "VIZARD_API_KEY" in problems["vizard"] and "OPUS_API_KEY" in problems["opus"]


def test_opus_asks_the_owner_to_confirm_it_finished(client, source, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "demo_mode", False)
    with transaction() as db:
        db.get(Source, source["id"]).demo = False
        video = SourceVideo(
            source_id=source["id"],
            external_id="abc",
            title="Episode",
            url="https://youtu.be/abc",
            duration=600,
            status="processing",
        )
        db.add(video)
        db.flush()
        project = ProviderProject(
            source_video_id=video.id, provider="opus", external_id="P1", status="processing"
        )
        db.add(project)
        db.flush()
        project_id = project.id

    [video] = progress(client)
    assert video["thumbnail"] == "https://i.ytimg.com/vi/abc/mqdefault.jpg"
    [opus] = video["engines"]
    assert (opus["needs_confirmation"], opus["confirmed"]) == (True, False)
    assert (opus["project_id"], opus["external_id"]) == (project_id, "P1")

    # A reachable signed webhook tells ClipBot itself, so there's nothing to ask.
    monkeypatch.setattr(settings, "public_api_base_url", "https://clipbot.example.com")
    monkeypatch.setattr(settings, "opus_webhook_secret", "contract-test-value")
    assert progress(client)[0]["engines"][0]["needs_confirmation"] is False
    monkeypatch.setattr(settings, "public_api_base_url", "")

    confirmed = client.post(
        f"/api/projects/{project_id}/reconcile", json={"external_id": "P1", "completion_confirmed": True}
    )
    assert confirmed.status_code == 200
    [opus] = progress(client)[0]["engines"]
    assert (opus["needs_confirmation"], opus["confirmed"]) == (False, True)


async def test_clips_are_ready_to_review_before_their_files_download(client, source, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "llm_provider", "local")
    with transaction() as db:
        row = db.get(Source, source["id"])
        row.demo, row.routing = False, "vizard"
        db.add(SocialAccount(platform="youtube", name="Live channel", demo=False))
    engine = clipping.DemoClippingProvider("vizard")
    listed = engine.get_clips

    async def clips_with_files(project_id):
        clips = await listed(project_id)
        for clip in clips:
            clip.media_url = f"https://cdn.example.com/{clip.external_id}.mp4"
        return clips

    async def save(self, url, key):
        self.path(key).parent.mkdir(parents=True, exist_ok=True)
        self.path(key).write_bytes(TINY_MP4)
        return key

    monkeypatch.setattr(engine, "get_clips", clips_with_files)
    monkeypatch.setattr(pipeline, "clipping_provider", lambda name, demo=False: engine)
    monkeypatch.setattr(LocalStorage, "archive", save)
    client.post(
        "/api/videos",
        json={
            "source_id": source["id"],
            "title": "Episode",
            "url": "https://example.com/e.mp4",
            "duration": 600,
        },
    )

    await drain()  # the downloads aren't due yet
    [video] = progress(client)
    assert video["stage"] == "done"
    assert video["clips"]["review"] == 3
    assert video["files"] == {"saved": 0, "pending": 3, "problem": None}
    with transaction() as db:
        clip = db.scalar(select(Clip).where(Clip.status == "reserve"))
        clip.manually_approved = True
        account = db.scalar(select(SocialAccount).where(SocialAccount.demo.is_(False)))
        with pytest.raises(Blocked, match="still downloading"):
            can_publish(db, clip, account, db.get(SystemState, 1))
        for job in db.scalars(select(SystemJob).where(SystemJob.kind == "download")):
            job.due_at = now()

    await drain()
    assert progress(client)[0]["files"] == {"saved": 3, "pending": 0, "problem": None}
    with Session() as db:
        assert all(c.storage_key for c in db.scalars(select(Clip)))


@respx.mock
async def test_vizard_codes_are_explained(monkeypatch):
    monkeypatch.setattr(get_settings(), "vizard_api_key", "contract-test-value")
    respx.get(f"{clipping.VizardProvider.base}/project/query/1").mock(
        return_value=httpx.Response(200, json={"code": 4007})
    )
    with pytest.raises(Blocked, match="out of processing minutes; top up") as caught:
        await clipping.VizardProvider().get_status("1")
    assert "code 4007" in str(caught.value)
