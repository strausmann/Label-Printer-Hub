"""Phase 7b Cluster 1e — readiness aggregator (all 8 checks).

Checks implemented:
  database         — SELECT 1 latency (critical)
  alembic          — alembic_version at head (critical)
  template_seed    — templates table non-empty (critical)
  printer_runtime  — app.state.printer_id set (non-critical)
  printer_db_sync  — runtime printer_id has a DB row (non-critical)
  snmp_discovery   — PrinterStatusCache recency (non-critical)
  print_queue      — print_queue in app.state (non-critical)
  sse_bus          — subscriber capacity (non-critical)

F4 wires the FastAPI route + HTTP status mapping.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.printer import Printer
from app.models.printer_status_cache import PrinterStatusCache
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


async def _check_printer_db_sync(session: AsyncSession, app_state: Any) -> CheckStatus:
    pid = getattr(app_state, "printer_id", None)
    if pid is None:
        return CheckStatus(status="skipped", detail="No runtime printer")
    row = await session.get(Printer, pid)
    if row is None:
        return CheckStatus(
            status="fail",
            detail=f"app.state.printer_id={pid} has no matching DB row",
        )
    return CheckStatus(status="ok")


async def _check_snmp_discovery(session: AsyncSession, app_state: Any) -> CheckStatus:
    pid = getattr(app_state, "printer_id", None)
    if pid is None:
        return CheckStatus(status="skipped", detail="No runtime printer")
    row = await session.get(PrinterStatusCache, pid)
    if row is None or row.captured_at is None:
        return CheckStatus(status="fail", detail="No SNMP probe recorded yet")
    captured = row.captured_at
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=UTC)
    age_s = int((datetime.now(UTC) - captured).total_seconds())
    metric: dict[str, Any] = {"last_probe_age_s": age_s}
    if age_s < 90:
        return CheckStatus(status="ok", metric=metric)
    if age_s < 600:
        return CheckStatus(status="stale", detail=f"{age_s}s ago (>90s)", metric=metric)
    return CheckStatus(
        status="fail",
        detail=f"{age_s}s ago (>600s) — printer offline?",
        metric=metric,
    )


def _check_print_queue(app_state: Any) -> CheckStatus:
    queue = getattr(app_state, "print_queue", None)
    if queue is None:
        return CheckStatus(status="fail", detail="print_queue not in app.state")
    worker_count_fn = getattr(queue, "worker_count", lambda: 1)
    return CheckStatus(status="ok", metric={"worker_count": worker_count_fn()})


def _check_sse_bus(app_state: Any, settings: Settings) -> CheckStatus:
    """Check SSE bus subscriber capacity.

    Supports both the real :class:`~app.services.event_bus.EventBus`
    (which exposes ``distinct_subscriber_count()``) and the lightweight
    ``types.SimpleNamespace`` fakes used in unit tests (which expose
    ``subscriber_count()`` and ``max_subscribers``).
    """
    bus = getattr(app_state, "event_bus", None)
    if bus is None:
        return CheckStatus(status="skipped", detail="event_bus not configured")
    # Prefer distinct_subscriber_count (real EventBus) — fall back to
    # subscriber_count (unit-test fakes that lack the real method).
    if hasattr(bus, "distinct_subscriber_count"):
        subs = bus.distinct_subscriber_count()
    else:
        subs = getattr(bus, "subscriber_count", lambda: 0)()
    # max_subscribers comes from Settings on the real bus; fakes expose it
    # directly as an attribute for hermetic unit tests.
    max_subs = getattr(bus, "max_subscribers", None) or settings.sse_max_subscribers
    metric: dict[str, Any] = {"subscribers": subs, "max": max_subs}
    if subs >= max_subs:
        return CheckStatus(status="fail", detail="subscriber pool exhausted", metric=metric)
    return CheckStatus(status="ok", metric=metric)


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
    """Run all 8 readiness checks and aggregate the result."""
    checks: dict[str, CheckStatus] = {
        "database": await _check_database(session),
        "alembic": await _check_alembic(settings),
        "template_seed": await _check_template_seed(session),
        "printer_runtime": _check_printer_runtime(app_state),
        "printer_db_sync": await _check_printer_db_sync(session, app_state),
        "snmp_discovery": await _check_snmp_discovery(session, app_state),
        "print_queue": _check_print_queue(app_state),
        "sse_bus": _check_sse_bus(app_state, settings),
    }
    return ReadinessResponse(
        status=_aggregate(checks),
        checks=checks,
        version=version,
        revision=revision,
    )
