from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .config import get_settings
from .errors import Blocked
from .models import Clip, ScheduledPost, SocialAccount, Source, SourceVideo, SystemState, now


def next_slot(state, existing, start=None, daily_limit=None):
    zone = ZoneInfo(state.timezone)
    current = (start or now()).replace(tzinfo=UTC)
    cap = min(state.daily_limit, daily_limit or state.daily_limit)
    occupied = [p.scheduled_at.replace(tzinfo=UTC) for p in existing if p.status != "cancelled"]
    for day in range(91):
        date = current.astimezone(zone).date() + timedelta(days=day)
        if sum(t.astimezone(zone).date() == date for t in occupied) >= cap:
            continue
        for slot in sorted(state.posting_times):
            hour, minute = map(int, slot.split(":"))
            local = datetime(date.year, date.month, date.day, hour, minute, tzinfo=zone)
            utc = local.astimezone(UTC)
            # A nonexistent DST local time cannot round-trip; skip it.
            if utc.astimezone(zone).replace(tzinfo=None) != local.replace(tzinfo=None):
                continue
            if utc <= current or any(
                abs((utc - t).total_seconds()) < state.min_interval * 60 for t in occupied
            ):
                continue
            return utc.replace(tzinfo=None)
    raise Blocked("No available posting slot within 90 days")


def can_publish(db, clip, account, state):
    video = db.get(SourceVideo, clip.source_video_id)
    source = db.get(Source, video.source_id)
    if clip.demo != get_settings().demo_mode:
        raise Blocked("Clip does not match the active demo/live environment")
    if video.status != "complete":
        raise Blocked("Wait for both engines and final duplicate selection before scheduling")
    if state.stop_all_posting or get_settings().stop_all_posting:
        raise Blocked("All posting is stopped")
    if not source.enabled or source.archived or account.platform not in source.authorized_platforms:
        raise Blocked("Source is disabled or not authorized for this platform")
    if not account.enabled or account.demo != clip.demo:
        raise Blocked("Account is disabled or does not match the clip environment")
    if clip.duplicate_of or clip.status in {"rejected", "candidate", "analyzing", "failed"}:
        raise Blocked("Clip is ineligible for publishing")
    if clip.policy_flags and not clip.manually_approved:
        raise Blocked("Flagged clip requires manual review")
    if clip.metadata_json.get("manual_review_required") and not clip.manually_approved:
        raise Blocked("Local review requires manual approval before publishing")
    if not state.autopilot and not clip.manually_approved:
        raise Blocked("Autopilot is off; manual approval is required")
    if not clip.metadata_json.get(account.platform):
        raise Blocked("Platform metadata is missing")
    if not clip.demo and not clip.storage_key:
        raise Blocked("Clip media has not been archived")
    if account.platform == "tiktok" and not clip.demo and clip.provider != "opus":
        raise Blocked(
            "TikTok publishing is mediated through OpusClip and only works for clips OpusClip "
            "generated (it must already hold the source video). Export this clip for manual posting."
        )


def schedule_clip(db, clip_id, account_id, requested=None, reactivate=False):
    clip, account = db.get(Clip, clip_id), db.get(SocialAccount, account_id)
    if not clip or not account:
        raise Blocked("Clip or social account was not found")
    existing_post = db.scalar(
        select(ScheduledPost).where(ScheduledPost.clip_id == clip_id, ScheduledPost.account_id == account_id)
    )
    if existing_post and (existing_post.status != "cancelled" or not reactivate):
        return existing_post
    state = db.get(SystemState, 1)
    can_publish(db, clip, account, state)
    if clip.status not in {"approved", "scheduled", "published"}:
        raise Blocked("Approve this clip before scheduling")
    existing = list(db.scalars(select(ScheduledPost).where(ScheduledPost.account_id == account_id)))
    scheduled_at = next_slot(state, existing, daily_limit=account.daily_limit)
    if requested:
        zone = ZoneInfo(state.timezone)
        if requested.tzinfo is None:
            raise Blocked("Scheduled time must include its timezone")
        proposed = requested.astimezone(UTC).replace(tzinfo=None)
        if proposed <= now():
            raise Blocked("Scheduled time must be in the future")
        date = proposed.replace(tzinfo=UTC).astimezone(zone).date()
        relevant = [p for p in existing if p.status != "cancelled"]
        if sum(p.scheduled_at.replace(tzinfo=UTC).astimezone(zone).date() == date for p in relevant) >= min(
            state.daily_limit, account.daily_limit
        ):
            raise Blocked("Daily account posting limit reached")
        if any(abs((proposed - p.scheduled_at).total_seconds()) < state.min_interval * 60 for p in relevant):
            raise Blocked("Minimum posting interval would be exceeded")
        scheduled_at = proposed
    zone = ZoneInfo(state.timezone)
    date = scheduled_at.replace(tzinfo=UTC).astimezone(zone).date()
    platform_posts = db.scalars(
        select(ScheduledPost).where(
            ScheduledPost.platform == account.platform, ScheduledPost.status != "cancelled"
        )
    )
    if (
        sum(p.scheduled_at.replace(tzinfo=UTC).astimezone(zone).date() == date for p in platform_posts)
        >= state.daily_limit
    ):
        raise Blocked("Platform daily limit reached across all accounts")
    all_posts = db.scalars(select(ScheduledPost).where(ScheduledPost.status != "cancelled"))
    if (
        sum(p.scheduled_at.replace(tzinfo=UTC).astimezone(zone).date() == date for p in all_posts)
        >= get_settings().max_clips_per_day
    ):
        raise Blocked("Global daily clip posting limit reached")
    post = existing_post or ScheduledPost(
        clip_id=clip_id,
        account_id=account_id,
        platform=account.platform,
        scheduled_at=scheduled_at,
        demo=clip.demo,
    )
    if existing_post:
        from .models import SystemJob

        job = db.scalar(select(SystemJob).where(SystemJob.idempotency_key == f"publish:{post.id}"))
        if job and job.status == "running":
            raise Blocked("Wait for the publishing worker to finish before rescheduling")
        post.scheduled_at, post.status, post.error = scheduled_at, "scheduled", None
        if job:
            job.status, job.due_at, job.attempts, job.error = "queued", scheduled_at, 0, None
    db.add(post)
    clip.status = "scheduled"
    return post
