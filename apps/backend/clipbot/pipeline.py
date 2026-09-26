from datetime import timedelta

from sqlalchemy import select

from .ai import classify, clean_transcript, llm_provider, prefer_provider_copy, validated_metadata
from .analytics import CHECKPOINTS, learn, normalize, preferences, route
from .budgets import reserve
from .clip_watch import watch
from .config import get_settings
from .db import Session, transaction
from .dedup import duplicate_reason
from .errors import Ambiguous, Blocked, Deferred, Transient
from .integrations.clipping import clipping_provider
from .integrations.social import publishing_provider
from .jobs import enqueue
from .models import (
    AnalyticsSnapshot,
    Clip,
    ClipEmbedding,
    ClipScore,
    ProviderProject,
    PublishedPost,
    ScheduledPost,
    SocialAccount,
    Source,
    SourceVideo,
    SystemState,
    now,
)
from .monitoring import discover, youtube_details, youtube_id
from .scheduling import can_publish, schedule_clip
from .storage import LocalStorage


def ingest(db, source, discovery):
    if source.demo != get_settings().demo_mode:
        raise Blocked("Source does not match the active demo/live environment")
    existing = db.scalar(
        select(SourceVideo).where(
            SourceVideo.source_id == source.id, SourceVideo.external_id == discovery.external_id
        )
    )
    if existing:
        return existing
    if not source.enabled or source.archived:
        raise Blocked("Source is disabled")
    if discovery.duration <= 0:
        raise Blocked("A verified or declared source duration is required for budget checks")
    video = SourceVideo(
        source_id=source.id,
        external_id=discovery.external_id,
        title=discovery.title,
        url=discovery.url,
        duration=discovery.duration,
        demo=source.demo,
    )
    db.add(video)
    db.flush()
    enqueue(db, "prepare", {"source_video_id": video.id}, f"prepare:{video.id}")
    return video


async def prepare(job):
    with Session() as db:
        video = db.get(SourceVideo, job.payload["source_video_id"])
        source = db.get(Source, video.source_id)
    if video.demo != get_settings().demo_mode:
        raise Blocked("Video does not match the active demo/live environment")
    actual = None
    if not video.demo and youtube_id(video.url):
        rows = await youtube_details([youtube_id(video.url)])
        if not rows:
            raise Blocked("YouTube video was not found or has no duration yet")
        actual = rows[0].duration
    with transaction() as db:
        video = db.get(SourceVideo, video.id)
        source = db.get(Source, video.source_id)
        if not source.enabled or source.archived:
            raise Blocked("Source is disabled")
        if actual:
            video.duration = actual
        reserve(
            db, f"minutes:{video.id}", "source", video.duration / 60, "minutes", video.id, demo=video.demo
        )
        for name in route(db, source, video.id):
            project = db.scalar(
                select(ProviderProject).where(
                    ProviderProject.source_video_id == video.id, ProviderProject.provider == name
                )
            )
            if not project:
                project = ProviderProject(source_video_id=video.id, provider=name)
                db.add(project)
                db.flush()
            enqueue(
                db,
                "submit",
                {"project_id": project.id, "provider": name, "source_video_id": video.id},
                f"submit:{project.id}",
            )
        video.status = "processing"


async def submit(job):
    cfg = get_settings()
    with Session() as db:
        project = db.get(ProviderProject, job.payload["project_id"])
        video = db.get(SourceVideo, project.source_video_id)
        source = db.get(Source, video.source_id)
        pref = preferences(db, source) if db.get(SystemState, 1).learning_enabled else {}
    provider = clipping_provider(project.provider, video.demo)
    if not source.enabled or source.archived:
        raise Blocked("Source is disabled")
    with transaction() as db:
        project = db.get(ProviderProject, project.id)
        if project.external_id:
            enqueue(db, "poll", {"project_id": project.id}, f"poll:{project.id}")
            return
        if project.status in {"submitting", "needs_reconciliation"}:
            raise Ambiguous("Provider submission may already exist; attach its external project ID")
        multiplier = 1.25 if project.provider == "vizard" and cfg.vizard_model == "clip_v2" else 1
        credits = video.duration / 60 * multiplier
        rate = cfg.vizard_cost_per_credit if project.provider == "vizard" else cfg.opus_cost_per_credit
        reserve(
            db,
            f"provider:{project.id}",
            project.provider,
            credits,
            "credits",
            video.id,
            cost=credits * rate,
            demo=video.demo,
        )
        project.status = "submitting"
    callback = (
        f"{cfg.public_api_base_url.rstrip('/')}/api/webhooks/opus/{project.id}"
        if cfg.public_api_base_url
        else ""
    )
    try:
        external_id = await provider.submit_video(
            video.url, f"{video.title} [ClipBot {project.id[:8]}]", video.duration, callback, pref
        )
    except Exception as exc:
        with transaction() as db:
            row = db.get(ProviderProject, project.id)
            row.status = (
                "pending"
                if isinstance(exc, (Transient, Blocked)) and not isinstance(exc, Ambiguous)
                else "needs_reconciliation"
            )
            row.error = "Check provider dashboard and job detail"
        raise
    with transaction() as db:
        project = db.get(ProviderProject, project.id)
        project.external_id, project.status, project.error = external_id, "processing", None
        enqueue(
            db,
            "poll",
            {"project_id": project.id, "source_video_id": video.id, "provider": project.provider},
            f"poll:{project.id}",
        )


async def poll(job):
    with Session() as db:
        project = db.get(ProviderProject, job.payload["project_id"])
        video = db.get(SourceVideo, project.source_video_id)
    if project.status == "complete":
        return
    try:
        candidates = await engine_clips(project, video)
    except Blocked as exc:
        # This engine is out for this video; let the other engine's clips finish without it.
        with transaction() as db:
            row = db.get(ProviderProject, project.id)
            row.status, row.error = "failed", str(exc)
            finish_video(db, video.id)
        raise
    with transaction() as db:
        for candidate in candidates:
            exists = db.scalar(
                select(Clip).where(
                    Clip.provider_project_id == project.id, Clip.external_id == candidate.external_id
                )
            )
            if exists:
                if candidate.media_url and not exists.storage_key and not exists.demo:
                    exists.media_url = candidate.media_url
                    exists.metadata_json = {**exists.metadata_json, "media_variant": candidate.media_variant}
                    saving = queue_download(db, exists)
                    if saving.status in {"blocked", "dead_letter", "retry"}:
                        saving.status, saving.error, saving.due_at, saving.attempts = "queued", None, now(), 0
                continue
            if candidate.duration <= 0:
                continue
            ranges = candidate.ranges
            clip = Clip(
                source_video_id=video.id,
                provider_project_id=project.id,
                provider=project.provider,
                external_id=candidate.external_id,
                title=candidate.title,
                transcript=candidate.transcript,
                duration=candidate.duration,
                media_url=candidate.media_url,
                metadata_json={"media_variant": candidate.media_variant},
                provider_score=candidate.provider_score,
                ranges=ranges,
                start_time=min(r[0] for r in ranges) if ranges else None,
                end_time=max(r[1] for r in ranges) if ranges else None,
                demo=video.demo,
            )
            db.add(clip)
            db.flush()
            enqueue(db, "evaluate", {"clip_id": clip.id, "source_video_id": video.id}, f"evaluate:{clip.id}")
            if not clip.demo:
                queue_download(db, clip)
        row = db.get(ProviderProject, project.id)
        row.status, row.error = "complete", None
        finish_video(db, video.id)


async def engine_clips(project, video):
    """Wait for one engine's project to finish, then return its clips (exported, for OpusClip)."""
    if now() - project.created_at > timedelta(hours=12):
        raise Blocked("Provider completion exceeded 12 hours; verify project before retrying")
    provider = clipping_provider(project.provider, video.demo)
    status = await provider.get_status(project.external_id)
    if status != "complete" and not project.detail.get("completion_confirmed"):
        raise Deferred(
            60,
            "Awaiting signed Opus completion callback"
            if project.provider == "opus"
            else "Clipping engine is processing",
        )
    candidates = await provider.get_clips(project.external_id)
    if project.provider == "opus" and not video.demo:
        export_state = dict(project.detail.get("export", {}))

        def save_export(state):
            with transaction() as db:
                row = db.get(ProviderProject, project.id)
                row.detail = {**row.detail, "export": dict(state)}

        candidates = await provider.export_clips(candidates, export_state, save_export, project.external_id)
    return candidates


def queue_download(db, clip):
    """Save the clip's video file after scoring: jobs run oldest-due first, so scores come back
    in seconds while the large files (often ~50 MB each) follow in the background."""
    return enqueue(
        db,
        "download",
        {"clip_id": clip.id, "source_video_id": clip.source_video_id},
        f"download:{clip.id}",
        due_at=now() + timedelta(seconds=5),
    )


async def download(job):
    """YouTube uploads need the file itself, and engine download links expire after seven days."""
    with Session() as db:
        clip = db.get(Clip, job.payload["clip_id"])
    if clip.demo or clip.storage_key:
        return
    if not clip.media_url:
        raise Blocked("The clipping engine hasn't supplied this clip's video file yet")
    key = await LocalStorage().archive(clip.media_url, f"clips/{clip.id}.mp4")
    with transaction() as db:
        db.get(Clip, clip.id).storage_key = key


def finish_video(db, video_id):
    """Queue final selection; reopen it if it already ran without this engine (e.g. a retried poll)."""
    job = enqueue(db, "finalize", {"source_video_id": video_id}, f"finalize:{video_id}")
    if job.status == "done":
        job.status, job.due_at, job.attempts, job.error = "queued", now(), 0, None
        db.get(SourceVideo, video_id).status = "processing"


async def evaluate(job):
    cfg = get_settings()
    with Session() as db:
        clip = db.get(Clip, job.payload["clip_id"])
        previous = db.scalar(select(ClipScore).where(ClipScore.clip_id == clip.id))
    if clip.status in {"approved", "scheduled", "published", "rejected", "reserve"}:
        return
    if not clip.transcript.strip():
        with transaction() as db:
            row = db.get(Clip, clip.id)
            row.status, row.reason = (
                "rejected",
                "Provider returned no transcript; cannot evaluate independently",
            )
        return
    provider = llm_provider(clip.demo)
    local_review = not clip.demo and cfg.llm_provider == "local"
    if not previous:
        with transaction() as db:
            db.get(Clip, clip.id).status = "analyzing"
            reservation = max(
                cfg.ai_call_reservation_usd,
                (16000 * cfg.ai_input_usd_per_million + 3500 * cfg.ai_output_usd_per_million) / 1_000_000,
            )
            usage = reserve(
                db,
                f"judge:{job.id}:{job.attempts}",
                "local" if local_review else "ai",
                1,
                "request",
                clip.source_video_id,
                cost=0 if clip.demo or local_review else reservation,
                demo=clip.demo,
            )
            usage_id = usage.id
        # Strip provider placeholder tokens once, so scoring, copy and hook
        # evidence checks all work on the same spoken text.
        transcript = clean_transcript(clip.transcript)
        result, tokens = await provider.evaluate(transcript)
        with transaction() as db:
            row = db.get(Clip, clip.id)
            state = db.get(SystemState, 1)
            row.overall_score, row.tier, row.policy_flags = classify(
                result, state.thresholds, state.policy_filters
            )
            row.reason, row.topic = result.reason, result.topic[:150]
            row.metadata_json = {**row.metadata_json, **validated_metadata(result, transcript)}
            if row.metadata_json.get("media_variant") == "opus_preview":
                row.reason += " Media is the original Opus preview MP4; branding and quality may differ from a full export. Review before publishing."
                row.tier = "reserve"
                row.metadata_json = {**row.metadata_json, "manual_review_required": True}
            if local_review:
                row.tier = "reserve"
                row.metadata_json = {
                    **row.metadata_json,
                    "review_mode": "local",
                    "manual_review_required": True,
                }
                row.metadata_json = prefer_provider_copy(row.metadata_json, row.title or "")
            row.hook_style = row.metadata_json["hooks"][0]["style"] if row.metadata_json["hooks"] else "story"
            db.add(
                ClipScore(
                    clip_id=clip.id,
                    scores=result.model_dump(),
                    model="demo-fixture"
                    if clip.demo
                    else "local-heuristic-v1"
                    if local_review
                    else cfg.llm_model,
                )
            )
            from .models import APIUsage

            if usage_id:
                db.get(APIUsage, usage_id).actual_tokens = tokens
    with Session() as db:
        embedding = db.scalar(select(ClipEmbedding).where(ClipEmbedding.clip_id == clip.id))
    if not embedding:
        with transaction() as db:
            reserve(
                db,
                f"embed:{job.id}:{job.attempts}",
                "local" if local_review else "ai",
                1,
                "embedding",
                clip.source_video_id,
                cost=0 if clip.demo or local_review else cfg.ai_call_reservation_usd,
                demo=clip.demo,
            )
        vector, model = await provider.embed(clean_transcript(clip.transcript))
        with transaction() as db:
            db.add(ClipEmbedding(clip_id=clip.id, vector=vector, model=model))


async def finalize(job):
    video_id = job.payload["source_video_id"]
    with transaction() as db:
        video = db.get(SourceVideo, video_id)
        projects = list(
            db.scalars(select(ProviderProject).where(ProviderProject.source_video_id == video_id))
        )
        if any(p.status not in {"complete", "failed"} for p in projects):
            raise Deferred(30, "Waiting for both clipping engines before final selection")
        clips = list(
            db.scalars(
                select(Clip)
                .where(Clip.source_video_id == video_id)
                .order_by(Clip.overall_score.desc(), Clip.id)
            )
        )
        embeddings = {e.clip_id: e for e in db.scalars(select(ClipEmbedding))}
        if any(
            c.status not in {"rejected", "failed"} and (c.overall_score is None or c.id not in embeddings)
            for c in clips
        ):
            raise Deferred(30, "Waiting for AI scores and embeddings")
        historic = list(
            db.scalars(
                select(Clip).where(
                    Clip.source_video_id != video_id,
                    Clip.demo == video.demo,
                    Clip.status.in_(["approved", "scheduled", "published"]),
                )
            )
        )
        winners = historic[:]
        state = db.get(SystemState, 1)
        for clip in clips:
            if clip.status in {"scheduled", "published", "rejected", "failed"}:
                continue
            if clip.status in {"approved", "reserve"}:
                # Already decided (by an earlier selection or by hand); keep it and compare against it.
                if clip.status == "approved" or clip.metadata_json.get("review_mode") == "local":
                    winners.append(clip)
                continue
            duplicate = next(
                (
                    (other, reason)
                    for other in winners
                    if (reason := duplicate_reason(clip, other, embeddings))
                ),
                None,
            )
            if duplicate:
                clip.duplicate_of, clip.reason, clip.status = duplicate[0].id, duplicate[1], "rejected"
                continue
            if clip.tier == "rejected":
                clip.status = "rejected"
            elif clip.tier == "reserve" or clip.policy_flags:
                clip.status = "reserve"
            else:
                clip.status = "approved" if state.autopilot or clip.manually_approved else "reserve"
            if clip.status == "approved" or (
                clip.status == "reserve" and clip.metadata_json.get("review_mode") == "local"
            ):
                winners.append(clip)
        video.status = "complete"


async def monitor(job):
    with Session() as db:
        source = db.get(Source, job.payload["source_id"])
    if get_settings().demo_mode or not source or not source.enabled or source.archived or source.demo:
        return
    try:
        items = await discover(source)
        with transaction() as db:
            current = db.get(Source, source.id)
            for item in items:
                ingest(db, current, item)
            current.last_checked_at, current.last_error = now(), None
    except Exception as exc:
        with transaction() as db:
            db.get(Source, source.id).last_error = (
                str(exc) if isinstance(exc, Blocked) else type(exc).__name__
            )
        raise


async def publish(job):
    with transaction() as db:
        post = db.get(ScheduledPost, job.payload["post_id"])
        if post.status in {"published", "cancelled"}:
            return
        if post.scheduled_at > now():
            raise Deferred((post.scheduled_at - now()).total_seconds())
        clip, account, state = (
            db.get(Clip, post.clip_id),
            db.get(SocialAccount, post.account_id),
            db.get(SystemState, 1),
        )
        can_publish(db, clip, account, state)
        # Not a mapped column: a plain read-only convenience attribute so
        # per-account provider IDs (e.g. OpusClip's postAccountId for TikTok)
        # reach PublishingProvider.publish without changing its signature.
        post.account_external_id = account.external_id
        post.status, clip.status = "publishing", "publishing"

    def persist(remote):
        with transaction() as db:
            current = db.get(ScheduledPost, post.id)
            current.remote_state = dict(remote)
            # Recheck the kill switch between resumable upload/container steps.
            can_publish(
                db,
                db.get(Clip, current.clip_id),
                db.get(SocialAccount, current.account_id),
                db.get(SystemState, 1),
            )

    try:
        result = await publishing_provider(post.platform, post.demo).publish(clip, post, persist)
    except Deferred:
        raise
    except Exception as exc:
        with transaction() as db:
            current = db.get(ScheduledPost, post.id)
            current.status = "needs_reconciliation" if isinstance(exc, Ambiguous) else "failed"
            current.error = str(exc) if isinstance(exc, Blocked) else type(exc).__name__
            db.get(Clip, clip.id).status = "scheduled"
        raise
    with transaction() as db:
        current = db.get(ScheduledPost, post.id)
        existing = db.scalar(select(PublishedPost).where(PublishedPost.scheduled_post_id == post.id))
        if not existing:
            publication = PublishedPost(
                scheduled_post_id=post.id,
                clip_id=clip.id,
                platform=post.platform,
                external_id=result.external_id,
                url=result.url,
                demo=post.demo,
            )
            db.add(publication)
            db.flush()
            for hours in CHECKPOINTS:
                enqueue(
                    db,
                    "metrics",
                    {"publication_id": publication.id, "hours": hours},
                    f"metrics:{publication.id}:{hours}",
                    now() + timedelta(hours=hours),
                )
        current.status, current.error = "published", None
        db.get(Clip, clip.id).status = "published"


async def metrics(job):
    with Session() as db:
        publication = db.get(PublishedPost, job.payload["publication_id"])
    hours = job.payload["hours"]
    result = await publishing_provider(publication.platform, publication.demo).metrics(publication)
    age = (now() - publication.published_at).total_seconds() / 3600
    with transaction() as db:
        if not db.scalar(
            select(AnalyticsSnapshot).where(
                AnalyticsSnapshot.published_post_id == publication.id,
                AnalyticsSnapshot.checkpoint_hours == hours,
            )
        ):
            db.add(
                AnalyticsSnapshot(
                    published_post_id=publication.id,
                    checkpoint_hours=hours,
                    metrics=result,
                    normalized=normalize(result, age),
                    provenance="demo_fixture" if publication.demo else "platform_api",
                )
            )


async def strategy(job):
    with transaction() as db:
        learn(db)


def sweep():
    """Idempotent scheduler: SQL outbox commits before dispatch, so Redis loss is recoverable."""
    from .jobs import recover_leases

    recover_leases()
    with transaction() as db:
        state = db.get(SystemState, 1)
        state.last_heartbeat = now()
        bucket = now().strftime("%Y-%m-%d-%H")
        for source in db.scalars(
            select(Source).where(Source.enabled.is_(True), Source.archived.is_(False), Source.demo.is_(False))
        ):
            if source.kind != "manual":
                enqueue(db, "monitor", {"source_id": source.id}, f"monitor:{source.id}:{bucket}")
        if state.autopilot and not state.stop_all_posting and not get_settings().stop_all_posting:
            for clip in db.scalars(
                select(Clip).where(Clip.status == "approved").order_by(Clip.overall_score.desc()).limit(100)
            ):
                for account in db.scalars(
                    select(SocialAccount).where(
                        SocialAccount.enabled.is_(True), SocialAccount.demo == clip.demo
                    )
                ):
                    if account.platform not in clip.metadata_json.get("recommended_platforms", []):
                        continue
                    try:
                        schedule_clip(db, clip.id, account.id)
                    except Blocked:
                        continue
        for post in db.scalars(
            select(ScheduledPost).where(
                ScheduledPost.status.in_(["scheduled", "publishing"]), ScheduledPost.scheduled_at <= now()
            )
        ):
            if not state.stop_all_posting:
                enqueue(
                    db,
                    "publish",
                    {"post_id": post.id, "platform": post.platform, "clip_id": post.clip_id},
                    f"publish:{post.id}",
                )
        enqueue(db, "strategy", {}, f"strategy:{bucket}")


HANDLERS = {
    "prepare": prepare,
    "submit": submit,
    "poll": poll,
    "evaluate": evaluate,
    "download": download,
    "finalize": finalize,
    "monitor": monitor,
    "publish": publish,
    "metrics": metrics,
    "strategy": strategy,
    "watch": watch,
}
