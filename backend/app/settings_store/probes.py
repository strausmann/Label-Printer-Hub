"""Test-connection probes for the integrations. Never echo the secret."""

from __future__ import annotations

import httpx

from app.integrations.urls import api_url

_PROBES: dict[str, tuple[str, str | None]] = {
    # name: (path, header template or None); {s} is replaced with the secret
    "snipeit": ("/api/v1/hardware?limit=1", "Authorization: Bearer {s}"),
    "grocy": ("/api/system/info", "GROCY-API-KEY: {s}"),
    "spoolman": ("/api/v1/info", None),
    # Not "/api/": Paperless-ngx answers that with a 302 to the schema view for any caller.
    # The documents list answers 200 for a valid token and 401 otherwise.
    "paperless": ("/api/documents/?page_size=1", "Authorization: Token {s}"),
}

# Integrations whose users may type the API root ("/api") as part of the base URL.
_STRIP_API: frozenset[str] = frozenset({"paperless"})


async def probe_integration(
    name: str, *, url: str, secret: str, timeout: float
) -> tuple[bool, int | None, str]:
    path, header = _PROBES[name]
    headers: dict[str, str] = {"Accept": "application/json"}
    if header and secret:
        hname, _, template = header.partition(": ")
        headers[hname] = template.replace("{s}", secret)
    try:
        # follow_redirects=False: never forward the secret to a redirect target.
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            resp = await client.get(
                api_url(url, path, strip_api=name in _STRIP_API), headers=headers
            )
    except UnicodeError:
        return False, None, "invalid characters in the URL or secret"
    except httpx.TimeoutException:
        return False, None, "timeout"
    except httpx.HTTPError as exc:
        return False, None, f"connection failed ({type(exc).__name__})"
    if 200 <= resp.status_code < 300:
        return True, resp.status_code, "ok"
    return False, resp.status_code, f"HTTP {resp.status_code}"
