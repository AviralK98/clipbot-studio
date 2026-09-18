from datetime import timedelta

from sqlalchemy import select

from .analytics import CHECKPOINTS
from .errors import Blocked
from .jobs import enqueue
from .models import Clip, PublishedPost, SystemJob, now


def record_publication(db, post, external_id, published_at):
    existing = db.scalar(select(PublishedPost).where(PublishedPost.scheduled_post_id == post.id))
    if existing:
        if existing.external_id != external_id:
            raise Blocked("An existing publication ID cannot be replaced")
        return existing
    if post.status not in {"needs_reconciliation", "failed"}:
        raise Blocked("Only an interrupted publication can be reconciled")
    if db.scalar(
        select(PublishedPost).where(
            PublishedPost.platform == post.platform, PublishedPost.external_id == external_id
        )
    ):
        raise Blocked("This platform publication is already attached to another clip")
    job = db.scalar(select(SystemJob).where(SystemJob.idempotency_key == f"publish:{post.id}"))
    if job and job.status == "running":
        raise Blocked("Wait for the publishing worker to finish before reconciling")
    publication = PublishedPost(
        scheduled_post_id=post.id,
        clip_id=post.clip_id,
        platform=post.platform,
        external_id=external_id,
        published_at=published_at,
        demo=post.demo,
        url=f"https://www.youtube.com/shorts/{external_id}"
        if post.platform == "youtube" and not post.demo
        else None,
    )
    db.add(publication)
    db.flush()
    post.status, post.error = "published", None
    post.remote_state = {**post.remote_state, "manually_reconciled": True, "reconciled_at": now().isoformat()}
    db.get(Clip, post.clip_id).status = "published"
    if job:
        job.status, job.error, job.lease_until, job.completed_at = "done", None, None, now()
    for hours in CHECKPOINTS:
        enqueue(
            db,
            "metrics",
            {"publication_id": publication.id, "hours": hours},
            f"metrics:{publication.id}:{hours}",
            published_at + timedelta(hours=hours),
        )
    return publication
