import httpx

from ..errors import Ambiguous, Blocked, Transient


async def request_json(client: httpx.AsyncClient, method: str, url: str, **kwargs):
    """Retry GETs via jobs. Ambiguous POSTs require reconciliation, not duplicate charges."""
    mutating = method.upper() not in {"GET", "HEAD"}
    try:
        response = await client.request(method, url, **kwargs)
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise Transient("Could not connect to provider") from exc
    except httpx.TransportError as exc:
        if mutating:
            raise Ambiguous("Provider response lost; check provider dashboard and reconcile") from exc
        raise Transient("Provider read interrupted") from exc
    if response.status_code == 429:
        retry = response.headers.get("retry-after", "60")
        raise Transient("Provider rate limit", int(retry) if retry.isdigit() else 60)
    if response.status_code >= 500:
        if mutating:
            raise Ambiguous("Provider returned a server error after submission; reconcile")
        raise Transient("Provider temporarily unavailable")
    if response.status_code >= 400:
        raise Blocked(
            f"Provider rejected request (HTTP {response.status_code}); check scopes, credentials and contract"
        )
    try:
        return response.json()
    except ValueError as exc:
        if mutating:
            raise Ambiguous("Provider accepted request but returned an invalid response; reconcile") from exc
        raise Blocked("Provider response does not match documented JSON contract") from exc
