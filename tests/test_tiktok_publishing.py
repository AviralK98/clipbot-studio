"""TikTok is mediated through OpusClip's /post-tasks endpoint (OpusClip is a TikTok-approved
posting partner; ClipBot never talks to TikTok directly). Only works for Opus-origin clips."""

from types import SimpleNamespace

import httpx
import pytest
import respx
from clipbot.config import get_settings
from clipbot.errors import Ambiguous, Blocked, Deferred, Transient
from clipbot.integrations.social import TikTokProvider

POST_TASKS_URL = "https://api.opus.pro/api/post-tasks"


def credentials(monkeypatch):
    monkeypatch.setattr(get_settings(), "opus_api_key", "contract-test-opus-key")
    monkeypatch.setattr(get_settings(), "opus_org_id", "")


def opus_clip(**overrides):
    values = dict(
        provider="opus",
        external_id="P3091801QuZd.0d88sqVOot",
        metadata_json={
            "tiktok": {
                "title": "A" * 130,  # deliberately over TikTok's 100-char limit
                "caption": "Full caption text",
                "hashtags": ["#one", "#two"],
            }
        },
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def scheduled_post(**overrides):
    values = {"remote_state": {}, "account_external_id": "postAccountId_xxx1"}
    values.update(overrides)
    return SimpleNamespace(**values)


async def test_vizard_clips_are_rejected(monkeypatch):
    credentials(monkeypatch)
    clip = opus_clip(provider="vizard")
    with pytest.raises(Blocked, match="OpusClip generated"):
        await TikTokProvider().publish(clip, scheduled_post(), lambda state: None)


async def test_missing_opus_post_account_id_is_blocked(monkeypatch):
    credentials(monkeypatch)
    with pytest.raises(Blocked, match="postAccountId"):
        await TikTokProvider().publish(opus_clip(), scheduled_post(account_external_id=""), lambda s: None)


async def test_malformed_external_id_is_blocked(monkeypatch):
    credentials(monkeypatch)
    clip = opus_clip(external_id="not-a-composite-id")
    with pytest.raises(Blocked, match="composite"):
        await TikTokProvider().publish(clip, scheduled_post(), lambda state: None)


@respx.mock
async def test_successful_publish_sends_bare_clip_id_and_no_privacy_field(monkeypatch):
    credentials(monkeypatch)
    route = respx.post(POST_TASKS_URL).mock(
        return_value=httpx.Response(201, json={"data": {"postId": "17722461986440WKW"}})
    )
    post = scheduled_post()

    def persist(state):
        post.remote_state = dict(state)

    result = await TikTokProvider().publish(opus_clip(), post, persist)

    assert result.external_id == "17722461986440WKW"
    assert result.url is None
    import json

    body = json.loads(route.calls[0].request.content)
    assert body["projectId"] == "P3091801QuZd"
    assert body["clipId"] == "0d88sqVOot"  # bare id, not the composite form
    assert body["postAccountId"] == "postAccountId_xxx1"
    assert body["postDetail"]["title"] == "A" * 100  # truncated to TikTok's limit
    assert body["postDetail"]["mediaType"] == "video"
    assert "Full caption text" in body["postDetail"]["custom"]["description"]
    assert "#one" in body["postDetail"]["custom"]["description"]
    assert "privacy" not in body["postDetail"]["custom"]
    assert route.calls[0].request.headers["Authorization"] == "Bearer contract-test-opus-key"
    assert post.remote_state["publish_attempted"] is True


@respx.mock
async def test_response_without_post_id_is_ambiguous(monkeypatch):
    credentials(monkeypatch)
    respx.post(POST_TASKS_URL).mock(return_value=httpx.Response(201, json={"data": {}}))
    with pytest.raises(Ambiguous, match="without a postId"):
        await TikTokProvider().publish(opus_clip(), scheduled_post(), lambda state: None)


@respx.mock
async def test_rate_limit_is_transient_and_unattempted_flag_is_rolled_back(monkeypatch):
    credentials(monkeypatch)
    respx.post(POST_TASKS_URL).mock(return_value=httpx.Response(429, headers={"retry-after": "30"}, json={}))
    post = scheduled_post()

    def persist(state):
        post.remote_state = dict(state)

    with pytest.raises(Transient):
        await TikTokProvider().publish(opus_clip(), post, persist)

    # A later retry must be able to initiate a fresh post, not think one already went out.
    assert post.remote_state["publish_attempted"] is False


@respx.mock
async def test_a_second_call_after_publish_attempted_is_set_needs_reconciliation(monkeypatch):
    credentials(monkeypatch)
    route = respx.post(POST_TASKS_URL).mock(return_value=httpx.Response(201, json={"data": {"postId": "x"}}))
    post = scheduled_post(remote_state={"publish_attempted": True})

    with pytest.raises(Ambiguous, match="reconciliation"):
        await TikTokProvider().publish(opus_clip(), post, lambda state: None)

    # Never a second live POST once we believe the first one may have gone out.
    assert route.call_count == 0


@respx.mock
async def test_tiktok_daily_quota_defers_and_stays_retryable(monkeypatch):
    credentials(monkeypatch)
    route = respx.post(POST_TASKS_URL).mock(
        return_value=httpx.Response(
            400,
            json={
                "errorName": "QuotaExceed",
                "errorMessage": "Post limit reached for TikTok  (15 per 24 hours). Please try again later.",
            },
        )
    )
    post = scheduled_post()

    def persist(state):
        post.remote_state = dict(state)

    with pytest.raises(Deferred) as caught:
        await TikTokProvider().publish(opus_clip(), post, persist)

    assert caught.value.seconds >= 3600
    assert "QuotaExceed" in str(caught.value)
    assert "15 per 24 hours" in str(caught.value)
    assert post.remote_state["publish_attempted"] is False
    assert route.call_count == 1


@respx.mock
async def test_export_not_ready_defers_and_stays_retryable(monkeypatch):
    credentials(monkeypatch)
    route = respx.post(POST_TASKS_URL).mock(
        return_value=httpx.Response(
            400,
            json={
                "errorName": "_ExportNotReadyError",
                "errorMessage": "We're preparing this clip for publishing. Try again in a couple of minutes.",
            },
        )
    )
    post = scheduled_post()

    def persist(state):
        post.remote_state = dict(state)

    with pytest.raises(Deferred) as caught:
        await TikTokProvider().publish(opus_clip(), post, persist)

    assert caught.value.seconds >= 60
    assert "preparing this clip" in str(caught.value)
    assert post.remote_state["publish_attempted"] is False  # a retry can cleanly re-post
    assert route.call_count == 1


@respx.mock
async def test_other_400_reports_opus_error_name_and_message(monkeypatch):
    credentials(monkeypatch)
    respx.post(POST_TASKS_URL).mock(
        return_value=httpx.Response(
            400, json={"errorName": "_InvalidTitleError", "errorMessage": "Title too long"}
        )
    )
    with pytest.raises(Blocked, match=r"_InvalidTitleError.*Title too long"):
        await TikTokProvider().publish(opus_clip(), scheduled_post(), lambda state: None)


async def test_metrics_are_not_yet_available(monkeypatch):
    credentials(monkeypatch)
    with pytest.raises(Blocked, match="does not yet expose analytics"):
        await TikTokProvider().metrics(SimpleNamespace())


async def test_missing_opus_credentials_is_blocked(monkeypatch):
    monkeypatch.setattr(get_settings(), "opus_api_key", "")
    with pytest.raises(Blocked, match="OPUS_API_KEY"):
        TikTokProvider()
