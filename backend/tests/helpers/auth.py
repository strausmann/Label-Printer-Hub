"""Shared auth bypass helpers for unit tests — Phase 7c.

Route unit tests call these helpers to override the require_scope dependency
with a no-op that returns a fake AuthContext. This avoids each test needing a
DB session and valid API key just to test route logic.
"""

from __future__ import annotations

from uuid import uuid4

from app.auth.dependencies import AuthContext, require_scope


_DEFAULT_AUTH_CONTEXT = AuthContext(
    source="api-key",
    scope="admin",  # admin satisfies everything
    api_key_id=uuid4(),
    ip="192.0.2.1",
)


def bypass_auth(app, *, scope: str = "admin", source: str = "api-key") -> None:
    """Override all require_scope dependencies on ``app`` with a passthrough.

    Call this in unit test app factories to skip auth verification.
    The override grants the specified scope (default: admin to satisfy all).

    Usage::

        app = FastAPI()
        app.include_router(some_router)
        bypass_auth(app)

    Or for scope-specific tests::

        bypass_auth(app, scope="read")
    """
    ctx = AuthContext(
        source=source,  # type: ignore[arg-type]
        scope=scope,    # type: ignore[arg-type]
        api_key_id=uuid4() if source == "api-key" else None,
        ip="192.0.2.1",
    )

    # Override all require_scope callables found in the dependency graph.
    # FastAPI stores dependencies by their callable identity, so we need to
    # replace the dependency at the route level for each registered scope.
    for route in app.routes:
        for dep in getattr(route, "dependencies", []):
            if dep.dependency in app.dependency_overrides:
                continue
            # Cover the 3 scope levels
            for level in ("read", "print", "admin"):
                app.dependency_overrides[require_scope(level)] = lambda _ctx=ctx: _ctx
