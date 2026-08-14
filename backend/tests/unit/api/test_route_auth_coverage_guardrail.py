"""Structural guardrail: every route must carry a recognised auth dependency
— or be explicitly and deliberately allowlisted here.

Why this exists (2026-08-14 security audit)
---------------------------------------------
Two REST endpoints shipped with NO auth dependency at all, while every
sibling endpoint in the same router file required one:

- ``GET /api/printers/{printer_id}`` (``printers.py::get_printer``) —
  ``list_printers``, ``get_printer_status``, ``get_printer_tape``,
  ``get_printer_queue``, ``pause_printer``, ``resume_printer`` and
  ``clear_printer_queue`` all required ``ReadAuthDep``/``PrintAuthDep``; the
  single-printer detail GET did not. It leaked full printer metadata
  (including the raw ``connection`` dict — host/port/SNMP config) to any
  caller that could reach the backend, with zero credentials.
- ``POST /api/jobs/{job_id}/retry`` (``jobs.py::retry_job``) — clones a
  terminal job into a fresh ``QUEUED`` job that the worker actually
  dispatches to the physical printer. ``list_jobs``, ``get_job`` and
  ``cancel_job`` in the same file all required ``read``/``print`` scope;
  ``retry_job`` (and, less severely, the ``pause``/``resume`` 501 stubs)
  did not — an unauthenticated caller could trigger real prints.

Both gaps were silent omissions (no docstring claims either is intentionally
public), unlike ``GET /api/events`` which documents "Auth: none beyond the
Pangolin proxy SSO at the network layer" right in its own module docstring,
or the ``qr.py`` landing pages which document "These routes intentionally
live outside the ``/api/`` prefix ... printed as QR payloads on physical
labels". Deliberate public-by-design routes are allowlisted below with a
pointer to where that decision is documented; anything else must resolve a
``require_read``/``require_print``/``require_admin``/``require_webhook_key``
dependency.

This test enumerates every ``APIRoute`` the real app (``app.main.create_app``)
actually mounts and fails the moment a NEW route is added without a
recognised auth dependency and without a conscious addition to the
allowlist — the guardrail fires while developing, not hopefully during
review (see ``.claude/rules/api-response-dto-boundary.md`` for the sibling
rule this generalises: enforcement belongs in the suite, upfront).
"""

from __future__ import annotations

from typing import Any

import app.models  # noqa: F401 — registers all SQLModel tables with metadata
from fastapi.routing import APIRoute

# ---------------------------------------------------------------------------
# Allowlist: routes that are deliberately reachable without an app-level
# auth dependency, and WHY. Every entry here is a conscious decision, not a
# gap — add to this list only alongside a docstring/comment at the route
# itself explaining the reasoning (matching the events.py / qr.py pattern).
# ---------------------------------------------------------------------------

_PUBLIC_BY_DESIGN: dict[tuple[str, str], str] = {
    ("GET", "/healthz"): "liveness probe — zero deps, no PII, own docstring",
    # /openapi.json, /docs, /docs/oauth2-redirect, /redoc are framework-added
    # Starlette Route objects (not APIRoute) — _iter_api_routes never visits
    # them, so they don't need (and can't take) an allowlist entry here.
    # /readiness is intentionally NOT allowlisted: it declares its own
    # Depends(require_read) and is correctly picked up as authenticated.
    ("GET", "/api/events"): "documented: 'Auth: none beyond the Pangolin proxy SSO "
    "at the network layer' (events.py module docstring)",
    ("GET", "/api/lookup/{app}/{entity_id}"): "read-only integration-entity lookup "
    "backing the public QR landing pages (lookup.py); same trust class as qr.py",
    ("GET", "/loc/{entity_id}"): "QR landing page — documented public-by-design "
    "(qr.py: 'printed as QR payloads on physical labels')",
    ("GET", "/asset/{entity_id}"): "QR landing page — see qr.py module docstring",
    ("GET", "/spool/{entity_id}"): "QR landing page — see qr.py module docstring",
    ("GET", "/product/{entity_id}"): "QR landing page — see qr.py module docstring",
}

# Dependency callables that count as "this route is authenticated". Matched
# by qualname substring so both the named singletons (require_read etc.,
# scope_deps.py) and the webhook key dependency are recognised regardless of
# how they're wired (function param vs. router-level `dependencies=[...]`).
_RECOGNISED_AUTH_MARKERS = ("require_scope", "require_webhook_key")


def _iter_api_routes(routes: list[Any]) -> list[APIRoute]:
    """Recursively flatten FastAPI's route tree into concrete APIRoute objects.

    Included routers show up as opaque wrapper objects (not the routes
    themselves) rather than being flattened into ``app.routes`` directly —
    each one exposes the original ``APIRouter`` via ``.original_router``.
    """
    out: list[APIRoute] = []
    for route in routes:
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            out.extend(_iter_api_routes(original_router.routes))
        elif isinstance(route, APIRoute):
            out.append(route)
    return out


def _collect_dependency_qualnames(dependant: Any) -> set[str]:
    names: set[str] = set()
    for sub in dependant.dependencies:
        fn = sub.call
        names.add(getattr(fn, "__qualname__", str(fn)))
        names |= _collect_dependency_qualnames(sub)
    return names


def _build_real_app() -> Any:
    """Return the actual FastAPI instance app.main mounts routes on.

    ``create_app()`` returns a ``_LifespanManager`` ASGI wrapper (so httpx's
    ASGITransport, which never sends a lifespan scope, still triggers
    startup) — the real ``FastAPI`` instance is its ``._app`` attribute.
    Building routes does not touch the DB or run the lifespan, so this is
    safe to call with no environment/DB setup beyond what module import
    already requires.
    """
    from app.main import create_app

    manager = create_app()
    return manager._app


def test_every_route_has_recognised_auth_or_is_explicitly_allowlisted() -> None:
    """Fail the build the moment a route ships with no recognised auth dependency.

    This is the guardrail: it re-discovers the exact class of bug this file's
    module docstring describes (GET /api/printers/{id}, POST
    /api/jobs/{id}/retry) and keeps rediscovering it for every future route.
    """
    app = _build_real_app()
    routes = _iter_api_routes(app.routes)
    assert routes, "expected at least one APIRoute — route discovery is broken"

    unguarded: list[str] = []
    for route in routes:
        for method in sorted(route.methods or []):
            if method == "HEAD":
                continue  # HEAD mirrors GET's auth — no separate handler
            key = (method, route.path)
            if key in _PUBLIC_BY_DESIGN:
                continue
            dep_names = _collect_dependency_qualnames(route.dependant)
            if any(marker in name for name in dep_names for marker in _RECOGNISED_AUTH_MARKERS):
                continue
            unguarded.append(f"{method} {route.path}")

    assert not unguarded, (
        "Route(s) with NO recognised auth dependency and NOT in the "
        "_PUBLIC_BY_DESIGN allowlist:\n  "
        + "\n  ".join(unguarded)
        + "\n\nEither add Depends(require_read/require_print/require_admin) "
        "(or require_webhook_key) to the route, or — only if this route is "
        "genuinely meant to be reachable without credentials — add it to "
        "_PUBLIC_BY_DESIGN in this file together with a comment at the "
        "route itself explaining why (see events.py / qr.py for the "
        "pattern)."
    )


def test_allowlist_entries_still_exist_as_routes() -> None:
    """Catch stale allowlist entries (renamed/removed routes) going forward.

    A shrinking allowlist that silently drops entries is as dangerous as a
    growing one that silently gains them — this keeps the allowlist honest.
    """
    app = _build_real_app()
    routes = _iter_api_routes(app.routes)
    live_keys = {(method, route.path) for route in routes for method in route.methods or []}

    stale = [key for key in _PUBLIC_BY_DESIGN if key not in live_keys]
    assert not stale, (
        f"Allowlist entries that no longer match any live route (stale — remove or fix): {stale}"
    )
