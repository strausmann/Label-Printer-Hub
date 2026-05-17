"""Phase 7b Cluster 1e — readiness aggregator (first 4 checks).

F3 adds the remaining 4 checks (printer_db_sync, snmp_discovery,
print_queue, sse_bus). F4 wires the FastAPI route + HTTP status mapping.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.template import Template
from app.schemas.readiness import CheckStatus, ReadinessResponse

_CRITICAL_CHECKS = ("database", "alembic", "template_seed")


async def _check_database(session: AsyncSession) -> CheckStatus:
    try:
        t0 = time.monotonic()
        await session.execute(text("SELECT 1"))
        latency_ms = round((time.monotonic() - t0) * 1000, 2)
        return CheckStatus(status="ok", metric={"latency_ms": latency_ms})
    except Exception as exc:
        return CheckStatus(status="fail", detail=str(exc))


async def _check_alembic(settings: Settings) -> CheckStatus:
    from app.db.lifespan import verify_alembic_at_head

    try:
        await verify_alembic_at_head(settings)
        return CheckStatus(status="ok")
    except Exception as exc:
        return CheckStatus(status="fail", detail=str(exc))


async def _check_template_seed(session: AsyncSession) -> CheckStatus:
    count = await session.scalar(select(func.count()).select_from(Template))
    cnt = int(count or 0)
    if cnt >= 1:
        return CheckStatus(status="ok", metric={"templates_in_db": cnt})
    return CheckStatus(
        status="fail",
        detail="Templates table is empty — lifespan init-order regression?",
        metric={"templates_in_db": cnt},
    )


def _check_printer_runtime(app_state: Any) -> CheckStatus:
    pid = getattr(app_state, "printer_id", None)
    if pid is None:
        return CheckStatus(status="fail", detail="app.state.printer_id is None")
    return CheckStatus(status="ok", metric={"printer_id": str(pid)})


def _aggregate(checks: dict[str, CheckStatus]) -> Literal["ready", "degraded", "not-ready"]:
    if any(checks[name].status == "fail" for name in _CRITICAL_CHECKS if name in checks):
        return "not-ready"
    if any(c.status == "fail" for c in checks.values()):
        return "degraded"
    return "ready"


async def build_readiness_response(
    session: AsyncSession,
    app_state: Any,
    settings: Settings,
    *,
    version: str,
    revision: str,
) -> ReadinessResponse:
    """Run all readiness checks and aggregate the result.

    F2 covers the first four checks. F3 will extend ``checks`` with
    printer_db_sync, snmp_discovery, print_queue, sse_bus. The aggregate
    helper already handles the additional check names — extending the
    dict is purely additive.
    """
    checks: dict[str, CheckStatus] = {
        "database": await _check_database(session),
        "alembic": await _check_alembic(settings),
        "template_seed": await _check_template_seed(session),
        "printer_runtime": _check_printer_runtime(app_state),
    }
    return ReadinessResponse(
        status=_aggregate(checks),
        checks=checks,
        version=version,
        revision=revision,
    )
