from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "development"
    admin_password: str = "clipbot-local"
    session_secret: str = "local-development-secret-change-before-deployment"
    api_token: str = ""
    web_origin: str = "http://localhost:3000"
    demo_mode: bool = False
    autopilot: bool = True
    stop_all_posting: bool = False
    database_url: str = "sqlite:///./data/clipbot.db"
    redis_url: str = "redis://localhost:6379/0"
    storage_root: Path = Path("data/media")
    source_directory: Path = Path("data/sources")
    public_media_base_url: str = ""
    public_api_base_url: str = ""
    opus_webhook_secret: str = ""
    vizard_api_key: str = ""
    vizard_model: str = "clip_v1"
    opus_api_key: str = ""
    opus_org_id: str = ""
    opus_model: str = "ClipBasic"
    opus_time_range_unit: str = "unknown"
    llm_provider: Literal["local", "openai", "anthropic"] = "local"
    llm_model: str = "gpt-4.1-mini"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_refresh_token: str = ""
    youtube_privacy: str = "private"
    youtube_data_api_key: str = ""
    instagram_access_token: str = ""
    instagram_user_id: str = ""
    instagram_api_version: str = "v25.0"
    max_source_minutes_per_day: float = 120
    max_clips_per_day: int = 20
    max_vizard_credits_per_day: float = 150
    max_opus_credits_per_day: float = 150
    max_ai_cost_per_day: float = 5
    vizard_cost_per_credit: float = 0
    opus_cost_per_credit: float = 0
    ai_input_usd_per_million: float = 1
    ai_output_usd_per_million: float = 5
    ai_call_reservation_usd: float = 0.10
    storage_usd_per_gb_month: float = 0
    timezone: str = "Europe/London"
    posting_times: str = "09:00,14:00,19:00"
    max_posts_per_platform_per_day: int = 3
    min_post_interval_minutes: int = 180
    max_download_bytes: int = 512 * 1024 * 1024
    max_job_attempts: int = 6
    job_lease_seconds: int = 1800

    @model_validator(mode="after")
    def production_secrets(self):
        if self.app_env == "production":
            if (
                len(self.admin_password) < 16
                or "local" in self.session_secret
                or len(self.session_secret) < 32
            ):
                raise ValueError("Production needs a strong ADMIN_PASSWORD and SESSION_SECRET")
            if not self.web_origin.startswith("https://") or self.demo_mode:
                raise ValueError("Production requires HTTPS WEB_ORIGIN and DEMO_MODE=false")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
