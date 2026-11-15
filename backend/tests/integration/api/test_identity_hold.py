# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""While a printer's device is flagged as swapped, sheet and calibration jobs are held (#231).

The full app (real queue, real ``SheetCellsOutcome``, the fake IPP printer) for the sheet and
calibration routes, the retries and the dispatch check; the small app of the test-print tests
for the jobs that are never held (tape, test print).

A hold is refused at submit and at retry with a 409 ``printer-identity-mismatch`` whose detail
names the printer id only. A job that was queued before the flag is failed at dispatch through
the runner's not-started path, so its sheet cells are freed. No identity value appears in any
of it.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from app.models.job import Job
from app.models.print_batch import PrintBatch
from app.models.printer import Printer
from app.printer_backends.snmp_helper import ObservedIdentity
from app.services.print_queue import PrintQueue
from PIL import Image

from tests.integration.api.test_page_job_retry import REJECTED, _fail_cleanly, _until_job
from tests.integration.api.test_sheet_print_api import (
    TIMEOUT_S,
    Rig,
    _body,
    _cells,
    _count,
    _sheet,
    running,
)
from tests.integration.api.test_sheet_types_api import _factory
from tests.integration.api.test_test_print_api import (  # noqa: F401  (fixtures + helpers)
    Env,
    _public_url,
    env,
)

pytestmark = pytest.mark.asyncio

CODE = "printer-identity-mismatch"
QR_KEY = "avery-zweckform-l4736rev"  # seeded: QR allowed
SERIAL_A = "E1234567ABC"
SERIAL_B = "E7654321XYZ"


def _hold(rig: Rig, held: bool = True) -> None:
    rig.app.state.print_queue.set_identity_hold(rig.printer_id, held)


def _problem(resp: httpx.Response, pid: UUID) -> dict[str, Any]:
    assert resp.status_code == 409, resp.text
    detail: dict[str, Any] = resp.json()["detail"]
    assert detail["type"] == CODE and detail["status"] == 409, detail
    assert str(pid) in detail["detail"]
    return detail


def _envelope(resp: httpx.Response, pid: UUID) -> dict[str, Any]:
    """The sheet routes keep their documented envelope; the detail names the printer id only."""
    assert resp.status_code == 409, resp.text
    detail: dict[str, Any] = resp.json()["detail"]
    assert set(detail) == {"error_code", "error_message", "error_detail"}, detail
    assert detail["error_code"] == CODE
    assert detail["error_detail"] == {"printer_id": str(pid)}
    return detail


async def _jobs() -> int:
    return await _count(Job)


async def _calibration(rig: Rig, **kw: Any) -> httpx.Response:
    return await rig.client.post(
        f"/api/v1/printers/{rig.printer_id}/calibration/auto/page",
        json={"type": "acme-t1"},
        headers=kw.pop("headers", rig.key),
    )


async def _retry(rig: Rig, job_id: str) -> httpx.Response:
    return await rig.client.post(f"/api/v1/jobs/{job_id}/retry", headers=rig.key)


def _prints(rig: Rig) -> int:
    return sum(1 for r in rig.fake.received if r.operation == "Print-Job")


# ---------------------------------------------------------------------------- submit


async def test_sheet_print_refused_on_mismatch() -> None:
    async with running() as rig:
        code = await _sheet()
        _hold(rig)

        resp = await rig.print(_body(code, 3))

        _envelope(resp, rig.printer_id)
        assert await _jobs() == 0 and await _count(PrintBatch) == 0
        assert await _cells() == []  # nothing reserved
        assert _prints(rig) == 0
        _hold(rig, False)  # control: without the hold the same request is accepted
        assert (await rig.print(_body(code, 3))).status_code == 202


async def test_calibration_page_refused_on_mismatch() -> None:
    async with running() as rig:
        _hold(rig)

        resp = await _calibration(rig)

        _problem(resp, rig.printer_id)
        assert await _jobs() == 0 and _prints(rig) == 0
        _hold(rig, False)
        assert (await _calibration(rig)).status_code == 202


async def test_sheet_with_id_cell_refused_on_mismatch() -> None:
    async with running() as rig:
        _hold(rig)

        resp = await rig.client.post(
            "/api/v1/sheets",
            json={"type": QR_KEY, "id_placement": "cell", "printer": "page-1"},
            headers=rig.key,
        )

        _envelope(resp, rig.printer_id)
        assert await _jobs() == 0 and await _cells() == []


async def test_mismatch_detail_has_no_identity() -> None:
    async with running() as rig:
        sink = rig.app.state.printer_runtime._identity_sink
        await sink(rig.printer_id, ObservedIdentity(SERIAL_A, None, None))
        assert await sink(rig.printer_id, ObservedIdentity(SERIAL_B, None, None)) == "different"
        code = await _sheet()

        sheet = await rig.print(_body(code, 1))
        _envelope(sheet, rig.printer_id)
        calibration = await _calibration(rig)
        _problem(calibration, rig.printer_id)
        for resp in (sheet, calibration):
            assert SERIAL_A not in resp.text and SERIAL_B not in resp.text
        problem = calibration.json()["detail"]
        assert set(problem) <= {"type", "title", "status", "detail", "extensions"}
        assert problem.get("extensions", {}) == {}


async def test_reattach_never_drops_the_hold_under_a_queued_job() -> None:
    """An admin edit re-wires a flagged printer while a sheet job waits: it must not print."""
    async with running() as rig:
        queue: PrintQueue = rig.app.state.print_queue
        runtime = rig.app.state.printer_runtime
        code = await _sheet()
        await queue.pause_printer(rig.printer_id, reason="test", source="user")
        resp = await rig.print(_body(code, 3))
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["pages"][0]["job_id"]
        sink = runtime._identity_sink
        await sink(rig.printer_id, ObservedIdentity(SERIAL_A, None, None))
        assert await sink(rig.printer_id, ObservedIdentity(SERIAL_B, None, None)) == "different"
        async with _factory()() as s:  # a wiring change: the IPP queue timeout is in the key
            printer = await s.get(Printer, rig.printer_id)
            assert printer is not None
            printer.queue_timeout_s = int(printer.queue_timeout_s) + 7
            await s.commit()

        await runtime.reconcile(rig.printer_id)

        assert queue.is_identity_held(rig.printer_id)
        row = await _until_job(job_id, "failed")
        assert (row.error or "").startswith(f"{CODE}:")
        assert _prints(rig) == 0


# ---------------------------------------------------------------------------- retry


async def test_retry_refused_on_mismatch_sheet_page() -> None:
    async with running() as rig:
        code = await _sheet(used=4)
        first_id, _ = await _fail_cleanly(rig, _body(code, 3))
        jobs_before = await _jobs()
        _hold(rig)

        resp = await _retry(rig, first_id)

        _problem(resp, rig.printer_id)
        assert await _jobs() == jobs_before  # no new job
        sheet = await rig.sheet(code)
        assert all(c["state"] != "reserved" for c in sheet["cells"])  # nothing reserved again
        _hold(rig, False)
        assert (await _retry(rig, first_id)).status_code == 201


async def test_retry_refused_on_mismatch_calibration_page() -> None:
    async with running() as rig:
        rig.fake.print_status = REJECTED
        resp = await _calibration(rig)
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job_id"]
        await _until_job(job_id, "failed")
        rig.fake.print_status = 0
        jobs_before = await _jobs()
        _hold(rig)

        retried = await _retry(rig, job_id)

        _problem(retried, rig.printer_id)
        assert await _jobs() == jobs_before
        _hold(rig, False)
        assert (await _retry(rig, job_id)).status_code == 201


# ---------------------------------------------------------------------------- dispatch


async def test_queued_sheet_job_fails_at_dispatch_on_mismatch() -> None:
    async with running() as rig:
        queue: PrintQueue = rig.app.state.print_queue
        code = await _sheet()
        await queue.pause_printer(rig.printer_id, reason="test", source="user")
        resp = await rig.print(_body(code, 3))
        assert resp.status_code == 202, resp.text
        (page,) = resp.json()["pages"]
        assert len(await _cells()) == 3  # reserved while the job waits
        _hold(rig)  # the swap is detected while the job is queued

        await queue.resume_printer(rig.printer_id)

        row = await _until_job(page["job_id"], "failed")
        assert (row.error or "").startswith(f"{CODE}:")
        assert row.result is not None and row.result.get("started") is False
        async with asyncio.timeout(TIMEOUT_S):  # the outcome handler settles after the end
            while await _cells():
                await asyncio.sleep(0.02)
        assert _prints(rig) == 0  # nothing reached the printer
        assert SERIAL_A not in (row.error or "")


async def test_a_queued_job_prints_once_the_hold_is_gone() -> None:
    async with running() as rig:
        queue: PrintQueue = rig.app.state.print_queue
        code = await _sheet()
        await queue.pause_printer(rig.printer_id, reason="test", source="user")
        resp = await rig.print(_body(code, 2))
        _hold(rig)
        _hold(rig, False)

        await queue.resume_printer(rig.printer_id)

        await _until_job(resp.json()["pages"][0]["job_id"], "done")
        assert _prints(rig) == 1


# ---------------------------------------------------------------------------- never held


class _Tape:
    def __init__(self, printer_id: UUID) -> None:
        self.id = printer_id
        self.prints = 0

    async def print_image(self, image: Image.Image, *, tape_mm: int, **options: Any) -> None:
        self.prints += 1


async def test_tape_and_plain_page_jobs_still_print_on_mismatch() -> None:
    tape = _Tape(uuid4())
    queue = PrintQueue([tape])
    await queue.start()
    try:
        queue.set_identity_hold(tape.id, True)

        job_id = await queue.submit(tape.id, Image.new("1", (300, 76)), tape_mm=12)
        done = await queue.wait_for_job(job_id, timeout_s=5)

        assert done.state.value == "completed" and tape.prints == 1
    finally:
        await queue.stop()


async def test_test_print_not_held_on_mismatch(env: Env) -> None:  # noqa: F811
    env.queue.set_identity_hold(env.page_id, True)
    env.queue.set_identity_hold(env.tape_id, True)

    page = await env.post(env.page_id)
    tape = await env.post(env.tape_id)

    assert page.status_code == 202, page.text
    assert tape.status_code == 202, tape.text
    await env.done(page.json()["job_id"])
    await env.done(tape.json()["job_id"])
    assert len(env.documents()) == 1  # the test page reached the printer
    assert len(env.tape.printed) == 1
    assert json.dumps(page.json()).count(CODE) == 0


async def test_the_hold_is_per_printer() -> None:
    async with running() as rig:
        rig.app.state.print_queue.set_identity_hold(uuid4(), True)  # another printer

        code = await _sheet()
        assert (await rig.print(_body(code, 1))).status_code == 202
