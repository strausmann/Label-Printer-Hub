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

from fastapi import FastAPI
from pydantic import BaseModel

from app import __version__


class Healthz(BaseModel):
    """Response body of /healthz.

    Intentionally minimal — no dependencies, no configuration, no PII.
    Container orchestrators check the HTTP status and read the JSON for
    a quick version sanity-check.
    """

    status: str
    version: str


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
    def healthz() -> Healthz:
        return Healthz(status="ok", version=__version__)

    return app


app = create_app()
