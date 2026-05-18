"""Named scope dependency singletons — Phase 7c.

Using named module-level dependency functions instead of inline require_scope()
calls makes it easy for tests to override via FastAPI's dependency_overrides
mechanism without needing to patch every callsite.

Usage in routes::

    from app.auth.scope_deps import require_read, require_print, require_admin
    from app.auth.dependencies import AuthContext

    @router.get("/api/printers")
    async def list_printers(
        session: SessionDep,
        _auth: Annotated[AuthContext, Depends(require_read)],
    ) -> list[...]:
        ...

Usage in unit tests::

    from app.auth.scope_deps import require_read
    from app.auth.dependencies import AuthContext
    from uuid import uuid4

    _FAKE_AUTH = AuthContext(source="api-key", scope="admin",
                             api_key_id=uuid4(), ip="192.0.2.1")

    def override_auth():
        return _FAKE_AUTH

    app.dependency_overrides[require_read] = override_auth
    app.dependency_overrides[require_print] = override_auth
    app.dependency_overrides[require_admin] = override_auth
"""

from __future__ import annotations

from app.auth.dependencies import require_scope

# Named singletons — importable and overridable by tests
require_read = require_scope("read")
require_print = require_scope("print")
require_admin = require_scope("admin")
