from datetime import timedelta

from sqlalchemy import func, select

from .config import get_settings
from .errors import Blocked, Deferred
from .models import APIUsage, now


def reserve(db, key, provider, units, kind, video_id=None, cost=0, demo=False):
    existing = db.scalar(select(APIUsage).where(APIUsage.idempotency_key == key))
    if existing:
        return existing
    cfg = get_settings()
    start = now().replace(hour=0, minute=0, second=0, microsecond=0)
    query = select(func.coalesce(func.sum(APIUsage.units), 0)).where(
        APIUsage.provider == provider, APIUsage.created_at >= start, APIUsage.demo == demo
    )
    limit = {
        "source": cfg.max_source_minutes_per_day,
        "vizard": cfg.max_vizard_credits_per_day,
        "opus": cfg.max_opus_credits_per_day,
    }.get(provider)
    if limit is not None and db.scalar(query) + units > limit:
        raise Blocked(f"Daily {provider} budget exhausted; adjust limits or retry tomorrow")
    if provider == "ai":
        spent = db.scalar(
            select(func.coalesce(func.sum(APIUsage.estimated_cost), 0)).where(
                APIUsage.provider == "ai", APIUsage.created_at >= start, APIUsage.demo == demo
            )
        )
        if spent + cost > cfg.max_ai_cost_per_day:
            raise Blocked("Daily AI cost budget exhausted; retry tomorrow")
    if provider == "vizard" and not demo:
        for minutes, cap in [(1, 3), (60, 20)]:
            count = db.scalar(
                select(func.count())
                .select_from(APIUsage)
                .where(
                    APIUsage.provider == provider,
                    APIUsage.demo.is_(False),
                    APIUsage.created_at > now() - timedelta(minutes=minutes),
                )
            )
            if count >= cap:
                raise Deferred(minutes * 60, "Vizard submission rate window full")
    row = APIUsage(
        idempotency_key=key,
        provider=provider,
        units=units,
        unit_type=kind,
        source_video_id=video_id,
        estimated_cost=cost,
        demo=demo,
    )
    db.add(row)
    db.flush()
    return row
