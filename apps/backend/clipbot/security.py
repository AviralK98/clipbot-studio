import hashlib
import hmac
import ipaddress
import secrets
import socket
from urllib.parse import urlparse

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import get_settings


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return f"{salt}:{digest}"


def verify_password(password: str, stored: str) -> bool:
    salt, expected = stored.split(":")
    actual = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(actual, expected)


def signer():
    return URLSafeTimedSerializer(get_settings().session_secret, salt="clipbot-session")


def start_session(response, password_hash: str) -> None:
    """Sign the owner in. Changing the password changes the fingerprint and ends older sessions."""
    response.set_cookie(
        "clipbot_session",
        signer().dumps({"sub": "owner", "credential": hashlib.sha256(password_hash.encode()).hexdigest()}),
        httponly=True,
        secure=get_settings().app_env == "production",
        samesite="lax",
        max_age=43200,
        path="/",
    )


def origin_allowed(origin: str | None) -> bool:
    """The dashboard's own origin. On this computer, localhost and 127.0.0.1 are the same place."""
    expected = get_settings().web_origin
    if origin == expected:
        return True
    ours, theirs = urlparse(expected), urlparse(origin or "")
    loopback = {"localhost", "127.0.0.1"}
    return (
        ours.hostname in loopback
        and theirs.hostname in loopback
        and (ours.scheme, ours.port) == (theirs.scheme, theirs.port)
    )


def require_auth(request: Request):
    cfg = get_settings()
    token = request.headers.get("x-api-key", "")
    if cfg.api_token and hmac.compare_digest(token, cfg.api_token):
        return "owner"
    try:
        owner = signer().loads(request.cookies.get("clipbot_session", ""), max_age=43200)
        from .db import Session
        from .models import User

        with Session() as db:
            stored = db.get(User, "owner")
            fingerprint = hashlib.sha256(stored.password_hash.encode()).hexdigest() if stored else ""
        if (
            not isinstance(owner, dict)
            or owner.get("sub") != "owner"
            or not hmac.compare_digest(owner.get("credential", ""), fingerprint)
        ):
            raise BadSignature("Invalid user or rotated credential")
    except (BadSignature, SignatureExpired):
        raise HTTPException(401, "Sign in to your studio") from None
    if request.method not in {"GET", "HEAD", "OPTIONS"} and not origin_allowed(request.headers.get("origin")):
        raise HTTPException(403, "Invalid request origin")
    return owner


def public_url(url: str, resolve: bool = True) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("A public HTTP(S) URL without credentials is required")
    if parsed.port not in {None, 80, 443}:
        raise ValueError("Only standard web ports are supported")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Private network URLs are not supported")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        addresses = (
            [ipaddress.ip_address(r[4][0]) for r in socket.getaddrinfo(host, parsed.port or 443)]
            if resolve
            else []
        )
    if any(not addr.is_global for addr in addresses):
        raise ValueError("Private network URLs are not supported")
    return url
