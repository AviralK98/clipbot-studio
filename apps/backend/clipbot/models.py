from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def now():
    return datetime.now(UTC).replace(tzinfo=None)


def uid():
    return str(uuid4())


class Entity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(Text)


class Source(Entity, Base):
    __tablename__ = "sources"
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(32), default="manual")
    authorization_type: Mapped[str] = mapped_column(String(32))
    authorization_note: Mapped[str] = mapped_column(Text, default="")
    authorized_platforms: Mapped[list] = mapped_column(JSON, default=list)
    category: Mapped[str] = mapped_column(String(100), default="podcast")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    routing: Mapped[str] = mapped_column(String(20), default="dual")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)


class SourceVideo(Entity, Base):
    __tablename__ = "source_videos"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(512))
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(Text)
    duration: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    demo: Mapped[bool] = mapped_column(Boolean, default=False)


class ProviderProject(Entity, Base):
    __tablename__ = "provider_projects"
    __table_args__ = (UniqueConstraint("source_video_id", "provider"),)
    source_video_id: Mapped[str] = mapped_column(ForeignKey("source_videos.id"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class Clip(Entity, Base):
    __tablename__ = "clips"
    __table_args__ = (UniqueConstraint("provider_project_id", "external_id"),)
    source_video_id: Mapped[str] = mapped_column(ForeignKey("source_videos.id"), index=True)
    provider_project_id: Mapped[str] = mapped_column(ForeignKey("provider_projects.id"))
    provider: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(Text)
    transcript: Mapped[str] = mapped_column(Text, default="")
    start_time: Mapped[float | None] = mapped_column(Float)
    end_time: Mapped[float | None] = mapped_column(Float)
    ranges: Mapped[list] = mapped_column(JSON, default=list)
    duration: Mapped[float] = mapped_column(Float)
    media_url: Mapped[str | None] = mapped_column(Text)
    storage_key: Mapped[str | None] = mapped_column(String(250))
    provider_score: Mapped[float | None] = mapped_column(Float)
    overall_score: Mapped[float | None] = mapped_column(Float, index=True)
    topic: Mapped[str] = mapped_column(String(150), default="Unclassified")
    hook_style: Mapped[str] = mapped_column(String(40), default="story")
    status: Mapped[str] = mapped_column(String(32), default="candidate", index=True)
    tier: Mapped[str | None] = mapped_column(String(20))
    duplicate_of: Mapped[str | None] = mapped_column(ForeignKey("clips.id"))
    reason: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    policy_flags: Mapped[list] = mapped_column(JSON, default=list)
    manually_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)


class ClipScore(Entity, Base):
    __tablename__ = "clip_scores"
    clip_id: Mapped[str] = mapped_column(ForeignKey("clips.id"), unique=True)
    scores: Mapped[dict] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String(100))
    rubric_version: Mapped[str] = mapped_column(String(20), default="1.0")


class ClipEmbedding(Entity, Base):
    __tablename__ = "clip_embeddings"
    clip_id: Mapped[str] = mapped_column(ForeignKey("clips.id"), unique=True)
    vector: Mapped[list] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String(100))


class SocialAccount(Entity, Base):
    __tablename__ = "social_accounts"
    platform: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    external_id: Mapped[str] = mapped_column(String(200), default="")
    credential_ref: Mapped[str] = mapped_column(String(100), default="environment")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_limit: Mapped[int] = mapped_column(Integer, default=3)


class ScheduledPost(Entity, Base):
    __tablename__ = "scheduled_posts"
    __table_args__ = (
        UniqueConstraint("clip_id", "account_id"),
        UniqueConstraint("account_id", "scheduled_at"),
    )
    clip_id: Mapped[str] = mapped_column(ForeignKey("clips.id"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("social_accounts.id"))
    platform: Mapped[str] = mapped_column(String(20))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(32), default="scheduled")
    error: Mapped[str | None] = mapped_column(Text)
    remote_state: Mapped[dict] = mapped_column(JSON, default=dict)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)


class PublishedPost(Entity, Base):
    __tablename__ = "published_posts"
    scheduled_post_id: Mapped[str] = mapped_column(ForeignKey("scheduled_posts.id"), unique=True)
    clip_id: Mapped[str] = mapped_column(ForeignKey("clips.id"), index=True)
    platform: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)


class AnalyticsSnapshot(Entity, Base):
    __tablename__ = "analytics_snapshots"
    __table_args__ = (UniqueConstraint("published_post_id", "checkpoint_hours"),)
    published_post_id: Mapped[str] = mapped_column(ForeignKey("published_posts.id"), index=True)
    checkpoint_hours: Mapped[int] = mapped_column(Integer)
    metrics: Mapped[dict] = mapped_column(JSON)
    normalized: Mapped[dict] = mapped_column(JSON, default=dict)
    provenance: Mapped[str] = mapped_column(String(40), default="platform_api")


class StrategyMetric(Entity, Base):
    __tablename__ = "strategy_metrics"
    __table_args__ = (UniqueConstraint("dimension", "label"),)
    dimension: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(200))
    samples: Mapped[int] = mapped_column(Integer)
    median_views: Mapped[float] = mapped_column(Float)
    weight: Mapped[float] = mapped_column(Float, default=1)


class ProviderMetric(Entity, Base):
    __tablename__ = "provider_metrics"
    provider: Mapped[str] = mapped_column(String(20), unique=True)
    metrics: Mapped[dict] = mapped_column(JSON)


class AIInsight(Entity, Base):
    __tablename__ = "ai_insights"
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)


class APIUsage(Entity, Base):
    __tablename__ = "api_usage"
    idempotency_key: Mapped[str] = mapped_column(String(250), unique=True)
    source_video_id: Mapped[str | None] = mapped_column(ForeignKey("source_videos.id"))
    provider: Mapped[str] = mapped_column(String(30), index=True)
    units: Mapped[float] = mapped_column(Float)
    unit_type: Mapped[str] = mapped_column(String(30))
    estimated_cost: Mapped[float] = mapped_column(Float, default=0)
    actual_tokens: Mapped[int | None] = mapped_column(Integer)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)


class SystemJob(Entity, Base):
    __tablename__ = "system_jobs"
    idempotency_key: Mapped[str] = mapped_column(String(250), unique=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    due_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class SystemState(Base):
    __tablename__ = "system_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    autopilot: Mapped[bool] = mapped_column(Boolean, default=True)
    stop_all_posting: Mapped[bool] = mapped_column(Boolean, default=False)
    timezone: Mapped[str] = mapped_column(String(80), default="Europe/London")
    posting_times: Mapped[list] = mapped_column(JSON, default=lambda: ["09:00", "14:00", "19:00"])
    daily_limit: Mapped[int] = mapped_column(Integer, default=3)
    min_interval: Mapped[int] = mapped_column(Integer, default=180)
    thresholds: Mapped[dict] = mapped_column(
        JSON, default=lambda: {"priority": 90, "approved": 82, "reserve": 75}
    )
    policy_filters: Mapped[list] = mapped_column(
        JSON,
        default=lambda: [
            "hate",
            "sexual_content",
            "violence",
            "self_harm",
            "illegal_activity",
            "personal_information",
            "copyright",
        ],
    )
    learning_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime)
