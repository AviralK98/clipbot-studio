"""Explicit development fixtures. No real media, accounts, metrics or AI calls."""

from datetime import timedelta

from sqlalchemy import select

from .analytics import normalize
from .models import (
    AnalyticsSnapshot,
    Clip,
    ProviderProject,
    PublishedPost,
    ScheduledPost,
    SocialAccount,
    Source,
    SourceVideo,
    now,
)
from .monitoring import Discovery
from .pipeline import ingest


def seed(db):
    if db.scalar(select(Source).where(Source.demo.is_(True))):
        return {"seeded": False, "detail": "Development data already exists"}
    source = Source(
        name="The Builder's Journal",
        url="https://example.com/authorized-demo.mp4",
        kind="manual",
        authorization_type="owner",
        authorization_note="Explicit development fixture. No real content is processed.",
        authorized_platforms=["youtube", "instagram", "tiktok"],
        category="podcast",
        demo=True,
    )
    db.add(source)
    db.flush()
    accounts = []
    for platform in ["youtube", "instagram", "tiktok"]:
        account = SocialAccount(
            platform=platform,
            name=f"Builder Notes · {platform.title()}",
            demo=True,
            external_id=f"demo-{platform}",
        )
        db.add(account)
        accounts.append(account)
    db.flush()
    history = SourceVideo(
        source_id=source.id,
        external_id="demo-history",
        title="Development history",
        url="https://example.com/history.mp4",
        duration=1800,
        status="complete",
        demo=True,
        created_at=now() - timedelta(days=8),
    )
    db.add(history)
    db.flush()
    projects = {}
    for provider in ["vizard", "opus"]:
        project = ProviderProject(
            source_video_id=history.id,
            provider=provider,
            external_id=f"demo-history-{provider}",
            status="complete",
        )
        db.add(project)
        db.flush()
        projects[provider] = project
    titles = [
        "Your first ten customers are closer than you think",
        "A launch is the start of a conversation",
        "Build the thing you wish existed",
        "A better question for your next interview",
        "Why I stopped measuring busy hours",
        "The feedback that made us start again",
        "Small experiments, useful answers",
        "One promise your product should keep",
        "Make room for the unexpected",
        "Start with the person using it",
        "The hardest part of saying no",
        "A week without the noise",
    ]
    for i, title in enumerate(titles):
        provider = "opus" if i % 2 else "vizard"
        clip = Clip(
            source_video_id=history.id,
            provider_project_id=projects[provider].id,
            provider=provider,
            external_id=f"demo-history-{i}",
            title=title,
            transcript=f"This is a development fixture for: {title}. No actual video or AI evaluation exists for this historical sample.",
            duration=[36, 42, 28, 55][i % 4],
            overall_score=84 + (i * 7) % 13,
            topic=["Founder stories", "Building in public", "Product thinking"][i % 3],
            hook_style=["curiosity", "story", "contrarian"][i % 3],
            status="published",
            tier="approved",
            demo=True,
            reason="Synthetic development fixture. All performance numbers are simulated.",
            metadata_json={
                p: {
                    "title": title,
                    "caption": title,
                    "description": "Development sample",
                    "hashtags": ["#BuildInPublic"],
                }
                for p in ["youtube", "instagram", "tiktok"]
            },
        )
        db.add(clip)
        db.flush()
        published_at = now().replace(hour=9 + (i % 3) * 5, minute=0, second=0, microsecond=0) - timedelta(
            days=7 - i // 2
        )
        account = accounts[i % 3]
        post = ScheduledPost(
            clip_id=clip.id,
            account_id=account.id,
            platform=account.platform,
            scheduled_at=published_at,
            status="published",
            demo=True,
        )
        db.add(post)
        db.flush()
        publication = PublishedPost(
            scheduled_post_id=post.id,
            clip_id=clip.id,
            platform=account.platform,
            external_id=f"demo-publication-{i}",
            published_at=published_at,
            created_at=published_at,
            demo=True,
        )
        db.add(publication)
        db.flush()
        views = [3210, 14820, 6820, 21240, 11940, 18300, 8640, 24680, 13450, 32180, 9280, 19830][i]
        for hours, fraction in [(1, 0.08), (6, 0.3), (24, 1)]:
            measured = published_at + timedelta(hours=hours)
            if measured > now():
                continue
            metrics = {
                "views": int(views * fraction),
                "likes": int(views * 0.06 * fraction),
                "comments": int(views * 0.008 * fraction),
                "shares": int(views * 0.012 * fraction),
                "followers_gained": int(views * 0.004 * fraction),
                "average_watch_percentage": 64 + (i * 3) % 22,
            }
            db.add(
                AnalyticsSnapshot(
                    published_post_id=publication.id,
                    checkpoint_hours=hours,
                    metrics=metrics,
                    normalized=normalize(metrics, hours),
                    provenance="demo_fixture",
                    created_at=measured,
                )
            )
    video = ingest(
        db,
        source,
        Discovery(
            "demo-new-episode",
            "Building something that matters · Episode 08",
            "https://example.com/new-episode.mp4",
            1800,
        ),
    )
    return {
        "seeded": True,
        "source_video_id": video.id,
        "detail": "Development history loaded; the new episode runs through the actual job pipeline using explicit demo adapters.",
    }
