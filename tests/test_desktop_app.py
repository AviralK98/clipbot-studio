"""The desktop app: keys saved from the app, first-run password, the served dashboard, and the worker."""

import asyncio
import json
import threading
import time
import urllib.parse

import httpx
import keyring
import keyring.backend
import keyring.errors
import pytest
import respx
from clipbot import desktop, local_worker, stored_settings, youtube_login
from clipbot.config import Settings, get_settings
from clipbot.db import Session, transaction
from clipbot.models import SocialAccount, User
from clipbot.security import origin_allowed
from fastapi.testclient import TestClient

# The keys screen's settings. (The session secret isn't reset: the test client is already signed in with it.)
KEYS = ["opus_api_key", "opus_org_id", "vizard_api_key", "youtube_client_id", "youtube_client_secret"]
KEYS += ["youtube_data_api_key", "youtube_privacy", "gemini_api_key", "youtube_refresh_token"]


class MemoryKeyring(keyring.backend.KeyringBackend):
    """Stands in for Windows Credential Manager."""

    priority = 1

    def __init__(self):
        self.saved = {}

    def get_password(self, service, username):
        return self.saved.get((service, username))

    def set_password(self, service, username, password):
        self.saved[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.saved:
            raise keyring.errors.PasswordDeleteError(username)
        del self.saved[(service, username)]


@pytest.fixture
def vault(tmp_path, monkeypatch):
    """App-managed settings (as in the desktop app), with an in-memory credential store."""
    previous = keyring.get_keyring()
    memory = MemoryKeyring()
    keyring.set_keyring(memory)
    monkeypatch.setenv("CLIPBOT_SETTINGS_DIR", str(tmp_path))
    settings = get_settings()
    for name in KEYS:
        monkeypatch.delenv(name.upper(), raising=False)
        # Start from defaults, not whatever a developer's .env holds; restored after the test.
        monkeypatch.setattr(settings, name, Settings.model_fields[name].default)
    yield memory
    keyring.set_keyring(previous)


def test_keys_go_to_the_credential_store_and_are_never_sent_back(client, vault, tmp_path):
    body = client.put(
        "/api/config",
        json={
            "values": {
                "opus_api_key": "opus-secret",
                "youtube_client_id": "id-1",
                "youtube_privacy": "unlisted",
            }
        },
    ).json()
    fields = {f["name"]: f for group in body["groups"] for f in group["fields"]}
    assert fields["opus_api_key"]["saved"] is True and fields["opus_api_key"]["value"] is None
    assert fields["youtube_client_id"]["value"] == "id-1"
    assert "opus-secret" not in json.dumps(body)
    assert vault.saved[("ClipBot", "opus_api_key")] == "opus-secret"
    plain = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert plain == {"youtube_client_id": "id-1", "youtube_privacy": "unlisted"}
    # The running app uses the new key straight away.
    assert get_settings().opus_api_key == "opus-secret"

    # Clearing removes it; clearing a choice restores its default.
    client.put("/api/config", json={"values": {"opus_api_key": "", "youtube_privacy": ""}})
    assert ("ClipBot", "opus_api_key") not in vault.saved
    assert get_settings().youtube_privacy == "private"


def test_saved_settings_load_on_start_but_environment_variables_win(vault, monkeypatch):
    stored_settings.save({"gemini_api_key": "from-app", "vizard_api_key": "vizard-from-app"})
    monkeypatch.setenv("VIZARD_API_KEY", "from-environment")
    fresh = Settings()
    assert fresh.gemini_api_key == "from-app"
    assert fresh.vizard_api_key == "from-environment"


def test_bad_settings_are_refused(client, vault, monkeypatch):
    assert client.put("/api/config", json={"values": {"database_url": "x"}}).status_code == 422
    assert client.put("/api/config", json={"values": {"youtube_privacy": "everyone"}}).status_code == 422
    monkeypatch.setenv("GEMINI_API_KEY", "set-outside")
    locked = client.put("/api/config", json={"values": {"gemini_api_key": "new"}})
    assert locked.status_code == 409 and "environment variable" in locked.json()["detail"]


def test_env_based_setups_show_keys_read_only(client):
    assert client.get("/api/config").json()["editable"] is False
    refused = client.put("/api/config", json={"values": {"gemini_api_key": "x"}})
    assert refused.status_code == 409 and ".env" in refused.json()["detail"]


def remove_password():
    with transaction() as db:
        db.delete(db.get(User, "owner"))


def test_first_run_creates_the_password_and_signs_in(client):
    from clipbot.api import app

    with TestClient(app, headers={"Origin": "http://localhost:3000"}) as fresh:
        remove_password()  # after start-up, which sets the test suite's ADMIN_PASSWORD
        assert fresh.get("/api/setup/status").json()["needs_password"] is True
        assert fresh.get("/api/studio").status_code == 401
        assert fresh.post("/api/setup/password", json={"password": "short"}).status_code == 422
        created = fresh.post("/api/setup/password", json={"password": "a long studio password"})
        assert created.status_code == 200
        assert fresh.get("/api/studio").status_code == 200  # signed in by the same request
        again = fresh.post("/api/setup/password", json={"password": "somebody else's password"})
        assert again.status_code == 409
    with TestClient(app, headers={"Origin": "https://elsewhere.example"}) as other:
        remove_password()
        assert (
            other.post("/api/setup/password", json={"password": "a long studio password"}).status_code == 403
        )


def test_a_password_is_only_forced_when_one_is_configured(monkeypatch):
    from clipbot import db as database

    monkeypatch.delenv("ADMIN_PASSWORD")
    unconfigured = Settings(_env_file=None)
    assert "admin_password" not in unconfigured.model_fields_set
    monkeypatch.setattr(database, "cfg", unconfigured)
    with transaction() as db:
        db.delete(db.get(User, "owner"))
    database.initialize()
    with Session() as db:
        assert db.get(User, "owner") is None  # left for the first-run screen


def test_the_dashboard_is_served_by_the_api(client, tmp_path, monkeypatch):
    (tmp_path / "_next/static/chunks").mkdir(parents=True)
    (tmp_path / "index.html").write_text("overview page")
    (tmp_path / "clips.html").write_text("clips page")
    (tmp_path / "404.html").write_text("not found page")
    (tmp_path / "_next/static/chunks/app.js").write_text("console.log(1)")
    (tmp_path.parent / "secret.txt").write_text("outside")
    monkeypatch.setattr(get_settings(), "frontend_dir", tmp_path)

    home = client.get("/")
    assert home.text == "overview page" and home.headers["x-frame-options"] == "DENY"
    assert home.headers["cache-control"] == "no-store"
    assert client.get("/clips").text == "clips page"
    script = client.get("/_next/static/chunks/app.js")
    assert "immutable" in script.headers["cache-control"]
    missing = client.get("/nothing-here")
    assert (missing.status_code, missing.text) == (404, "not found page")
    assert client.get("/..%2Fsecret.txt").status_code == 404
    assert client.get("/api/not-a-route").json() == {"detail": "Not found"}
    assert client.get("/health").json()["service"] == "clipbot"


def test_localhost_and_127_0_0_1_are_the_same_origin(monkeypatch):
    monkeypatch.setattr(get_settings(), "web_origin", "http://127.0.0.1:8742")
    assert origin_allowed("http://127.0.0.1:8742")
    assert origin_allowed("http://localhost:8742")
    assert not origin_allowed("http://localhost:9999")
    assert not origin_allowed("https://127.0.0.1:8742")
    assert not origin_allowed("https://clipbot.example")
    assert not origin_allowed(None)


async def test_the_worker_keeps_going_after_an_error_and_stops_when_asked(monkeypatch):
    stop = threading.Event()
    passes = []

    def sweep():
        passes.append(time.monotonic())
        if len(passes) == 1:
            raise RuntimeError("database is locked")

    async def drain(stopping):
        if len(passes) >= 2:
            stop.set()

    monkeypatch.setattr(local_worker, "sweep", sweep)
    monkeypatch.setattr(local_worker, "drain", drain)
    await asyncio.wait_for(local_worker.run(stop), timeout=15)
    assert len(passes) == 2


def test_desktop_keeps_the_database_apart_from_the_clips(tmp_path, monkeypatch, vault):
    monkeypatch.setenv("CLIPBOT_CONFIG_DIR", str(tmp_path / "config"))
    env = desktop.prepare_environment({"clips_dir": str(tmp_path / "clips"), "port": 8742})
    # The database stays in the app's own folder (the system drive); clips go where the owner chose.
    assert env["DATABASE_URL"] == f"sqlite:///{(tmp_path / 'config' / 'clipbot.db').as_posix()}"
    assert (env["STORAGE_ROOT"], env["SOURCE_DIRECTORY"]) == (
        str(tmp_path / "clips"),
        str(tmp_path / "clips" / "sources"),
    )
    assert env["WEB_ORIGIN"] == "http://127.0.0.1:8742"
    assert env["CLIPBOT_SETTINGS_DIR"] == str(tmp_path / "config")
    assert desktop.frontend_dir().parts[-3:] == ("apps", "frontend", "out")

    desktop.save_config({"clips_dir": "D:/ClipBot", "port": 9000})
    assert desktop.load_config() == {"clips_dir": "D:/ClipBot", "port": 9000}

    desktop.ensure_session_secret()
    first = vault.saved[("ClipBot", "session_secret")]
    desktop.ensure_session_secret()
    assert vault.saved[("ClipBot", "session_secret")] == first and len(first) > 40


@respx.mock
def test_connect_youtube_saves_the_login_and_adds_the_channel(client, vault, monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_mode", False)
    client.put("/api/config", json={"values": {"youtube_client_id": "id-1", "youtube_client_secret": "s-1"}})

    def google_redirect():
        url = youtube_login.connect_status()["url"]
        return {"state": urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0], "code": "c"}

    monkeypatch.setattr(youtube_login, "wait_for_redirect", google_redirect)
    monkeypatch.setattr(
        youtube_login,
        "exchange_code",
        lambda *args: {"refresh_token": "fresh-token", "access_token": "access"},
    )
    monkeypatch.setattr(youtube_login, "check_refresh_token", lambda *args: None)
    respx.get("https://www.googleapis.com/youtube/v3/channels").mock(
        return_value=httpx.Response(200, json={"items": [{"id": "UC1", "snippet": {"title": "Melancholy"}}]})
    )
    monkeypatch.setattr(youtube_login, "_connection", {"status": "idle", "message": "", "url": None})

    url = client.post("/api/youtube/connect", json={}).json()["url"]
    assert url.startswith(youtube_login.AUTH_URL) and "client_id=id-1" in url
    for _ in range(100):
        status = client.get("/api/youtube/connect").json()
        if status["status"] != "waiting":
            break
        time.sleep(0.05)
    assert status == {"connected": True, "status": "connected", "message": status["message"], "url": None}
    assert "Melancholy" in status["message"]
    assert vault.saved[("ClipBot", "youtube_refresh_token")] == "fresh-token"
    with Session() as db:
        channel = db.query(SocialAccount).filter_by(platform="youtube", demo=False).one()
        assert (channel.name, channel.external_id) == ("Melancholy", "UC1")


def test_connect_youtube_needs_the_client_first(client, vault):
    refused = client.post("/api/youtube/connect", json={})
    assert refused.status_code == 409 and "client ID and secret" in refused.json()["detail"]


def test_an_env_setup_moves_into_the_app(vault, tmp_path):
    env = tmp_path / "old.env"
    env.write_text(
        "OPUS_API_KEY=opus-secret\nYOUTUBE_CLIENT_ID=id-1\nMAX_CLIPS_PER_DAY=12\n"
        "DATABASE_URL=sqlite:///elsewhere.db\nSESSION_SECRET=old\nADMIN_PASSWORD=pw\n"
        "POSTGRES_PASSWORD=not-ours\nGEMINI_API_KEY=\n# VIZARD_API_KEY=commented\n",
        encoding="utf-8",
    )
    assert stored_settings.import_env_file(env) == {"keys": 1, "settings": 2}
    assert vault.saved == {("ClipBot", "opus_api_key"): "opus-secret"}
    plain = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert plain == {"youtube_client_id": "id-1", "max_clips_per_day": "12"}
    loaded = Settings(_env_file=None)
    assert (loaded.opus_api_key, loaded.max_clips_per_day) == ("opus-secret", 12)
    assert loaded.database_url != "sqlite:///elsewhere.db"  # this computer's paths stay the app's
