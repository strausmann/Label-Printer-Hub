"""Flatten FastAPI's route tree for tests that inspect every route.

Included routers show up as opaque wrapper objects rather than being flattened into
``app.routes``; each exposes the original ``APIRouter`` via ``.original_router``. A naive walk
of ``app.routes`` therefore misses nearly every route and can pass vacuously.
"""

from __future__ import annotations

from typing import Any

from fastapi.routing import APIRoute
from starlette.routing import BaseRoute


def iter_routes(routes: list[Any]) -> list[BaseRoute]:
    """Every concrete route: ``APIRoute``s and top-level Starlette ``Route``s (the SPA)."""
    out: list[BaseRoute] = []
    for route in routes:
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            out.extend(iter_routes(original_router.routes))
        elif hasattr(route, "path"):
            out.append(route)
    return out


def iter_api_routes(routes: list[Any]) -> list[APIRoute]:
    """Only the ``APIRoute``s of :func:`iter_routes`."""
    return [r for r in iter_routes(routes) if isinstance(r, APIRoute)]
