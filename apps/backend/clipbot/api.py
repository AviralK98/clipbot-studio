import hashlib
import hmac
import json
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from .analytics import analytics_report, normalize
from .clip_watch import current_analysis, request_analysis
from .config import get_settings
from .db import Session, initialize, transaction
from .errors import Blocked
from .jobs import enqueue
from .models import (
    AIInsight,
    AnalyticsSnapshot,
    APIUsage,
    Clip,
    ClipScore,
    ProviderProject,
    PublishedPost,
    ScheduledPost,
    SocialAccount,
    Source,
    SourceVideo,
    StrategyMetric,
    SystemJob,
    SystemState,
    User,
    now,
)
from .monitoring import Discovery, youtube_id
from .pipeline import ingest
from .scheduling import can_publish, schedule_clip
from .schemas import (
    AccountInput,
    Login,
    MetricsInput,
    PublicationReconcileInput,
    ReconcileInput,
    ReviewInput,
    ScheduleInput,
    SettingsInput,
    SourceInput,
    VideoInput,
)
from .security import require_auth, signer, verify_password
from .storage import LocalStorage
from .video_insights import (
    compare_videos,
    published_videos,
    top_videos,
    video_analysis,
    video_context,
)

cfg = get_settings()
log = logging.getLogger("clipbot.api")


@asynccontextmanager
async def lifespan(app):
    initialize()
    yield


app = FastAPI(title="ClipBot API", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def request_context(request, call_next):
    request_id = str(uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    log.info(
        json.dumps(
            {
                "event": "request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
            }
        )
    )
    return response


@app.exception_handler(Blocked)
async def blocked_handler(request, exc):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(IntegrityError)
async def integrity_handler(request, exc):
    return JSONResponse(
        status_code=409,
        content={"detail": "This record or scheduled slot already exists. Refresh and try again."},
    )


def dump(row, omit=()):
    if row is None:
        return None
    data = {c.key: getattr(row, c.key) for c in inspect(row).mapper.column_attrs if c.key not in omit}
    for key, value in data.items():
        if hasattr(value, "isoformat"):
            data[key] = value.isoformat() + "Z"
    return data


def get_or_404(db, model, id):
    row = db.get(model, id)
    if row is None:
        raise HTTPException(404, "Record not found")
    return row


@app.get("/health")
def health():
    return {"status": "ok", "service": "clipbot", "version": "0.1.0"}


@app.get("/ready")
def ready():
    try:
        with Session() as db:
            db.execute(text("SELECT 1"))
        if cfg.app_env == "production":
            from redis import Redis

            Redis.from_url(cfg.redis_url, socket_connect_timeout=2).ping()
        return {
            "database": "ready",
            "broker": "checked" if cfg.app_env == "production" else "optional_local_runner",
        }
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready"})


login_attempts = defaultdict(list)


@app.post("/api/auth/login")
def login(payload: Login, request: Request, response: Response):
    if request.headers.get("origin") != cfg.web_origin:
        raise HTTPException(403, "Invalid request origin")
    address = request.client.host if request.client else "local"
    history = [t for t in login_attempts[address] if time.time() - t < 300]
    if len(history) >= 10:
        raise HTTPException(429, "Too many sign-in attempts. Try again in five minutes.")
    login_attempts[address] = history + [time.time()]
    with Session() as db:
        user = db.get(User, "owner")
        if not user or not verify_password(payload.password, user.password_hash):
            raise HTTPException(401, "Incorrect studio password")
    login_attempts.pop(address, None)
    response.set_cookie(
        "clipbot_session",
        signer().dumps(
            {"sub": "owner", "credential": hashlib.sha256(user.password_hash.encode()).hexdigest()}
        ),
        httponly=True,
        secure=cfg.app_env == "production",
        samesite="lax",
        max_age=43200,
        path="/",
    )
    return {"user": "Studio owner", "demo_mode": cfg.demo_mode}


@app.post("/api/auth/logout", dependencies=[Depends(require_auth)])
def logout(response: Response):
    response.delete_cookie("clipbot_session", path="/")
    return {"ok": True}


@app.get("/api/studio", dependencies=[Depends(require_auth)])
def studio():
    with Session() as db:
        state = db.get(SystemState, 1)
        counts = dict(db.execute(select(Clip.status, func.count()).group_by(Clip.status)).all())
        data = analytics_report(db, demo=cfg.demo_mode)
        spend = list(
            db.execute(
                select(APIUsage.provider, func.sum(APIUsage.estimated_cost), func.sum(APIUsage.units))
                .where(
                    APIUsage.created_at >= now().replace(hour=0, minute=0, second=0, microsecond=0),
                    APIUsage.demo == cfg.demo_mode,
                )
                .group_by(APIUsage.provider)
            ).all()
        )
        usage = [{"provider": p, "cost": c, "units": u} for p, c, u in spend]
        return {
            "demo_mode": cfg.demo_mode,
            "settings": dump(state),
            "analytics": data,
            "usage": usage,
            "counts": {
                "sources": db.scalar(
                    select(func.count()).select_from(Source).where(Source.archived.is_(False))
                ),
                "videos": db.scalar(select(func.count()).select_from(SourceVideo)),
                "clips": sum(counts.values()),
                **counts,
            },
            "sources": [
                dump(s)
                for s in db.scalars(
                    select(Source).where(Source.archived.is_(False)).order_by(Source.created_at.desc())
                )
            ],
            "accounts": [dump(a) for a in db.scalars(select(SocialAccount))],
            "jobs": [
                dump(j)
                for j in db.scalars(select(SystemJob).order_by(SystemJob.created_at.desc()).limit(100))
            ],
            "projects": [
                dump(p)
                for p in db.scalars(
                    select(ProviderProject).order_by(ProviderProject.created_at.desc()).limit(100)
                )
            ],
            "insights": [
                dump(i) for i in db.scalars(select(AIInsight).order_by(AIInsight.created_at.desc()))
            ],
            "strategy": [dump(m) for m in db.scalars(select(StrategyMetric))],
            "limits": {
                "source_minutes": cfg.max_source_minutes_per_day,
                "clips": cfg.max_clips_per_day,
                "vizard_credits": cfg.max_vizard_credits_per_day,
                "opus_credits": cfg.max_opus_credits_per_day,
                "ai_cost": cfg.max_ai_cost_per_day,
            },
            "integrations": [
                {
                    "id": "vizard",
                    "configured": bool(cfg.vizard_api_key),
                    "variables": ["VIZARD_API_KEY"],
                    "detail": "Submit, poll and archive clips",
                },
                {
                    "id": "opus",
                    "configured": bool(cfg.opus_api_key),
                    "variables": ["OPUS_API_KEY", "OPUS_WEBHOOK_SECRET", "PUBLIC_API_BASE_URL"],
                    "detail": "Signed completion webhook required for autonomous finalization",
                },
                {
                    "id": "ai",
                    "configured": cfg.llm_provider == "local"
                    or (
                        bool(cfg.openai_api_key)
                        and (cfg.llm_provider == "openai" or bool(cfg.anthropic_api_key))
                    ),
                    "variables": []
                    if cfg.llm_provider == "local"
                    else (
                        ["OPENAI_API_KEY", "LLM_MODEL"]
                        if cfg.llm_provider == "openai"
                        else ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LLM_MODEL"]
                    ),
                    "detail": "Free local review: transcript ranking, extracted captions and wording comparison. No AI keys needed; approve clips manually."
                    if cfg.llm_provider == "local"
                    else "Paid AI review and semantic embeddings",
                },
                {
                    "id": "youtube",
                    "configured": all(
                        [cfg.youtube_client_id, cfg.youtube_client_secret, cfg.youtube_refresh_token]
                    ),
                    "variables": [
                        "YOUTUBE_CLIENT_ID",
                        "YOUTUBE_CLIENT_SECRET",
                        "YOUTUBE_REFRESH_TOKEN",
                        "YOUTUBE_DATA_API_KEY",
                    ],
                    "detail": "Resumable upload; private until your API project is audited",
                },
                {
                    "id": "instagram",
                    "configured": bool(cfg.instagram_access_token and cfg.instagram_user_id),
                    "variables": ["INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_USER_ID", "PUBLIC_MEDIA_BASE_URL"],
                    "detail": "Professional account, Facebook Login / Page token",
                },
                {
                    "id": "tiktok",
                    "configured": False,
                    "variables": [],
                    "detail": "Export handoff. Direct Post excludes personal account utilities.",
                },
            ],
        }


@app.get("/api/insights/videos", dependencies=[Depends(require_auth)])
def insight_videos():
    with Session() as db:
        return {"videos": published_videos(db)}


@app.get("/api/insights/top", dependencies=[Depends(require_auth)])
async def insight_top(period: str = Query("week", pattern="^(day|week|month|year)$"), refresh: bool = False):
    with Session() as db:
        published = published_videos(db)
    return await top_videos(published, period, refresh)


@app.get("/api/insights/compare", dependencies=[Depends(require_auth)])
async def insight_compare(refresh: bool = False):
    with Session() as db:
        published = published_videos(db)
    return await compare_videos(published, refresh)


@app.get("/api/insights/videos/{video_id}", dependencies=[Depends(require_auth)])
async def insight_video(video_id: str, refresh: bool = False):
    with Session() as db:
        context = video_context(db, video_id)
    if context is None:
        raise HTTPException(404, "ClipBot did not publish this YouTube video")
    return await video_analysis(context, refresh)


@app.get("/api/insights/videos/{video_id}/watch", dependencies=[Depends(require_auth)])
def insight_watch(video_id: str):
    with Session() as db:
        return current_analysis(db, video_id)


@app.post("/api/insights/videos/{video_id}/watch", dependencies=[Depends(require_auth)])
def insight_watch_start(video_id: str):
    with transaction() as db:
        state = request_analysis(db, video_id)
    if state is None:
        raise HTTPException(404, "ClipBot did not publish this YouTube video")
    return state


@app.get("/api/clips", dependencies=[Depends(require_auth)])
def clips(
    q: str = "",
    status: str = "all",
    provider: str = "all",
    offset: int = Query(0, ge=0),
    limit: int = Query(24, ge=1, le=100),
):
    with Session() as db:
        query = select(Clip)
        if status != "all":
            query = query.where(Clip.status == status)
        if provider != "all":
            query = query.where(Clip.provider == provider)
        if q:
            query = query.where(Clip.title.ilike(f"%{q[:200]}%") | Clip.topic.ilike(f"%{q[:200]}%"))
        count = db.scalar(select(func.count()).select_from(query.subquery()))
        values = []
        for clip in db.scalars(
            query.order_by(Clip.overall_score.desc().nullslast(), Clip.created_at.desc())
            .offset(offset)
            .limit(limit)
        ):
            item = dump(clip, ("media_url",))
            video = db.get(SourceVideo, clip.source_video_id)
            item["source"] = db.get(Source, video.source_id).name
            values.append(item)
        return {"items": values, "total": count, "offset": offset, "limit": limit}


class BulkClipsInput(BaseModel):
    clip_ids: list[str] = Field(min_length=1, max_length=500)
    account_id: str | None = None


@app.get("/api/clips/bulk-preview", dependencies=[Depends(require_auth)])
def bulk_preview(provider: str = "all", q: str = ""):
    with Session() as db:
        rows = list(db.scalars(select(Clip).where(Clip.demo == cfg.demo_mode)))
        rows = [
            c
            for c in rows
            if (provider == "all" or c.provider == provider)
            and (not q or q.lower() in c.title.lower() or q.lower() in c.topic.lower())
            and not c.duplicate_of
            and c.overall_score is not None
            and db.get(SourceVideo, c.source_video_id).status == "complete"
        ]
        return {
            "approve": [c.id for c in rows if c.status == "reserve" and not c.policy_flags],
            "upload": [c.id for c in rows if c.status == "approved"],
            "privacy": cfg.youtube_privacy,
        }


@app.post("/api/clips/bulk-approve", dependencies=[Depends(require_auth)])
def bulk_approve(payload: BulkClipsInput):
    changed, skipped = [], []
    with transaction() as db:
        for cid in dict.fromkeys(payload.clip_ids):
            c = db.get(Clip, cid)
            if (
                not c
                or c.demo != cfg.demo_mode
                or c.status != "reserve"
                or c.duplicate_of
                or c.policy_flags
                or c.overall_score is None
                or not c.metadata_json
                or db.get(SourceVideo, c.source_video_id).status != "complete"
            ):
                skipped.append({"id": cid, "reason": "Not eligible; flagged clips need individual review"})
                continue
            c.status, c.manually_approved = "approved", True
            changed.append(cid)
    return {"changed": changed, "skipped": skipped}


@app.post("/api/clips/bulk-upload", dependencies=[Depends(require_auth)])
def bulk_upload(payload: BulkClipsInput):
    from datetime import UTC
    from zoneinfo import ZoneInfo

    changed, skipped = [], []
    with transaction() as db:
        account = get_or_404(db, SocialAccount, payload.account_id)
        state = db.get(SystemState, 1)
        if state.stop_all_posting or cfg.stop_all_posting:
            raise Blocked("All posting is stopped; resume posting in Queue first")
        zone = ZoneInfo(state.timezone)
        today = now().replace(tzinfo=UTC).astimezone(zone).date()
        posts = list(
            db.scalars(
                select(ScheduledPost).where(
                    ScheduledPost.status != "cancelled", ScheduledPost.demo == cfg.demo_mode
                )
            )
        )
        todays = [p for p in posts if p.scheduled_at.replace(tzinfo=UTC).astimezone(zone).date() == today]
        capacity = min(
            account.daily_limit - sum(p.account_id == account.id for p in todays),
            state.daily_limit - sum(p.platform == account.platform for p in todays),
            cfg.max_clips_per_day - len(todays),
        )
        for cid in dict.fromkeys(payload.clip_ids):
            c = db.get(Clip, cid)
            if not c or c.status != "approved":
                skipped.append({"id": cid, "reason": "Approve this clip first"})
                continue
            existing = db.scalar(
                select(ScheduledPost).where(
                    ScheduledPost.clip_id == cid, ScheduledPost.account_id == account.id
                )
            )
            if existing:
                skipped.append({"id": cid, "reason": "Already queued, published or cancelled; use Queue"})
                continue
            try:
                can_publish(db, c, account, state)
            except Blocked as error:
                skipped.append({"id": cid, "reason": str(error)})
                continue
            if capacity <= 0:
                skipped.append({"id": cid, "reason": "Daily posting limit reached"})
                continue
            # Explicit upload-now action bypasses time slots and spacing, not daily caps.
            post = ScheduledPost(
                clip_id=cid,
                account_id=account.id,
                platform=account.platform,
                scheduled_at=now(),
                demo=c.demo,
                status="scheduled",
            )
            db.add(post)
            db.flush()
            c.status = "scheduled"
            enqueue(
                db,
                "publish",
                {"post_id": post.id, "clip_id": cid, "platform": account.platform},
                f"publish:{post.id}",
            )
            changed.append(cid)
            capacity -= 1
    return {"changed": changed, "skipped": skipped}


@app.get("/api/clips/{clip_id}", dependencies=[Depends(require_auth)])
def clip_detail(clip_id: str):
    with Session() as db:
        clip = get_or_404(db, Clip, clip_id)
        score = db.scalar(select(ClipScore).where(ClipScore.clip_id == clip_id))
        return {
            **dump(clip, ("media_url",)),
            "evaluation": score.scores if score else None,
            "source": db.get(Source, db.get(SourceVideo, clip.source_video_id).source_id).name,
        }


@app.get("/api/clips/{clip_id}/media", dependencies=[Depends(require_auth)])
def clip_media(clip_id: str):
    with Session() as db:
        clip = get_or_404(db, Clip, clip_id)
        if not clip.storage_key:
            raise HTTPException(404, "No archived media; development fixtures have no video")
        file = LocalStorage().path(clip.storage_key)
        if not file.exists():
            raise HTTPException(404, "Media file is missing")
        return FileResponse(file, media_type="video/mp4", filename=f"clipbot-{clip.id}.mp4")


@app.post("/api/clips/{clip_id}/review", dependencies=[Depends(require_auth)])
def review(clip_id: str, payload: ReviewInput):
    with transaction() as db:
        clip = get_or_404(db, Clip, clip_id)
        if clip.status in {"publishing", "published", "scheduled"}:
            raise Blocked("Cancel queued posts before changing this clip; published clips are immutable")
        if payload.action == "approve":
            if db.get(SourceVideo, clip.source_video_id).status != "complete":
                raise Blocked("Wait for both engines and final duplicate selection before approval")
            if clip.duplicate_of:
                raise Blocked("Duplicate clips cannot be approved")
            if clip.overall_score is None or not clip.metadata_json:
                raise Blocked("Finish clip evaluation before approval")
            if clip.policy_flags and not payload.acknowledge_flags:
                raise Blocked("Review and explicitly acknowledge the content flags")
            clip.status, clip.manually_approved = "approved", True
        else:
            clip.status, clip.manually_approved = "rejected", False
        if payload.note:
            clip.reason = payload.note
        return dump(clip, ("media_url",))


@app.post("/api/sources", dependencies=[Depends(require_auth)])
def add_source(payload: SourceInput):
    with transaction() as db:
        source = Source(**payload.model_dump(), demo=cfg.demo_mode)
        db.add(source)
        db.flush()
        return dump(source)


@app.put("/api/sources/{source_id}", dependencies=[Depends(require_auth)])
def edit_source(source_id: str, payload: SourceInput):
    with transaction() as db:
        source = get_or_404(db, Source, source_id)
        for key, value in payload.model_dump().items():
            setattr(source, key, value)
        return dump(source)


@app.delete("/api/sources/{source_id}", dependencies=[Depends(require_auth)])
def delete_source(source_id: str):
    with transaction() as db:
        source = get_or_404(db, Source, source_id)
        source.enabled, source.archived = False, True
        return {"archived": True, "detail": "Authorization history retained for existing publications"}


@app.post("/api/sources/{source_id}/scan", dependencies=[Depends(require_auth)])
def scan(source_id: str):
    with transaction() as db:
        source = get_or_404(db, Source, source_id)
        if source.kind == "manual":
            raise Blocked("Manual sources accept videos through Add video")
        return dump(
            enqueue(
                db, "monitor", {"source_id": source.id}, f"scan:{source.id}:{now().strftime('%Y%m%d%H%M')}"
            )
        )


@app.post("/api/videos", dependencies=[Depends(require_auth)])
def add_video(payload: VideoInput):
    with transaction() as db:
        source = get_or_404(db, Source, payload.source_id)
        identity = youtube_id(payload.url) or hashlib.sha256(payload.url.encode()).hexdigest()
        return dump(ingest(db, source, Discovery(identity, payload.title, payload.url, payload.duration)))


@app.post("/api/accounts", dependencies=[Depends(require_auth)])
def add_account(payload: AccountInput):
    with transaction() as db:
        if db.scalar(
            select(SocialAccount).where(
                SocialAccount.platform == payload.platform, SocialAccount.demo == cfg.demo_mode
            )
        ):
            raise Blocked("A destination for this platform already exists in the active environment")
        account = SocialAccount(**payload.model_dump(), demo=cfg.demo_mode)
        db.add(account)
        db.flush()
        return dump(account)


@app.post("/api/accounts/{account_id}/toggle", dependencies=[Depends(require_auth)])
def toggle_account(account_id: str):
    with transaction() as db:
        account = get_or_404(db, SocialAccount, account_id)
        account.enabled = not account.enabled
        return dump(account)


@app.get("/api/queue", dependencies=[Depends(require_auth)])
def queue():
    with Session() as db:
        values = []
        for post in db.scalars(select(ScheduledPost).order_by(ScheduledPost.scheduled_at.desc()).limit(300)):
            publication = db.scalar(select(PublishedPost).where(PublishedPost.scheduled_post_id == post.id))
            values.append(
                {
                    **dump(post, ("remote_state",)),
                    "title": db.get(Clip, post.clip_id).title,
                    "account": db.get(SocialAccount, post.account_id).name,
                    "publication": dump(publication),
                }
            )
        return values


@app.post("/api/queue", dependencies=[Depends(require_auth)])
def schedule(payload: ScheduleInput):
    with transaction() as db:
        post = schedule_clip(db, payload.clip_id, payload.account_id, payload.scheduled_at, reactivate=True)
        db.flush()
        return dump(post, ("remote_state",))


@app.post("/api/queue/{post_id}/cancel", dependencies=[Depends(require_auth)])
def cancel(post_id: str):
    with transaction() as db:
        post = get_or_404(db, ScheduledPost, post_id)
        if post.status not in {"scheduled", "failed"}:
            raise Blocked("Only unsent posts can be cancelled")
        post.status = "cancelled"
        db.flush()
        if not db.scalar(
            select(ScheduledPost).where(
                ScheduledPost.clip_id == post.clip_id, ScheduledPost.status != "cancelled"
            )
        ):
            db.get(Clip, post.clip_id).status = "approved"
        return {"cancelled": True}


@app.post("/api/queue/{post_id}/reconcile", dependencies=[Depends(require_auth)])
def reconcile_publication(post_id: str, payload: PublicationReconcileInput):
    from .reconciliation import record_publication

    with transaction() as db:
        post = get_or_404(db, ScheduledPost, post_id)
        return dump(record_publication(db, post, payload.external_id, payload.published_at))


@app.patch("/api/settings", dependencies=[Depends(require_auth)])
def settings(payload: SettingsInput):
    with transaction() as db:
        state = db.get(SystemState, 1)
        for key, value in payload.model_dump(exclude_none=True).items():
            setattr(state, key, value)
        return dump(state)


@app.post("/api/jobs/{job_id}/retry", dependencies=[Depends(require_auth)])
def retry(job_id: str):
    with transaction() as db:
        job = get_or_404(db, SystemJob, job_id)
        if job.status == "needs_reconciliation":
            raise Blocked("Reconcile the external project/publication before retrying")
        if job.status not in {"blocked", "dead_letter", "retry"}:
            raise Blocked("This job is already active or completed")
        job.status, job.due_at, job.attempts, job.error = "queued", now(), 0, None
        return dump(job)


@app.post("/api/projects/{project_id}/reconcile", dependencies=[Depends(require_auth)])
def reconcile(project_id: str, payload: ReconcileInput):
    with transaction() as db:
        project = get_or_404(db, ProviderProject, project_id)
        if project.external_id and project.external_id != payload.external_id:
            raise Blocked("An existing external project ID cannot be replaced")
        if project.status == "complete":
            return dump(project)
        project.external_id, project.status, project.error = payload.external_id, "processing", None
        project.detail = {**project.detail, "completion_confirmed": payload.completion_confirmed}
        job = enqueue(db, "poll", {"project_id": project.id}, f"poll:{project.id}")
        job.status, job.due_at = "queued", now()
        submit_job = db.scalar(select(SystemJob).where(SystemJob.idempotency_key == f"submit:{project.id}"))
        if submit_job:
            submit_job.status, submit_job.error = "done", None
        return dump(project)


@app.post("/api/publications/{publication_id}/metrics", dependencies=[Depends(require_auth)])
def attach_metrics(publication_id: str, payload: MetricsInput):
    with transaction() as db:
        publication = get_or_404(db, PublishedPost, publication_id)
        result = payload.model_dump(exclude={"checkpoint_hours"})
        snapshot = db.scalar(
            select(AnalyticsSnapshot).where(
                AnalyticsSnapshot.published_post_id == publication_id,
                AnalyticsSnapshot.checkpoint_hours == payload.checkpoint_hours,
            )
        )
        if snapshot:
            raise Blocked("A snapshot already exists for this checkpoint")
        row = AnalyticsSnapshot(
            published_post_id=publication_id,
            checkpoint_hours=payload.checkpoint_hours,
            metrics=result,
            normalized=normalize(result, (now() - publication.published_at).total_seconds() / 3600),
            provenance="manual_export",
        )
        db.add(row)
        db.flush()
        return dump(row)


@app.post("/api/webhooks/opus/{project_id}")
async def opus_webhook(project_id: str, request: Request):
    secret = cfg.opus_webhook_secret
    if not secret:
        raise HTTPException(503, "OPUS_WEBHOOK_SECRET is not configured")
    body = await request.body()
    if len(body) > 1024 * 1024:
        raise HTTPException(413, "Webhook body too large")
    salt, signature = request.headers.get("x-opus-salt", ""), request.headers.get("x-opus-signature", "")
    try:
        timestamp = int(request.headers.get("x-opus-timestamp", "0"))
    except ValueError:
        raise HTTPException(401, "Invalid timestamp") from None
    expected = hmac.new(secret.encode(), body + salt.encode(), hashlib.sha256).hexdigest()
    if (
        not salt
        or len(salt) > 128
        or abs(time.time() - timestamp) > 300
        or not hmac.compare_digest(expected, signature)
    ):
        raise HTTPException(401, "Invalid Opus signature")
    with transaction() as db:
        replay = db.scalar(select(SystemJob).where(SystemJob.idempotency_key == f"opus-webhook:{salt}"))
        if replay:
            return {"received": True, "duplicate": True}
        project = get_or_404(db, ProviderProject, project_id)
        if project.provider != "opus":
            raise HTTPException(400, "Wrong provider")
        try:
            payload = json.loads(body)
        except ValueError:
            raise HTTPException(400, "Invalid webhook JSON") from None
        external_id = payload.get("projectId") or payload.get("id") if isinstance(payload, dict) else None
        if not external_id or str(external_id) != project.external_id:
            raise HTTPException(
                409,
                "Webhook project ID must match the stored external project; inspect the live callback schema",
            )
        # notifyFailure=false makes this a successful conclusion signal. Fetch clips independently.
        project.detail = {**project.detail, "completion_confirmed": True}
        receipt = enqueue(db, "poll", {"project_id": project.id}, f"opus-webhook:{salt}")
        receipt.status = "done"
        poll_job = enqueue(db, "poll", {"project_id": project.id}, f"poll:{project.id}")
        if poll_job.status != "running":
            poll_job.status, poll_job.due_at = "queued", now()
    return {"received": True}


@app.post("/api/demo/seed", dependencies=[Depends(require_auth)])
def seed_demo():
    if not cfg.demo_mode:
        raise HTTPException(409, "Set DEMO_MODE=true in .env and restart to enable development fixtures")
    from .demo import seed

    with transaction() as db:
        return seed(db)
