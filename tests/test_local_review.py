from types import SimpleNamespace

import pytest
from clipbot.ai import LocalProvider, llm_provider
from clipbot.config import get_settings
from clipbot.db import Session, transaction
from clipbot.dedup import duplicate_reason
from clipbot.errors import Blocked
from clipbot.models import APIUsage, Clip, ClipEmbedding, ClipScore, SocialAccount, SystemState
from clipbot.pipeline import evaluate, finalize
from clipbot.scheduling import can_publish
from sqlalchemy import delete, select
from test_pipeline import finish_demo


async def test_local_review_is_extractive_deterministic_and_keyless(monkeypatch):
    cfg = get_settings()
    monkeypatch.setattr(cfg, "demo_mode", False)
    monkeypatch.setattr(cfg, "llm_provider", "local")
    monkeypatch.setattr(cfg, "openai_api_key", "")
    monkeypatch.setattr(cfg, "anthropic_api_key", "")
    provider = llm_provider()
    assert isinstance(provider, LocalProvider)
    text = "A practical example. " * 300
    result, tokens = await provider.evaluate(text)
    assert tokens == 0
    assert result.youtube.title in text
    assert result.youtube.description == text.strip()[:4500]
    assert result.hooks == []
    assert result.recommended_platforms == []
    assert await provider.embed(text) == await provider.embed(text)
    assert (await provider.embed(text))[1] == "local-lexical-v1"
    with pytest.raises(Blocked):
        await provider.evaluate(" ")


def test_local_connection_does_not_request_keys(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_provider", "local")
    integration = next(i for i in client.get("/api/studio").json()["integrations"] if i["id"] == "ai")
    assert integration["configured"] is True
    assert integration["variables"] == []


async def test_local_pipeline_costs_zero_and_waits_for_approval(client, monkeypatch):
    video_id = await finish_demo(client)
    with transaction() as db:
        clip = db.scalar(select(Clip).where(Clip.source_video_id == video_id, Clip.status == "approved"))
        clip_id = clip.id
        clip.demo = False
        clip.status = "candidate"
        clip.storage_key = "already-archived.mp4"
        db.execute(delete(ClipScore).where(ClipScore.clip_id == clip_id))
        db.execute(delete(ClipEmbedding).where(ClipEmbedding.clip_id == clip_id))
    cfg = get_settings()
    monkeypatch.setattr(cfg, "demo_mode", False)
    monkeypatch.setattr(cfg, "llm_provider", "local")
    monkeypatch.setattr(cfg, "max_ai_cost_per_day", 0)
    job = SimpleNamespace(id="local-test", attempts=1, payload={"clip_id": clip_id})
    await evaluate(job)
    await finalize(SimpleNamespace(payload={"source_video_id": video_id}))
    with Session() as db:
        clip = db.get(Clip, clip_id)
        assert clip.status == "reserve"
        assert clip.metadata_json["manual_review_required"] is True
        assert db.scalar(select(ClipScore).where(ClipScore.clip_id == clip_id)).model == "local-heuristic-v1"
        usage = list(db.scalars(select(APIUsage).where(APIUsage.demo.is_(False))))
        assert len(usage) == 2
        assert all(u.estimated_cost == 0 for u in usage)
        account = db.scalar(select(SocialAccount).where(SocialAccount.platform == "youtube"))
        account.demo = False
        state = db.get(SystemState, 1)
        state.autopilot = True
        with pytest.raises(Blocked, match="Local review requires manual approval"):
            can_publish(db, clip, account, state)
        clip.manually_approved = True
        can_publish(db, clip, account, state)


def test_lexical_counts_alone_do_not_claim_semantic_duplicates():
    a = SimpleNamespace(id="a", transcript="one two three", ranges=[], source_video_id="a")
    b = SimpleNamespace(id="b", transcript="three two one", ranges=[], source_video_id="b")
    embeddings = {key: SimpleNamespace(model="local-lexical-v1", vector=[1, 1]) for key in ("a", "b")}
    assert duplicate_reason(a, b, embeddings) is None
