"""Renew ClipBot's YouTube login and save the new refresh token into .env.

While the Google OAuth app is in "Testing", Google expires refresh tokens after 7 days.
Run `python -m clipbot.youtube_login` (or double-click renew-youtube-login.bat) from the project
folder: your browser opens Google's sign-in, you approve, and the new token is written to .env.
The token is never printed.

One-time setup for a "Web application" OAuth client: add REDIRECT_URI below to the client's
Authorized redirect URIs in Google Cloud. "Desktop app" clients accept it without setup.
"""

import base64
import hashlib
import secrets
import socket
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx

PORT = 8765
REDIRECT_URI = f"http://localhost:{PORT}/oauth/callback"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
)
WAIT_SECONDS = 300
DONE_PAGE = (
    b"<!doctype html><meta charset=utf-8><title>ClipBot</title>"
    b"<body style='font-family:sans-serif;padding:40px'><h2>All done</h2>"
    b"<p>You can close this tab and go back to the ClipBot window.</p>"
)


class LoginError(RuntimeError):
    pass


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_env_value(path: Path, key: str, value: str) -> None:
    """Set KEY=value in .env, keeping every other line and the file's line endings as they were."""
    # newline="" keeps "\r\n" as-is; read_text would silently turn it into "\n".
    with open(path, encoding="utf-8", newline="") as stream:
        text = stream.read()
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key and not line.lstrip().startswith("#"):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    path.write_text(newline.join(lines) + newline, encoding="utf-8", newline="")


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def consent_url(client_id: str, state: str, challenge: str) -> str:
    return (
        AUTH_URL
        + "?"
        + urllib.parse.urlencode(
            {
                "client_id": client_id,
                "redirect_uri": REDIRECT_URI,
                "response_type": "code",
                "scope": " ".join(SCOPES),
                "access_type": "offline",
                "prompt": "consent",  # always return a refresh token
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
    )


def wait_for_redirect(timeout: float = WAIT_SECONDS) -> dict[str, str]:
    """Serve the loopback redirect on IPv4 and IPv6 localhost; return its query parameters."""
    received: dict[str, str] = {}
    arrived = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path != "/oauth/callback":
                self.send_error(404)
                return
            if not arrived.is_set():
                received.update({k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()})
                arrived.set()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DONE_PAGE)

        def log_message(self, *args):  # keep the console quiet
            pass

    class IPv6Server(HTTPServer):
        address_family = socket.AF_INET6

    servers = []
    for server_class, host in ((HTTPServer, "127.0.0.1"), (IPv6Server, "::1")):
        try:
            servers.append(server_class((host, PORT), Handler))
        except OSError:
            continue  # e.g. no IPv6 loopback; the other address still works
    if not servers:
        raise LoginError(f"Port {PORT} is busy; close whatever is using it and try again")
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        if not arrived.wait(timeout):
            raise LoginError(
                "Timed out waiting for Google. If Google showed an error page such as "
                f"'redirect_uri_mismatch', add {REDIRECT_URI} to your OAuth client's Authorized redirect URIs "
                "in Google Cloud (Google Auth Platform, then Clients), then run this again"
            )
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
    return received


def exchange_code(client_id: str, client_secret: str, code: str, verifier: str) -> dict:
    response = httpx.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        },
        timeout=30,
    )
    data = response.json()
    if response.status_code != 200:
        raise LoginError(
            f"Google refused the sign-in: {data.get('error')} {data.get('error_description', '')}"
        )
    if not data.get("refresh_token"):
        raise LoginError("Google didn't return a refresh token; run it again and approve every permission")
    granted = set(data.get("scope", "").split())
    missing = [scope.rsplit("/", 1)[-1] for scope in SCOPES if scope not in granted]
    if missing:
        raise LoginError(
            f"These permissions were not ticked: {', '.join(missing)}. Run it again and tick all of them"
        )
    return data


def check_refresh_token(client_id: str, client_secret: str, refresh_token: str) -> None:
    response = httpx.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise LoginError("The new login didn't work when tested; run it again")


def main(env_path: Path = Path(".env"), open_browser=webbrowser.open) -> int:
    if not env_path.is_file():
        print(f"Can't find {env_path.resolve()}; run this from the clipbot-studio folder.")
        return 1
    env = read_env(env_path)
    client_id, client_secret = env.get("YOUTUBE_CLIENT_ID"), env.get("YOUTUBE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set in .env first.")
        return 1
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    url = consent_url(client_id, state, challenge)
    print("Opening Google sign-in in your browser. Sign in, tick every permission, and approve.")
    print("(If Google says the app isn't verified, click Continue: it's your own app.)")
    print(f"\nIf no browser opens, paste this into one:\n{url}\n")
    open_browser(url)
    try:
        reply = wait_for_redirect()
        if reply.get("state") != state:
            raise LoginError("The sign-in reply didn't match this request; run it again")
        if "error" in reply:
            raise LoginError(f"Google sign-in was cancelled or refused ({reply['error']})")
        tokens = exchange_code(client_id, client_secret, reply.get("code", ""), verifier)
        check_refresh_token(client_id, client_secret, tokens["refresh_token"])
    except LoginError as exc:
        print(f"\nNot renewed: {exc}")
        return 1
    write_env_value(env_path, "YOUTUBE_REFRESH_TOKEN", tokens["refresh_token"])
    print("\nYouTube login renewed and saved to .env.")
    print("Restart ClipBot (backend and worker) so it uses the new login. It lasts 7 days.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
