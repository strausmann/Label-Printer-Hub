"""Startup wiring of IPP page printers: one status producer each, no tape wiring.

Runs the real lifespan against a stored ``ipp`` printer whose transport is the fake printer.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin, require_print, require_read
from app.models.printer import Printer
from app.models.printer_status_cache import PrinterStatusCache
from httpx import ASGITransport, AsyncClient

from tests.helpers.fake_ipp_printer import FAKE_URI, FakeIppPrinter


async def _until(predicate, timeout_s: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if await predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not reached in time")


@pytest.mark.parametrize("enabled", [True, False])
async def test_ipp_printer_gets_a_producer_and_print_answers_503(enabled: bool) -> None:
    import app.db.engine as eng
    from app.main import create_app

    fake = FakeIppPrinter(reasons=["media-empty-error"])
    async with eng.async_session() as s:
        printer = Printer(
            name="Page",
            slug="page-1",
            model="x",
            backend="ipp",
            connection={"uri": FAKE_URI, "tls_verify": True},
            enabled=enabled,
        )
        s.add(printer)
        await s.commit()
        pid = printer.id

    app = create_app()
    inner = app._app
    inner.state.ipp_transport_factory = lambda _uri: ASGITransport(app=fake)
    fake_auth = AuthContext(source="api-key", scope="admin", api_key_id=uuid4(), ip="127.0.0.1")
    for dep in (require_read, require_print, require_admin):
        inner.dependency_overrides[dep] = lambda _c=fake_auth: _c

    async with inner.router.lifespan_context(inner):
        states = inner.state.ipp_printer_states
        if enabled:

            async def _cached() -> bool:
                async with eng.async_session() as s:
                    return await s.get(PrinterStatusCache, pid) is not None

            await _until(_cached)
            assert pid in states and states[pid].status is not None
            assert states[pid].status.blocking_reason == "media-empty"
        else:
            await asyncio.sleep(0.1)
            assert states == {}
            async with eng.async_session() as s:
                assert await s.get(PrinterStatusCache, pid) is None
        # IPP-only install: no tape print service, so /print answers a clear 503.
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post(
                "/print",
                json={
                    "content_type": "qr_two_lines",
                    "data": {"title": "T", "primary_id": "P-1", "qr_payload": "https://e.x"},
                },
            )
        assert r.status_code == 503, r.text
        assert r.json()["error_code"] == "no_tape_printer"
        assert "error_message" in r.json()


async def test_bad_stored_uri_does_not_stop_startup() -> None:
    import app.db.engine as eng
    from app.main import create_app

    async with eng.async_session() as s:
        s.add(
            Printer(
                name="Broken",
                slug="page-bad",
                model="x",
                backend="ipp",
                connection={"uri": "ftp://nope"},
                enabled=True,
            )
        )
        await s.commit()
    app = create_app()
    inner = app._app
    async with inner.router.lifespan_context(inner):
        assert inner.state.ipp_printer_states == {}
