"""Phase 7b Cluster 1e — readiness aggregator (7 checks).

Checks implemented:
  database         — SELECT 1 latency (critical)
  alembic          — alembic_version at head (critical)
  printer_runtime  — app.state.printer_id set (non-critical)
  printer_db_sync  — runtime printer_id has a DB row (non-critical)
  snmp_discovery   — PrinterStatusCache recency (non-critical)
  print_queue      — print_queue in app.state (non-critical)
  sse_bus          — subscriber capacity (non-critical)

Phase 1k.1a Task 24: template_seed check removed (templates table dropped).
F4 wires the FastAPI route + HTTP status mapping.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.printer import Printer
from app.models.printer_status_cache import PrinterStatusCache
from app.schemas.readiness import CheckStatus, ReadinessResponse

_CRITICAL_CHECKS = ("database", "alembic")


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


def _runtime_printer_ids(app_state: Any) -> list[Any]:
    """The printers the hub runs: the first tape printer, else the page (IPP) printers.

    A hub whose only enabled printers are page printers has no ``printer_id`` but is
    still a working hub; a hub without any printer has neither.
    """
    pid = getattr(app_state, "printer_id", None)
    if pid is not None:
        return [pid]
    return list((getattr(app_state, "ipp_printer_states", None) or {}).keys())


def _check_printer_runtime(app_state: Any) -> CheckStatus:
    ids = _runtime_printer_ids(app_state)
    if not ids:
        return CheckStatus(status="fail", detail="app.state.printer_id is None")
    if getattr(app_state, "printer_id", None) is not None:
        return CheckStatus(status="ok", metric={"printer_id": str(ids[0])})
    return CheckStatus(status="ok", metric={"page_printers": len(ids)})


async def _check_printer_db_sync(session: AsyncSession, app_state: Any) -> CheckStatus:
    ids = _runtime_printer_ids(app_state)
    if not ids:
        return CheckStatus(status="skipped", detail="No runtime printer")
    for pid in ids:
        if await session.get(Printer, pid) is None:
            return CheckStatus(
                status="fail",
                detail=f"app.state.printer_id={pid} has no matching DB row",
            )
    return CheckStatus(status="ok")


_SEVERITY = {"ok": 0, "stale": 1, "fail": 2}


async def _check_snmp_discovery(session: AsyncSession, app_state: Any) -> CheckStatus:
    """Cache recency of the runtime printer; for page printers the worst of them counts."""
    ids = _runtime_printer_ids(app_state)
    if not ids:
        return CheckStatus(status="skipped", detail="No runtime printer")
    results = [await _check_cache_recency(session, pid) for pid in ids]
    return max(results, key=lambda r: _SEVERITY[r.status])


async def _check_cache_recency(session: AsyncSession, pid: Any) -> CheckStatus:
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
