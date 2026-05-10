"""FastAPI application entry point.

This module exposes the ASGI app that uvicorn runs in the container. It owns:

- The OpenAPI metadata (title, version, description, /openapi.json, /docs, /redoc)
- The /healthz endpoint for container orchestrators
- (Forthcoming) the registration of all API routers (printers, jobs, layouts, …)

Routers live under :mod:`app.api` and are mounted here. Keeping the app
instance in one place makes it trivial for tests to import.

See:
    docs/decisions/0002-python-fastapi-backend.md — choice of FastAPI
    docs/decisions/0011-openapi-as-api-contract.md — /openapi.json contract
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, ConfigDict

from app import __version__

# Per ADR 0011 we pin the OpenAPI version explicitly rather than relying on
# FastAPI's default, so a FastAPI upgrade can't drift the API contract version.
OPENAPI_VERSION = "3.1.0"

# Build-info ENV vars are set by the Dockerfile at build time. Fall back to
# sensible defaults so local non-container runs and unit tests still work.
HUB_VERSION: str = os.environ.get("HUB_VERSION") or __version__
HUB_REVISION: str = os.environ.get("HUB_REVISION", "unknown")
HUB_BUILD_DATE: str = os.environ.get("HUB_BUILD_DATE", "1970-01-01T00:00:00Z")
HUB_REPO_URL: str = os.environ.get(
    "HUB_REPO_URL", "https://github.com/strausmann/label-printer-hub"
)


class Healthz(BaseModel):
    """Response body of /healthz.

    Intentionally minimal — no dependencies, no configuration, no PII.
    Container orchestrators check the HTTP status and read the JSON for
    a quick version sanity-check; ops use the build-info fields to confirm
    which image is running without digging through ``docker inspect``.

    Frozen so callers can't accidentally mutate the response model in-place
    (the same immutability discipline we apply to dataclasses — see
    ``docs/learnings/code-review-patterns.md``).
    """

    model_config = ConfigDict(frozen=True)

    status: str
    version: str
    revision: str
    build_date: str
    repository: str


def _pinned_openapi_schema(app: FastAPI) -> Any:
    """Build the OpenAPI schema with an explicitly pinned version.

    Per ADR 0011 we lock the OpenAPI document version to a known value so a
    future FastAPI upgrade can't silently change it. We do this by overriding
    ``app.openapi`` with a function that calls FastAPI's own ``get_openapi``
    with our chosen ``openapi_version`` — that is the framework-supported
    extension point and stays stable across FastAPI releases. The result is
    cached on ``app.openapi_schema`` so the schema is only built once.
    """
    if app.openapi_schema:
        return app.openapi_schema
    app.openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=OPENAPI_VERSION,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
        servers=app.servers,
    )
    return app.openapi_schema


def create_app() -> FastAPI:
    """Build the FastAPI app. Kept as a factory so tests can re-instantiate."""
    app = FastAPI(
        title="Label Printer Hub — backend",
        description=(
            "REST + SSE API for the Label Printer Hub backend. "
            "The Go frontend consumes the OpenAPI spec at /openapi.json via "
            "oapi-codegen; humans browse the interactive docs at /docs "
            "(Swagger UI) or /redoc."
        ),
        version=__version__,
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    # Pin the OpenAPI document version per ADR 0011 via the supported
    # extension point: replace `app.openapi` with our wrapped builder.
    app.openapi = lambda: _pinned_openapi_schema(app)  # type: ignore[method-assign]

    @app.get(
        "/healthz",
        response_model=Healthz,
        tags=["meta"],
        summary="Liveness probe",
        description=(
            "Returns 200 OK with a fixed shape. No authentication required. "
            "Used by Docker, Kubernetes, and reverse proxies to decide whether "
            "the backend is up. Has zero dependencies — does not touch the "
            "database, the printer queue, SNMP, or any integration."
        ),
    )
    async def healthz() -> Healthz:
        # async def avoids the threadpool roundtrip for this hot, dependency-
        # free endpoint. FastAPI runs sync route handlers in a threadpool
        # by default, which is wasted overhead for trivial responders.
        return Healthz(
            status="ok",
            version=HUB_VERSION,
            revision=HUB_REVISION,
            build_date=HUB_BUILD_DATE,
            repository=HUB_REPO_URL,
        )

    return app


app = create_app()
