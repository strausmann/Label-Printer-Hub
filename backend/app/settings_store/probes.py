"""Test-connection probes for the integrations. Never echo the secret."""

from __future__ import annotations

import httpx

_PROBES: dict[str, tuple[str, str | None]] = {
    # name: (path, header template or None); {s} is replaced with the secret
    "snipeit": ("/api/v1/hardware?limit=1", "Authorization: Bearer {s}"),
    "grocy": ("/api/system/info", "GROCY-API-KEY: {s}"),
    "spoolman": ("/api/v1/info", None),
    "paperless": ("/api/", "Authorization: Token {s}"),
}


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
            resp = await client.get(url.rstrip("/") + path, headers=headers)
    except httpx.TimeoutException:
        return False, None, "timeout"
    except httpx.HTTPError as exc:
        return False, None, f"connection failed ({type(exc).__name__})"
    if 200 <= resp.status_code < 300:
        return True, resp.status_code, "ok"
    return False, resp.status_code, f"HTTP {resp.status_code}"
