import json
import logging
import random
from datetime import timedelta

from sqlalchemy import select

from .config import get_settings
from .db import Session, transaction
from .errors import Ambiguous, Blocked, Deferred, Transient
from .models import SystemJob, now

log = logging.getLogger("clipbot.jobs")


def enqueue(db, kind, payload, key, due_at=None):
    existing = db.scalar(select(SystemJob).where(SystemJob.idempotency_key == key))
    if existing:
        return existing
    job = SystemJob(kind=kind, payload=payload, idempotency_key=key, due_at=due_at or now())
    db.add(job)
    db.flush()
    return job


def claim(job_id):
    with transaction() as db:
        job = db.get(SystemJob, job_id)
        if not job or job.status not in {"queued", "retry"} or job.due_at > now():
            return None
        job.status = "running"
        job.lease_until = now() + timedelta(seconds=get_settings().job_lease_seconds)
        job.attempts += 1
        return job


async def execute(job_id):
    job = claim(job_id)
    if not job:
        return
    from .pipeline import HANDLERS

    status, error, delay = "done", None, 0
    try:
        await HANDLERS[job.kind](job)
    except Deferred as exc:
        status, error, delay = "queued", str(exc), exc.seconds
    except Ambiguous as exc:
        status, error = "needs_reconciliation", str(exc)
    except Blocked as exc:
        status, error = "blocked", str(exc)
    except Exception as exc:
        # Avoid logging provider bodies, URLs with credentials, or raw request exceptions.
        status = "dead_letter" if job.attempts >= get_settings().max_job_attempts else "retry"
        error = (
            str(exc)
            if isinstance(exc, Transient)
            else f"{type(exc).__name__}: job failed; inspect the provider and retry"
        )
        delay = max(getattr(exc, "retry_after", 0), min(3600, 2**job.attempts * 10 + random.randint(0, 10)))
    with transaction() as db:
        current = db.get(SystemJob, job_id)
        current.status, current.error, current.lease_until = status, error, None
        if delay:
            current.due_at = now() + timedelta(seconds=delay)
        if status == "queued":
            current.attempts = max(0, current.attempts - 1)
        if status == "done":
            current.completed_at = now()
    log.info(
        json.dumps(
            {
                "event": "job_finished",
                "job_id": job_id,
                "kind": job.kind,
                "status": status,
                **{
                    k: v for k, v in job.payload.items() if k.endswith("_id") or k in {"provider", "platform"}
                },
            }
        )
    )


def due_jobs(limit=100):
    with Session() as db:
        return list(
            db.scalars(
                select(SystemJob.id)
                .where(SystemJob.status.in_(["queued", "retry"]), SystemJob.due_at <= now())
                .order_by(SystemJob.due_at)
                .limit(limit)
            )
        )


def recover_leases():
    with transaction() as db:
        for job in db.scalars(
            select(SystemJob).where(SystemJob.status == "running", SystemJob.lease_until < now())
        ):
            job.status = "retry"
            job.error = "Worker lease expired; recovering from persisted checkpoints"
            job.due_at = now()
            job.lease_until = None


async def drain(limit=100, stopping=lambda: False):
    """Local development worker, sharing the exact production handlers."""
    count = 0
    for _ in range(limit):
        jobs = due_jobs()
        if not jobs:
            break
        for job_id in jobs:
            if stopping():  # the app is quitting; unstarted jobs stay queued
                return count
            await execute(job_id)
            count += 1
    return count
