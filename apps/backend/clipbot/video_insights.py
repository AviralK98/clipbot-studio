"""Per-video YouTube analysis for the AI insights page.

Reads the channel owner's own YouTube Analytics reports for videos ClipBot published.
YouTube refreshes those reports roughly daily and 1-2 days behind, so results are cached
for a few minutes instead of being re-requested on every page render.
"""

import asyncio
import re
import statistics
import time
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select

from .ai import clean_transcript
from .config import get_settings
from .errors import Blocked
from .integrations.social import YouTubeProvider, google_error
from .models import AnalyticsSnapshot, Clip, PublishedPost, now

REPORTS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
# "day" covers yesterday and today: YouTube rarely has today's numbers yet.
PERIOD_DAYS = {"day": 2, "week": 7, "month": 30, "year": 365}
CACHE_SECONDS = 15 * 60
LAG_NOTE = (
    "YouTube Analytics runs 1-2 days behind and uses US Pacific-time days; "
    "live view counts come straight from YouTube."
)
SUMMARY_METRICS = (
    "views,engagedViews,averageViewDuration,averageViewPercentage,likes,comments,shares,subscribersGained"
)
TOP_METRICS = "views,engagedViews,averageViewPercentage,averageViewDuration,likes,shares,subscribersGained"
TRAFFIC_LABELS = {
    "SHORTS": "Shorts feed",
    "YT_SEARCH": "YouTube search",
    "YT_OTHER_PAGE": "Other YouTube pages",
    "RELATED_VIDEO": "Suggested videos",
    "SUBSCRIBER": "Home & subscriptions",
    "YT_CHANNEL": "Your channel page",
    "YT_PLAYLIST_PAGE": "Playlist pages",
    "PLAYLIST": "Playlists",
    "HASHTAGS": "Hashtag pages",
    "SOUND_PAGE": "Sound pages",
    "NOTIFICATION": "Notifications",
    "EXT_URL": "External websites",
    "NO_LINK_EMBEDDED": "Embedded players",
    "NO_LINK_OTHER": "Direct or unknown",
    "VIDEO_REMIXES": "Remixes",
    "END_SCREEN": "End screens",
    "ADVERTISING": "Ads",
}

_cache: dict[tuple, tuple[float, object]] = {}


def _remember(key, value):
    _cache[key] = (time.monotonic(), value)
    return value


def _recall(key, refresh):
    hit = _cache.get(key)
    if hit and not refresh and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    return None


def _require_live():
    if get_settings().demo_mode:
        raise Blocked("Per-video analysis reads live YouTube data, so it is off while DEMO_MODE=true")


def _thumbnail(video_id):
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def _iso(value):
    return value.isoformat() + "Z" if value else None


def _seconds(iso_duration):
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration or "")
    if not match:
        return None
    hours, minutes, secs = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + secs


def published_videos(db):
    """YouTube videos ClipBot published, newest first, with the last view count ClipBot recorded."""
    rows = db.execute(
        select(PublishedPost, Clip)
        .join(Clip, Clip.id == PublishedPost.clip_id)
        .where(PublishedPost.platform == "youtube", PublishedPost.demo == get_settings().demo_mode)
        .order_by(PublishedPost.published_at.desc())
    ).all()
    latest = {}
    for snap in db.scalars(
        select(AnalyticsSnapshot)
        .where(AnalyticsSnapshot.published_post_id.in_([post.id for post, _ in rows]))
        .order_by(AnalyticsSnapshot.created_at)
    ):
        latest[snap.published_post_id] = snap.metrics.get("views")
    return [
        {
            "video_id": post.external_id,
            "title": clip.title,
            "published_at": _iso(post.published_at),
            "clip_id": clip.id,
            "engine": clip.provider,
            "duration": clip.duration,
            "views": latest.get(post.id),
            "url": post.url or f"https://www.youtube.com/shorts/{post.external_id}",
            "thumbnail": _thumbnail(post.external_id),
        }
        for post, clip in rows
    ]


def video_context(db, video_id):
    """Everything ClipBot itself knows about one video, or None if ClipBot did not publish it."""
    videos = published_videos(db)
    video = next((v for v in videos if v["video_id"] == video_id), None)
    if video is None:
        return None
    clip = db.get(Clip, video["clip_id"])
    others = [v["views"] for v in videos if v["video_id"] != video_id and v["views"] is not None]
    opening = " ".join(clean_transcript(clip.transcript).split()[:30])
    return {**video, "opening": opening, "typical_views": statistics.median(others) if others else None}


async def _token(client):
    try:
        return await YouTubeProvider().token(client)
    except Blocked as exc:
        raise Blocked(
            f"Could not sign in to YouTube ({exc}). If the login expired, generate a new "
            "YOUTUBE_REFRESH_TOKEN and restart the backend."
        ) from exc


async def _report(client, token, **params):
    try:
        response = await client.get(
            REPORTS_URL,
            headers={"Authorization": f"Bearer {token}"},
            params={"ids": "channel==MINE", **params},
        )
    except httpx.HTTPError as exc:
        raise Blocked("Could not reach YouTube Analytics; check the connection and try again") from exc
    if response.status_code != 200:
        reason, message = google_error(response)
        if reason == "accessNotConfigured":
            raise Blocked("Turn on the YouTube Analytics API for your Google Cloud project, then try again")
        detail = f" {reason}" if reason else ""
        raise Blocked(
            f"YouTube Analytics refused the request (HTTP {response.status_code}){detail}. {message}"
        )
    data = response.json()
    names = [header["name"] for header in data.get("columnHeaders", [])]
    return [dict(zip(names, row, strict=False)) for row in data.get("rows") or []]


async def _video_details(client, token, ids):
    details = {}
    for start in range(0, len(ids), 50):
        try:
            response = await client.get(
                VIDEOS_URL,
                headers={"Authorization": f"Bearer {token}"},
                params={"part": "snippet,statistics,contentDetails", "id": ",".join(ids[start : start + 50])},
            )
        except httpx.HTTPError as exc:
            raise Blocked("Could not reach YouTube; check the connection and try again") from exc
        if response.status_code != 200:
            reason, message = google_error(response)
            raise Blocked(
                f"YouTube refused the video lookup (HTTP {response.status_code}) {reason}. {message}"
            )
        for item in response.json().get("items", []):
            details[item["id"]] = item
    return details


def _stats(row):
    views = row.get("views") or 0
    engaged = row.get("engagedViews")
    return {
        "views": views,
        "engaged_views": engaged,
        "stayed_rate": engaged / views if views and engaged is not None else None,
        "average_view_percentage": row.get("averageViewPercentage"),
        "average_view_duration": row.get("averageViewDuration"),
        "likes": row.get("likes"),
        "comments": row.get("comments"),
        "shares": row.get("shares"),
        "subscribers_gained": row.get("subscribersGained"),
    }


def _window(days):
    today = now().date()
    return today - timedelta(days=days - 1), today


async def top_videos(published, period, refresh=False, limit=10):
    """Most-viewed videos in a rolling window. `published` is published_videos(db)."""
    _require_live()
    key = ("top", period, limit)
    cached = _recall(key, refresh)
    if cached is not None:
        return cached
    start, end = _window(PERIOD_DAYS[period])
    known = {v["video_id"]: v for v in published}
    async with httpx.AsyncClient(timeout=30) as client:
        token = await _token(client)
        rows = await _report(
            client,
            token,
            startDate=start.isoformat(),
            endDate=end.isoformat(),
            dimensions="video",
            metrics=TOP_METRICS,
            sort="-views",
            maxResults=limit,
        )
        rows = [row for row in rows if row.get("views")]
        details = await _video_details(client, token, [row["video"] for row in rows]) if rows else {}
    videos = []
    for row in rows:
        video_id = row["video"]
        ours = known.get(video_id, {})
        snippet = details.get(video_id, {}).get("snippet", {})
        videos.append(
            {
                "video_id": video_id,
                "title": snippet.get("title") or ours.get("title") or video_id,
                "published_at": snippet.get("publishedAt") or ours.get("published_at"),
                "thumbnail": _thumbnail(video_id),
                "url": ours.get("url") or f"https://www.youtube.com/shorts/{video_id}",
                "published_by_clipbot": video_id in known,
                **_stats(row),
            }
        )
    return _remember(
        key,
        {
            "period": period,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "videos": videos,
            "note": LAG_NOTE,
        },
    )


async def video_analysis(context, refresh=False):
    _require_live()
    video_id = context["video_id"]
    key = ("video", video_id)
    cached = _recall(key, refresh)
    if cached is not None:
        return cached
    # YouTube Analytics days are US Pacific time, which is behind UTC; start a day early so
    # the first hours after posting (still "yesterday" in California) are not cut off.
    start = date.fromisoformat(context["published_at"][:10]) - timedelta(days=1)
    end = now().date()
    window = {
        "startDate": start.isoformat(),
        "endDate": max(start, end).isoformat(),
        "filters": f"video=={video_id}",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        token = await _token(client)
        summary, traffic, daily, countries, retention, details = await asyncio.gather(
            _report(client, token, metrics=SUMMARY_METRICS, **window),
            _report(
                client, token, dimensions="insightTrafficSourceType", metrics="views", sort="-views", **window
            ),
            _report(client, token, dimensions="day", metrics="views,engagedViews", sort="day", **window),
            _report(
                client, token, dimensions="country", metrics="views", sort="-views", maxResults=8, **window
            ),
            _report(
                client,
                token,
                dimensions="elapsedVideoTimeRatio",
                metrics="audienceWatchRatio,relativeRetentionPerformance",
                **window,
            ),
            _video_details(client, token, [video_id]),
        )
    item = details.get(video_id, {})
    duration = _seconds(item.get("contentDetails", {}).get("duration")) or context["duration"] or 0
    live = item.get("statistics", {})
    stats = _stats(summary[0] if summary else {})
    traffic_total = sum(row["views"] for row in traffic) or 0
    result = {
        "video": {
            "video_id": video_id,
            "title": item.get("snippet", {}).get("title") or context["title"],
            "url": context["url"],
            "thumbnail": context["thumbnail"],
            "published_at": context["published_at"],
            "engine": context["engine"],
            "duration": duration,
            "opening": context["opening"],
            # YouTube returns no video record once a video is deleted or taken down.
            "removed": not details,
        },
        "range": {"start": window["startDate"], "end": window["endDate"]},
        "live": {
            key: int(live[key]) if key in live else None for key in ("viewCount", "likeCount", "commentCount")
        },
        "summary": stats,
        "typical_views": context["typical_views"],
        "traffic": [
            {
                "source": row["insightTrafficSourceType"],
                "label": TRAFFIC_LABELS.get(
                    row["insightTrafficSourceType"], row["insightTrafficSourceType"].replace("_", " ").title()
                ),
                "views": row["views"],
                "share": row["views"] / traffic_total if traffic_total else None,
            }
            for row in traffic
            if row["views"]
        ],
        "daily": [
            {"date": row["day"], "views": row["views"], "engaged_views": row.get("engagedViews")}
            for row in daily
        ],
        "countries": [
            {"country": row["country"], "views": row["views"]} for row in countries if row["views"]
        ],
        "retention": [
            {
                "position": row["elapsedVideoTimeRatio"],
                "second": round(row["elapsedVideoTimeRatio"] * duration, 1),
                "watching": row["audienceWatchRatio"],
                "relative": row.get("relativeRetentionPerformance"),
            }
            for row in retention
        ],
        "note": LAG_NOTE,
        "fetched_at": _iso(now()),
    }
    result["observations"] = observations(result)
    return _remember(key, result)


def observations(analysis):
    """Plain-language notes about one video's numbers. Rules, not a language model."""
    stats, notes = analysis["summary"], []
    views = stats["views"]
    if not views:
        return ["YouTube hasn't reported views for this video yet; its analytics run 1-2 days behind."]
    typical = analysis.get("typical_views")
    if typical is not None and views >= 2 * max(typical, 1):
        notes.append(f"{views / max(typical, 1):.0f}x the views of your typical video ({typical:g}).")
    traffic = analysis["traffic"]
    if traffic and traffic[0]["share"]:
        top = traffic[0]
        if top["source"] == "SHORTS" and top["share"] >= 0.6:
            notes.append(
                f"{top['share']:.0%} of views came from the Shorts feed: YouTube chose to show it to people."
            )
        elif top["source"] == "YT_SEARCH" and top["share"] >= 0.5:
            notes.append(
                f"{top['share']:.0%} of views came from YouTube search: people looked for it, "
                "but YouTube didn't push it in the Shorts feed."
            )
        else:
            notes.append(f"Most views came from {top['label'].lower()} ({top['share']:.0%}).")
    daily = analysis["daily"]
    total = sum(row["views"] for row in daily)
    if total and len(daily) >= 3:
        # Best two consecutive reported days: a burst straddles midnight Pacific time.
        best = max(range(len(daily) - 1), key=lambda i: daily[i]["views"] + daily[i + 1]["views"])
        share = (daily[best]["views"] + daily[best + 1]["views"]) / total
        latest = daily[-1]["views"]
        if share >= 0.8 and latest <= 0.05 * total:
            first = date.fromisoformat(daily[best]["date"])
            notes.append(
                f"{share:.0%} of its views came within about a day ({first:%d %b}-"
                f"{first + timedelta(days=1):%d %b}), then it went quiet."
            )
        elif latest >= 0.1 * max(row["views"] for row in daily):
            notes.append("Still picking up views in the latest days YouTube has reported.")
    if stats["stayed_rate"] is not None:
        notes.append(
            f"{stats['stayed_rate']:.0%} of viewers stayed past the first few seconds; the rest swiped away."
        )
    curve = analysis["retention"]
    if len(curve) >= 10:
        step = max(1, len(curve) // 10)
        start, end = max(
            ((i, i + step) for i in range(len(curve) - step)),
            key=lambda pair: curve[pair[0]]["watching"] - curve[pair[1]]["watching"],
        )
        drop = curve[start]["watching"] - curve[end]["watching"]
        if drop > 0.05:
            notes.append(
                f"Biggest drop-off between {curve[start]['second']:.0f}s and {curve[end]['second']:.0f}s: "
                f"{drop:.0%} of viewers left there."
            )
        # No hook note from the curve: Shorts loop, so replays inflate its opening and it can
        # contradict the stayed-past-the-opening rate above, which is the reliable hook signal.
        finish = curve[-1]["watching"]
        notes.append(
            f"{finish:.0%} of viewers were still watching at the end"
            + (" (over 100% means replays)." if finish > 1 else ".")
        )
        relative = [point["relative"] for point in curve if point["relative"] is not None]
        if relative:
            score = statistics.mean(relative)
            verdict = (
                "worse than most"
                if score < 0.4
                else "better than most"
                if score > 0.6
                else "about as well as"
            )
            notes.append(f"Held viewers {verdict} similar Shorts (score {score:.2f}; 0.50 is typical).")
    if stats["subscribers_gained"]:
        count = stats["subscribers_gained"]
        notes.append(f"Brought in {count} new subscriber{'s' if count != 1 else ''}.")
    return notes


# A video counts as "shown in the Shorts feed" once the feed sent it this many views.
FEED_TESTED_VIEWS = 20


def _ordinal(n):
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


async def compare_videos(published, refresh=False):
    """Every published video side by side, including where its views came from."""
    _require_live()
    key = ("compare",)
    cached = _recall(key, refresh)
    if cached is not None:
        return cached
    end = now().date()
    # A day early for YouTube's US Pacific-time reporting days (see video_analysis).
    first_day = min((date.fromisoformat(v["published_at"][:10]) for v in published), default=end)
    window = {"startDate": (first_day - timedelta(days=1)).isoformat(), "endDate": end.isoformat()}
    async with httpx.AsyncClient(timeout=30) as client:
        token = await _token(client)
        totals = {
            row["video"]: row
            for row in await _report(
                client,
                token,
                dimensions="video",
                metrics="views,engagedViews,averageViewPercentage",
                sort="-views",
                maxResults=200,
                **window,
            )
        }
        # YouTube only breaks traffic sources down one video at a time.
        limit = asyncio.Semaphore(5)

        async def sources(video_id):
            async with limit:
                rows = await _report(
                    client,
                    token,
                    dimensions="insightTrafficSourceType",
                    metrics="views",
                    filters=f"video=={video_id}",
                    **window,
                )
            return video_id, {row["insightTrafficSourceType"]: row["views"] for row in rows}

        traffic = dict(await asyncio.gather(*(sources(v) for v, row in totals.items() if row.get("views"))))
    zone = ZoneInfo(get_settings().timezone)

    def posted_day(video):
        return datetime.fromisoformat(video["published_at"][:-1]).replace(tzinfo=UTC).astimezone(zone).date()

    per_day = Counter(posted_day(v) for v in published)
    order = {v["video_id"]: i + 1 for i, v in enumerate(sorted(published, key=lambda v: v["published_at"]))}
    videos = []
    for video in published:
        row = totals.get(video["video_id"], {})
        by_source = traffic.get(video["video_id"], {})
        views = row.get("views") or 0
        feed, search = by_source.get("SHORTS", 0), by_source.get("YT_SEARCH", 0)
        videos.append(
            {
                "video_id": video["video_id"],
                "title": video["title"],
                "thumbnail": video["thumbnail"],
                "url": video["url"],
                "published_at": video["published_at"],
                "engine": video["engine"],
                "duration": video["duration"],
                "views": views,
                "feed_views": feed,
                "search_views": search,
                "other_views": max(0, sum(by_source.values()) - feed - search),
                "stayed_rate": _stats(row)["stayed_rate"] if views else None,
                "average_view_percentage": row.get("averageViewPercentage") if views else None,
                "posted_day": posted_day(video).isoformat(),
                "posted_same_day": per_day[posted_day(video)],
                "upload_number": order[video["video_id"]],
                "feed_tested": feed >= FEED_TESTED_VIEWS,
            }
        )
    videos.sort(key=lambda v: (-v["views"], v["upload_number"]))
    return _remember(
        key,
        {
            "start": window["startDate"],
            "end": window["endDate"],
            "videos": videos,
            "findings": comparison_findings(videos),
            "note": LAG_NOTE,
        },
    )


def comparison_findings(videos):
    """Plain-language answer to "why did some videos get views and others not?". Rules, not a model."""
    total = sum(v["views"] for v in videos)
    if not total:
        return ["YouTube hasn't reported views for your videos yet; its analytics run 1-2 days behind."]
    notes = []
    tested = [v for v in videos if v["feed_tested"]]
    others = [v for v in videos if not v["feed_tested"] and v["views"]]
    if not tested:
        notes.append(
            f"None of your {len(videos)} videos has been shown in the Shorts feed yet, so all "
            f"{total:,} views came from search and other pages."
        )
    else:
        share = sum(v["views"] for v in tested) / total
        which = f"“{tested[0]['title']}”" if len(tested) == 1 else f"{len(tested)} of them"
        notes.append(
            f"Only {len(tested)} of your {len(videos)} videos {'was' if len(tested) == 1 else 'were'} "
            f"shown in the Shorts feed ({which}), and that brought in {share:.0%} of all your views. "
            "That is the main difference: YouTube showed it to people who don't follow you and didn't do "
            "the same for the rest."
        )
        tested_stay = [v["stayed_rate"] for v in tested if v["stayed_rate"] is not None]
        other_stay = [v["stayed_rate"] for v in others if v["stayed_rate"] is not None]
        if tested_stay and other_stay:
            mine, theirs = statistics.median(tested_stay), statistics.median(other_stay)
            if mine - theirs >= 0.1:
                notes.append(
                    f"Viewers did react better to it: {mine:.0%} stayed past the opening, against "
                    f"{theirs:.0%} for your other videos."
                )
            else:
                notes.append(
                    f"Viewers didn't react better to it: {mine:.0%} stayed past the opening, "
                    f"{'about the same as' if abs(mine - theirs) < 0.1 else 'fewer than'} your other videos "
                    f"({theirs:.0%}). So the gap is about who YouTube showed it to, not how good it was."
                )
        for video in tested:
            if video["upload_number"] <= 3:
                notes.append(
                    f"“{video['title']}” was the {_ordinal(video['upload_number'])} video you ever posted."
                )
    busy = sorted(
        {(v["posted_day"], v["posted_same_day"]) for v in videos if v["posted_same_day"] >= 5},
    )
    if busy:
        days = ", ".join(f"{count} on {date.fromisoformat(day):%a %d %b}" for day, count in busy)
        busy_days = {day for day, _ in busy}
        busy_videos = [v for v in videos if v["posted_day"] in busy_days]
        shown = sum(v["feed_tested"] for v in busy_videos)
        notes.append(
            f"You posted in big batches ({days}). Of those {len(busy_videos)} videos, "
            f"{shown} {'was' if shown == 1 else 'were'} shown in the Shorts feed."
        )
    searched = [v for v in videos if v["views"] >= 5 and v["search_views"] >= 0.5 * v["views"]]
    if searched:
        top = max(searched, key=lambda v: v["search_views"])
        notes.append(
            f"{len(searched)} video{'s' if len(searched) != 1 else ''} got most views from YouTube search, "
            f"led by “{top['title']}” ({top['search_views']} of {top['views']}): people searched for "
            "what's in the title."
        )
    if len(tested) < 3:
        notes.append(
            "With so few videos shown in the feed, there isn't enough evidence yet to say what makes YouTube "
            "pick one clip over another. This gets clearer as more of your videos get a feed test."
        )
    return notes
