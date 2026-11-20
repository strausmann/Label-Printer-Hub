# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""A tape printer's address is for admin keys only (#234).

The connection of a tape printer (host, port, SNMP block) and the device error of a failed
probe name the printer's address. Read and print keys get neither; admin keys keep the
connection. The fixture runs the real lifespan with the model lookup and the status probe
patched, so no DNS or SNMP traffic happens.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import app.models  # noqa: F401
import ptouch
import pytest
import pytest_asyncio
from app.models.printer import Printer
from app.printer_backends.exceptions import PrinterOfflineError, StatusQueryFailedError
from httpx import ASGITransport, AsyncClient
from pysnmp.error import PySnmpError

from tests.integration.api.test_auth_session import _factory, _insert_key
from tests.integration.api.test_events_v1 import Stream, _connected, _key_header

pytestmark = pytest.mark.asyncio

HOST = "printer.example.invalid"
PJL = "MFG:Brother;CMD:PJL;MDL:PT-P750W;CLS:PRINTER;"
PROBE_ERROR = PySnmpError(
    f"Bad IPv4/UDP transport address {HOST}@161: [Errno -2] Name or service not known"
)


@dataclass
class Hub:
    app: Any
    client: AsyncClient
    printer_id: UUID

    async def probe(self) -> None:
        # The producer's own loop probes once at start; wait for that row so the driven probe
        # updates it instead of racing it on the insert.
        from app.models.printer_status_cache import PrinterStatusCache

        for _ in range(100):
            async with _factory()() as s:
                if await s.get(PrinterStatusCache, self.printer_id) is not None:
                    break
            await asyncio.sleep(0.05)
        wiring = self.app._app.state.printer_runtime._wired[self.printer_id]
        await wiring.producer._probe_once()


@pytest_asyncio.fixture
async def hub(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Hub]:
    import app.db.engine as _engine_module
    import app.db.session as _session_module
    from app.integrations import (  # type: ignore[attr-defined]
        IntegrationRegistry,
        _discover_plugins,
    )
    from app.main import create_app

    _session_module.async_session = _engine_module.async_session
    if not IntegrationRegistry.names():
        _discover_plugins()
    monkeypatch.setattr("app.services.printer_runtime.query_model_pjl", AsyncMock(return_value=PJL))
    monkeypatch.setattr(
        "app.services.producers.status_probe_producer.query_preflight",
        AsyncMock(side_effect=PROBE_ERROR),
    )
    async with _factory()() as s:
        printer = Printer(
            name="Tape",
            slug="tape-visibility",
            model="PT-P750W",
            backend="ptouch",
            connection={
                "host": HOST,
                "port": 9100,
                "snmp": {"discover": True, "community": "fake-community"},
            },
        )
        s.add(printer)
        await s.commit()
        await s.refresh(printer)
        printer_id = printer.id
    app = create_app()
    inner = app._app
    async with (
        inner.router.lifespan_context(inner),
        AsyncClient(transport=ASGITransport(app=inner), base_url="http://t") as client,
    ):
        yield Hub(app=app, client=client, printer_id=printer_id)


async def _get(hub: Hub, scope: str, path: str):
    key, _ = await _insert_key([scope])
    return await hub.client.get(path, headers=_key_header(key))


async def test_read_key_list_has_no_tape_address(hub: Hub) -> None:
    resp = await _get(hub, "read", "/api/v1/printers")
    assert resp.status_code == 200, resp.text
    row = next(p for p in resp.json() if p["id"] == str(hub.printer_id))
    assert row["connection"] == {}
    assert HOST not in resp.text


async def test_print_key_detail_has_no_tape_address(hub: Hub) -> None:
    resp = await _get(hub, "print", f"/api/v1/printers/{hub.printer_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["connection"] == {}
    assert HOST not in resp.text


async def test_admin_detail_keeps_host_port_and_community_set(hub: Hub) -> None:
    resp = await _get(hub, "admin", f"/api/v1/printers/{hub.printer_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["connection"] == {
        "host": HOST,
        "port": 9100,
        "snmp": {"discover": True, "community_set": True},
    }


async def test_failed_probe_status_has_no_host(hub: Hub) -> None:
    await hub.probe()
    key, _ = await _insert_key(["read"])
    path = f"/api/v1/printers/{hub.printer_id}/status"
    resp = await hub.client.get(path, headers=_key_header(key))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["online"] is False
    assert body["last_error"] == "PySnmpError"
    assert HOST not in resp.text

    stream = Stream(hub.app, "/api/v1/events", _key_header(key))
    try:
        await _connected(stream)
        status_ev = await stream.event_of_type("printer.status")
        assert HOST not in str(status_ev)
    finally:
        await stream.close()


_PRINT_BODY = {
    "content_type": "qr_two_lines",
    "data": {"title": "T", "primary_id": "ID-1", "qr_payload": "https://e.invalid"},
}


async def _failed_tape_job(hub: Hub, monkeypatch: pytest.MonkeyPatch, exc: Exception) -> dict:
    """Print on the tape printer with a backend that fails with *exc*; return the key headers.

    The key may read and print, so it sees its own failed job on ``/jobs`` and ``/queue``.
    """
    from app.printer_backends.mock_backend import MockPrinterBackend
    from app.printer_backends.ptouch_backend import _ptouch_errors

    async def print_fails(self: Any, *_a: Any, **_kw: Any) -> None:
        # The ptouch backend wraps the library's errors like this; other errors pass through.
        with _ptouch_errors():
            raise exc

    # The test environment builds mock backends; they stand in for the tape backend, whose
    # connection errors carry the address (ptouch_backend._ptouch_errors).
    monkeypatch.setattr(MockPrinterBackend, "print_image", print_fails)
    key, _ = await _insert_key(["read", "print"], rate_limit_per_minute=6000)
    headers = _key_header(key)
    resp = await hub.client.post("/api/v1/print", json=_PRINT_BODY, headers=headers)
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]
    for _ in range(100):
        job = (await hub.client.get(f"/api/v1/jobs/{job_id}", headers=headers)).json()
        assert "state" in job, job
        if job["state"] == "failed":
            return {"headers": headers, "job": job}
        await asyncio.sleep(0.05)
    raise AssertionError(f"job never failed: {job}")


@pytest.mark.parametrize(
    "exc",
    [
        PrinterOfflineError(f"Connection to printer at {HOST}:9100 timed out after 10s"),
        StatusQueryFailedError(f"Failed to connect to printer at {HOST}:9100"),
        OSError(f"[Errno -2] Name or service not known: {HOST}"),
        ptouch.PrinterWriteError(f"Failed to write to printer at {HOST}:9100: broken pipe"),
        ptouch.PrinterTimeoutError(f"Connection to printer at {HOST}:9100 timed out after 5s"),
    ],
    ids=["offline", "status_query", "generic", "ptouch_write", "ptouch_timeout"],
)
async def test_failed_tape_job_has_no_host(
    hub: Hub, monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    """The error of a failed tape job is readable with a read key: no host in it (#234)."""
    failed = await _failed_tape_job(hub, monkeypatch, exc)
    headers = failed["headers"]
    assert HOST not in str(failed["job"])
    listed = await hub.client.get("/api/v1/jobs", headers=headers)
    assert listed.status_code == 200, listed.text
    assert failed["job"]["id"] in listed.text  # the route returns the job: the check is not vacuous
    assert HOST not in listed.text
    one = await hub.client.get(f"/api/v1/jobs/{failed['job']['id']}", headers=headers)
    assert HOST not in one.text
    assert failed["job"]["error"]  # a failure still says something


async def test_no_route_shows_a_tape_address_to_a_read_key(
    hub: Hub, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard: the other routes a read key can reach never carry the tape address.

    A failed tape job exists first, so ``/jobs`` and ``/queue`` return data.
    """
    failed = await _failed_tape_job(
        hub, monkeypatch, PrinterOfflineError(f"Connection to printer at {HOST}:9100 timed out")
    )
    await hub.probe()
    headers = failed["headers"]
    for path in (
        f"/api/v1/printers/{hub.printer_id}/tape",
        f"/api/v1/printers/{hub.printer_id}/queue",
        "/api/v1/jobs",
    ):
        resp = await hub.client.get(path, headers=headers)
        # /tape answers 404 "printer offline" after the failed print; its body is checked too.
        assert resp.status_code in (200, 404), (path, resp.text)
        assert HOST not in resp.text, path
    jobs = await hub.client.get("/api/v1/jobs", headers=headers)
    assert failed["job"]["id"] in jobs.text

    stream = Stream(hub.app, "/api/v1/events", headers)
    try:
        await _connected(stream)
        seen = [await stream.event_of_type("printer.status")]
        assert HOST not in str(seen)
    finally:
        await stream.close()
