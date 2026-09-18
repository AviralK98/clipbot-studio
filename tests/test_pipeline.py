from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from clipbot.analytics import analytics_report, learn
from clipbot.budgets import reserve
from clipbot.config import get_settings
from clipbot.db import Session, transaction
from clipbot.errors import Blocked
from clipbot.jobs import claim, drain
from clipbot.models import (
    APIUsage,
    Clip,
    ProviderProject,
    PublishedPost,
    ScheduledPost,
    SocialAccount,
    Source,
    SourceVideo,
    StrategyMetric,
    SystemJob,
    SystemState,
    now,
)
from clipbot.scheduling import can_publish, next_slot, schedule_clip
from sqlalchemy import select


async def finish_demo(client):
    response = client.post("/api/demo/seed", json={})
    assert response.status_code == 200, response.text
    video_id = response.json()["source_video_id"]
    await drain()
    with transaction() as db:
        for job in db.scalars(select(SystemJob).where(SystemJob.kind == "finalize")):
            job.due_at = now()
    await drain()
    return video_id


async def test_full_dual_engine_pipeline_ranks_deduplicates_and_publishes(client):
    video_id = await finish_demo(client)
    with Session() as db:
        projects = list(
            db.scalars(select(ProviderProject).where(ProviderProject.source_video_id == video_id))
        )
        clips = list(db.scalars(select(Clip).where(Clip.source_video_id == video_id)))
        assert len(projects) == 2 and all(p.status == "complete" for p in projects)
        assert len(clips) == 6
        assert sum(bool(c.duplicate_of) for c in clips) == 1
        assert sum(c.status == "approved" for c in clips) == 4
        assert sum(c.status == "rejected" for c in clips) == 2
        assert all(c.overall_score is not None for c in clips)
        assert db.get(SourceVideo, video_id).status == "complete"
        chosen = max((c for c in clips if c.status == "approved"), key=lambda c: c.overall_score)
        account = db.scalar(select(SocialAccount).where(SocialAccount.platform == "youtube"))
    result = client.post("/api/queue", json={"clip_id": chosen.id, "account_id": account.id})
    assert result.status_code == 200, result.text
    assert (
        client.post("/api/queue", json={"clip_id": chosen.id, "account_id": account.id}).json()["id"]
        == result.json()["id"]
    )
    from clipbot.pipeline import sweep

    with transaction() as db:
        db.get(ScheduledPost, result.json()["id"]).scheduled_at = now() - timedelta(seconds=1)
        db.get(SystemState, 1).autopilot = False
        db.get(Clip, chosen.id).manually_approved = True
    sweep()
    await drain()
    with Session() as db:
        assert db.get(ScheduledPost, result.json()["id"]).status == "published"
        publication = db.scalar(
            select(PublishedPost).where(PublishedPost.scheduled_post_id == result.json()["id"])
        )
        assert publication.demo and publication.external_id.startswith("demo-")
        assert db.scalar(select(SystemJob).where(SystemJob.idempotency_key == f"metrics:{publication.id}:24"))


async def test_kill_switch_and_revoked_authorization_rechecked(client):
    video_id = await finish_demo(client)
    with transaction() as db:
        clip = db.scalar(select(Clip).where(Clip.source_video_id == video_id, Clip.status == "approved"))
        account = db.scalar(select(SocialAccount).where(SocialAccount.platform == "youtube"))
        state = db.get(SystemState, 1)
        state.stop_all_posting = True
        with pytest.raises(Blocked, match="stopped"):
            can_publish(db, clip, account, state)
        state.stop_all_posting = False
        source = db.get(Source, db.get(SourceVideo, video_id).source_id)
        source.authorized_platforms = ["instagram"]
        with pytest.raises(Blocked, match="authorized"):
            can_publish(db, clip, account, state)


async def test_demo_clips_never_publish_to_live_accounts(client):
    video_id = await finish_demo(client)
    with transaction() as db:
        clip = db.scalar(select(Clip).where(Clip.source_video_id == video_id, Clip.status == "approved"))
        account = SocialAccount(platform="youtube", name="Live", demo=False)
        db.add(account)
        db.flush()
        with pytest.raises(Blocked, match="environment"):
            schedule_clip(db, clip.id, account.id)


async def test_manual_mode_requires_approval(client):
    video_id = await finish_demo(client)
    with transaction() as db:
        clip = db.scalar(select(Clip).where(Clip.source_video_id == video_id, Clip.status == "approved"))
        account = db.scalar(select(SocialAccount).where(SocialAccount.platform == "youtube"))
        state = db.get(SystemState, 1)
        state.autopilot = False
        with pytest.raises(Blocked, match="manual approval"):
            can_publish(db, clip, account, state)


def test_schedule_respects_london_dst_and_minimum_interval():
    state = SimpleNamespace(
        timezone="Europe/London", daily_limit=3, min_interval=180, posting_times=["09:00", "14:00", "19:00"]
    )
    result = next_slot(state, [], datetime(2026, 6, 1, 7, 0))
    assert result == datetime(2026, 6, 1, 8, 0)
    result = next_slot(
        state, [SimpleNamespace(scheduled_at=result, status="scheduled")], datetime(2026, 6, 1, 7, 0)
    )
    assert result == datetime(2026, 6, 1, 13, 0)
    state.posting_times = ["01:30", "09:00"]
    assert next_slot(state, [], datetime(2026, 3, 29, 0, 0)) == datetime(2026, 3, 29, 8, 0)


def test_daily_budget_is_reserved_once_and_caps_next_job():
    cfg = get_settings()
    with transaction() as db:
        first = reserve(db, "test-one", "source", cfg.max_source_minutes_per_day, "minutes")
        assert reserve(db, "test-one", "source", cfg.max_source_minutes_per_day, "minutes").id == first.id
        with pytest.raises(Blocked, match="budget"):
            reserve(db, "test-two", "source", 1, "minutes")
    with Session() as db:
        assert len(list(db.scalars(select(APIUsage)))) == 1


def test_job_claim_is_exclusive(client, source):
    client.post(
        "/api/videos",
        json={
            "source_id": source["id"],
            "title": "Episode",
            "url": "https://example.com/e.mp4",
            "duration": 600,
        },
    )
    with Session() as db:
        job = db.scalar(select(SystemJob))
    assert claim(job.id) is not None
    assert claim(job.id) is None


async def test_demo_metrics_never_influence_live_learning(client):
    await finish_demo(client)
    with transaction() as db:
        report = analytics_report(db, demo=True)
        assert report["views_7d"] > 0
        assert len([b for b in report["breakdown"] if b["dimension"] == "provider"]) == 2
        learn(db)
        assert len(list(db.scalars(select(StrategyMetric)))) == 0


async def test_missing_credentials_leave_actionable_job(client, source, monkeypatch):
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
    with Session() as db:
        jobs = list(db.scalars(select(SystemJob).where(SystemJob.kind == "submit")))
        assert len(jobs) == 2
        assert all(j.status == "blocked" for j in jobs)
        assert any("VIZARD_API_KEY" in j.error for j in jobs)
        assert any("OPUS_API_KEY" in j.error for j in jobs)
