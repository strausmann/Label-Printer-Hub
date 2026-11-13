"""Startup robustness of the lifespan (#264 seed, #265 producer start).

A failing seed must not block startup; a failing ``PrinterRuntime.start`` must still stop the
producers it already started.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin, require_print, require_read
from app.models.printer import Printer
from app.services.printer_runtime import PrinterRuntime
from httpx import ASGITransport, AsyncClient

from tests.helpers.fake_ipp_printer import FAKE_URI, FakeIppPrinter


async def test_failing_sheet_seed_does_not_block_startup(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """264-09: a seed that raises is logged once; the hub starts and answers ``/healthz``."""

    async def _boom(_factory: Any) -> None:
        raise RuntimeError("seed failed")

    with (
        patch("app.seed.sheet_seed.run_sheet_seed", _boom),
        caplog.at_level(logging.ERROR, logger="app.main"),
    ):
        response = await client.get("/healthz")  # the first request starts the lifespan
    assert response.status_code == 200
    failures = [r for r in caplog.records if "Sheet type seeding failed" in r.getMessage()]
    assert len(failures) == 1


async def test_start_failure_stops_started_producers() -> None:
    """265-04: ``runtime.start()`` raising after it started producers still reaches
    ``runtime.stop()``; no probe task outlives the failed startup."""
    import app.db.engine as eng
    from app.main import create_app

    async with eng.async_session() as s:
        printer = Printer(
            name="Page",
            slug="page-1",
            model="x",
            backend="ipp",
            connection={"uri": FAKE_URI, "tls_verify": True},
            enabled=True,
        )
        s.add(printer)
        await s.commit()

    app = create_app()
    inner = app._app
    fake = FakeIppPrinter()
    inner.state.ipp_transport_factory = lambda _uri: ASGITransport(app=fake)
    auth = AuthContext(source="api-key", scope="admin", api_key_id=uuid4(), ip="127.0.0.1")
    for dep in (require_read, require_print, require_admin):
        inner.dependency_overrides[dep] = lambda _c=auth: _c

    real_start = PrinterRuntime.start
    started: list[Any] = []

    async def _start_then_fail(self: PrinterRuntime) -> None:
        await real_start(self)
        started.extend(w.producer for w in self._wired.values())
        raise RuntimeError("start failed")

    runtime_seen: list[PrinterRuntime] = []
    real_stop = PrinterRuntime.stop

    async def _stop(self: PrinterRuntime) -> None:
        runtime_seen.append(self)
        await real_stop(self)

    with (
        patch.object(PrinterRuntime, "start", _start_then_fail),
        patch.object(PrinterRuntime, "stop", _stop),
        pytest.raises(RuntimeError, match="start failed"),
    ):
        async with inner.router.lifespan_context(inner):
            pytest.fail("the lifespan must not reach the yield")  # pragma: no cover
    assert len(runtime_seen) == 1  # stop() ran
    assert started and all(p is not None for p in started)
    assert all(p._task is not None and p._task.done() for p in started)
