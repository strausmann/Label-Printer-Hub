"""Admin changes take effect live (#224): no hub restart between a save and its effect.

Runs the real lifespan (``lifespan_context``, so the runtime stops cleanly after each test)
with two fake IPP printers behind ``app.state.ipp_transport_factory`` and SNMP patched; no
network is touched. The probe interval is 0.2 s and the page-job poll interval 0.05 s, so
every wait is short; each is bounded.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import app.models  # noqa: F401
import httpx
import pytest
import pytest_asyncio
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin, require_print, require_read
from app.config import get_settings
from app.models.job import Job as DbJob
from app.models.printer import Printer
from app.printer_backends.snmp_helper import PreflightStatus
from app.services.page_job_runner import PageJobRunner
from app.sheets import type_service as ts
from app.sheets.geometry import Geometry
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.helpers.fake_ipp_printer import FakeIppPrinter

pytestmark = pytest.mark.asyncio

URI = "ipp://printer.example.invalid/ipp/print"
URI_2 = "ipps://second-printer.example.invalid/ipp/print"
ADMIN = "/api/v1/admin/printers"
INTERVAL_S = 0.2
WAIT_S = 10.0
G48 = Geometry("A4", 21000, 29700, 4570, 2120, 4, 12, 4820, 2120, 2130, 985, None, "rectangle")


@dataclass
class Live:
    client: AsyncClient
    app: Any
    fakes: dict[str, FakeIppPrinter]
    factory_calls: list[str] = field(default_factory=list)

    def gpa(self, uri: str) -> int:
        """Get-Printer-Attributes requests (admin probe or status probe) on *uri*'s printer."""
        return [r.operation for r in self.fakes[uri].received].count("Get-Printer-Attributes")

    def print_jobs(self, uri: str) -> int:
        return [r.operation for r in self.fakes[uri].received].count("Print-Job")

    @property
    def runtime(self) -> Any:
        return self.app.state.printer_runtime


def _factory():
    import app.db.engine as _engine_module

    return _engine_module.async_session


@pytest_asyncio.fixture
async def live(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Live]:
    from app.integrations import (  # type: ignore[attr-defined]
        IntegrationRegistry,
        _discover_plugins,
    )
    from app.main import create_app

    if not IntegrationRegistry.names():
        _discover_plugins()
    monkeypatch.setenv("PRINTER_HUB_SSE_PROBE_INTERVAL_S", str(INTERVAL_S))
    monkeypatch.setattr(
        "app.services.print_queue.PageJobRunner",
        functools.partial(PageJobRunner, poll_interval_s=0.05),
    )
    get_settings.cache_clear()
    fakes = {u: FakeIppPrinter(media_sources=["tray-1", "tray-2"]) for u in (URI, URI_2)}
    app = create_app()
    inner = app._app
    h = Live(client=None, app=inner, fakes=fakes)  # type: ignore[arg-type]

    def factory(uri: str) -> httpx.AsyncBaseTransport:
        h.factory_calls.append(uri)
        return ASGITransport(app=fakes[uri])

    inner.state.ipp_transport_factory = factory
    auth = AuthContext(source="api-key", scope="admin", api_key_id=uuid4(), ip="127.0.0.1")
    for dep in (require_read, require_print, require_admin):
        inner.dependency_overrides[dep] = lambda _c=auth: _c
    try:
        async with (
            inner.router.lifespan_context(inner),
            AsyncClient(transport=ASGITransport(app=inner), base_url="http://t") as c,
        ):
            h.client = c
            yield h
    finally:
        get_settings.cache_clear()


async def _until(
    predicate: Callable[[], Awaitable[bool]],
    what: str | Callable[[], str],
    timeout_s: float = WAIT_S,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if await predicate():
            return
        await asyncio.sleep(0.02)
    text = what() if callable(what) else what
    raise AssertionError(f"not reached within {timeout_s} s: {text}")


def _ipp_payload(slug: str = "office-laser", uri: str = URI, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": f"Laser {slug}",
        "slug": slug,
        "backend": "ipp",
        "connection": {"uri": uri},
        "trays": [
            {"key": "auto", "label": "Automatic", "is_default": True},
            {"key": "tray-2", "label": "Tray 2"},
        ],
    }
    body.update(over)
    return body


async def _create(live: Live, **over: Any) -> UUID:
    resp = await live.client.post(ADMIN, json=_ipp_payload(**over))
    assert resp.status_code == 201, resp.text
    return UUID(resp.json()["id"])


async def _status(live: Live, pid: UUID) -> dict[str, Any]:
    resp = await live.client.get(f"/api/v1/printers/{pid}/status")
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


async def _wait_online(live: Live, pid: UUID) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    async def _online() -> bool:
        seen.update(await _status(live, pid))
        return seen.get("online") is True

    await _until(_online, lambda: f"status of {pid} online (last: {seen})")
    return seen


async def _sheet_type(key: str = "cal-live") -> str:
    async with _factory()() as s:
        await ts.create_type(
            s, ts.TypeFields(key, "CALLIVE", "Acme", [], None, None), G48, actor="t"
        )
    return key


async def _print_page(live: Live, pid: UUID, type_key: str) -> httpx.Response:
    return await live.client.post(
        f"/api/v1/printers/{pid}/calibration/auto/page", json={"type": type_key}
    )


async def _job_state(jid: UUID) -> str | None:
    async with _factory()() as s:
        row = await s.get(DbJob, jid)
        return row.state if row is not None else None


async def _wait_job(jid: UUID, state: str) -> None:
    async def _reached() -> bool:
        return await _job_state(jid) == state

    await _until(_reached, f"job {jid} {state}")


async def _wait_printing(jid: UUID) -> None:
    async def _tracked() -> bool:
        async with _factory()() as s:
            row = await s.get(DbJob, jid)
            return row is not None and "ipp_job_id" in (row.result or {})

    await _until(_tracked, f"job {jid} at the printer")


def _producers(pid: UUID) -> int:
    return sum(
        1 for t in asyncio.all_tasks() if t.get_name() == f"ipp-status-{pid}" and not t.done()
    )


# ---------------------------------------------------------------------------- create


async def test_created_ipp_printer_has_status_without_restart(live: Live) -> None:
    pid = await _create(live)
    status = await _wait_online(live, pid)
    assert status["printer_state"] is not None
    assert status["captured_at"] is not None
    caps = await live.client.get(f"/api/v1/printers/{pid}/capabilities")
    assert caps.status_code == 200, caps.text
    assert caps.json()["resolution_dpi"]["max"] is not None
    assert caps.json()["media"] is not None


async def test_created_ipp_printer_prints_without_restart(live: Live) -> None:
    type_key = await _sheet_type()
    pid = await _create(live)
    resp = await _print_page(live, pid, type_key)
    assert resp.status_code == 202, resp.text
    await _wait_job(UUID(resp.json()["job_id"]), "done")
    assert live.print_jobs(URI) == 1


async def test_tape_printer_created_with_snmp_discover_has_status(live: Live) -> None:
    preflight = AsyncMock(return_value=PreflightStatus(hr_printer_status="idle", loaded_tape_mm=12))
    body = {
        "name": "Workshop",
        "slug": "workshop",
        "model": "PT-P750W",
        "backend": "ptouch",
        "connection": {
            "host": "192.0.2.10",
            "port": 9100,
            "snmp": {"discover": True, "community": "public"},
        },
    }
    with (
        patch(
            "app.services.printer_runtime._resolve_model_id_from_config",
            AsyncMock(return_value="PT-P750W"),
        ),
        patch("app.services.producers.status_probe_producer.query_preflight", preflight),
    ):
        resp = await live.client.post(ADMIN, json=body)
        assert resp.status_code == 201, resp.text
        pid = UUID(resp.json()["id"])
        status = await _wait_online(live, pid)
    assert status["tape_loaded"] == "12mm"
    assert status["captured_at"] is not None
    assert live.runtime.print_service_for(pid) is not None


async def test_ql_layout_default_round_trips_and_reaches_the_service(live: Live) -> None:
    """#258: PUT stores the default per tape width, GET shows it, the service uses it."""
    from app.printer_models.ql import QL820NWBDriver
    from app.printer_models.registry import ModelRegistry

    # The integration conftest clears the registry; the QL driver registers on import only
    # (no entry point), so register it for this test (the fixture restores the registry).
    ModelRegistry.register(QL820NWBDriver)  # type: ignore[arg-type]
    body = {
        "name": "Shelf QL",
        "slug": "shelf-ql",
        "model": "QL-820NWB",
        "backend": "brother_ql",
        "connection": {"host": "192.0.2.12", "port": 9100},
        "layout_defaults": {"62": {"orientation": "across", "preset": "small_qr"}},
    }
    with patch(
        "app.services.printer_runtime._resolve_model_id_from_config",
        AsyncMock(return_value="QL-820NWB"),
    ):
        resp = await live.client.post(ADMIN, json=body)
        assert resp.status_code == 201, resp.text
        pid = UUID(resp.json()["id"])
        assert resp.json()["layout_defaults"] == {
            "62": {"orientation": "across", "preset": "small_qr"}
        }
        resp = await live.client.put(
            f"{ADMIN}/shelf-ql", json={"layout_defaults": {"62": {"orientation": "along"}}}
        )
        assert resp.status_code == 200, resp.text
        bad = await live.client.put(
            f"{ADMIN}/shelf-ql", json={"layout_defaults": {"12": {"orientation": "across"}}}
        )
    assert bad.status_code == 422
    got = await live.client.get(f"{ADMIN}/shelf-ql")
    assert got.json()["layout_defaults"] == {"62": {"orientation": "along", "preset": None}}
    service = live.runtime.print_service_for(pid)
    assert service is not None
    assert {w: d.model_dump(mode="json") for w, d in service.layout_defaults.items()} == {
        62: {"orientation": "along", "preset": None}
    }


# ---------------------------------------------------------------------------- disable / enable


async def test_disable_stops_polling_and_refuses_jobs(live: Live) -> None:
    type_key = await _sheet_type()
    pid = await _create(live)
    await _wait_online(live, pid)
    resp = await live.client.post(f"{ADMIN}/office-laser/disable")
    assert resp.status_code == 200, resp.text
    before = live.gpa(URI)
    await asyncio.sleep(INTERVAL_S * 4)  # four intervals: a live producer would probe again
    assert live.gpa(URI) == before
    refused = await _print_page(live, pid, type_key)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["type"] == "printer-unavailable"


async def test_enable_restores_polling(live: Live) -> None:
    type_key = await _sheet_type()
    pid = await _create(live)
    await _wait_online(live, pid)
    assert (await live.client.post(f"{ADMIN}/office-laser/disable")).status_code == 200
    stopped = live.gpa(URI)
    resp = await live.client.post(f"{ADMIN}/office-laser/enable")
    assert resp.status_code == 200, resp.text

    async def _probing() -> bool:
        return live.gpa(URI) >= stopped + 2

    await _until(_probing, "probes after enable")
    job = await _print_page(live, pid, type_key)
    assert job.status_code == 202, job.text
    await _wait_job(UUID(job.json()["job_id"]), "done")


# ---------------------------------------------------------------------------- update


async def test_update_uri_moves_polling(live: Live) -> None:
    pid = await _create(live)
    await _wait_online(live, pid)
    resp = await live.client.put(f"{ADMIN}/office-laser", json={"connection": {"uri": URI_2}})
    assert resp.status_code == 200, resp.text
    old = live.gpa(URI)
    admin_probe = 1  # the save probed the new URI once before the commit

    async def _moved() -> bool:
        return live.gpa(URI_2) >= admin_probe + 2

    await _until(_moved, "status probes on the new URI")
    await asyncio.sleep(INTERVAL_S * 2)
    assert live.gpa(URI) == old  # the old printer is no longer polled


async def test_rename_does_not_rewire(live: Live) -> None:
    type_key = await _sheet_type()
    live.fakes[URI].job_script = [3, 5]  # sticks at 5: the page is printing
    pid = await _create(live)
    job = await _print_page(live, pid, type_key)
    assert job.status_code == 202, job.text
    jid = UUID(job.json()["job_id"])
    await _wait_printing(jid)
    calls = list(live.factory_calls)
    state = live.app.state.ipp_printer_states[pid]
    resp = await live.client.put(f"{ADMIN}/office-laser", json={"name": "Renamed laser"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Renamed laser"
    assert live.factory_calls == calls  # no new IPP client: nothing re-wired
    assert live.app.state.ipp_printer_states[pid] is state
    live.fakes[URI].job_script = [9]  # the tracking that ran before the rename goes on
    await _wait_job(jid, "done")


async def test_update_during_inflight_job_keeps_job(live: Live) -> None:
    """Review Focus 1: the job printing finishes, the one waiting behind it stays queued and
    prints after the re-wire; nothing prints twice."""
    type_key = await _sheet_type()
    live.fakes[URI].job_script = [3, 5]
    pid = await _create(live)
    first = await _print_page(live, pid, type_key)
    assert first.status_code == 202, first.text
    a = UUID(first.json()["job_id"])
    await _wait_printing(a)
    second = await _print_page(live, pid, type_key)
    assert second.status_code == 202, second.text
    b = UUID(second.json()["job_id"])
    put = asyncio.create_task(
        live.client.put(f"{ADMIN}/office-laser", json={"connection": {"uri": URI_2}})
    )
    await asyncio.sleep(0.3)
    assert not put.done()  # the re-wire waits for the job at the printer
    assert await _job_state(b) == "queued"
    live.fakes[URI].job_script = [9]
    resp = await asyncio.wait_for(put, WAIT_S)
    assert resp.status_code == 200, resp.text
    await _wait_job(a, "done")
    await _wait_job(b, "done")
    assert live.print_jobs(URI) == 1
    assert live.print_jobs(URI_2) == 1


async def test_concurrent_reconcile_single_producer(live: Live) -> None:
    """Review Focus 2: two saves at once end in the state of the last committed row, with one
    producer and the probes of one producer."""
    pid = await _create(live)
    await _wait_online(live, pid)
    r1, r2 = await asyncio.gather(
        live.client.put(
            f"{ADMIN}/office-laser", json={"connection": {"uri": URI, "tls_verify": False}}
        ),
        live.client.put(f"{ADMIN}/office-laser", json={"queue": {"timeout_s": 45}}),
    )
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert _producers(pid) == 1
    assert list(live.app.state.ipp_printer_states) == [pid]
    start = live.gpa(URI)
    window = INTERVAL_S * 5
    await asyncio.sleep(window)
    assert live.gpa(URI) - start <= window / INTERVAL_S + 1  # two producers would double it
    async with _factory()() as s:
        row = await s.get(Printer, pid)
        assert row is not None
        assert row.connection["tls_verify"] is False and row.queue_timeout_s == 45


async def test_concurrent_reconcile_ends_in_the_last_committed_row(live: Live) -> None:
    """Review Focus 2, deterministic: save A re-wires and is held after its queue add; save B
    (committed later) must wait for it and then wire B's row, not lose to A's late wiring."""
    pid = await _create(live)
    await _wait_online(live, pid)
    runtime = live.runtime
    real_tray_keys = runtime._tray_keys
    held = asyncio.Event()
    gate = asyncio.Event()

    async def _tray_keys(printer_id: UUID) -> list[str]:
        # The call after the queue add of a re-wire: the old wiring is gone, the new one is
        # not stored yet (the skip check before the detach sees the old wiring and passes).
        if printer_id == pid and printer_id not in runtime._wired and not held.is_set():
            held.set()
            await gate.wait()
        keys: list[str] = await real_tray_keys(printer_id)
        return keys

    with patch.object(runtime, "_tray_keys", _tray_keys):
        put_a = asyncio.create_task(
            live.client.put(f"{ADMIN}/office-laser", json={"queue": {"timeout_s": 45}})
        )
        try:
            await asyncio.wait_for(held.wait(), WAIT_S)
            put_b = asyncio.create_task(
                live.client.put(f"{ADMIN}/office-laser", json={"connection": {"uri": URI_2}})
            )
            await asyncio.sleep(0.3)  # B is saved and its reconcile has started
        finally:
            gate.set()
        r_a, r_b = await asyncio.wait_for(asyncio.gather(put_a, put_b), WAIT_S)
    assert r_a.status_code == 200, r_a.text
    assert r_b.status_code == 200, r_b.text
    old = live.gpa(URI)

    async def _on_b() -> bool:
        return live.gpa(URI_2) >= 1 + 2  # the admin probe of B plus status probes

    await _until(_on_b, "the last saved row (URI 2) is polled")
    await asyncio.sleep(INTERVAL_S * 2)
    assert live.gpa(URI) == old
    assert _producers(pid) == 1


async def test_reconcile_survives_client_disconnect(live: Live) -> None:
    """The reconcile is shielded: a cancelled request does not leave the printer detached."""
    pid = await _create(live)
    await _wait_online(live, pid)
    queue = live.app.state.print_queue
    real_remove = queue.remove_printer
    entered = asyncio.Event()
    gate = asyncio.Event()

    async def _remove(printer_id: UUID, timeout_s: float) -> None:
        entered.set()
        await gate.wait()
        await real_remove(printer_id, timeout_s)

    with patch.object(queue, "remove_printer", _remove):
        put = asyncio.create_task(
            live.client.put(f"{ADMIN}/office-laser", json={"connection": {"uri": URI_2}})
        )
        try:
            await asyncio.wait_for(entered.wait(), WAIT_S)
            put.cancel()  # the client goes away mid-reconcile
            await asyncio.gather(put, return_exceptions=True)
        finally:
            gate.set()

        async def _attached() -> bool:
            return pid in live.app.state.ipp_printer_states and live.gpa(URI_2) >= 3

        await _until(_attached, "the reconcile finished after the disconnect")
    assert _producers(pid) == 1


async def test_reconcile_lock_is_per_printer(live: Live) -> None:
    """A re-wire of A waiting for A's job at the printer does not delay a re-wire of B."""
    type_key = await _sheet_type()
    live.fakes[URI].job_script = [3, 5]
    a = await _create(live)
    b = await _create(live, slug="second-laser", uri=URI_2)
    job = await _print_page(live, a, type_key)
    assert job.status_code == 202, job.text
    await _wait_printing(UUID(job.json()["job_id"]))
    put_a = asyncio.create_task(
        live.client.put(f"{ADMIN}/office-laser", json={"queue": {"timeout_s": 45}})
    )
    try:
        await asyncio.sleep(0.2)
        assert not put_a.done()  # A's detach waits for the job
        put_b = await asyncio.wait_for(
            live.client.put(
                f"{ADMIN}/second-laser", json={"connection": {"uri": URI_2, "tls_verify": False}}
            ),
            1.0,
        )
        assert put_b.status_code == 200, put_b.text
        assert b in live.app.state.ipp_printer_states
    finally:
        live.fakes[URI].job_script = [9]
        await asyncio.wait_for(put_a, WAIT_S)


async def test_admin_response_reports_the_row_when_the_wiring_fails(live: Live) -> None:
    """Review Focus 3 at the route: the save succeeds and reports the saved row even when the
    runtime cannot wire it; the printer stays detached and the hub keeps answering."""
    pid = await _create(live)
    await _wait_online(live, pid)

    async def _broken(printer_id: UUID, timeout_s: float) -> None:
        raise RuntimeError("store down")

    with patch.object(live.app.state.print_queue, "remove_printer", _broken):
        resp = await live.client.put(f"{ADMIN}/office-laser", json={"connection": {"uri": URI_2}})
    assert resp.status_code == 200, resp.text
    assert resp.json()["connection"]["uri"] == URI_2
    assert pid not in live.app.state.ipp_printer_states
    assert (await live.client.get("/healthz")).status_code == 200
    async with _factory()() as s:
        rows = (await s.execute(select(Printer.slug))).scalars().all()
    assert list(rows) == ["office-laser"]
