from collections import defaultdict
from datetime import UTC, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select

from .models import (
    AIInsight,
    AnalyticsSnapshot,
    Clip,
    ProviderMetric,
    PublishedPost,
    Source,
    SourceVideo,
    StrategyMetric,
    SystemState,
    now,
)

CHECKPOINTS = (1, 6, 24, 72, 168)


def normalize(metrics, hours):
    views = metrics.get("views") or 0

    def per_thousand(key):
        return (metrics[key] * 1000 / views) if views and metrics.get(key) is not None else None

    known_engagement = [metrics.get(k) for k in ("likes", "comments", "shares")]
    return {
        "views_per_hour": views / max(hours, 1 / 60),
        "shares_per_1000": per_thousand("shares"),
        "comments_per_1000": per_thousand("comments"),
        "followers_per_1000": per_thousand("followers_gained"),
        "watch_completion": metrics.get("average_watch_percentage"),
        "engagement_rate": sum(known_engagement) / views
        if views and all(v is not None for v in known_engagement)
        else None,
    }


def duration_bucket(seconds):
    for edge, name in [(20, "0–20"), (30, "20–30"), (45, "30–45"), (60, "45–60"), (90, "60–90")]:
        if seconds <= edge:
            return name
    return "90+"


def analytics_report(db, demo=False):
    posts = {p.id: p for p in db.scalars(select(PublishedPost).where(PublishedPost.demo == demo))}
    snapshots = (
        list(
            db.scalars(
                select(AnalyticsSnapshot)
                .where(AnalyticsSnapshot.published_post_id.in_(posts))
                .order_by(AnalyticsSnapshot.created_at)
            )
        )
        if posts
        else []
    )
    latest, previous, daily = {}, {}, defaultdict(int)
    for snap in snapshots:
        views = snap.metrics.get("views") or 0
        daily[snap.created_at.date().isoformat()] += max(0, views - previous.get(snap.published_post_id, 0))
        previous[snap.published_post_id] = views
        latest[snap.published_post_id] = snap
    groups = defaultdict(list)
    for post_id, snap in latest.items():
        post = posts[post_id]
        clip = db.get(Clip, post.clip_id)
        groups[("provider", clip.provider)].append(snap)
        groups[("topic", clip.topic)].append(snap)
        groups[("platform", post.platform)].append(snap)
        groups[("duration", duration_bucket(clip.duration))].append(snap)
        groups[("hook", clip.hook_style)].append(snap)
        zone = ZoneInfo(db.get(SystemState, 1).timezone)
        groups[
            (
                "posting_time",
                post.published_at.replace(tzinfo=UTC).astimezone(zone).strftime("%H:00"),
            )
        ].append(snap)
    breakdown = []
    for (dimension, label), values in groups.items():

        def available(metric, rows=values):
            return [v.normalized[metric] for v in rows if v.normalized.get(metric) is not None]

        breakdown.append(
            {
                "dimension": dimension,
                "label": label,
                "published": len(values),
                "median_views": median(v.metrics.get("views") or 0 for v in values),
                **{
                    k: median(available(k)) if available(k) else None
                    for k in ("watch_completion", "shares_per_1000", "followers_per_1000", "engagement_rate")
                },
            }
        )
    today = now().date()
    trend = [
        {
            "date": (today - timedelta(days=i)).isoformat(),
            "views": daily[(today - timedelta(days=i)).isoformat()],
        }
        for i in reversed(range(7))
    ]
    return {
        "views": sum(v.metrics.get("views") or 0 for v in latest.values()),
        "views_today": daily[today.isoformat()],
        "views_7d": sum(d["views"] for d in trend),
        "followers_gained": sum(v.metrics.get("followers_gained") or 0 for v in latest.values()),
        "followers_available": any(v.metrics.get("followers_gained") is not None for v in latest.values()),
        "trend": trend,
        "breakdown": breakdown,
        "snapshots": len(snapshots),
        "note": "Daily views are observed snapshot gains; reporting gaps and platform delays affect attribution.",
    }


def learn(db):
    """Use real 24h cohorts only. Small samples do not drive autonomous changes."""
    state = db.get(SystemState, 1)
    if not state.learning_enabled:
        return
    rows = db.execute(
        select(AnalyticsSnapshot, PublishedPost, Clip, SourceVideo, Source)
        .join(PublishedPost, AnalyticsSnapshot.published_post_id == PublishedPost.id)
        .join(Clip, PublishedPost.clip_id == Clip.id)
        .join(SourceVideo, Clip.source_video_id == SourceVideo.id)
        .join(Source, SourceVideo.source_id == Source.id)
        .where(
            PublishedPost.demo.is_(False),
            AnalyticsSnapshot.checkpoint_hours == 24,
            AnalyticsSnapshot.provenance == "platform_api",
        )
    ).all()
    groups = defaultdict(list)
    zone = ZoneInfo(state.timezone)
    for snap, post, clip, _video, source in rows:
        age = (snap.created_at - post.published_at).total_seconds() / 3600
        if not 23 <= age <= 27 or snap.metrics.get("views") is None:
            continue
        labels = {
            "provider": clip.provider,
            "topic": clip.topic,
            "source": source.name,
            "category_provider": f"{source.category}:{clip.provider}",
            "hook": clip.hook_style,
            "duration": duration_bucket(clip.duration),
            "platform": post.platform,
            "posting_time": post.published_at.replace(tzinfo=UTC).astimezone(zone).strftime("%H:00"),
        }
        for dim, label in labels.items():
            groups[(dim, label)].append(snap.metrics["views"])
    baseline = (
        median([snap.metrics["views"] for snap, *_ in rows if snap.metrics.get("views") is not None])
        if rows
        else 0
    )
    db.execute(delete(StrategyMetric))
    db.execute(delete(ProviderMetric))
    db.execute(delete(AIInsight))
    for (dim, label), values in groups.items():
        center = median(values)
        weight = max(0.5, min(1.5, (center + 100) / (baseline + 100))) if len(values) >= 5 else 1
        db.add(
            StrategyMetric(
                dimension=dim, label=label, samples=len(values), median_views=center, weight=weight
            )
        )
        if dim == "provider":
            db.add(
                ProviderMetric(provider=label, metrics={"samples": len(values), "median_24h_views": center})
            )
        if len(values) >= 5 and weight >= 1.2:
            db.add(
                AIInsight(
                    title=f"{label} is gaining traction",
                    body=f"Median {center:,.0f} views at 24 hours across {len(values)} publications. Selection weight is {weight:.2f}×.",
                    evidence={
                        "dimension": dim,
                        "sample_size": len(values),
                        "cohort_hours": 24,
                        "weight": weight,
                    },
                )
            )


def preferences(db, source):
    metrics = list(db.scalars(select(StrategyMetric).where(StrategyMetric.samples >= 5)))
    result = {}
    for dim in ("topic", "duration"):
        options = [m for m in metrics if m.dimension == dim]
        if options:
            result[dim] = max(options, key=lambda m: m.weight).label
    return result


def route(db, source, video_id):
    if source.routing != "learned":
        return ["vizard", "opus"] if source.routing == "dual" else [source.routing]
    weights = {p: 1.0 for p in ("vizard", "opus")}
    for m in db.scalars(
        select(StrategyMetric).where(
            StrategyMetric.dimension == "category_provider", StrategyMetric.samples >= 5
        )
    ):
        category, provider = m.label.rsplit(":", 1)
        if category == source.category and provider in weights:
            weights[provider] = m.weight
    if weights["vizard"] == weights["opus"]:
        return ["vizard", "opus"]
    import hashlib

    draw = int(hashlib.sha256(video_id.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    probability = max(0.2, min(0.8, weights["vizard"] / sum(weights.values())))
    return ["vizard" if draw < probability else "opus"]
