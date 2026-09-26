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


# YouTube refuses further uploads once the channel's own daily allowance is used up
# (reason "uploadLimitExceeded"). Retrying sooner cannot succeed, so those jobs wait
# instead of being marked failed and burning the whole batch in one pass.
DEFERRABLE_UPLOAD_REASONS = frozenset(
    {"uploadLimitExceeded", "rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"}
)
UPLOAD_ALLOWANCE_RETRY_SECONDS = 6 * 3600


def google_error(response: httpx.Response) -> tuple[str, str]:
    """Return the (reason, message) Google reported, or empty strings when absent."""
    try:
        error = response.json().get("error")
    except ValueError:
        return "", ""
    if not isinstance(error, dict):
        return "", ""
    details = error.get("errors") or [{}]
    first = details[0] if isinstance(details[0], dict) else {}
    return str(first.get("reason") or ""), str(error.get("message") or "")[:200]


def upload_rejection(action: str, response: httpx.Response) -> Blocked | Deferred:
    """Defer when the upload allowance is exhausted; otherwise report Google's reason."""
    reason, message = google_error(response)
    if reason in DEFERRABLE_UPLOAD_REASONS:
        return Deferred(
            UPLOAD_ALLOWANCE_RETRY_SECONDS,
            f"YouTube upload allowance exhausted ({reason}); waiting before retrying. {message}",
        )
    detail = f" {reason}" if reason else ""
    detail += f": {message}" if message else ""
    return Blocked(f"YouTube {action} (HTTP {response.status_code}){detail}")


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
        try:
            response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": self.cfg.youtube_client_id,
                    "client_secret": self.cfg.youtube_client_secret,
                    "refresh_token": self.cfg.youtube_refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        except httpx.TransportError as exc:
            raise Transient("Could not reach Google to sign in to YouTube") from exc
        if response.status_code == 200:
            return response.json()["access_token"]
        try:
            reason = str(response.json().get("error") or "")
        except ValueError:
            reason = ""
        if reason == "invalid_grant":
            # The saved login expired (7 days while the OAuth app is in Testing) or was revoked.
            # Wait rather than fail, so uploads and view checks resume once it is renewed.
            raise Deferred(
                3600,
                "YouTube login expired or was revoked: reconnect it in ClipBot (Connections, then "
                "Connect YouTube). Retrying hourly.",
            )
        detail = f": {reason}" if reason else ""
        raise Blocked(
            f"Google refused the YouTube sign-in (HTTP {response.status_code}{detail}); "
            "check YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET"
        )

    async def publish(self, clip, post, persist):
        from ..storage import LocalStorage, is_video_file

        file = LocalStorage().path(clip.storage_key)
        if not is_video_file(file):
            raise Blocked(
                "This clip's video file is damaged (it is not a valid MP4), so ClipBot won't upload it. "
                "Re-download the clip, then retry."
            )
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
                    raise upload_rejection("rejected upload initiation", response)
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
            raise upload_rejection("upload failed", response)

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


def opus_error(response: httpx.Response) -> tuple[str, str]:
    """Return the (errorName, errorMessage) OpusClip reported, or empty strings when absent."""
    try:
        data = response.json()
    except ValueError:
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    return str(data.get("errorName") or ""), str(data.get("errorMessage") or "")[:200]


# Reasons OpusClip has been observed to reject a /post-tasks call with 400 for, that mean
# "nothing was created, try again later" rather than a real problem with the request. Each
# gets its own retry delay - these are different kinds of "later":
#   _ExportNotReadyError (2026-09-21): clip still being prepared for the destination platform;
#       its own message says "try again in a couple of minutes", so retry soon.
#   QuotaExceed (2026-09-22): "Post limit reached for TikTok (15 per 24 hours)." - OpusClip's
#       own per-platform posting quota, separate from ClipBot's daily caps and from TikTok's
#       own account-level limits. Retrying every 6h allows up to 4 attempts within the 24h
#       window without needing a human.
OPUS_DEFERRAL_RETRY_SECONDS: dict[str, int] = {
    "_ExportNotReadyError": 120,
    "QuotaExceed": 6 * 3600,
}


class TikTokProvider(PublishingProvider):
    """Posts via OpusClip's /post-tasks endpoint.

    TikTok's Direct Post API refuses unaudited apps that only post to their own
    owner's accounts (see docs/SOCIAL_APIS.md). OpusClip is a TikTok-approved
    posting partner, so ClipBot hands it the already-clipped video and caption
    instead of talking to TikTok directly. This only works for clips OpusClip
    itself produced (it must already hold the source video); Vizard clips still
    require manual export.
    """

    base = "https://api.opus.pro/api"

    def __init__(self):
        self.cfg = get_settings()
        if not self.cfg.opus_api_key:
            raise Blocked("Populate OPUS_API_KEY in .env and restart backend/worker")

    def _headers(self):
        headers = {"Authorization": f"Bearer {self.cfg.opus_api_key}"}
        if self.cfg.opus_org_id:
            headers["x-opus-org-id"] = self.cfg.opus_org_id
        return headers

    async def publish(self, clip, post, persist):
        if clip.provider != "opus":
            raise Blocked(
                "TikTok publishing is mediated through OpusClip and only works for clips OpusClip "
                "generated (it must already hold the source video). Export this clip for manual posting."
            )
        if not post.account_external_id:
            raise Blocked(
                "This TikTok destination has no OpusClip postAccountId; set external_id on the "
                "social account to the ID returned by GET /api/social-accounts on OpusClip."
            )
        project_id, dot, clip_id = clip.external_id.partition(".")
        if not dot or not project_id or not clip_id:
            raise Blocked(
                f"Unexpected Opus clip id {clip.external_id!r}; expected the composite "
                "'{projectId}.{clipId}' form returned by exportable-clips"
            )
        state = dict(post.remote_state)
        if state.get("publish_attempted"):
            raise Ambiguous("TikTok publication needs reconciliation; check OpusClip before retrying")
        copy = clip.metadata_json["tiktok"]
        state["publish_attempted"] = True
        persist(state)
        body = {
            "projectId": project_id,
            "clipId": clip_id,
            "postAccountId": post.account_external_id,
            "postDetail": {
                "title": copy["title"][:100],
                "mediaType": "video",
                "custom": {
                    # No "privacy" field: OpusClip's docs describe it as a YouTube-specific
                    # public/private/unlisted enum, not TikTok's own privacy levels (SELF_ONLY,
                    # FOLLOWER_OF_CREATOR, MUTUAL_FOLLOW_FRIENDS, PUBLIC_TO_EVERYONE). Sending it
                    # for a TikTok destination is undocumented, so the account's own default
                    # posting privacy (set in TikTok Studio) applies instead.
                    "description": (copy["caption"] + chr(10) + " ".join(copy["hashtags"]))[:2200],
                },
            },
        }
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                response = await client.post(f"{self.base}/post-tasks", headers=self._headers(), json=body)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                state["publish_attempted"] = False
                persist(state)
                raise Transient("Could not connect to OpusClip") from exc
            except httpx.TransportError as exc:
                raise Ambiguous("OpusClip response lost; check its dashboard and reconcile") from exc
        if response.status_code == 400:
            reason, message = opus_error(response)
            if reason in OPUS_DEFERRAL_RETRY_SECONDS:
                state["publish_attempted"] = False
                persist(state)
                raise Deferred(
                    OPUS_DEFERRAL_RETRY_SECONDS[reason],
                    f"OpusClip could not post to TikTok yet ({reason}); retrying automatically. {message}",
                )
        if response.status_code == 429:
            state["publish_attempted"] = False
            persist(state)
            retry = response.headers.get("retry-after", "60")
            raise Transient("OpusClip rate limit", int(retry) if retry.isdigit() else 60)
        if response.status_code >= 500:
            raise Ambiguous("OpusClip returned a server error after submission; reconcile")
        if response.status_code >= 400:
            name, message = opus_error(response)
            detail = f" {name}" if name else ""
            detail += f": {message}" if message else ""
            raise Blocked(f"OpusClip rejected the TikTok post (HTTP {response.status_code}){detail}")
        try:
            data = response.json()
        except ValueError as exc:
            raise Ambiguous(
                "OpusClip accepted the TikTok post but returned an invalid response; reconcile"
            ) from exc
        post_id = data.get("data", {}).get("postId") if isinstance(data, dict) else None
        if not post_id:
            raise Ambiguous("OpusClip accepted the TikTok post without a postId; reconcile")
        return Publication(post_id, None)

    async def metrics(self, publication):
        # OpusClip's own dashboard marks Analytics as "Coming soon" (checked 2026-09-21); there is
        # no documented per-post metrics endpoint yet. Blocked (not Deferred) so this does not
        # retry forever waiting for data that does not exist.
        raise Blocked("OpusClip does not yet expose analytics for TikTok posts; unsupported for now")


def publishing_provider(platform, demo=False):
    if demo:
        if not get_settings().demo_mode:
            raise Blocked("Demo publishing disabled")
        return DemoPublishingProvider()
    if get_settings().demo_mode:
        raise Blocked("Live API calls are disabled while DEMO_MODE=true")
    return {"youtube": YouTubeProvider, "instagram": InstagramProvider, "tiktok": TikTokProvider}[platform]()
