from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .security import public_url

Platform = Literal["youtube", "tiktok", "instagram"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(Input):
    password: str = Field(min_length=1, max_length=512)


class SourceInput(Input):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2000)
    kind: Literal[
        "manual", "youtube_channel", "youtube_playlist", "rss", "local", "google_drive", "dropbox"
    ] = "manual"
    authorization_type: Literal["owner", "licensed", "permission"]
    authorization_note: str = Field(min_length=1, max_length=3000)
    authorized_platforms: list[Platform] = Field(min_length=1, max_length=3)
    category: str = Field(default="podcast", min_length=1, max_length=100)
    enabled: bool = True
    routing: Literal["dual", "vizard", "opus", "learned"] = "dual"

    @model_validator(mode="after")
    def validate_url(self):
        if self.kind != "local":
            public_url(self.url, resolve=False)
        elif self.url.startswith(("/", "\\")) or ".." in self.url or ":" in self.url:
            raise ValueError("Local folder must be relative to SOURCE_DIRECTORY")
        return self


class VideoInput(Input):
    source_id: str
    url: str = Field(max_length=2000)
    title: str = Field(min_length=1, max_length=300)
    duration: float = Field(gt=0, le=36000)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value):
        return public_url(value, resolve=False)


class ReviewInput(Input):
    action: Literal["approve", "reject"]
    note: str = Field(default="", max_length=1000)
    acknowledge_flags: bool = False


class ScheduleInput(Input):
    clip_id: str
    account_id: str
    scheduled_at: datetime | None = None


class AccountInput(Input):
    platform: Platform
    name: str = Field(min_length=1, max_length=120)
    external_id: str = Field(default="", max_length=200)
    daily_limit: int = Field(default=3, ge=1, le=30)


class SettingsInput(Input):
    autopilot: bool | None = None
    stop_all_posting: bool | None = None
    timezone: str | None = None
    posting_times: list[str] | None = None
    daily_limit: int | None = Field(default=None, ge=1, le=30)
    min_interval: int | None = Field(default=None, ge=15, le=1440)
    thresholds: dict[str, float] | None = None
    policy_filters: list[str] | None = None
    learning_enabled: bool | None = None

    @field_validator("timezone")
    @classmethod
    def timezone_exists(cls, value):
        if value is not None:
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError:
                raise ValueError("Unknown timezone") from None
        return value

    @field_validator("posting_times")
    @classmethod
    def times_valid(cls, value):
        import re

        if value is not None and (
            not 1 <= len(value) <= 24
            or len(set(value)) != len(value)
            or any(not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", v) for v in value)
        ):
            raise ValueError("Provide 1–24 unique HH:MM posting times")
        return value

    @field_validator("thresholds")
    @classmethod
    def scores_valid(cls, value):
        if value is not None:
            if (
                set(value) != {"priority", "approved", "reserve"}
                or not 0 <= value["reserve"] < value["approved"] < value["priority"] <= 100
            ):
                raise ValueError("Thresholds must satisfy 0 ≤ reserve < approved < priority ≤ 100")
        return value

    @field_validator("policy_filters")
    @classmethod
    def flags_valid(cls, value):
        allowed = {
            "hate",
            "sexual_content",
            "violence",
            "self_harm",
            "illegal_activity",
            "personal_information",
            "copyright",
        }
        if value is not None and not set(value) <= allowed:
            raise ValueError("Unknown content policy category")
        return value


class MetricsInput(Input):
    checkpoint_hours: Literal[1, 6, 24, 72, 168]
    views: int | None = Field(default=None, ge=0)
    likes: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)
    followers_gained: int | None = Field(default=None, ge=0)
    watch_time_minutes: float | None = Field(default=None, ge=0)
    average_watch_percentage: float | None = Field(default=None, ge=0, le=1000)


class ReconcileInput(Input):
    external_id: str = Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9._-]+$")
    completion_confirmed: bool = False


class PublicationReconcileInput(Input):
    external_id: str = Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9._-]+$")
    published_at: datetime
    publication_confirmed: Literal[True]

    @field_validator("published_at")
    @classmethod
    def valid_published_at(cls, value):
        if value.tzinfo is None:
            raise ValueError("Publication time must include a timezone")
        if value > datetime.now(UTC):
            raise ValueError("Publication time cannot be in the future")
        return value.astimezone(UTC).replace(tzinfo=None)
