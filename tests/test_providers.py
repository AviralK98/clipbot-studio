import httpx
import pytest
import respx
from clipbot.config import Settings
from clipbot.errors import Ambiguous, Blocked, Transient
from clipbot.integrations.clipping import OpusProvider, VizardProvider
from clipbot.integrations.http import request_json


def test_missing_live_credentials_do_not_fall_back_to_demo():
    with pytest.raises(Blocked):
        VizardProvider(Settings(vizard_api_key="", _env_file=None))
    with pytest.raises(Blocked):
        OpusProvider(Settings(opus_api_key="", _env_file=None))


@respx.mock
async def test_vizard_submission_contract_and_normalization():
    provider = VizardProvider(Settings(vizard_api_key="test", _env_file=None))
    submit = respx.post(provider.base + "/project/create").mock(
        return_value=httpx.Response(200, json={"code": 2000, "projectId": 123})
    )
    assert await provider.submit_video("https://youtube.com/watch?v=abc", "Owned", 600) == "123"
    import json

    body = json.loads(submit.calls[0].request.content)
    assert body["videoType"] == 2 and body["ratioOfClip"] == 1 and body["preferLength"] == [2]
    assert submit.calls[0].request.headers["VIZARDAI_API_KEY"] == "test"
    respx.get(provider.base + "/project/query/123").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": 2000,
                "videos": [
                    {
                        "videoId": 42,
                        "videoMsDuration": 41500,
                        "title": "Moment",
                        "transcript": "text",
                        "viralScore": "8",
                        "videoUrl": "https://cdn.example.com/c.mp4",
                    }
                ],
            },
        )
    )
    assert await provider.get_status("123") == "complete"
    clip = (await provider.get_clips("123"))[0]
    assert clip.duration == 41.5 and clip.provider_score == 8
    assert clip.ranges == []


@respx.mock
async def test_vizard_application_rate_limit():
    provider = VizardProvider(Settings(vizard_api_key="test", _env_file=None))
    respx.get(provider.base + "/project/query/123").mock(
        return_value=httpx.Response(200, json={"code": 4003})
    )
    with pytest.raises(Transient):
        await provider.get_status("123")


@respx.mock
async def test_opus_contract_and_ambiguous_timestamp_units():
    provider = OpusProvider(Settings(opus_api_key="test", opus_org_id="org-1", _env_file=None))
    submit = respx.post(provider.base + "/clip-projects").mock(
        return_value=httpx.Response(201, json={"id": "opus-1"})
    )
    assert await provider.submit_video("https://example.com/v.mp4", "Owned", 600) == "opus-1"
    assert submit.calls[0].request.headers["Authorization"] == "Bearer test"
    respx.get(provider.base + "/exportable-clips").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "opus-1.c1",
                    "title": "Moment",
                    "text": "Transcript",
                    "durationMs": 19478,
                    "timeRanges": [[192170, 211630]],
                    "uriForExport": "https://example.com/clip.mp4",
                }
            ],
        )
    )
    assert await provider.get_status("opus-1") == "awaiting_webhook"
    clip = (await provider.get_clips("opus-1"))[0]
    assert clip.duration == 19.478
    assert clip.ranges == []  # Do not guess units from contradictory docs.
    provider.cfg.opus_time_range_unit = "milliseconds"
    assert (await provider.get_clips("opus-1"))[0].ranges == [[192.17, 211.63]]


@respx.mock
async def test_mutation_server_error_requires_reconciliation():
    respx.post("https://example.com/projects").mock(return_value=httpx.Response(500))
    async with httpx.AsyncClient() as client:
        with pytest.raises(Ambiguous):
            await request_json(client, "POST", "https://example.com/projects", json={})


@respx.mock
async def test_get_server_error_and_429_are_retryable():
    respx.get("https://example.com/projects").mock(return_value=httpx.Response(503))
    respx.post("https://example.com/projects").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "120"})
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(Transient):
            await request_json(client, "GET", "https://example.com/projects")
        with pytest.raises(Transient) as exc:
            await request_json(client, "POST", "https://example.com/projects")
        assert exc.value.retry_after == 120


@respx.mock
async def test_opus_data_envelope():
    provider = OpusProvider(Settings(opus_api_key="test", _env_file=None))
    respx.get(provider.base + "/exportable-clips").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [{"id": "c1", "title": "Clip", "text": "Transcript", "durationMs": 30000}],
                "total": 1,
            },
        )
    )
    clips = await provider.get_clips("p1")
    assert len(clips) == 1
    assert clips[0].external_id == "c1"
    assert clips[0].media_url is None


@respx.mock
async def test_opus_collection_export_recovers_membership(monkeypatch):
    import asyncio

    from clipbot.integrations.clipping import Candidate

    async def no_wait(_):
        pass

    monkeypatch.setattr(asyncio, "sleep", no_wait)
    provider = OpusProvider(Settings(opus_api_key="test", _env_file=None))
    respx.get(provider.base + "/collections").mock(
        return_value=httpx.Response(
            200, json={"data": {"list": [{"collectionId": "col", "collectionName": "ClipBot export p"}]}}
        )
    )
    add = respx.post(provider.base + "/collection-contents").mock(return_value=httpx.Response(200, json={}))
    respx.post(provider.base + "/collections/col/export").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "contentList": [{"contentId": "p.c", "uriForExport": "https://example.com/export.mp4"}]
                }
            },
        )
    )
    state = {}
    saved = []
    clips = await provider.export_clips(
        [Candidate("p.c", "title", "text", 30)], state, lambda s: saved.append(dict(s)), "p"
    )
    assert clips[0].media_url == "https://example.com/export.mp4"
    assert not add.called
    assert state["added"] == ["p.c"]
    assert saved


@respx.mock
async def test_opus_preview_fallback_is_explicit(monkeypatch):
    import asyncio

    from clipbot.integrations.clipping import Candidate

    async def no_wait(_):
        pass

    monkeypatch.setattr(asyncio, "sleep", no_wait)
    provider = OpusProvider(Settings(opus_api_key="test", _env_file=None))
    respx.post(provider.base + "/collections/col/export").mock(
        return_value=httpx.Response(
            200, json={"data": {"contentList": [{"contentId": "p.c", "uriForExport": ""}]}}
        )
    )
    clips = await provider.export_clips(
        [Candidate("p.c", "title", "text", 30, preview_url="https://example.com/preview.mp4")],
        {"collection_id": "col", "added": ["p.c"]},
        lambda s: None,
        "p",
    )
    assert clips[0].media_variant == "opus_preview"
    assert clips[0].media_url == "https://example.com/preview.mp4"
