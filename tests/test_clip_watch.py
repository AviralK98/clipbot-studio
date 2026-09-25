"""Gemini watch-through analysis of a published Short: queueing, the job, fallbacks and failures."""

import asyncio
import base64
import json
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
import respx
from clipbot import clip_watch
from clipbot.config import get_settings
from clipbot.db import Session, transaction
from clipbot.errors import Blocked, Transient
from clipbot.models import ClipAnalysis, SystemJob, now
from sqlalchemy import select

VIDEO = "EdJ1Ebbaedg"
PRIMARY = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"
FALLBACK = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.7-flash:generateContent"
ANSWER = {
    "summary": "It opens on the punchline, then drags.",
    "hook": {"first_seconds": "00:00-00:03, the Apu guess", "rating": "mixed", "why": "Funny but no setup."},
    "moments": [
        {"time": "00:31", "kind": "drop_off", "happening": "A Vizard promo card", "effect": "0.25 to 0.11"}
    ],
    "worked": ["Instant payoff"],
    "hurt": ["Promo outro"],
    "next_time": ["End the clip at 00:06"],
    "luck_vs_content": "Mostly YouTube's first-day test.",
}
STATS = {
    "video": {"title": "Finally Guessing The Character!", "duration": 34},
    "live": {"viewCount": 1164},
    "summary": {
        "views": 1219,
        "stayed_rate": 0.44,
        "average_view_percentage": 44.0,
        "shares": 0,
        "subscribers_gained": 0,
    },
    "traffic": [{"label": "Shorts feed", "share": 0.97}],
    "daily": [{"date": "2026-09-17", "views": 303}, {"date": "2026-09-18", "views": 859}],
    "retention": [{"second": i * 0.34, "watching": 1.05 - i / 110, "relative": 0.2} for i in range(1, 101)],
}


def gemini_reply(answer=ANSWER, finish="STOP"):
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {"parts": [{"text": json.dumps(answer), "thoughtSignature": "sig"}]},
                    "finishReason": finish,
                }
            ],
            "usageMetadata": {"totalTokenCount": 5000},
        },
    )


def busy():
    return httpx.Response(
        503, json={"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}}
    )


@pytest.fixture
def gemini(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "contract-test-gemini")
    monkeypatch.setattr(settings, "gemini_model", "gemini-3.8-flash")
    monkeypatch.setattr(settings, "gemini_fallback_model", "gemini-3.7-flash")


@pytest.fixture
def youtube_numbers(monkeypatch):
    async def fake_analysis(context, refresh=False):
        return STATS

    monkeypatch.setattr(clip_watch, "video_analysis", fake_analysis)


def queue():
    with transaction() as db:
        return clip_watch.request_analysis(db, VIDEO)


def run_job(attempts=1):
    asyncio.run(clip_watch.watch(SimpleNamespace(payload={"video_id": VIDEO}, attempts=attempts)))


def saved():
    with Session() as db:
        return db.scalar(select(ClipAnalysis).where(ClipAnalysis.video_id == VIDEO))


def test_watch_endpoints_require_login():
    from clipbot.api import app
    from fastapi.testclient import TestClient

    with TestClient(app, headers={"Origin": "http://localhost:3000"}) as anonymous:
        assert anonymous.get(f"/api/insights/videos/{VIDEO}/watch").status_code == 401
        assert anonymous.post(f"/api/insights/videos/{VIDEO}/watch").status_code == 401


def test_starting_without_a_gemini_key_explains_how_to_add_one(client, published, monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "")
    assert client.get(f"/api/insights/videos/{VIDEO}/watch").json() == {"status": "none", "configured": False}
    response = client.post(f"/api/insights/videos/{VIDEO}/watch")
    assert response.status_code == 409
    assert "GEMINI_API_KEY" in response.json()["detail"]


def test_start_queues_a_single_watch_job(client, published, gemini):
    first = client.post(f"/api/insights/videos/{VIDEO}/watch")
    assert first.status_code == 200 and first.json()["status"] == "queued"
    again = client.post(f"/api/insights/videos/{VIDEO}/watch")
    assert again.json()["status"] == "queued"
    with Session() as db:
        jobs = db.scalars(select(SystemJob).where(SystemJob.kind == "watch")).all()
    assert [job.payload for job in jobs] == [{"video_id": VIDEO}]  # a second click doesn't queue twice


def test_unknown_video_is_404(client, published, gemini):
    assert client.post("/api/insights/videos/not-ours/watch").status_code == 404


@respx.mock
def test_job_sends_the_clip_and_numbers_and_saves_the_answer(client, published, gemini, youtube_numbers):
    route = respx.post(PRIMARY).mock(return_value=gemini_reply())
    queue()
    run_job()

    row = saved()
    assert (row.status, row.model, row.error) == ("done", "gemini-3.8-flash", None)
    assert row.result["summary"] == ANSWER["summary"]

    request = json.loads(route.calls[0].request.content)
    assert route.calls[0].request.headers["x-goog-api-key"] == "contract-test-gemini"
    video_part, text_part = request["contents"][0]["parts"]
    assert base64.b64decode(video_part["inlineData"]["data"]) == published["media"].read_bytes()
    assert video_part["inlineData"]["mimeType"] == "video/mp4"
    assert '"share_who_stayed_past_the_first_seconds": 0.44' in text_part["text"]
    assert '"clipped_by": "Vizard"' in text_part["text"]
    assert request["generationConfig"]["responseJsonSchema"]["required"] == clip_watch.SCHEMA["required"]

    body = client.get(f"/api/insights/videos/{VIDEO}/watch").json()
    assert body["status"] == "done" and body["result"]["next_time"] == ["End the clip at 00:06"]


@respx.mock
def test_busy_main_model_falls_back_to_the_second(published, gemini, youtube_numbers):
    respx.post(PRIMARY).mock(return_value=busy())
    respx.post(FALLBACK).mock(return_value=gemini_reply())
    queue()
    run_job()
    assert (saved().status, saved().model) == ("done", "gemini-3.7-flash")


@respx.mock
def test_both_models_busy_retries_then_gives_up_on_the_last_attempt(published, gemini, youtube_numbers):
    respx.post(PRIMARY).mock(return_value=busy())
    respx.post(FALLBACK).mock(return_value=busy())
    queue()
    with pytest.raises(Transient) as caught:
        run_job(attempts=1)
    assert caught.value.retry_after == clip_watch.BUSY_RETRY_SECONDS
    assert saved().status == "queued" and "busy" in saved().error

    with pytest.raises(Transient):
        run_job(attempts=get_settings().max_job_attempts)
    assert saved().status == "failed" and "Gave up" in saved().error


@respx.mock
def test_safety_block_fails_with_a_clear_reason(published, gemini, youtube_numbers):
    respx.post(PRIMARY).mock(
        return_value=httpx.Response(200, json={"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"}})
    )
    queue()
    with pytest.raises(Blocked):
        run_job()
    assert saved().status == "failed"
    assert "declined to analyse this clip (PROHIBITED_CONTENT)" in saved().error


@respx.mock
def test_missing_youtube_numbers_still_watches_the_clip(published, gemini, monkeypatch):
    async def unavailable(context, refresh=False):
        raise Blocked("YouTube login expired")

    monkeypatch.setattr(clip_watch, "video_analysis", unavailable)
    route = respx.post(PRIMARY).mock(return_value=gemini_reply())
    queue()
    run_job()
    assert saved().status == "done"
    prompt = json.loads(route.calls[0].request.content)["contents"][0]["parts"][1]["text"]
    assert "YouTube numbers are unavailable right now (YouTube login expired)" in prompt


@respx.mock
def test_damaged_clip_file_is_not_sent_to_gemini(published, gemini, youtube_numbers):
    route = respx.post(PRIMARY).mock(return_value=gemini_reply())
    published["media"].write_bytes(bytes([0x24, 0x1A, 0x9C, 0x92]) * 64)
    queue()
    with pytest.raises(Blocked, match="damaged"):
        run_job()
    assert saved().status == "failed" and "damaged" in saved().error
    assert route.call_count == 0


def test_interrupted_analysis_shows_as_stalled_and_can_be_restarted(client, published, gemini):
    queue()
    with transaction() as db:
        row = db.scalar(select(ClipAnalysis).where(ClipAnalysis.video_id == VIDEO))
        row.status, row.updated_at = "running", now() - timedelta(minutes=30)
    assert client.get(f"/api/insights/videos/{VIDEO}/watch").json()["status"] == "stalled"
    assert client.post(f"/api/insights/videos/{VIDEO}/watch").json()["status"] == "queued"
    with Session() as db:
        assert len(db.scalars(select(SystemJob).where(SystemJob.kind == "watch")).all()) == 2


def test_unfinished_or_incomplete_answers_are_rejected():
    with pytest.raises(Blocked, match="stopped before finishing"):
        clip_watch.parse_answer(json.loads(gemini_reply(finish="MAX_TOKENS").content))
    without_hook = {key: value for key, value in ANSWER.items() if key != "hook"}
    with pytest.raises(Blocked, match="missing hook"):
        clip_watch.parse_answer(json.loads(gemini_reply(without_hook).content))
