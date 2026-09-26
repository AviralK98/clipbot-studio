import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from ..config import Settings, get_settings
from ..errors import Blocked, Transient
from .http import request_json


@dataclass
class Candidate:
    external_id: str
    title: str
    transcript: str
    duration: float
    media_url: str | None = None
    provider_score: float | None = None
    ranges: list = field(default_factory=list)
    preview_url: str | None = None
    media_variant: str = "export"


class ClippingProvider(ABC):
    @abstractmethod
    async def submit_video(
        self, url: str, title: str, duration: float, callback: str = "", preferences: dict | None = None
    ) -> str: ...

    @abstractmethod
    async def get_status(self, project_id: str) -> str: ...

    @abstractmethod
    async def get_clips(self, project_id: str) -> list[Candidate]: ...


# https://docs.vizard.ai/docs/response
VIZARD_CODES = {
    4001: "Vizard rejected the API key; replace VIZARD_API_KEY in .env and restart",
    4002: "Vizard could not create the project",
    4004: "Vizard does not support this video's format",
    4005: "Vizard says the video file is broken",
    4006: "Vizard rejected a request setting",
    4007: "Vizard is out of processing minutes; top up your Vizard plan or wait for it to renew",
    4008: "Vizard could not download the video from its link",
    4009: "Vizard says the video link is invalid",
    4010: "Vizard could not detect the spoken language",
}


class VizardProvider(ClippingProvider):
    base = "https://elb-api.vizard.ai/hvizard-server-front/open-api/v1"

    def __init__(self, settings: Settings | None = None):
        self.cfg = settings or get_settings()
        if not self.cfg.vizard_api_key:
            raise Blocked("Populate VIZARD_API_KEY in .env and restart backend/worker")

    async def _request(self, method, endpoint, **kwargs):
        async with httpx.AsyncClient(timeout=60) as client:
            data = await request_json(
                client,
                method,
                self.base + endpoint,
                headers={"VIZARDAI_API_KEY": self.cfg.vizard_api_key},
                **kwargs,
            )
        code = data.get("code")
        if code == 4003:
            raise Transient("Vizard rate limit", 180)
        if code not in {2000, 1000}:
            reason = VIZARD_CODES.get(code, "Vizard rejected the request; see docs/VIZARD.md")
            raise Blocked(f"{reason} (Vizard code {code})")
        return data

    async def submit_video(self, url, title, duration, callback="", preferences=None):
        host = (urlparse(url).hostname or "").lower()
        video_type = 2 if host in {"youtu.be", "youtube.com", "www.youtube.com", "m.youtube.com"} else 1
        if host == "drive.google.com":
            video_type = 3
        if host in {"dropbox.com", "www.dropbox.com"}:
            video_type = 13
        pref = preferences or {}
        body = {
            "lang": "auto",
            "preferLength": [2],
            "videoUrl": url,
            "videoType": video_type,
            "ratioOfClip": 1,
            "projectName": title,
            "maxClipNumber": 20,
            "clipModel": self.cfg.vizard_model,
            "headlineSwitch": 0,
        }
        if video_type == 1:
            body["ext"] = urlparse(url).path.rsplit(".", 1)[-1].lower()
            if body["ext"] not in {"mp4", "3gp", "avi", "mov"}:
                raise Blocked("Vizard remote files must have a supported video extension")
        if pref.get("topic"):
            body["keywords"] = pref["topic"]
        if pref.get("duration") == "0–20":
            body["preferLength"] = [1]
        data = await self._request("POST", "/project/create", json=body)
        if not data.get("projectId"):
            from ..errors import Ambiguous

            raise Ambiguous("Vizard accepted submission without a project ID; reconcile")
        return str(data["projectId"])

    async def get_status(self, project_id):
        data = await self._request("GET", f"/project/query/{project_id}")
        return "complete" if data["code"] == 2000 else "processing"

    async def get_clips(self, project_id):
        data = await self._request("GET", f"/project/query/{project_id}")
        return [
            Candidate(
                external_id=str(c["videoId"]),
                title=c.get("title", "Untitled clip"),
                transcript=c.get("transcript", ""),
                duration=c["videoMsDuration"] / 1000,
                media_url=c.get("videoUrl"),
                provider_score=float(c["viralScore"]) if c.get("viralScore") else None,
            )
            for c in data.get("videos", [])
        ]


class OpusProvider(ClippingProvider):
    base = "https://api.opus.pro/api"

    def __init__(self, settings: Settings | None = None):
        self.cfg = settings or get_settings()
        if not self.cfg.opus_api_key:
            raise Blocked("Populate OPUS_API_KEY in .env and restart backend/worker")

    async def _request(self, method, endpoint, **kwargs):
        headers = {"Authorization": f"Bearer {self.cfg.opus_api_key}"}
        if self.cfg.opus_org_id:
            headers["x-opus-org-id"] = self.cfg.opus_org_id
        async with httpx.AsyncClient(timeout=60) as client:
            return await request_json(client, method, self.base + endpoint, headers=headers, **kwargs)

    async def submit_video(self, url, title, duration, callback="", preferences=None):
        prefs = preferences or {}
        body = {
            "videoUrl": url,
            "uploadedVideoAttr": {"title": title},
            "curationPref": {"model": self.cfg.opus_model, "clipDurations": [[30, 60]]},
            "renderPref": {"layoutAspectRatio": "portrait"},
        }
        if prefs.get("topic") and self.cfg.opus_model == "ClipBasic":
            body["curationPref"]["topicKeywords"] = [prefs["topic"]]
        if callback:
            body["conclusionActions"] = [{"type": "WEBHOOK", "notifyFailure": False, "url": callback}]
        data = await self._request("POST", "/clip-projects", json=body)
        if not data.get("id"):
            from ..errors import Ambiguous

            raise Ambiguous("Opus accepted submission without an ID; reconcile")
        return data["id"]

    async def get_status(self, project_id):
        # Official API exposes completion callbacks, not a verified project-status GET.
        # Never infer full completion from a partial exportable-clips response.
        return "awaiting_webhook"

    async def export_clips(self, candidates, state, save, project_id):
        """Export existing renders through a durable collection; never re-submit video."""
        missing = [c for c in candidates if not c.media_url]
        if not missing:
            return candidates
        name = "ClipBot export " + project_id
        if not state.get("collection_id"):
            existing = await self._request("GET", "/collections", params={"q": "mine"})
            matches = [c for c in existing.get("data", {}).get("list", []) if c.get("collectionName") == name]
            if matches:
                state["collection_id"] = matches[0]["collectionId"]
            else:
                await asyncio.sleep(2.2)
                created = await self._request("POST", "/collections", json={"collectionName": name})
                state["collection_id"] = created["data"]["collectionId"]
            save(state)
        collection = state["collection_id"]
        added = set(state.get("added", []))
        for clip in missing:
            if clip.external_id in added:
                continue
            await asyncio.sleep(2.2)
            # Membership lookup makes a retry after a lost response safe.
            memberships = await self._request(
                "GET", "/collections", params={"q": "findByContentId", "contentId": clip.external_id}
            )
            if not any(c["collectionId"] == collection for c in memberships.get("data", {}).get("list", [])):
                await asyncio.sleep(2.2)
                await self._request(
                    "POST",
                    "/collection-contents",
                    json={"collectionId": collection, "contentId": clip.external_id},
                )
            added.add(clip.external_id)
            state["added"] = sorted(added)
            save(state)
        await asyncio.sleep(2.2)
        exported = await self._request("POST", f"/collections/{collection}/export", json={})
        urls = {
            c["contentId"]: c.get("uriForExport") for c in exported.get("data", {}).get("contentList", [])
        }
        for clip in missing:
            clip.media_url = urls.get(clip.external_id)
            if not clip.media_url and clip.preview_url:
                clip.media_url = clip.preview_url
                clip.media_variant = "opus_preview"
        if any(not c.media_url for c in candidates):
            raise Transient("Opus export is not ready; retrying the existing collection", 60)
        return candidates

    async def get_clips(self, project_id):
        result = []
        for page in range(1, 101):
            data = await self._request(
                "GET",
                "/exportable-clips",
                params={"q": "findByProjectId", "projectId": project_id, "pageNum": page, "pageSize": 100},
            )
            total = data.get("total") if isinstance(data, dict) else None
            if isinstance(data, dict):
                data = data.get("data")
            if not isinstance(data, list):
                raise Blocked("Unexpected Opus clips response; expected an array or data array")
            for c in data:
                ranges = []
                if self.cfg.opus_time_range_unit in {"seconds", "milliseconds"}:
                    divisor = 1000 if self.cfg.opus_time_range_unit == "milliseconds" else 1
                    ranges = [[a / divisor, b / divisor] for a, b in c.get("timeRanges", [])]
                result.append(
                    Candidate(
                        external_id=c["id"],
                        title=c.get("title", "Untitled clip"),
                        transcript=c.get("text", ""),
                        duration=c["durationMs"] / 1000,
                        media_url=c.get("uriForExport"),
                        preview_url=c.get("uriForPreview"),
                        ranges=ranges,
                    )
                )
            if len(data) < 100 or (isinstance(total, int) and len(result) >= total):
                return result
        raise Blocked("Opus pagination exceeded limit; investigate before importing")


DEMO_TRANSCRIPTS = [
    (
        "The customer conversation that changed everything",
        "We thought our product was the problem. Then we interviewed twenty customers and discovered that nobody understood the first screen. We simplified onboarding to one question. More people finished setup. The lesson is simple: ask what confused them before building another feature.",
    ),
    (
        "A smaller team, a clearer decision",
        "The biggest mistake we made was inviting everyone to every decision. We chose one owner for each product change, wrote down the reason, and reviewed the outcome a week later. Decisions became faster because responsibility was clear.",
    ),
    (
        "Why your best idea needs a bad first draft",
        "A perfect first draft is a trap. I now write the rough version in twenty minutes, then ask a colleague which part is confusing. That question tells me where to spend the next hour. Progress starts when there is something real to improve.",
    ),
    (
        "The meeting nobody needed",
        "We replaced our status meeting with a short written update. Each person shared what changed, what was blocked, and what they needed. We kept a meeting only when there was a decision to make. It gave us time back without losing context.",
    ),
    (
        "An unfinished thought",
        "And so that was what happened next, you know, because of what I said earlier. And then we looked at the other one and...",
    ),
]


class DemoClippingProvider(ClippingProvider):
    def __init__(self, provider):
        self.provider = provider

    async def submit_video(self, url, title, duration, callback="", preferences=None):
        return f"demo-{self.provider}-{abs(sum(map(ord, url)))}"

    async def get_status(self, project_id):
        return "complete"

    async def get_clips(self, project_id):
        picks = [0, 1, 4] if self.provider == "vizard" else [0, 2, 3]
        return [
            Candidate(
                external_id=f"{project_id}-{i}",
                title=DEMO_TRANSCRIPTS[i][0],
                transcript=DEMO_TRANSCRIPTS[i][1],
                duration=35 + i * 3,
                ranges=[[120 + i * 90, 155 + i * 93]],
                provider_score=89 - i * 2,
            )
            for i in picks
        ]


def clipping_provider(name: str, demo: bool = False) -> ClippingProvider:
    if demo:
        if not get_settings().demo_mode:
            raise Blocked("Demo adapters require DEMO_MODE=true")
        return DemoClippingProvider(name)
    if get_settings().demo_mode:
        raise Blocked("Live API calls are disabled while DEMO_MODE=true")
    return {"vizard": VizardProvider, "opus": OpusProvider}[name]()
