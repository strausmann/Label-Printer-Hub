# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""A hub restart while a page job is at the printer: the real lifespan runs twice on one
database, the fake IPP printer outlives both. The second run resumes the tracking and the job
ends ``done`` — no second Print-Job, one ``on_completed``. A third case checks the unknown
outcome (the restart came during the upload). Waits are bounded."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.models.job import Job as DbJob
from app.models.printer import Printer
from httpx import ASGITransport

from tests.helpers.fake_ipp_printer import FAKE_URI, FakeIppPrinter
from tests.helpers.page_jobs import RecordingHandler, payload, registered

TIMEOUT_S = 10.0


async def _until(predicate: Callable[[], Awaitable[bool]]) -> None:
    async with asyncio.timeout(TIMEOUT_S):
        while not await predicate():
            await asyncio.sleep(0.02)


async def _printer() -> UUID:
    import app.db.engine as eng

    async with eng.async_session() as s:
        printer = Printer(
            name="Page",
            slug="page-restart",
            model="x",
            backend="ipp",
            connection={"uri": FAKE_URI, "tls_verify": True},
            enabled=True,
        )
        s.add(printer)
        await s.commit()
        return printer.id


def _app(fake: FakeIppPrinter) -> object:
    from app.main import create_app

    app = create_app()
    app._app.state.ipp_transport_factory = lambda _uri: ASGITransport(app=fake)
    return app._app


async def _row(job_id: UUID) -> DbJob:
    import app.db.engine as eng

    async with eng.async_session() as s:
        row = await s.get(DbJob, job_id)
        assert row is not None
        return row


async def test_restart_mid_job_ends_done() -> None:
    fake = FakeIppPrinter(job_script=[3, 5])  # sticks at "printing"
    pid = await _printer()
    with registered(RecordingHandler()) as handler:
        first = _app(fake)
        async with first.router.lifespan_context(first):  # type: ignore[attr-defined]
            jid = await first.state.print_queue.submit_page_job(  # type: ignore[attr-defined]
                pid, payload(), api_key_id=None, source_ip=None
            )

            async def _started() -> bool:
                return bool(((await _row(jid)).result or {}).get("started"))

            await _until(_started)
            await _until(_names(handler, jid, ["started"]))
        assert (await _row(jid)).state == "printing"  # the shutdown left it with the printer

        fake.job_script = [5, 9]
        second = _app(fake)
        async with second.router.lifespan_context(second):  # type: ignore[attr-defined]

            async def _done() -> bool:
                return (await _row(jid)).state == "done"

            await _until(_done)
            await _until(_names(handler, jid, ["started", "completed"]))
    assert [r.operation for r in fake.received].count("Print-Job") == 1


async def test_restart_during_upload_is_an_unknown_outcome() -> None:
    fake = FakeIppPrinter(job_script=[9])
    pid = await _printer()
    with registered(RecordingHandler()) as handler:
        import app.db.engine as eng

        # What a crash during the upload leaves behind: printing, no IPP job id yet.
        async with eng.async_session() as s:
            row = DbJob(
                printer_id=pid,
                template_key=None,
                payload=payload().model_dump(mode="json"),
                state="printing",
                result={"phase": "uploading", "started": False},
            )
            s.add(row)
            await s.commit()
            jid = row.id
        app = _app(fake)
        async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
            await _until(_names(handler, jid, ["unknown"]))
    assert (await _row(jid)).state == "failed_restart"
    assert "Print-Job" not in [r.operation for r in fake.received]


def _names(
    handler: RecordingHandler, jid: UUID, expected: list[str]
) -> Callable[[], Awaitable[bool]]:
    async def _check() -> bool:
        return handler.names(jid) == expected

    return _check
