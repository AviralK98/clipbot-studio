"""First-run password, the keys screen and "Connect YouTube", so nobody has to edit a .env file."""

from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from . import stored_settings, youtube_login
from .config import get_settings
from .db import Session, transaction
from .errors import Blocked
from .models import SocialAccount, SystemJob, User, now
from .security import hash_password, origin_allowed, require_auth, start_session

router = APIRouter()

# What the keys screen shows. Secrets are never sent back to the browser, only whether they're saved.
GROUPS = [
    {
        "id": "opus",
        "title": "OpusClip",
        "about": "Finds clips in your videos and posts them to TikTok. Posting needs an OpusClip Pro plan. "
        "Create the API key in your OpusClip account's API settings.",
        "fields": [
            {"name": "opus_api_key", "label": "API key"},
            {"name": "opus_org_id", "label": "Organisation ID (only if OpusClip gave you one)"},
        ],
    },
    {
        "id": "vizard",
        "title": "Vizard",
        "about": "A second clipping engine (optional). Create the API key in your Vizard account.",
        "fields": [{"name": "vizard_api_key", "label": "API key"}],
    },
    {
        "id": "youtube",
        "title": "YouTube",
        "about": "Posts Shorts to your channel and reads their stats, through your own Google Cloud project. "
        "Follow the setup guide to create it, then paste the OAuth client and API key here and click "
        "Connect YouTube.",
        "link": "https://console.cloud.google.com/apis/credentials",
        "fields": [
            {"name": "youtube_client_id", "label": "OAuth client ID"},
            {"name": "youtube_client_secret", "label": "OAuth client secret"},
            {"name": "youtube_data_api_key", "label": "API key (reads video details)"},
            {
                "name": "youtube_privacy",
                "label": "New uploads are",
                "choices": ["public", "unlisted", "private"],
            },
        ],
    },
    {
        "id": "gemini",
        "title": "Google Gemini",
        "about": "Watches your Shorts for the AI insights page. The free tier is enough; note that Google may "
        "use free-tier content to improve its products.",
        "link": "https://aistudio.google.com/apikey",
        "fields": [{"name": "gemini_api_key", "label": "API key"}],
    },
]
EDITABLE = {f["name"] for group in GROUPS for f in group["fields"]}


class PasswordInput(BaseModel):
    password: str = Field(min_length=8, max_length=200)


class ConfigInput(BaseModel):
    values: dict[str, str]


def owner_exists() -> bool:
    with Session() as db:
        return db.get(User, "owner") is not None


@router.get("/api/setup/status")
def setup_status():
    return {"needs_password": not owner_exists(), "app_settings": stored_settings.enabled()}


@router.post("/api/setup/password")
def create_password(payload: PasswordInput, request: Request, response: Response):
    """First run only: the owner picks the studio password, and is signed in."""
    if not origin_allowed(request.headers.get("origin")):
        raise HTTPException(403, "Invalid request origin")
    with transaction() as db:
        if db.get(User, "owner"):
            raise HTTPException(409, "A studio password already exists; sign in with it")
        user = User(id="owner", name="Studio owner", password_hash=hash_password(payload.password))
        db.add(user)
    start_session(response, user.password_hash)
    return {"user": "Studio owner"}


def config_view():
    settings = get_settings()
    groups = []
    for group in GROUPS:
        fields = []
        for field in group["fields"]:
            name = field["name"]
            value = getattr(settings, name) or ""
            secret = name in stored_settings.SECRET_FIELDS
            fields.append(
                {
                    **field,
                    "secret": secret,
                    "saved": bool(value),
                    "value": None if secret else value,
                    "from_environment": stored_settings.from_environment(name),
                }
            )
        groups.append({**group, "fields": fields})
    return {
        "editable": stored_settings.enabled(),
        "groups": groups,
        "youtube": {"connected": bool(settings.youtube_refresh_token), **youtube_login.connect_status()},
    }


@router.get("/api/config", dependencies=[Depends(require_auth)])
def read_config():
    return config_view()


@router.put("/api/config", dependencies=[Depends(require_auth)])
def update_config(payload: ConfigInput):
    if not stored_settings.enabled():
        raise Blocked("This ClipBot reads its keys from environment variables (.env); change them there")
    unknown = set(payload.values) - EDITABLE
    if unknown:
        raise HTTPException(422, f"Unknown settings: {', '.join(sorted(unknown))}")
    locked = [name for name in payload.values if stored_settings.from_environment(name)]
    if locked:
        raise Blocked(f"Set by an environment variable, so it can't be changed here: {', '.join(locked)}")
    choices = {f["name"]: f["choices"] for group in GROUPS for f in group["fields"] if "choices" in f}
    for name, value in payload.values.items():
        if name in choices and value and value not in choices[name]:
            raise HTTPException(422, f"{name} must be one of {', '.join(choices[name])}")
    stored_settings.apply(payload.values)
    return config_view()


def save_youtube_login(tokens: dict) -> str:
    """Store the new login, add the channel as a destination if it's new, and wake waiting jobs."""
    token = tokens["refresh_token"]
    if stored_settings.enabled():
        stored_settings.apply({"youtube_refresh_token": token})
    else:
        youtube_login.write_env_value(Path(".env"), "YOUTUBE_REFRESH_TOKEN", token)
        get_settings().youtube_refresh_token = token
    try:
        items = (
            httpx.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"part": "snippet", "mine": "true"},
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
                timeout=30,
            )
            .json()
            .get("items")
            or []
        )
    except (httpx.HTTPError, ValueError):
        items = []  # the login is saved either way; the channel name is a nicety
    title = items[0]["snippet"]["title"] if items else "your channel"
    with transaction() as db:
        demo = get_settings().demo_mode
        if items and not db.scalar(
            select(SocialAccount).where(SocialAccount.platform == "youtube", SocialAccount.demo == demo)
        ):
            snippet = items[0]["snippet"]
            db.add(
                SocialAccount(
                    platform="youtube",
                    name=title,
                    external_id=snippet.get("customUrl") or items[0]["id"],
                    daily_limit=3,
                    demo=demo,
                )
            )
        # Jobs that were waiting for a fresh login can go now instead of at their hourly retry.
        for job in db.scalars(
            select(SystemJob).where(
                SystemJob.status.in_(["queued", "retry"]), SystemJob.error.like("%YouTube login expired%")
            )
        ):
            job.due_at = now()
    return f"Connected to YouTube channel “{title}”."


@router.post("/api/youtube/connect", dependencies=[Depends(require_auth)])
def connect_youtube():
    settings = get_settings()
    if not settings.youtube_client_id or not settings.youtube_client_secret:
        raise Blocked("Save your YouTube OAuth client ID and secret first")
    url = youtube_login.start_connect(
        settings.youtube_client_id, settings.youtube_client_secret, save_youtube_login
    )
    return {"url": url}


@router.get("/api/youtube/connect", dependencies=[Depends(require_auth)])
def youtube_connection():
    return {"connected": bool(get_settings().youtube_refresh_token), **youtube_login.connect_status()}
