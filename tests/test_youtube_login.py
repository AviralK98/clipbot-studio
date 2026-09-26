"""The renew-youtube-login tool: consent URL, loopback redirect, token exchange, and the .env update."""

import threading
import time
import urllib.parse

import httpx
import pytest
import respx
from clipbot import youtube_login
from clipbot.youtube_login import SCOPES, TOKEN_URL, LoginError

ENV_TEXT = "ADMIN_PASSWORD=local\r\n# YOUTUBE_REFRESH_TOKEN=commented-out\r\nYOUTUBE_CLIENT_ID=client-123\r\nYOUTUBE_CLIENT_SECRET=secret-456\r\nYOUTUBE_REFRESH_TOKEN=old-token\r\n"


@pytest.fixture
def env_file(tmp_path):
    path = tmp_path / ".env"
    path.write_bytes(ENV_TEXT.encode())
    return path


def test_env_update_replaces_only_the_token_and_keeps_line_endings(env_file):
    youtube_login.write_env_value(env_file, "YOUTUBE_REFRESH_TOKEN", "new-token")
    text = env_file.read_bytes().decode()
    assert text == ENV_TEXT.replace("YOUTUBE_REFRESH_TOKEN=old-token", "YOUTUBE_REFRESH_TOKEN=new-token")
    assert "# YOUTUBE_REFRESH_TOKEN=commented-out" in text


def test_env_update_appends_a_missing_key(tmp_path):
    path = tmp_path / ".env"
    path.write_text("A=1\n", encoding="utf-8")
    youtube_login.write_env_value(path, "YOUTUBE_REFRESH_TOKEN", "t")
    assert path.read_text(encoding="utf-8") == "A=1\nYOUTUBE_REFRESH_TOKEN=t\n"


def test_consent_url_asks_for_all_scopes_offline_with_pkce():
    params = urllib.parse.parse_qs(urllib.parse.urlparse(youtube_login.consent_url("cid", "st", "ch")).query)
    assert params["scope"] == [" ".join(SCOPES)]
    assert params["access_type"] == ["offline"] and params["prompt"] == ["consent"]
    assert params["code_challenge_method"] == ["S256"] and params["code_challenge"] == ["ch"]
    assert params["redirect_uri"] == [youtube_login.REDIRECT_URI] and params["state"] == ["st"]


def test_loopback_server_captures_googles_redirect():
    result = {}
    thread = threading.Thread(target=lambda: result.update(youtube_login.wait_for_redirect(timeout=10)))
    thread.start()
    base = f"http://127.0.0.1:{youtube_login.PORT}"
    for _ in range(50):
        try:
            assert httpx.get(base + "/favicon.ico").status_code == 404
            page = httpx.get(base + "/oauth/callback?code=abc&state=s1")
            break
        except httpx.ConnectError:
            time.sleep(0.05)
    thread.join(timeout=10)
    assert page.status_code == 200 and b"All done" in page.content
    assert result == {"code": "abc", "state": "s1"}


def token_replies(scope=None):
    scope = scope or " ".join(SCOPES)
    return [
        httpx.Response(
            200, json={"access_token": "a", "refresh_token": "brand-new-refresh-token", "scope": scope}
        ),
        httpx.Response(200, json={"access_token": "b"}),
    ]


def run_main(env_file, monkeypatch, state_override=None):
    seen = {}

    def open_browser(url):
        seen["state"] = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]

    monkeypatch.setattr(
        youtube_login,
        "wait_for_redirect",
        lambda timeout=0: {"state": state_override or seen["state"], "code": "the-code"},
    )
    return youtube_login.main(env_file, open_browser=open_browser)


@respx.mock
def test_main_saves_the_new_token_without_printing_it(env_file, monkeypatch, capsys):
    route = respx.post(TOKEN_URL).mock(side_effect=token_replies())
    assert run_main(env_file, monkeypatch) == 0
    assert "YOUTUBE_REFRESH_TOKEN=brand-new-refresh-token\r\n" in env_file.read_bytes().decode()
    assert "brand-new-refresh-token" not in capsys.readouterr().out
    exchange = urllib.parse.parse_qs(route.calls[0].request.content.decode())
    assert exchange["grant_type"] == ["authorization_code"] and exchange["code"] == ["the-code"]
    assert exchange["code_verifier"][0]  # PKCE verifier sent with the code


@respx.mock
def test_unticked_permission_leaves_env_untouched(env_file, monkeypatch, capsys):
    respx.post(TOKEN_URL).mock(side_effect=token_replies(scope=SCOPES[0]))
    assert run_main(env_file, monkeypatch) == 1
    assert env_file.read_bytes().decode() == ENV_TEXT
    assert "not ticked: youtube.force-ssl, yt-analytics.readonly" in capsys.readouterr().out


def test_mismatched_state_is_rejected(env_file, monkeypatch, capsys):
    assert run_main(env_file, monkeypatch, state_override="forged") == 1
    assert env_file.read_bytes().decode() == ENV_TEXT
    assert "didn't match this request" in capsys.readouterr().out


@respx.mock
def test_google_refusal_is_reported():
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant", "error_description": "Bad code"})
    )
    with pytest.raises(LoginError, match="invalid_grant Bad code"):
        youtube_login.exchange_code("cid", "secret", "code", "verifier")
