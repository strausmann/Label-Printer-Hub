# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""HTTP tests of the calibration page: the job, the download, scopes and errors.

Two apps: the full app (keys, scopes, printer restriction, error cases) and a small app with a
real ``PrintQueue`` whose page printer is the fake IPP printer (the job reaches the printer).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import app.models  # noqa: F401
import bcrypt
import httpx
import pytest
import pytest_asyncio
from app.api.routes.calibration import router as calibration_router
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_print, require_read
from app.calibration import page as page_module
from app.calibration.page import render_calibration_page
from app.db.session import get_session
from app.models.api_key import ApiKey
from app.models.printer import Printer
from app.models.printer_calibration import PrinterCalibration
from app.models.printer_tray import PrinterTray
from app.printer_backends.ipp.client import IppClient
from app.services.job_store_sqlite import SQLiteJobStore
from app.services.page_job_runner import PageJobRunner
from app.services.page_jobs import IppPagePrinter
from app.services.print_queue import PrintQueue
from app.services.producers.ipp_status_producer import IppPrinterState
from app.sheets import type_service as ts
from app.sheets.geometry import Geometry
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.helpers.fake_ipp_printer import FAKE_URI, FakeIppPrinter
from tests.helpers.page_jobs import RecordingHandler, registered

pytestmark = pytest.mark.asyncio

G48 = Geometry("A4", 21000, 29700, 4570, 2120, 4, 12, 4820, 2120, 2130, 985, None, "rectangle")
ONE_COL = Geometry("A4", 21000, 29700, 4570, 2120, 1, 12, 4820, 2120, 2130, 985, None, "rectangle")
DAY = "2026-11-05"


@pytest.fixture(autouse=True)
def _pinned_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(page_module, "today_iso", lambda: DAY)


async def _type(factory: async_sessionmaker[AsyncSession], key: str, g: Geometry = G48) -> None:
    async with factory() as s:
        await ts.create_type(
            s,
            ts.TypeFields(key, key.replace("-", "").upper()[:8], "Acme", [], None, None),
            g,
            actor="t",
        )


async def _printer(
    factory: async_sessionmaker[AsyncSession], backend: str = "ipp", pid: UUID | None = None
) -> UUID:
    async with factory() as s:
        p = Printer(
            id=pid or uuid4(),
            name=f"Office ({uuid4().hex[:4]})",
            slug=f"p-{uuid4().hex[:6]}",
            model="m",
            backend=backend,
            connection={"uri": FAKE_URI},
        )
        s.add(p)
        s.add(PrinterTray(printer_id=p.id, tray_key="auto", label="Auto", is_default=True))
        s.add(PrinterTray(printer_id=p.id, tray_key="off", label="Off", enabled=False))
        await s.commit()
        return p.id


def _factory() -> async_sessionmaker[AsyncSession]:
    import app.db.engine as _engine_module

    return _engine_module.async_session


async def _key(scopes: list[str], allowed: list[str] | None = None) -> dict[str, str]:
    plaintext = f"lh_pat_{uuid4().hex}"
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with _factory()() as s:
        s.add(
            ApiKey(
                name=f"calp-{uuid4().hex[:6]}",
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


def _err(resp: Any) -> dict[str, Any]:
    return resp.json()["detail"]


# ---------------------------------------------------------------------------- the full app


async def test_download_returns_a_pdf_attachment(api_client_with_seed: httpx.AsyncClient) -> None:
    c = api_client_with_seed
    await _type(_factory(), "cal-pg")
    pid = await _printer(_factory())
    r = await c.get(
        f"/api/v1/printers/{pid}/calibration/auto/page/pdf?type=cal-pg",
        headers=await _key(["read"]),
    )
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF")
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'attachment; filename="calibration-cal-pg-v1.pdf"'


async def test_scopes_and_printer_restriction(api_client_with_seed: httpx.AsyncClient) -> None:
    c = api_client_with_seed
    await _type(_factory(), "cal-sc")
    pid, other = await _printer(_factory()), await _printer(_factory())
    url = f"/api/v1/printers/{pid}/calibration/auto/page"
    body = {"type": "cal-sc"}

    def refused(r: Any, status: int, code: str) -> None:
        assert r.status_code == status and _err(r)["error_code"] == code, r.text

    # Printing needs the print scope: a read key is refused by the scope layer.
    refused(await c.post(url, json=body, headers=await _key(["read"])), 403, "insufficient_scope")
    # A key with no scope at all is refused as structurally invalid; no key at all as anonymous.
    refused(await c.post(url, json=body, headers=await _key([])), 401, "key_no_scopes")
    refused(await c.get(f"{url}/pdf?type=cal-sc", headers=await _key([])), 401, "key_no_scopes")
    refused(await c.post(url, json=body), 401, "missing_credentials")
    refused(await c.get(f"{url}/pdf?type=cal-sc"), 401, "missing_credentials")
    # A key bound to another printer is refused on both routes, with the stable error code.
    bound = await _key(["print"], allowed=[str(other)])
    refused(await c.post(url, json=body, headers=bound), 403, "printer_not_allowed")
    refused(await c.get(f"{url}/pdf?type=cal-sc", headers=bound), 403, "printer_not_allowed")
    # The download needs only read, and print implies read.
    for scopes in (["read"], ["print"]):
        r = await c.get(f"{url}/pdf?type=cal-sc", headers=await _key(scopes))
        assert r.status_code == 200 and r.content.startswith(b"%PDF"), scopes


# ---------------------------------------------------------------------------- queue + fake printer


class _Env:
    def __init__(
        self, app: FastAPI, queue: PrintQueue, fake: FakeIppPrinter, factory: Any, pid: UUID
    ):
        self.app, self.queue, self.fake, self.factory, self.printer_id = (
            app,
            queue,
            fake,
            factory,
            pid,
        )

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://t")

    def documents(self) -> list[Any]:
        return [r for r in self.fake.received if r.operation == "Print-Job"]


@pytest_asyncio.fixture
async def env(async_session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[_Env]:
    with registered(RecordingHandler(), render=render_calibration_page):
        pid = await _printer(async_session_factory)
        await _type(async_session_factory, "cal-job")
        fake = FakeIppPrinter(job_script=[3, 5, 9])
        client = IppClient(FAKE_URI, transport=httpx.ASGITransport(app=fake))
        page = IppPagePrinter(id=pid, client=client, state=IppPrinterState())
        store = SQLiteJobStore(async_session_factory)
        runner = PageJobRunner(
            store=store, notify=lambda *a, **k: None, poll_interval_s=0.01, max_backoff_s=0
        )
        queue = PrintQueue([], store=store, page_printers=[page], page_runner=runner)
        await queue.start()
        app = FastAPI()
        app.include_router(calibration_router)
        app.state.print_queue = queue

        async def _session() -> AsyncIterator[AsyncSession]:
            async with async_session_factory() as s:
                yield s

        auth = AuthContext(source="api-key", scope="admin", api_key_id=uuid4(), ip="127.0.0.1")
        for dep in (require_read, require_print):
            app.dependency_overrides[dep] = lambda _c=auth: _c
        app.dependency_overrides[get_session] = _session
        try:
            yield _Env(app, queue, fake, async_session_factory, pid)
        finally:
            await queue.stop(timeout_s=2)
            await client.aclose()


async def _printed(env: _Env, job_id: str) -> None:
    async with asyncio.timeout(10):
        await env.queue.wait_for_job(job_id, timeout_s=10)


async def test_post_queues_a_page_job_the_printer_receives(env: _Env) -> None:
    async with env.client() as c:
        r = await c.post(
            f"/api/v1/printers/{env.printer_id}/calibration/auto/page", json={"type": "cal-job"}
        )
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]
        await _printed(env, job_id)
        pdf_resp = await c.get(
            f"/api/v1/printers/{env.printer_id}/calibration/auto/page/pdf?type=cal-job"
        )
    [sent] = env.documents()
    assert sent.document.startswith(b"%PDF")
    assert sent.attributes["document-format"] == ["application/pdf"]
    [media] = sent.job_attributes["media-col"]
    assert media.members["media-type"] == ["labels"]
    from app.printer_backends.ipp.job_attrs import wire_job_name

    assert sent.attributes["job-name"] == [wire_job_name("Calibration page · cal-job v1", job_id)]
    assert pdf_resp.status_code == 200
    assert pdf_resp.content == sent.document  # OC-35: the download is what the job sent
    job = await env.queue.get(job_id)
    assert job.kind == "calibration_page"
    from app.models.job import Job

    async with env.factory() as s:
        row = await s.get(Job, UUID(job_id))
    assert row is not None
    assert row.payload["kind"] == "calibration_page"
    assert row.payload["detail"]["date"] == DAY
    assert row.payload["calibration"] is None
    assert row.payload["job_name"] == "Calibration page · cal-job v1"


async def test_no_sheet_record_is_created(env: _Env) -> None:
    from app.models.sheet import Sheet
    from sqlalchemy import func, select

    async def count() -> int:
        async with env.factory() as s:
            return (await s.execute(select(func.count()).select_from(Sheet))).scalar_one()

    before = await count()
    async with env.client() as c:
        r = await c.post(
            f"/api/v1/printers/{env.printer_id}/calibration/auto/page", json={"type": "cal-job"}
        )
        await _printed(env, r.json()["job_id"])
    assert await count() == before


async def test_corrected_page_uses_the_stored_calibration_and_matches_the_download(
    env: _Env,
) -> None:
    async with env.factory() as s:
        s.add(
            PrinterCalibration(
                printer_id=env.printer_id,
                tray_key="auto",
                method="manual",
                offset_x_hmm=150,
                offset_y_hmm=-60,
                scale_x_ppm=1_000_500,
                scale_y_ppm=999_800,
                rotation_udeg=200_000,
            )
        )
        await s.commit()
    body = {"type": "cal-job", "corrected": True}
    async with env.client() as c:
        r = await c.post(f"/api/v1/printers/{env.printer_id}/calibration/auto/page", json=body)
        await _printed(env, r.json()["job_id"])
        dl = await c.get(
            f"/api/v1/printers/{env.printer_id}/calibration/auto/page/pdf?type=cal-job&corrected=true"
        )
        plain = await c.get(
            f"/api/v1/printers/{env.printer_id}/calibration/auto/page/pdf?type=cal-job"
        )
    [sent] = env.documents()
    assert dl.content == sent.document != plain.content


async def test_corrected_page_of_an_uncalibrated_tray_does_not_crash(env: _Env) -> None:
    async with env.client() as c:
        r = await c.get(
            f"/api/v1/printers/{env.printer_id}/calibration/auto/page/pdf?type=cal-job&corrected=true"
        )
    assert r.status_code == 200 and r.content.startswith(b"%PDF")


async def test_errors(env: _Env) -> None:
    f = env.factory
    await _type(f, "cal-one", ONE_COL)
    tape = await _printer(f, "brother_ql")

    async def post(printer: Any, tray: str, **body: Any) -> Any:
        async with env.client() as c:
            return await c.post(f"/api/v1/printers/{printer}/calibration/{tray}/page", json=body)

    pid = env.printer_id
    unsuitable = await post(pid, "auto", type="cal-one")
    assert unsuitable.status_code == 422
    assert _err(unsuitable)["error_code"] == "calibration_type_unsuitable"
    async with env.client() as c:
        as_download = await c.get(f"/api/v1/printers/{pid}/calibration/auto/page/pdf?type=cal-one")
    assert as_download.status_code == 422
    assert _err(as_download)["error_code"] == "calibration_type_unsuitable"
    cases = [
        (await post(pid, "auto", type="nope"), 404, "sheet_type_not_found"),
        # Spec 15: a missing version of an existing type has its own code.
        (await post(pid, "auto", type="cal-job", version=9), 404, "sheet_type_version_not_found"),
        (await post(pid, "nope", type="cal-job"), 422, "tray_unknown"),
        (await post(pid, "off", type="cal-job"), 422, "tray_unknown"),
        (await post(tape, "auto", type="cal-job"), 409, "media_kind_mismatch"),
        (await post(uuid4(), "auto", type="cal-job"), 404, "printer_not_found"),
    ]
    for resp, status, code in cases:
        assert resp.status_code == status and _err(resp)["error_code"] == code, resp.text
    assert (await post(pid, "auto", type="")).status_code == 422  # validation, not a crash
    assert env.documents() == []  # none of these reached the printer


async def test_a_printer_the_queue_does_not_know_is_a_409(env: _Env) -> None:
    unknown = await _printer(env.factory)  # in the database, never registered with the queue
    async with env.client() as c:
        r = await c.post(
            f"/api/v1/printers/{unknown}/calibration/auto/page", json={"type": "cal-job"}
        )
    assert r.status_code == 409, r.text
    assert _err(r)["type"] == "printer-unavailable"
    assert env.documents() == []


async def test_the_409_is_part_of_the_documented_contract(env: _Env) -> None:
    spec = env.app.openapi()
    post = spec["paths"]["/api/v1/printers/{printer_id}/calibration/{tray}/page"]["post"]
    assert "409" in post["responses"] and "202" in post["responses"]
