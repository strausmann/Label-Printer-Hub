"""Phase 7b Cluster 1e — readiness checks: database, alembic,
printer_runtime, printer_db_sync, snmp_discovery, print_queue, sse_bus.

Phase 1k.1a (Task 25): template_seed check removed from readiness.py
(templates table deleted). Tests for template_seed removed; fixture
renamed from async_session_with_one_template to async_session_with_one_printer.
"""

from __future__ import annotations

import types
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.models.printer import Printer
from app.models.printer_status_cache import PrinterStatusCache
from app.schemas.readiness import ReadinessResponse

pytestmark = pytest.mark.asyncio


class _FakeState:
    """Minimal stand-in for app.state with a printer_id."""

    def __init__(self, printer_id=None):
        self.printer_id = printer_id


# ---------------------------------------------------------------------------
# Helper for states that include print_queue + event_bus
# ---------------------------------------------------------------------------


def _state_with_queue_and_bus(printer_id=None, subs=0, max_subs=100):
    state = _FakeState(printer_id=printer_id)
    state.print_queue = types.SimpleNamespace(worker_count=lambda: 1)
    state.event_bus = types.SimpleNamespace(
        subscriber_count=lambda: subs,
        max_subscribers=max_subs,
    )
    return state


async def test_build_readiness_with_all_ok(
    async_session_with_one_printer, settings_at_head, runtime_printer_id
):
    from app.services.readiness import build_readiness_response

    # Use a state that includes print_queue + event_bus so all checks pass.
    state = _state_with_queue_and_bus(printer_id=runtime_printer_id)
    body = await build_readiness_response(
        async_session_with_one_printer,
        state,
        settings_at_head,
        version="dev",
        revision="abc",
    )
    assert isinstance(body, ReadinessResponse)
    # printer_db_sync will be fail (runtime_printer_id has no DB row) → degraded
    # but all critical checks pass.
    for name in ("database", "alembic", "printer_runtime"):
        assert body.checks[name].status == "ok", f"{name} not ok: {body.checks[name]}"
    assert body.status in {"ready", "degraded"}
    # template_seed check was removed in Phase 1k.1a
    assert "template_seed" not in body.checks


async def test_build_readiness_printer_runtime_fails_when_no_id(
    async_session_with_one_printer, settings_at_head
):
    from app.services.readiness import build_readiness_response

    state = _FakeState(printer_id=None)
    body = await build_readiness_response(
        async_session_with_one_printer,
        state,
        settings_at_head,
        version="dev",
        revision="abc",
    )
    assert body.checks["printer_runtime"].status == "fail"
    # printer_runtime is non-critical → aggregate is degraded
    assert body.status == "degraded"


# ---------------------------------------------------------------------------
# F3: printer_db_sync
# ---------------------------------------------------------------------------


async def test_check_printer_db_sync_skipped_when_no_runtime_id(
    async_session_with_one_printer, settings_at_head
):
    from app.services.readiness import build_readiness_response

    body = await build_readiness_response(
        async_session_with_one_printer,
        _state_with_queue_and_bus(printer_id=None),
        settings_at_head,
        version="v",
        revision="r",
    )
    assert body.checks["printer_db_sync"].status == "skipped"


async def test_check_printer_db_sync_fail_when_id_has_no_row(
    async_session_with_one_printer, settings_at_head
):
    from app.services.readiness import build_readiness_response

    body = await build_readiness_response(
        async_session_with_one_printer,
        _state_with_queue_and_bus(printer_id=uuid4()),  # any uuid; not in DB
        settings_at_head,
        version="v",
        revision="r",
    )
    assert body.checks["printer_db_sync"].status == "fail"


async def test_check_printer_db_sync_ok_when_row_exists(
    async_session_with_one_printer, settings_at_head
):
    pid = uuid4()
    # Insert a Printer row matching the runtime id
    async_session_with_one_printer.add(
        Printer(
            id=pid,
            name="x",
            model="pt-p750w",
            backend="mock",
            connection={"host": "192.0.2.50", "port": 9100},
            enabled=True,
        )
    )
    await async_session_with_one_printer.flush()

    from app.services.readiness import build_readiness_response

    body = await build_readiness_response(
        async_session_with_one_printer,
        _state_with_queue_and_bus(printer_id=pid),
        settings_at_head,
        version="v",
        revision="r",
    )
    assert body.checks["printer_db_sync"].status == "ok"


# ---------------------------------------------------------------------------
# F3: snmp_discovery
# ---------------------------------------------------------------------------


async def test_check_snmp_discovery_fail_when_no_probe_yet(
    async_session_with_one_printer, settings_at_head
):
    pid = uuid4()
    async_session_with_one_printer.add(
        Printer(
            id=pid,
            name="x",
            model="pt-p750w",
            backend="mock",
            connection={"host": "h", "port": 9100},
            enabled=True,
        )
    )
    await async_session_with_one_printer.flush()
    from app.services.readiness import build_readiness_response

    body = await build_readiness_response(
        async_session_with_one_printer,
        _state_with_queue_and_bus(printer_id=pid),
        settings_at_head,
        version="v",
        revision="r",
    )
    assert body.checks["snmp_discovery"].status == "fail"


async def test_check_snmp_discovery_ok_when_fresh(async_session_with_one_printer, settings_at_head):
    pid = uuid4()
    async_session_with_one_printer.add(
        Printer(
            id=pid,
            name="x",
            model="pt-p750w",
            backend="mock",
            connection={"host": "h", "port": 9100},
            enabled=True,
        )
    )
    async_session_with_one_printer.add(
        PrinterStatusCache(
            printer_id=pid,
            captured_at=datetime.now(UTC),
            parsed={"online": True, "tape_width_mm": 12},
            raw_block=None,
        )
    )
    await async_session_with_one_printer.flush()
    from app.services.readiness import build_readiness_response

    body = await build_readiness_response(
        async_session_with_one_printer,
        _state_with_queue_and_bus(printer_id=pid),
        settings_at_head,
        version="v",
        revision="r",
    )
    assert body.checks["snmp_discovery"].status == "ok"
    assert "last_probe_age_s" in body.checks["snmp_discovery"].metric


async def test_check_snmp_discovery_stale_between_90_and_600(
    async_session_with_one_printer, settings_at_head
):
    pid = uuid4()
    async_session_with_one_printer.add(
        Printer(
            id=pid,
            name="x",
            model="pt-p750w",
            backend="mock",
            connection={"host": "h", "port": 9100},
            enabled=True,
        )
    )
    async_session_with_one_printer.add(
        PrinterStatusCache(
            printer_id=pid,
            captured_at=datetime.now(UTC) - timedelta(seconds=200),
            parsed={"online": True},
            raw_block=None,
        )
    )
    await async_session_with_one_printer.flush()
    from app.services.readiness import build_readiness_response

    body = await build_readiness_response(
        async_session_with_one_printer,
        _state_with_queue_and_bus(printer_id=pid),
        settings_at_head,
        version="v",
        revision="r",
    )
    assert body.checks["snmp_discovery"].status == "stale"


# ---------------------------------------------------------------------------
# F3: print_queue
# ---------------------------------------------------------------------------


async def test_check_print_queue_fail_when_missing(
    async_session_with_one_printer, settings_at_head
):
    state = _FakeState(printer_id=uuid4())
    # NO print_queue attribute
    state.event_bus = types.SimpleNamespace(subscriber_count=lambda: 0, max_subscribers=100)
    from app.services.readiness import build_readiness_response

    body = await build_readiness_response(
        async_session_with_one_printer,
        state,
        settings_at_head,
        version="v",
        revision="r",
    )
    assert body.checks["print_queue"].status == "fail"


# ---------------------------------------------------------------------------
# F3: sse_bus
# ---------------------------------------------------------------------------


async def test_check_sse_bus_fail_when_subscribers_at_max(
    async_session_with_one_printer, settings_at_head
):
    from app.services.readiness import build_readiness_response

    body = await build_readiness_response(
        async_session_with_one_printer,
        _state_with_queue_and_bus(printer_id=uuid4(), subs=100, max_subs=100),
        settings_at_head,
        version="v",
        revision="r",
    )
    assert body.checks["sse_bus"].status == "fail"
