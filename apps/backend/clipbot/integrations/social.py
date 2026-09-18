from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from ..config import get_settings
from ..errors import Ambiguous, Blocked, Deferred, Transient
from .http import request_json


@dataclass
class Publication:
    external_id: str
    url: str | None


class PublishingProvider(ABC):
    @abstractmethod
    async def publish(self, clip, post, persist) -> Publication: ...

    @abstractmethod
    async def metrics(self, publication) -> dict: ...


class YouTubeProvider(PublishingProvider):
    def __init__(self):
        self.cfg = get_settings()
        if not all(
            [self.cfg.youtube_client_id, self.cfg.youtube_client_secret, self.cfg.youtube_refresh_token]
        ):
            raise Blocked(
                "Configure YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN in .env"
            )

    async def token(self, client):
        result = await request_json(
            client,
            "POST",
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": self.cfg.youtube_client_id,
                "client_secret": self.cfg.youtube_client_secret,
                "refresh_token": self.cfg.youtube_refresh_token,
                "grant_type": "refresh_token",
            },
        )
        return result["access_token"]

    async def publish(self, clip, post, persist):
        from ..storage import LocalStorage

        file = LocalStorage().path(clip.storage_key)
        size = file.stat().st_size
        state = dict(post.remote_state)
        async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
            auth = {"Authorization": f"Bearer {await self.token(client)}"}
            if not state.get("session_url"):
                if state.get("init_attempted"):
                    raise Ambiguous("YouTube upload initiation needs reconciliation")
                state["init_attempted"] = True
                persist(state)
                copy = clip.metadata_json["youtube"]
                body = {
                    "snippet": {
                        "title": copy["title"][:100],
                        "description": copy["description"] + "\n" + " ".join(copy["hashtags"]),
                        "categoryId": "22",
                    },
                    "status": {"privacyStatus": self.cfg.youtube_privacy},
                }
                try:
                    response = await client.post(
                        "https://www.googleapis.com/upload/youtube/v3/videos",
                        params={"uploadType": "resumable", "part": "snippet,status"},
                        json=body,
                        headers={
                            **auth,
                            "X-Upload-Content-Type": "video/mp4",
                            "X-Upload-Content-Length": str(size),
                        },
                    )
                except httpx.TransportError as exc:
                    raise Ambiguous("YouTube upload initiation response lost; reconcile") from exc
                if response.status_code == 429:
                    state["init_attempted"] = False
                    persist(state)
                    raise Transient("YouTube rate limit")
                if response.status_code >= 500:
                    raise Ambiguous("YouTube upload initiation may have succeeded; reconcile")
                if response.status_code >= 400:
                    state["init_attempted"] = False
                    persist(state)
                    raise Blocked(f"YouTube rejected upload initiation (HTTP {response.status_code})")
                location = response.headers.get("location", "")
                host = urlparse(location).hostname or ""
                if urlparse(location).scheme != "https" or not (
                    host == "googleapis.com" or host.endswith(".googleapis.com")
                ):
                    raise Ambiguous("Unexpected YouTube resumable upload Location; reconcile")
                state["session_url"] = location
                persist(state)
            # Query existing session on every attempt: a lost final response must not create another video.
            response = await client.put(
                state["session_url"],
                headers={**auth, "Content-Length": "0", "Content-Range": f"bytes */{size}"},
                content=b"",
            )
            if response.status_code in {200, 201}:
                result = response.json()
                return Publication(result["id"], f"https://www.youtube.com/shorts/{result['id']}")
            if response.status_code != 308:
                if response.status_code >= 500 or response.status_code == 429:
                    raise Transient("YouTube upload status unavailable")
                raise Ambiguous("YouTube upload session is unavailable; reconcile before restarting")
            offset = (
                int(response.headers.get("range", "bytes=0--1").rsplit("-", 1)[-1]) + 1
                if response.headers.get("range")
                else 0
            )
            with file.open("rb") as stream:
                stream.seek(offset)
                chunk = stream.read(8 * 1024 * 1024)
            if not chunk:
                raise Deferred(30, "Waiting for YouTube upload confirmation")
            end = offset + len(chunk) - 1
            response = await client.put(
                state["session_url"],
                headers={
                    **auth,
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{end}/{size}",
                },
                content=chunk,
            )
            if response.status_code in {200, 201}:
                result = response.json()
                return Publication(result["id"], f"https://www.youtube.com/shorts/{result['id']}")
            if response.status_code == 308:
                raise Deferred(1, "Uploading next YouTube chunk")
            if response.status_code >= 500 or response.status_code == 429:
                raise Transient("YouTube resumable upload paused")
            raise Blocked(f"YouTube upload failed (HTTP {response.status_code})")

    async def metrics(self, publication):
        async with httpx.AsyncClient(timeout=30) as client:
            auth = {"Authorization": f"Bearer {await self.token(client)}"}
            data = await request_json(
                client,
                "GET",
                "https://www.googleapis.com/youtube/v3/videos",
                headers=auth,
                params={"part": "statistics", "id": publication.external_id},
            )
            if not data.get("items"):
                raise Deferred(3600, "YouTube publication metrics not yet available")
            stat = data["items"][0]["statistics"]
            result = {
                "views": int(stat["viewCount"]) if "viewCount" in stat else None,
                "likes": int(stat["likeCount"]) if "likeCount" in stat else None,
                "comments": int(stat["commentCount"]) if "commentCount" in stat else None,
                "shares": None,
                "watch_time_minutes": None,
                "average_watch_percentage": None,
                "followers_gained": None,
            }
            from ..models import now

            # Owner Analytics scopes are optional; missing metrics stay null, never fabricated zero.
            try:
                report = await request_json(
                    client,
                    "GET",
                    "https://youtubeanalytics.googleapis.com/v2/reports",
                    headers=auth,
                    params={
                        "ids": "channel==MINE",
                        "startDate": publication.published_at.date().isoformat(),
                        "endDate": now().date().isoformat(),
                        "filters": f"video=={publication.external_id}",
                        "metrics": "shares,estimatedMinutesWatched,averageViewPercentage,subscribersGained",
                    },
                )
                if report.get("rows"):
                    mapping = {
                        "shares": "shares",
                        "estimatedMinutesWatched": "watch_time_minutes",
                        "averageViewPercentage": "average_watch_percentage",
                        "subscribersGained": "followers_gained",
                    }
                    result.update(
                        {
                            mapping[h["name"]]: v
                            for h, v in zip(report["columnHeaders"], report["rows"][0], strict=True)
                            if h["name"] in mapping
                        }
                    )
            except Blocked:
                result["analytics_note"] = (
                    "Owner Analytics unavailable; grant analytics scopes and allow reporting delay"
                )
            return result


class InstagramProvider(PublishingProvider):
    """Facebook Login / Page token flow, verified against Meta's official Postman collection."""

    def __init__(self):
        self.cfg = get_settings()
        if not self.cfg.instagram_access_token or not self.cfg.instagram_user_id:
            raise Blocked("Configure INSTAGRAM_ACCESS_TOKEN (Page token) and INSTAGRAM_USER_ID")
        self.base = f"https://graph.facebook.com/{self.cfg.instagram_api_version}"

    async def publish(self, clip, post, persist):
        state = dict(post.remote_state)
        if state.get("publish_attempted"):
            raise Ambiguous("Instagram publication needs reconciliation; verify the account before retrying")
        if not self.cfg.public_media_base_url:
            raise Blocked("Instagram needs a publicly reachable PUBLIC_MEDIA_BASE_URL for archived clips")
        headers = {"Authorization": f"Bearer {self.cfg.instagram_access_token}"}
        async with httpx.AsyncClient(timeout=60) as client:
            if not state.get("container_id"):
                if state.get("init_attempted"):
                    raise Ambiguous("Instagram container initiation needs reconciliation")
                state["init_attempted"] = True
                persist(state)
                copy = clip.metadata_json["instagram"]
                try:
                    data = await request_json(
                        client,
                        "POST",
                        f"{self.base}/{self.cfg.instagram_user_id}/media",
                        headers=headers,
                        data={
                            "media_type": "REELS",
                            "video_url": f"{self.cfg.public_media_base_url.rstrip('/')}/{clip.storage_key}",
                            "caption": copy["caption"] + "\n" + " ".join(copy["hashtags"]),
                            "share_to_feed": "true",
                        },
                    )
                except Transient:
                    state["init_attempted"] = False
                    persist(state)
                    raise
                state["container_id"] = data["id"]
                persist(state)
            status = await request_json(
                client,
                "GET",
                f"{self.base}/{state['container_id']}",
                headers=headers,
                params={"fields": "status_code,status"},
            )
            if status["status_code"] in {"ERROR", "EXPIRED"}:
                raise Blocked("Instagram container failed or expired")
            if status["status_code"] != "FINISHED":
                raise Deferred(60, "Instagram is processing the Reel")
            state["publish_attempted"] = True
            persist(state)
            try:
                data = await request_json(
                    client,
                    "POST",
                    f"{self.base}/{self.cfg.instagram_user_id}/media_publish",
                    headers=headers,
                    data={"creation_id": state["container_id"]},
                )
            except Transient:
                state["publish_attempted"] = False
                persist(state)
                raise
            return Publication(data["id"], None)

    async def metrics(self, publication):
        raise Blocked(
            "Instagram insight permissions and metric schema must be validated for your app version. Attach exported analytics in the dashboard."
        )


class TikTokProvider(PublishingProvider):
    async def publish(self, clip, post, persist):
        raise Blocked("TikTok Direct Post excludes private account utilities; use the clip export handoff")

    async def metrics(self, publication):
        raise Blocked("Attach a TikTok analytics export; no unsupported analytics access is attempted")


class DemoPublishingProvider(PublishingProvider):
    async def publish(self, clip, post, persist):
        return Publication(f"demo-{post.id}", None)

    async def metrics(self, publication):
        import hashlib

        sample = int(hashlib.sha256(publication.id.encode()).hexdigest()[:5], 16) % 12000 + 800
        return {
            "views": sample,
            "likes": sample // 20,
            "comments": sample // 150,
            "shares": sample // 95,
            "watch_time_minutes": sample // 3,
            "average_watch_percentage": 72,
            "followers_gained": sample // 450,
        }


def publishing_provider(platform, demo=False):
    if demo:
        if not get_settings().demo_mode:
            raise Blocked("Demo publishing disabled")
        return DemoPublishingProvider()
    if get_settings().demo_mode:
        raise Blocked("Live API calls are disabled while DEMO_MODE=true")
    return {"youtube": YouTubeProvider, "instagram": InstagramProvider, "tiktok": TikTokProvider}[platform]()
