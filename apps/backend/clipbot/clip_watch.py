"""Gemini watches a published Short and explains why it performed the way it did.

The clip file ClipBot already holds is sent inline together with that video's real YouTube
Analytics, so every claim can be tied to a timestamp or a number. It runs as a background job
("watch") because a watch-through takes 10-60 seconds, and the result is saved so each video is
analysed once unless the owner asks again.
"""

import base64
import json
import statistics
from datetime import timedelta

import httpx
from sqlalchemy import select

from .config import get_settings
from .db import Session, transaction
from .errors import Blocked, Transient
from .jobs import enqueue
from .models import Clip, ClipAnalysis, now
from .storage import LocalStorage, is_video_file
from .video_insights import video_analysis, video_context

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Requests are capped at 100 MB and base64 grows the file by a third.
INLINE_LIMIT_BYTES = 70 * 1024 * 1024
BUSY_RETRY_SECONDS = 300
# A queued/running analysis older than this was interrupted (e.g. the worker stopped).
STALE_AFTER = timedelta(minutes=10)

SYSTEM_PROMPT = (
    "You analyse YouTube Shorts for the creator who posted them. You get the video itself and its real "
    "YouTube Analytics. Explain specifically and honestly why it performed the way it did. Ground every "
    "claim in something you can see or hear at a timestamp (MM:SS), or in the numbers given; when you cite "
    "a number, copy it exactly from the data. Never invent numbers. If the result looks driven by YouTube's "
    "distribution or luck rather than the content, say so. The clips are cut automatically from longer "
    "videos by an AI clipping tool, so practical advice is about where a clip should start and end, its "
    "length, captions and on-screen additions. Write for a non-technical creator: plain words, short sentences."
)
TASK = (
    "Real numbers for this Short (still-watching values above 1.0 mean people replayed that part):\n"
    "{numbers}\n\n"
    "Watch the whole video, then: describe the hook in the first ~3 seconds; walk through the key moments, "
    "including every point where the numbers show viewers leaving; explain why it did better or worse than "
    "this creator's typical video; and give concrete changes for their next clips."
)
SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "2-3 sentences: why this Short performed as it did"},
        "hook": {
            "type": "object",
            "properties": {
                "first_seconds": {"type": "string", "description": "What a viewer sees and hears first"},
                "rating": {"type": "string", "enum": ["strong", "mixed", "weak"]},
                "why": {"type": "string"},
            },
            "required": ["first_seconds", "rating", "why"],
        },
        "moments": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "time": {"type": "string", "description": "MM:SS"},
                    "kind": {
                        "type": "string",
                        "enum": ["hook", "payoff", "drop_off", "rewatch", "slow", "other"],
                    },
                    "happening": {"type": "string", "description": "What is on screen and being said"},
                    "effect": {"type": "string", "description": "How viewers reacted, citing the numbers"},
                },
                "required": ["time", "kind", "happening", "effect"],
            },
        },
        "worked": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "hurt": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "next_time": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "luck_vs_content": {
            "type": "string",
            "description": "How much is the content versus YouTube's distribution",
        },
    },
    "required": ["summary", "hook", "moments", "worked", "hurt", "next_time", "luck_vs_content"],
}


def _ready():
    cfg = get_settings()
    if cfg.demo_mode:
        raise Blocked("Clip analysis reads live YouTube data, so it is off while DEMO_MODE=true")
    if not cfg.gemini_api_key:
        raise Blocked(
            "Add GEMINI_API_KEY to .env (free at aistudio.google.com/apikey), then restart the backend and worker"
        )


def _state(row):
    if row is None:
        return {"status": "none"}
    status = row.status
    if status in ("queued", "running") and now() - row.updated_at > STALE_AFTER:
        status = "stalled"
    return {
        "status": status,
        "model": row.model or None,
        "result": row.result or None,
        "error": row.error,
        "updated_at": row.updated_at.isoformat() + "Z",
    }


def current_analysis(db, video_id):
    row = db.scalar(select(ClipAnalysis).where(ClipAnalysis.video_id == video_id))
    return {**_state(row), "configured": bool(get_settings().gemini_api_key)}


def request_analysis(db, video_id):
    """Queue a watch-through (or a fresh one). Returns None if ClipBot did not publish the video."""
    _ready()
    context = video_context(db, video_id)
    if context is None:
        return None
    row = db.scalar(select(ClipAnalysis).where(ClipAnalysis.video_id == video_id))
    if row and row.status in ("queued", "running") and now() - row.updated_at <= STALE_AFTER:
        return {**_state(row), "configured": True}
    if row is None:
        row = ClipAnalysis(video_id=video_id, clip_id=context["clip_id"])
        db.add(row)
    # Any earlier result stays visible while the new analysis runs.
    row.status, row.error, row.updated_at = "queued", None, now()
    db.flush()
    enqueue(db, "watch", {"video_id": video_id}, f"watch:{video_id}:{row.updated_at:%Y%m%d%H%M%S%f}")
    return {**_state(row), "configured": True}


def _rounded(value):
    return round(value, 3) if isinstance(value, float) else value


def numbers_for(stats, context):
    """The YouTube facts Gemini gets alongside the video."""
    summary, retention = stats["summary"], stats["retention"]
    relative = [point["relative"] for point in retention if point["relative"] is not None]
    return {
        "title": stats["video"]["title"],
        "clipped_by": "OpusClip" if context["engine"] == "opus" else "Vizard",
        "length_seconds": stats["video"]["duration"],
        "live_views": stats["live"]["viewCount"],
        "views_in_youtube_analytics": summary["views"],
        "typical_views_of_this_creators_other_videos": context["typical_views"],
        "share_who_stayed_past_the_first_seconds": _rounded(summary["stayed_rate"]),
        "average_percent_of_video_watched": _rounded(summary["average_view_percentage"]),
        "shares": summary["shares"],
        "new_subscribers": summary["subscribers_gained"],
        "where_views_came_from": {row["label"]: _rounded(row["share"]) for row in stats["traffic"]},
        "views_per_day_us_pacific": {row["date"]: row["views"] for row in stats["daily"]},
        "share_still_watching_by_second": {
            f"{point['second']:.0f}s": _rounded(point["watching"]) for point in retention[4::5]
        },
        "retention_vs_similar_shorts_half_is_typical": _rounded(statistics.mean(relative))
        if relative
        else None,
    }


def _google_message(response):
    try:
        return str(response.json().get("error", {}).get("message", ""))[:300]
    except ValueError:
        return ""


def parse_answer(data):
    candidates = data.get("candidates") or []
    if not candidates:
        reason = (data.get("promptFeedback") or {}).get("blockReason") or "no answer"
        raise Blocked(f"Gemini declined to analyse this clip ({reason})")
    candidate = candidates[0]
    if candidate.get("finishReason") not in (None, "STOP"):
        raise Blocked(f"Gemini stopped before finishing ({candidate['finishReason']}); try again")
    text = "".join(
        part.get("text", "")
        for part in candidate.get("content", {}).get("parts", [])
        if not part.get("thought")
    )
    try:
        result = json.loads(text)
    except ValueError as exc:
        raise Blocked("Gemini returned an answer ClipBot could not read; try again") from exc
    missing = [key for key in SCHEMA["required"] if key not in result]
    if missing:
        raise Blocked(f"Gemini's answer was missing {', '.join(missing)}; try again")
    return result


async def ask_gemini(video, numbers):
    """Returns (analysis, model). Tries the fallback model when the main one is overloaded."""
    cfg = get_settings()
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"inlineData": {"mimeType": "video/mp4", "data": base64.b64encode(video).decode()}},
                    {"text": TASK.format(numbers=json.dumps(numbers, indent=1))},
                ],
            }
        ],
        "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": SCHEMA},
    }
    busy = "Gemini is busy"
    async with httpx.AsyncClient(timeout=300) as client:
        for model in dict.fromkeys(m for m in (cfg.gemini_model, cfg.gemini_fallback_model) if m):
            try:
                response = await client.post(
                    GEMINI_URL.format(model=model), headers={"x-goog-api-key": cfg.gemini_api_key}, json=body
                )
            except httpx.HTTPError as exc:
                raise Transient("Could not reach Gemini; ClipBot will retry", 120) from exc
            if response.status_code in (429, 500, 502, 503, 504):
                busy = f"Gemini is busy (HTTP {response.status_code} from {model}); ClipBot will retry"
                continue
            if response.status_code != 200:
                raise Blocked(
                    f"Gemini rejected the request (HTTP {response.status_code}): {_google_message(response)}"
                )
            return parse_answer(response.json()), model
    raise Transient(busy, BUSY_RETRY_SECONDS)


def _save(video_id, **fields):
    with transaction() as db:
        row = db.scalar(select(ClipAnalysis).where(ClipAnalysis.video_id == video_id))
        if row is not None:
            for name, value in fields.items():
                setattr(row, name, value)
            row.updated_at = now()


async def watch(job):
    """Background job: watch one published Short and save Gemini's analysis."""
    video_id = job.payload["video_id"]
    with Session() as db:
        exists = db.scalar(select(ClipAnalysis.id).where(ClipAnalysis.video_id == video_id))
        context = video_context(db, video_id)
        clip = db.get(Clip, context["clip_id"]) if context else None
    if not exists or clip is None:
        raise Blocked("This clip analysis request no longer exists")
    _save(video_id, status="running", error=None)
    try:
        _ready()
        media = LocalStorage().path(clip.storage_key) if clip.storage_key else None
        if media is None or not media.exists():
            raise Blocked("ClipBot no longer has this clip's video file in data/media")
        if not is_video_file(media):
            raise Blocked("This clip's video file is damaged (it is not a valid MP4); re-download the clip")
        if media.stat().st_size > INLINE_LIMIT_BYTES:
            raise Blocked("This clip's video file is too large to send to Gemini")
        try:
            numbers = numbers_for(await video_analysis(context), context)
        except Blocked as exc:
            # Still worth watching the clip itself; Gemini is told the numbers are missing.
            numbers = {"note": f"YouTube numbers are unavailable right now ({exc})"}
        result, model = await ask_gemini(media.read_bytes(), numbers)
    except Transient as exc:
        if job.attempts >= get_settings().max_job_attempts:
            _save(
                video_id,
                status="failed",
                error=f"{exc}. Gave up after {job.attempts} tries; try again later.",
            )
        else:
            _save(video_id, status="queued", error=str(exc))
        raise
    except Blocked as exc:
        _save(video_id, status="failed", error=str(exc))
        raise
    except Exception:
        _save(video_id, status="failed", error="The analysis failed unexpectedly; try again")
        raise
    _save(video_id, status="done", result=result, model=model, error=None)
