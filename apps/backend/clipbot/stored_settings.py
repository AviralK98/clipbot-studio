"""Settings the owner enters in the app instead of a .env file.

Keys go to the operating system's credential store (Windows Credential Manager, macOS Keychain),
encrypted to the signed-in user; everything else goes to settings.json in CLIPBOT_SETTINGS_DIR.
The store is only used when CLIPBOT_SETTINGS_DIR is set (the desktop app sets it). Environment
variables still take priority, so servers, Docker and .env-based development work as before.
"""

import json
import os
from pathlib import Path


def service() -> str:
    """The credential store entry name; a second, separate copy of ClipBot can set its own."""
    return os.environ.get("CLIPBOT_KEYRING_SERVICE", "ClipBot")


# Never returned by the API; shown only as "saved".
SECRET_FIELDS = {
    "session_secret",
    "api_token",
    "opus_api_key",
    "opus_webhook_secret",
    "vizard_api_key",
    "gemini_api_key",
    "openai_api_key",
    "anthropic_api_key",
    "youtube_client_secret",
    "youtube_refresh_token",
    "youtube_data_api_key",
    "instagram_access_token",
}
# What the keys screen may change. settings.json can also hold tuning values (limits, models) that
# were imported from a .env file; see import_env_file.
PLAIN_FIELDS = {
    "opus_org_id",
    "youtube_client_id",
    "youtube_privacy",
    "instagram_user_id",
    "public_api_base_url",
    "llm_provider",
}
# Decided by the desktop app for this computer (or by the environment); never read from settings.json.
MACHINE_FIELDS = {
    "app_env",
    "admin_password",
    "database_url",
    "redis_url",
    "storage_root",
    "source_directory",
    "web_origin",
    "frontend_dir",
}


def enabled() -> bool:
    return bool(os.environ.get("CLIPBOT_SETTINGS_DIR"))


def settings_file() -> Path:
    return Path(os.environ["CLIPBOT_SETTINGS_DIR"]) / "settings.json"


def _keyring():
    import keyring

    return keyring


def _read_plain() -> dict[str, str]:
    try:
        values = json.loads(settings_file().read_text(encoding="utf-8-sig"))  # tolerate hand edits
    except FileNotFoundError:
        return {}
    return {
        k: v
        for k, v in values.items()
        if k not in SECRET_FIELDS and k not in MACHINE_FIELDS and isinstance(v, str)
    }


def load() -> dict[str, str]:
    """Everything stored, for the settings loader. Empty when the store isn't in use."""
    if not enabled():
        return {}
    values = _read_plain()
    keyring = _keyring()
    for name in SECRET_FIELDS:
        value = keyring.get_password(service(), name)
        if value:
            values[name] = value
    return values


def save(changes: dict[str, str]) -> None:
    """Store or clear (empty string) the given fields."""
    unknown = set(changes) - SECRET_FIELDS - PLAIN_FIELDS
    if unknown:
        raise KeyError(f"Not a setting the app can store: {', '.join(sorted(unknown))}")
    keyring = _keyring()
    plain = _read_plain()
    for name, value in changes.items():
        value = value.strip()
        if name in SECRET_FIELDS:
            if value:
                keyring.set_password(service(), name, value)
            else:
                try:
                    keyring.delete_password(service(), name)
                except keyring.errors.PasswordDeleteError:
                    pass  # wasn't stored
        elif value:
            plain[name] = value
        else:
            plain.pop(name, None)
    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plain, indent=2), encoding="utf-8")


def apply(changes: dict[str, str]) -> None:
    """Save, then update the running settings so the change takes effect without a restart."""
    from .config import get_settings

    save(changes)
    settings = get_settings()
    for name, value in changes.items():
        setattr(settings, name, value.strip() or type(settings).model_fields[name].default)


def from_environment(name: str) -> bool:
    """Environment variables win over stored values, so the app can't change these."""
    return name.upper() in os.environ


def import_env_file(path: Path) -> dict[str, int]:
    """Move a .env-based setup into the app: keys into the credential store, tuning values
    (limits, models, posting times) into settings.json. Values are never printed or returned."""
    from .config import Settings
    from .youtube_login import read_env

    keys, tuning = {}, {}
    for name, value in read_env(path).items():
        field = name.lower()
        if not value or field not in Settings.model_fields or field in MACHINE_FIELDS:
            continue
        if field == "session_secret":
            continue  # the app keeps its own
        (keys if field in SECRET_FIELDS else tuning)[field] = value
    for name, value in keys.items():
        _keyring().set_password(service(), name, value)
    plain = _read_plain() | tuning
    settings_file().parent.mkdir(parents=True, exist_ok=True)
    settings_file().write_text(json.dumps(plain, indent=2), encoding="utf-8")
    return {"keys": len(keys), "settings": len(tuning)}
