"""Where each recently added video is in the pipeline, for the dashboard's progress card."""

from datetime import timedelta

from sqlalchemy import func, or_, select

from .config import get_settings
from .models import Clip, ClipScore, ProviderProject, SourceVideo, SystemJob, now
from .monitoring import youtube_id

ENGINE_NAMES = {"vizard": "Vizard", "opus": "OpusClip"}
PROBLEMS = {"blocked", "dead_letter", "needs_reconciliation"}
SHOW_FINISHED_FOR = timedelta(hours=24)


def iso(value):
    return value.isoformat() + "Z" if value else None


def stage_of(video, projects):
    if video.status == "complete":
        return "done"
    if projects and all(p.status == "failed" for p in projects):
        return "failed"
    if not projects or any(p.status in {"pending", "submitting"} for p in projects):
        return "sending"
    if any(p.status not in {"complete", "failed"} for p in projects):
        return "clipping"
    return "scoring"


def latest_problem(jobs):
    stuck = [j for j in jobs if j.status in PROBLEMS and j.error]
    return max(stuck, key=lambda j: j.created_at).error if stuck else None


def video_progress(db, demo, limit=5):
    cfg = get_settings()
    opus_webhook = bool(cfg.public_api_base_url and cfg.opus_webhook_secret)
    rows = []
    videos = db.scalars(
        select(SourceVideo)
        .where(SourceVideo.demo == demo)
        .order_by(SourceVideo.created_at.desc())
        .limit(limit)
    )
    for video in videos:
        projects = list(
            db.scalars(select(ProviderProject).where(ProviderProject.source_video_id == video.id))
        )
        jobs = list(
            db.scalars(
                select(SystemJob).where(
                    or_(
                        SystemJob.payload["source_video_id"].as_string() == video.id,
                        SystemJob.payload["project_id"].as_string().in_([p.id for p in projects]),
                    )
                )
            )
        )
        finalize = next((j for j in jobs if j.kind == "finalize"), None)
        finished_at = finalize.completed_at if finalize and video.status == "complete" else None
        if video.status == "complete" and now() - (finished_at or video.created_at) > SHOW_FINISHED_FOR:
            continue
        clips = dict(
            db.execute(
                select(Clip.status, func.count())
                .where(Clip.source_video_id == video.id)
                .group_by(Clip.status)
            ).all()
        )
        scored = db.scalar(
            select(func.count())
            .select_from(ClipScore)
            .join(Clip, Clip.id == ClipScore.clip_id)
            .where(Clip.source_video_id == video.id)
        )
        per_engine = dict(
            db.execute(
                select(Clip.provider_project_id, func.count())
                .where(Clip.source_video_id == video.id)
                .group_by(Clip.provider_project_id)
            ).all()
        )
        engines = []
        for project in sorted(projects, key=lambda p: p.provider):
            problem = None
            if project.status != "complete":
                own_jobs = [j for j in jobs if j.payload.get("project_id") == project.id]
                problem = latest_problem(own_jobs) or (project.error if project.status == "failed" else None)
            confirmed = bool(project.detail.get("completion_confirmed"))
            engines.append(
                {
                    "provider": project.provider,
                    "name": ENGINE_NAMES.get(project.provider, project.provider),
                    "project_id": project.id,
                    "external_id": project.external_id,
                    "status": project.status,
                    "problem": problem,
                    "clips": per_engine.get(project.id, 0),
                    # Importing clips after the owner confirmed OpusClip finished.
                    "confirmed": confirmed and project.status == "processing",
                    # OpusClip has no status API; without its webhook, the owner confirms completion.
                    "needs_confirmation": project.provider == "opus"
                    and project.status == "processing"
                    and bool(project.external_id)
                    and not confirmed
                    and not opus_webhook,
                }
            )
        video_id = youtube_id(video.url)
        rows.append(
            {
                "id": video.id,
                "title": video.title,
                "url": video.url,
                "thumbnail": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg" if video_id else "",
                "duration": video.duration,
                "added_at": iso(video.created_at),
                "finished_at": iso(finished_at),
                "stage": stage_of(video, projects),
                # Problems before any engine started (e.g. the video couldn't be found).
                "problem": latest_problem([j for j in jobs if j.kind in {"prepare", "finalize"}]),
                "engines": engines,
                # Video files download after scoring; a clip can only be posted once its file is saved.
                "files": {
                    "saved": db.scalar(
                        select(func.count())
                        .select_from(Clip)
                        .where(Clip.source_video_id == video.id, Clip.storage_key.is_not(None))
                    ),
                    "pending": sum(
                        j.kind == "download" and j.status in {"queued", "running", "retry"} for j in jobs
                    ),
                    "problem": latest_problem([j for j in jobs if j.kind == "download"]),
                },
                "clips": {
                    "found": sum(clips.values()),
                    "scored": scored,
                    "scoring": clips.get("candidate", 0) + clips.get("analyzing", 0),
                    "approved": clips.get("approved", 0),
                    "review": clips.get("reserve", 0),
                    "rejected": clips.get("rejected", 0),
                },
            }
        )
    return rows
