"""Webhook API-key authentication dependency.

Protects the webhook routes (``/api/webhook/spoolman``,
``/api/webhook/grocy``) behind a shared-secret header check.

Usage::

    from fastapi import Depends
    from app.api.dependencies.webhook_auth import require_webhook_key

    @router.post("/api/webhook/spoolman", dependencies=[Depends(require_webhook_key)])
    async def spoolman_webhook(...) -> ...:
        ...

The key is read from ``app.config.Settings.webhook_api_key`` (env var
``PRINTER_HUB_WEBHOOK_API_KEY``) via :func:`app.config.get_settings`, which
is ``@lru_cache``-decorated so the env var is read once at startup rather than
on every request.

A missing key (empty string) returns **503** rather than 401 — this gives the
operator a clear signal that the service is misconfigured, not that the caller
supplied a wrong key.

Note
----
The ``config.py`` validator rejects keys shorter than 32 characters, so any
non-empty value that reaches this function is already validated.

References:
    docs/superpowers/specs/2026-05-16-phase6a-rest-api-design.md
    app/config.py — Settings.webhook_api_key validator
"""

from __future__ import annotations

import hmac

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings


async def require_webhook_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> None:
    """FastAPI dependency that validates the ``X-API-Key`` header.

    Raises
    ------
    HTTPException(503)
        When ``PRINTER_HUB_WEBHOOK_API_KEY`` is not set (empty string).
    HTTPException(401)
        When the supplied key does not match the configured key.
    """
    expected = settings.webhook_api_key.get_secret_value()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook auth not configured (PRINTER_HUB_WEBHOOK_API_KEY missing)",
        )
    if not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
