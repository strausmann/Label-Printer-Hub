"""Phase 7b Cluster 1e — first 4 readiness checks: database, alembic,
template_seed, printer_runtime."""

from __future__ import annotations

import pytest
from app.schemas.readiness import ReadinessResponse

pytestmark = pytest.mark.asyncio


class _FakeState:
    """Minimal stand-in for app.state with a printer_id."""

    def __init__(self, printer_id=None):
        self.printer_id = printer_id


async def test_build_readiness_with_all_ok(
    async_session_with_one_template, settings_at_head, runtime_printer_id
):
    from app.services.readiness import build_readiness_response

    state = _FakeState(printer_id=runtime_printer_id)
    body = await build_readiness_response(
        async_session_with_one_template,
        state,
        settings_at_head,
        version="dev",
        revision="abc",
    )
    assert isinstance(body, ReadinessResponse)
    for name in ("database", "alembic", "template_seed", "printer_runtime"):
        assert body.checks[name].status == "ok", f"{name} not ok: {body.checks[name]}"
    assert body.status == "ready"


async def test_build_readiness_template_seed_fails_when_empty(
    async_session_empty, settings_at_head
):
    from app.services.readiness import build_readiness_response

    state = _FakeState(printer_id=None)
    body = await build_readiness_response(
        async_session_empty,
        state,
        settings_at_head,
        version="dev",
        revision="abc",
    )
    assert body.checks["template_seed"].status == "fail"
    # template_seed is critical → aggregate is not-ready
    assert body.status == "not-ready"


async def test_build_readiness_printer_runtime_fails_when_no_id(
    async_session_with_one_template, settings_at_head
):
    from app.services.readiness import build_readiness_response

    state = _FakeState(printer_id=None)
    body = await build_readiness_response(
        async_session_with_one_template,
        state,
        settings_at_head,
        version="dev",
        revision="abc",
    )
    assert body.checks["printer_runtime"].status == "fail"
    # printer_runtime is non-critical → aggregate is degraded
    assert body.status == "degraded"
