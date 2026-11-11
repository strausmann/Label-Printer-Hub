"""HTTP tests of ``POST /api/v1/printers/{id}/test-print`` (#228).

Two apps. The *small* app wires the real router, a real ``PrintQueue`` (a fake tape printer and
the fake IPP printer), the real ``PrintService`` and the real jobs router, behind a stand-in
runtime; it carries the state-dependent refusals and the flows. The *full* app carries what only
the real auth layer decides: scopes and the per-key printer restriction.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import app.models  # noqa: F401
import bcrypt
import httpx
import pytest
import pytest_asyncio
from app.api.dependencies.printer_runtime import get_printer_runtime
from app.api.routes.jobs import router as jobs_router
from app.api.routes.test_print import router as printing_router
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_print, require_read
from app.config import get_settings
from app.db.session import get_session
from app.models.api_key import ApiKey
from app.models.job import Job as DbJob
from app.models.printer import Printer
from app.models.printer_status_cache import PrinterStatusCache
from app.models.printer_tray import PrinterTray
from app.models.sheet import Sheet
from app.page_render.test_page import render_test_page
from app.printer_backends.exceptions import NoTapeLoadedError, PrinterOfflineError
from app.printer_backends.ipp.attributes import (
    IppStatusRecord,
    Margins,
    TrayLoad,
)
from app.printer_backends.ipp.client import IppClient
from app.printer_backends.snmp_helper import PreflightStatus
from app.repositories import printer_state as printer_state_repo
from app.schemas.tape_geometry import TAPE_GEOMETRY
from app.services import page_jobs
from app.services.job_store_sqlite import SQLiteJobStore
from app.services.layout_engine import LayoutEngine
from app.services.page_job_runner import PageJobRunner
from app.services.page_jobs import IppPagePrinter
from app.services.print_queue import PrintQueue
from app.services.print_service import PrintService
from app.services.producers.ipp_status_producer import IppPrinterState, _empty_summary
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.helpers import pdf_inspect as pi
from tests.helpers.fake_ipp_printer import FAKE_URI, FakeIppPrinter

pytestmark = pytest.mark.asyncio

A4_KEY = "iso_a4_210x297mm"
LETTER_KEY = "na_letter_8.5x11in"
PUBLIC = "https://hub.example.invalid/"


def _factory() -> async_sessionmaker[AsyncSession]:
    import app.db.engine as _engine_module

    return _engine_module.async_session


def _err(resp: Any) -> dict[str, Any]:
    return resp.json()["detail"]


def _url(pid: UUID | str) -> str:
    return f"/api/v1/printers/{pid}/test-print"


# ---------------------------------------------------------------------------- rows


async def _printer(
    factory: async_sessionmaker[AsyncSession],
    backend: str = "ipp",
    *,
    enabled: bool = True,
    paused: bool = False,
    connection: dict[str, Any] | None = None,
    name: str | None = None,
) -> UUID:
    async with factory() as s:
        p = Printer(
            id=uuid4(),
            name=name or f"Office ({uuid4().hex[:4]})",
            slug=f"p-{uuid4().hex[:6]}",
            model="m",
            backend=backend,
            enabled=enabled,
            connection=connection or {"uri": FAKE_URI},
        )
        s.add(p)
        if backend == "ipp":
            s.add(PrinterTray(printer_id=p.id, tray_key="auto", label="Auto", is_default=True))
            s.add(PrinterTray(printer_id=p.id, tray_key="tray-2", label="Tray 2"))
            s.add(PrinterTray(printer_id=p.id, tray_key="off", label="Off", enabled=False))
        await s.commit()
        if paused:
            await printer_state_repo.set_paused(s, p.id, True)
        return p.id


async def _page_cache(
    factory: async_sessionmaker[AsyncSession],
    pid: UUID,
    *,
    age_s: float = 1,
    online: bool = True,
    tray_media: str | None = A4_KEY,
    media_default: str | None = None,
    margins: Margins | None = None,
) -> None:
    summary = _empty_summary().model_copy(
        update={"margins_hmm": margins, "media_default": media_default}
    )
    record = IppStatusRecord(
        online=online,
        printer_state="idle",
        reasons=[],
        blocking_reason=None,
        warnings=[],
        markers=[],
        trays=[
            TrayLoad(key=key, media=tray_media, ready=tray_media is not None)
            for key in ("auto", "tray-2")
        ],
        jobs_ahead=0,
        summary=summary,
    )
    stamp = datetime.now(UTC) - timedelta(seconds=age_s)
    async with factory() as s:
        s.add(
            PrinterStatusCache(
                printer_id=pid,
                parsed=record.model_dump(mode="json"),
                captured_at=stamp,
                updated_at=stamp,
            )
        )
        await s.commit()


# ---------------------------------------------------------------------------- the small app


class _TapePrinter:
    """The queue's side of a tape printer; remembers what it was asked to print."""

    def __init__(self, printer_id: UUID) -> None:
        self.id = printer_id
        self.printed: list[tuple[Any, int]] = []

    async def print_image(self, image: Any, *, tape_mm: int, **options: Any) -> None:
        self.printed.append((image, tape_mm))


class _Runtime:
    def __init__(self) -> None:
        self.polled: set[UUID] = set()
        self.services: dict[UUID, PrintService] = {}

    def is_polled(self, printer_id: UUID) -> bool:
        return printer_id in self.polled

    def print_service_for(self, printer_id: UUID) -> PrintService | None:
        return self.services.get(printer_id)


class Env:
    def __init__(
        self,
        app: FastAPI,
        queue: PrintQueue,
        fake: FakeIppPrinter,
        factory: async_sessionmaker[AsyncSession],
        runtime: _Runtime,
        backend: AsyncMock,
        tape: _TapePrinter,
        tape_id: UUID,
        page_id: UUID,
        auth: AuthContext,
    ) -> None:
        self.app, self.queue, self.fake, self.factory = app, queue, fake, factory
        self.runtime, self.backend, self.tape = runtime, backend, tape
        self.tape_id, self.page_id, self.auth = tape_id, page_id, auth

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://t")

    def documents(self) -> list[Any]:
        return [r for r in self.fake.received if r.operation == "Print-Job"]

    async def post(self, pid: UUID | str, **body: Any) -> httpx.Response:
        async with self.client() as c:
            return await c.post(_url(pid), json=body)

    async def job_rows(self) -> list[DbJob]:
        async with self.factory() as s:
            return list((await s.execute(select(DbJob))).scalars().all())

    async def done(self, job_id: str) -> None:
        async with asyncio.timeout(10):
            await self.queue.wait_for_job(job_id, timeout_s=10)


@contextmanager
def _test_page_renderer() -> Iterator[None]:
    """The real renderer, uncompressed so the PDF can be read back; the registry is restored."""
    saved = dict(page_jobs._RENDERERS)
    page_jobs.register_page_renderer("test_page", lambda p: render_test_page(p, compress=False))
    try:
        yield
    finally:
        page_jobs._RENDERERS.clear()
        page_jobs._RENDERERS.update(saved)


@pytest.fixture(autouse=True)
def _public_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("LABELYARD_PUBLIC_URL", PUBLIC)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def env(async_session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[Env]:
    with _test_page_renderer():
        tape_id = await _printer(
            async_session_factory,
            "ptouch",
            connection={"host": "192.0.2.10", "snmp": {"community": "hunter2-community"}},
        )
        page_id = await _printer(async_session_factory)
        await _page_cache(async_session_factory, page_id)
        fake = FakeIppPrinter(job_script=[3, 5, 9])
        client = IppClient(FAKE_URI, transport=httpx.ASGITransport(app=fake))
        page = IppPagePrinter(id=page_id, client=client, state=IppPrinterState())
        tape = _TapePrinter(tape_id)
        store = SQLiteJobStore(async_session_factory)
        runner = PageJobRunner(
            store=store, notify=lambda *a, **k: None, poll_interval_s=0.01, max_backoff_s=0
        )
        queue = PrintQueue([tape], store=store, page_printers=[page], page_runner=runner)
        await queue.start()
        backend = AsyncMock()
        backend.preflight_check.return_value = PreflightStatus(
            hr_printer_status="idle", loaded_tape_mm=24, error_flags=[]
        )
        service = PrintService(
            printer_id=tape_id,
            backend=backend,
            queue=queue,
            store=store,
            engine=LayoutEngine(),
        )
        runtime = _Runtime()
        runtime.services[tape_id] = service
        runtime.polled = {page_id, tape_id}
        app = FastAPI()
        app.include_router(printing_router)
        app.include_router(jobs_router)
        app.state.print_queue = queue
        app.state.job_store = store

        async def _session() -> AsyncIterator[AsyncSession]:
            async with async_session_factory() as s:
                yield s

        auth = AuthContext(source="api-key", scope="print", api_key_id=uuid4(), ip="127.0.0.1")
        for dep in (require_read, require_print):
            app.dependency_overrides[dep] = lambda _c=auth: _c
        app.dependency_overrides[get_session] = _session
        app.dependency_overrides[get_printer_runtime] = lambda: runtime
        try:
            yield Env(
                app, queue, fake, async_session_factory, runtime, backend, tape, tape_id, page_id,
                auth,
            )  # fmt: skip
        finally:
            await queue.stop(timeout_s=2)
            await client.aclose()


# ---------------------------------------------------------------------------- tape printers


async def test_tape_test_print_creates_one_job_done(env: Env) -> None:
    r = await env.post(env.tape_id)
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    await env.done(job_id)
    [row] = await env.job_rows()
    assert str(row.id) == job_id
    assert row.template_key == "test_label"
    assert row.payload["content_type"] == "qr_three_lines"
    assert row.payload["tape_mm"] == 24
    [(image, tape_mm)] = env.tape.printed
    assert tape_mm == 24
    assert image.height == TAPE_GEOMETRY[24].printable_px  # rendered for the tape the preflight saw
    assert env.backend.preflight_check.await_count == 1  # one preflight, not two


async def test_tape_label_names_the_printer_and_points_at_it(env: Env) -> None:
    r = await env.post(env.tape_id)
    await env.done(r.json()["job_id"])
    [row] = await env.job_rows()
    data = row.payload["label_data"]
    assert data["qr_payload"] == f"https://hub.example.invalid/printers/{env.tape_id}"
    assert data["title"].startswith("24 mm · ")
    assert data["secondary"][0].startswith("Printer Hub ")


async def test_tape_label_carries_no_connection_details(env: Env) -> None:
    r = await env.post(env.tape_id)
    await env.done(r.json()["job_id"])
    [row] = await env.job_rows()
    stored = str(row.payload)
    for leak in ("192.0.2.10", "hunter2", "community", "ptouch", "snmp"):
        assert leak not in stored


async def test_unpolled_tape_printer_test_print_is_202(env: Env) -> None:
    env.runtime.polled.discard(env.tape_id)  # snmp.discover=false: no producer, preflight answers
    r = await env.post(env.tape_id)
    assert r.status_code == 202, r.text
    await env.done(r.json()["job_id"])


async def test_tape_offline_is_409_from_the_preflight(env: Env) -> None:
    env.backend.preflight_check.side_effect = PrinterOfflineError("unreachable")
    r = await env.post(env.tape_id)
    assert r.status_code == 409
    assert _err(r)["type"] == "printer-offline"
    assert await env.job_rows() == []


async def test_tape_without_tape_is_409(env: Env) -> None:
    env.backend.preflight_check.side_effect = None
    env.backend.preflight_check.return_value = PreflightStatus(
        hr_printer_status="idle", loaded_tape_mm=None, error_flags=[]
    )
    r = await env.post(env.tape_id)
    assert r.status_code == 409
    assert _err(r)["type"] == "no-tape-loaded"
    assert NoTapeLoadedError  # the existing error the mapping is for
    assert await env.job_rows() == []


async def test_tape_test_label_prints_on_62mm_with_its_long_printer_url(env: Env) -> None:
    """#258: the fixed QR box takes the version the payload needs; the >= 67-byte printer URL
    of the test label prints on 62 mm across (it did not fit a fixed version 3)."""
    env.backend.preflight_check.return_value = PreflightStatus(
        hr_printer_status="idle", loaded_tape_mm=62, error_flags=[]
    )
    r = await env.post(env.tape_id)
    assert r.status_code == 202, r.text
    await env.done(r.json()["job_id"])
    [row] = await env.job_rows()
    assert len(row.payload["label_data"]["qr_payload"]) >= 67
    assert row.payload["options"]["orientation"] == "across"
    [(image, tape_mm)] = env.tape.printed
    assert (tape_mm, image.width) == (62, 696)


async def test_tape_test_label_too_long_for_the_qr_box_is_422(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A printer link beyond 4 px modules is refused with its own problem type, never a 500."""
    monkeypatch.setattr(
        "app.api.routes.test_print.printer_url", lambda *_a: "https://h.invalid/" + "p" * 200
    )
    env.backend.preflight_check.return_value = PreflightStatus(
        hr_printer_status="idle", loaded_tape_mm=62, error_flags=[]
    )
    r = await env.post(env.tape_id)
    assert r.status_code == 422, r.text
    assert _err(r)["type"] == "qr-payload-too-long"
    assert await env.job_rows() == []


async def test_tray_on_tape_printer_is_422(env: Env) -> None:
    r = await env.post(env.tape_id, tray="auto")
    assert r.status_code == 422
    assert _err(r)["type"] == "tray-invalid"
    assert env.backend.preflight_check.await_count == 0


async def test_tape_printer_the_runtime_does_not_know_is_409(env: Env) -> None:
    del env.runtime.services[env.tape_id]
    r = await env.post(env.tape_id)
    assert r.status_code == 409
    assert _err(r)["type"] == "printer-unavailable"


# ---------------------------------------------------------------------------- page printers


async def test_page_test_print_creates_one_job_done(env: Env) -> None:
    await _replace_cache(env, margins=Margins(top=420, left=600, bottom=420, right=600))
    r = await env.post(env.page_id, tray="tray-2")
    assert r.status_code == 202, r.text
    await env.done(r.json()["job_id"])
    [sent] = env.documents()
    pdf = sent.document
    assert len(re.findall(rb"/Type /Page\b(?!s)", pdf)) == 1
    [frame] = [a for op, a in pi.operations(pdf) if op == "re"]
    k = 72 / 25.4
    assert frame[0] == pytest.approx(6.0 * k, abs=0.5 * k)  # left margin
    assert frame[2] == pytest.approx(198.0 * k, abs=0.5 * k)  # 210 - 6 - 6
    joined = " | ".join(pi.texts(pdf))
    assert "tray-2" in joined
    assert (await _printer_row(env, env.page_id)).name in joined
    rows = [x for x in await env.job_rows() if x.printer_id == env.page_id]
    assert len(rows) == 1 and rows[0].payload["kind"] == "test_page"


async def _printer_row(env: Env, pid: UUID) -> Printer:
    async with env.factory() as s:
        p = await s.get(Printer, pid)
    assert p is not None
    return p


async def _replace_cache(env: Env, **kw: Any) -> None:
    async with env.factory() as s:
        row = await s.get(PrinterStatusCache, env.page_id)
        if row is not None:
            await s.delete(row)
        await s.commit()
    await _page_cache(env.factory, env.page_id, **kw)


async def test_default_tray_is_used_when_none_is_given(env: Env) -> None:
    r = await env.post(env.page_id)
    assert r.status_code == 202, r.text
    await env.done(r.json()["job_id"])
    [sent] = env.documents()
    assert "auto" in " | ".join(pi.texts(sent.document))


async def test_unpolled_page_printer_is_409_status_unknown(env: Env) -> None:
    env.runtime.polled.discard(env.page_id)
    r = await env.post(env.page_id)
    assert r.status_code == 409
    assert _err(r)["type"] == "printer-status-unknown"
    assert env.documents() == []


async def test_test_page_media_falls_back_to_media_default(env: Env) -> None:
    await _replace_cache(env, tray_media=None, media_default=LETTER_KEY)
    r = await env.post(env.page_id)
    assert r.status_code == 202, r.text
    await env.done(r.json()["job_id"])
    [sent] = env.documents()
    assert pi.media_box(sent.document) == pytest.approx((0, 0, 612, 792), abs=1e-3)


async def test_media_unknown_is_409(env: Env) -> None:
    await _replace_cache(env, tray_media=None, media_default=None)
    r = await env.post(env.page_id)
    assert r.status_code == 409
    assert _err(r)["type"] == "media-unknown"
    assert env.documents() == []


async def test_tray_media_wins_over_media_default(env: Env) -> None:
    await _replace_cache(env, tray_media=A4_KEY, media_default=LETTER_KEY)
    r = await env.post(env.page_id)
    await env.done(r.json()["job_id"])
    [sent] = env.documents()
    assert pi.media_box(sent.document) == pytest.approx((0, 0, 595.2756, 841.8898), abs=1e-3)


async def test_test_page_without_margins_draws_inset_frame(env: Env) -> None:
    r = await env.post(env.page_id)
    await env.done(r.json()["job_id"])
    [sent] = env.documents()
    k = 72 / 25.4
    [frame] = [a for op, a in pi.operations(sent.document) if op == "re"]
    assert frame[0] == pytest.approx(5.0 * k, abs=0.5 * k)
    assert "Margins not reported" in pi.texts(sent.document)


async def test_test_page_retry_resubmits(env: Env) -> None:
    r = await env.post(env.page_id)
    first = r.json()["job_id"]
    await env.done(first)
    async with env.client() as c:
        again = await c.post(f"/api/v1/jobs/{first}/retry")
    assert again.status_code == 201, again.text
    second = again.json()["id"]
    assert second != first
    await env.done(second)
    first_doc, second_doc = [d.document for d in env.documents()]
    assert first_doc == second_doc  # the same page: the stored payload, date and all


async def test_unknown_tray_is_422(env: Env) -> None:
    r = await env.post(env.page_id, tray="nope")
    assert r.status_code == 422
    assert _err(r)["type"] == "tray-invalid"


async def test_disabled_tray_is_422(env: Env) -> None:
    r = await env.post(env.page_id, tray="off")
    assert r.status_code == 422
    assert _err(r)["type"] == "tray-invalid"
    assert env.documents() == []


async def test_offline_is_409(env: Env) -> None:
    await _replace_cache(env, online=False)
    page = await env.post(env.page_id)
    assert page.status_code == 409 and _err(page)["type"] == "printer-offline"
    env.backend.preflight_check.side_effect = PrinterOfflineError("down")
    tape = await env.post(env.tape_id)
    assert tape.status_code == 409 and _err(tape)["type"] == "printer-offline"
    assert env.documents() == []


async def test_stale_page_printer_is_409(env: Env) -> None:
    await _replace_cache(env, age_s=3600)
    r = await env.post(env.page_id)
    assert r.status_code == 409
    assert _err(r)["type"] == "printer-offline"


async def test_page_printer_without_a_cache_row_is_409_offline(env: Env) -> None:
    async with env.factory() as s:
        row = await s.get(PrinterStatusCache, env.page_id)
        assert row is not None
        await s.delete(row)
        await s.commit()
    r = await env.post(env.page_id)
    assert r.status_code == 409
    assert _err(r)["type"] == "printer-offline"


async def test_disabled_is_409(env: Env) -> None:
    pid = await _printer(env.factory, enabled=False)
    r = await env.post(pid)
    assert r.status_code == 409
    assert _err(r)["type"] == "printer-disabled"
    tape = await _printer(env.factory, "ptouch", enabled=False)
    r2 = await env.post(tape)
    assert r2.status_code == 409 and _err(r2)["type"] == "printer-disabled"


async def test_paused_is_409(env: Env) -> None:
    async with env.factory() as s:
        await printer_state_repo.set_paused(s, env.page_id, True)
    r = await env.post(env.page_id)
    assert r.status_code == 409
    assert _err(r)["type"] == "printer-paused"
    assert env.documents() == []


async def test_unknown_printer_is_404(env: Env) -> None:
    r = await env.post(uuid4())
    assert r.status_code == 404
    assert _err(r)["type"] == "printer-not-found"


async def test_extra_body_field_is_422(env: Env) -> None:
    r = await env.post(env.page_id, tray="auto", copies=5)
    assert r.status_code == 422


async def test_restricted_key_own_printer_is_202(env: Env) -> None:
    env.auth.allowed_printer_ids = [str(env.page_id)]
    r = await env.post(env.page_id)
    assert r.status_code == 202, r.text
    await env.done(r.json()["job_id"])


async def test_test_print_reserves_no_sheet_cells(env: Env) -> None:
    async def sheet_rows() -> int:
        async with env.factory() as s:
            return int((await s.execute(select(func.count()).select_from(Sheet))).scalar_one())

    before = await sheet_rows()
    r = await env.post(env.page_id)
    await env.done(r.json()["job_id"])
    assert await sheet_rows() == before


async def test_printer_url_has_single_slash(env: Env) -> None:
    # PUBLIC ends in "/": the QR must not point at "//printers/...".
    r = await env.post(env.tape_id)
    await env.done(r.json()["job_id"])
    [row] = await env.job_rows()
    url = row.payload["label_data"]["qr_payload"]
    assert url == f"https://hub.example.invalid/printers/{env.tape_id}"
    assert "//printers" not in url


async def test_printer_url_drops_credentials_from_the_public_url(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LABELYARD_PUBLIC_URL", "https://admin:pw-leak@hub.example.invalid/base")
    get_settings.cache_clear()
    r = await env.post(env.tape_id)
    await env.done(r.json()["job_id"])
    [row] = await env.job_rows()
    url = row.payload["label_data"]["qr_payload"]
    assert url == f"https://hub.example.invalid/base/printers/{env.tape_id}"
    assert "pw-leak" not in str(row.payload)


async def test_test_page_never_carries_connection_details(env: Env) -> None:
    async with env.factory() as s:
        p = await s.get(Printer, env.page_id)
        assert p is not None
        p.connection = {"uri": "ipps://scan:s3cret@printer.example.invalid/ipp/print"}
        s.add(p)
        await s.commit()
    r = await env.post(env.page_id)
    await env.done(r.json()["job_id"])
    [sent] = env.documents()
    for leak in (b"s3cret", b"scan:", b"ipps://", b"printer.example.invalid"):
        assert leak not in sent.document
    [row] = [x for x in await env.job_rows() if x.printer_id == env.page_id]
    assert "s3cret" not in str(row.payload)


async def test_renderer_is_registered_on_the_real_app() -> None:
    import app.main  # noqa: F401

    assert "test_page" in page_jobs._RENDERERS


async def test_the_route_documents_its_refusals() -> None:
    spec = app_openapi()
    post = spec["paths"]["/api/v1/printers/{printer_id}/test-print"]["post"]
    assert "202" in post["responses"] and "409" in post["responses"]


def app_openapi() -> dict[str, Any]:
    from app.main import create_app

    return create_app()._app.openapi()  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------- the full app


async def _key(scopes: list[str], allowed: list[str] | None = None) -> dict[str, str]:
    plaintext = f"lh_pat_{uuid4().hex}"
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with _factory()() as s:
        s.add(
            ApiKey(
                name=f"tp-{uuid4().hex[:6]}",
                key_hash=hashed,
                key_prefix=plaintext[:16],
                scopes=scopes,
                allowed_printer_ids=allowed or [],
                enabled=True,
                rate_limit_per_minute=6000,
            )
        )
        await s.commit()
    return {"X-Label-Hub-Key": plaintext}


async def test_read_key_is_403(api_client_with_seed: httpx.AsyncClient) -> None:
    c = api_client_with_seed
    pid = await _printer(_factory())
    r = await c.post(_url(pid), json={}, headers=await _key(["read"]))
    assert r.status_code == 403, r.text


async def test_read_key_on_unknown_printer_is_403(api_client_with_seed: httpx.AsyncClient) -> None:
    r = await api_client_with_seed.post(_url(uuid4()), json={}, headers=await _key(["read"]))
    assert r.status_code == 403, r.text  # the scope layer runs before the lookup


async def test_restricted_key_other_printer_is_403(api_client_with_seed: httpx.AsyncClient) -> None:
    c = api_client_with_seed
    pid = await _printer(_factory())
    other = await _printer(_factory())
    r = await c.post(_url(pid), json={}, headers=await _key(["print"], allowed=[str(other)]))
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["error_code"] == "printer_not_allowed"


async def test_print_key_on_unknown_printer_is_404(api_client_with_seed: httpx.AsyncClient) -> None:
    r = await api_client_with_seed.post(_url(uuid4()), json={}, headers=await _key(["print"]))
    assert r.status_code == 404, r.text
