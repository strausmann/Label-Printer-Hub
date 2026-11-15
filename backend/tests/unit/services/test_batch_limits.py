# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""263-76 / 263-78 / 266-07 / 266-14: bounded memory, lookups, render threads and loop time.

A tape batch keeps one PNG per distinct item (its copies share it); a printer holds at most
``LABELYARD_MAX_QUEUED_RUNS_PER_PRINTER`` runs and a key at most
``LABELYARD_MAX_QUEUED_RUNS_PER_KEY`` (over: 429 ``too-many-queued-runs``); a run that waits
for ``/continue`` drops its pictures after 15 minutes and draws them again on continue. The
lookups of one batch run at most eight at once. A preview render keeps its slot until its
thread ends, and one key previews one sheet at a time. ``reserve`` plans in a thread.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import httpx
import pytest
from app.config import Settings
from app.models.job import Job as DbJob
from app.models.printer import Printer
from app.printer_backends.snmp_helper import PreflightStatus
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.print_request import PrintLookupRequest, PrintOptions, PrintRequest
from app.services import print_queue as pq
from app.services.cleanup_task import CleanupTask
from app.services.job_lifecycle import JobState
from app.services.job_store import MemoryJobStore
from app.services.layout_engine import LayoutEngine
from app.services.print_queue import (
    MAX_HELD_RUNS_PER_KEY_PER_PRINTER,
    MAX_HELD_RUNS_PER_PRINTER,
    MAX_LABELS_PER_TAPE_JOB,
    WAITING_RUN_PICTURES_TTL_S,
    PrintQueue,
    TooManyQueuedRunsError,
)
from app.services.print_service import MAX_BATCH_LOOKUPS, PrintService
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.unit.services.test_print_queue_tape_runs import TapeRoll, _run, _until

pytestmark = pytest.mark.anyio


def _img(w: int = 80) -> Image.Image:
    return Image.new("1", (w, 40), color=1)


async def _queue(printer: TapeRoll, store: MemoryJobStore | None = None) -> PrintQueue:
    queue = PrintQueue([printer], store=store or MemoryJobStore())
    await queue.start()
    return queue


async def _one_label_run(
    queue: PrintQueue,
    printer_id: UUID,
    *,
    slot: UUID | None = None,
    store: MemoryJobStore | None = None,
) -> tuple[UUID, UUID]:
    jid = uuid4()
    if store is not None:
        await store.save_queued(DbJob(id=jid, printer_id=printer_id, payload={}))
    run_id = await queue.enqueue_batch(
        printer_id=printer_id,
        images=[_img()],
        job_ids=[jid],
        tape_mm=12,
        options={},
        slot=slot,
    )
    return run_id, jid


def _claim(queue: PrintQueue, printer_id: UUID, key: UUID | None, **limits: int) -> UUID:
    return queue.claim_run_slot(
        printer_id,
        key,
        per_printer=limits.get("per_printer", 5),
        per_key=limits.get("per_key", 20),
    )


# ---------------------------------------------------------------------------- settings


def test_the_limits_are_settings_with_the_agreed_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings()
    assert s.max_queued_runs_per_printer == 5
    assert s.max_queued_runs_per_key == 20
    monkeypatch.setenv("LABELYARD_MAX_QUEUED_RUNS_PER_PRINTER", "6")
    monkeypatch.setenv("LABELYARD_MAX_QUEUED_RUNS_PER_KEY", "7")
    s = Settings()
    assert (s.max_queued_runs_per_printer, s.max_queued_runs_per_key) == (6, 7)
    assert WAITING_RUN_PICTURES_TTL_S == 15 * 60
    assert MAX_BATCH_LOOKUPS == 8


# ---------------------------------------------------------------------------- 263-76 PNGs


async def test_copies_share_one_png(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    real = pq._serialize_image_to_png

    def counting(image: Image.Image) -> bytes:
        calls.append(id(image))
        return real(image)

    monkeypatch.setattr(pq, "_serialize_image_to_png", counting)
    printer = TapeRoll()
    printer.gate = asyncio.Event()  # keep the run in memory while it is looked at
    queue = await _queue(printer)
    try:
        a, b = _img(80), _img(96)
        ids = [uuid4() for _ in range(4)]
        run_id = await queue.enqueue_batch(
            printer_id=printer.id,
            images=[a, a, a, b],  # three copies of one item, one other item
            job_ids=ids,
            tape_mm=12,
            options={},
        )
        run = queue._runs[run_id]
        keys = [str(j) for j in ids]
        assert len(calls) == 2  # one PNG per distinct item
        assert run.payloads[keys[0]] is run.payloads[keys[1]] is run.payloads[keys[2]]
        assert run.payloads[keys[3]] is not run.payloads[keys[0]]
        jobs = [await queue.get(j) for j in ids]
        assert jobs[0].image_payload is jobs[2].image_payload is run.payloads[keys[0]]
        printer.gate.set()
        await _until(lambda: queue.run_info(run_id) is None)
        assert printer.calls == [4]
    finally:
        await queue.stop(timeout_s=2.0)


# ---------------------------------------------------------------------------- 263-76 caps


async def test_queued_run_cap_per_printer() -> None:
    printer = TapeRoll()
    printer.gate = asyncio.Event()  # the first run blocks in the printer, the rest wait
    queue = await _queue(printer)
    key = uuid4()
    try:
        runs = []
        for _ in range(5):
            slot = _claim(queue, printer.id, key)
            runs.append(await _one_label_run(queue, printer.id, slot=slot))
            queue.release_run_slot(slot)  # what dispatch_batch does after the submit
        with pytest.raises(TooManyQueuedRunsError) as exc:
            _claim(queue, printer.id, uuid4())  # another key: the printer's cap still holds
        assert (exc.value.scope, exc.value.limit) == ("printer", 5)
        # Release path: the runs end, the cap frees.
        printer.gate.set()
        await _until(lambda: all(queue.run_info(r) is None for r, _ in runs))
        assert printer.calls == [1] * 5
        for _ in range(5):
            _claim(queue, printer.id, key)
    finally:
        await queue.stop(timeout_s=2.0)


async def test_a_pending_claim_counts_and_a_failed_submit_frees_it() -> None:
    printer = TapeRoll()
    queue = await _queue(printer)
    try:
        held = [_claim(queue, printer.id, None, per_printer=2) for _ in range(2)]
        with pytest.raises(TooManyQueuedRunsError):
            _claim(queue, printer.id, None, per_printer=2)
        # The submit failed before the queue took the run (render, lookup, preflight).
        queue.release_run_slot(held[0])
        queue.release_run_slot(held[0])  # idempotent
        _claim(queue, printer.id, None, per_printer=2)
    finally:
        await queue.stop(timeout_s=2.0)


async def test_a_cancelled_run_frees_the_cap() -> None:
    printer = TapeRoll()
    queue = await _queue(printer)
    queue._worker_states[printer.id] = pq.PrinterWorkerState.PAUSED  # nothing prints
    try:
        store = queue._store  # type: ignore[assignment]
        slot = _claim(queue, printer.id, None, per_printer=1)
        _run_id, jid = await _one_label_run(queue, printer.id, slot=slot, store=store)  # type: ignore[arg-type]
        queue.release_run_slot(slot)
        with pytest.raises(TooManyQueuedRunsError):
            _claim(queue, printer.id, None, per_printer=1)
        assert await queue.cancel(str(jid))
        _claim(queue, printer.id, None, per_printer=1)
    finally:
        await queue.stop(timeout_s=2.0)


async def _held_run(queue: PrintQueue, printer_id: UUID, key: UUID | None) -> UUID:
    """A run of *key* that waits for the confirmation of its second sub-job."""
    slot = _claim(queue, printer_id, key, per_printer=100, per_key=100)
    ids = [uuid4() for _ in range(MAX_LABELS_PER_TAPE_JOB + 1)]
    run_id = await queue.enqueue_batch(
        printer_id=printer_id,
        images=[_img() for _ in ids],
        job_ids=ids,
        tape_mm=12,
        options={},
        slot=slot,
    )
    queue.release_run_slot(slot)
    await _until(
        lambda: (
            queue.run_info(run_id) is not None
            and queue.run_info(run_id).state == "awaiting_confirmation"
        )  # type: ignore[union-attr]
    )
    return run_id


async def test_a_held_run_counts_against_its_key_until_it_is_discarded() -> None:
    printer = TapeRoll()
    queue = await _queue(printer)
    key = uuid4()
    try:
        run_id = await _held_run(queue, printer.id, key)
        with pytest.raises(TooManyQueuedRunsError) as exc:
            _claim(queue, printer.id, key, per_key=1)
        assert exc.value.scope == "key"
        # Security review: a held run does not use the printer; another key may queue.
        queue.release_run_slot(_claim(queue, printer.id, uuid4(), per_printer=1))
        await queue.discard_run(run_id)
        _claim(queue, printer.id, key, per_key=1)
    finally:
        await queue.stop(timeout_s=2.0)


async def test_a_stopped_run_counts_against_its_key_until_it_is_discarded() -> None:
    printer = TapeRoll(5)  # the tape ends in the first group: the run stops (fails)
    queue = await _queue(printer)
    key = uuid4()
    try:
        slot = _claim(queue, printer.id, key)
        ids = [uuid4() for _ in range(12)]
        run_id = await queue.enqueue_batch(
            printer_id=printer.id,
            images=[_img() for _ in ids],
            job_ids=ids,
            tape_mm=12,
            options={},
            slot=slot,
        )
        queue.release_run_slot(slot)
        await _until(
            lambda: queue.run_info(run_id) is not None and queue.run_info(run_id).state == "stopped"  # type: ignore[union-attr]
        )
        with pytest.raises(TooManyQueuedRunsError):
            _claim(queue, printer.id, key, per_key=1)
        queue.release_run_slot(_claim(queue, printer.id, uuid4(), per_printer=1))
        await queue.discard_run(run_id)
        _claim(queue, printer.id, key, per_key=1)
    finally:
        await queue.stop(timeout_s=2.0)


async def _fill_held(queue: PrintQueue, printer_id: UUID, keys: list[UUID | None]) -> list[UUID]:
    return [await _held_run(queue, printer_id, k) for k in keys]


def _held_ids(queue: PrintQueue, printer_id: UUID) -> list[UUID]:
    return [i.run_id for i in queue.held_runs(printer_id)]


async def test_a_key_holds_at_most_its_share_of_a_printer() -> None:
    """Security review 3: key A keeps at most MAX_HELD_RUNS_PER_KEY_PER_PRINTER held runs on a
    printer; a further one discards A's own oldest (``run_discarded_limit``)."""
    assert MAX_HELD_RUNS_PER_KEY_PER_PRINTER == 2 < MAX_HELD_RUNS_PER_PRINTER
    printer = TapeRoll()
    queue = await _queue(printer)
    a = uuid4()
    try:
        runs = await _fill_held(queue, printer.id, [a] * 4)
        assert _held_ids(queue, printer.id) == runs[2:]
        for gone in runs[:2]:
            assert queue._runs.get(gone) is None
    finally:
        await queue.stop(timeout_s=2.0)


async def test_a_small_batch_prints_while_every_held_place_is_taken() -> None:
    """F1/SR3: with all five held places taken by other keys, key B is refused a batch that
    can wait (more than one sub-job), but a batch of one sub-job is let through and prints."""
    printer = TapeRoll()
    queue = await _queue(printer)
    a, c, d, b = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        held = await _fill_held(queue, printer.id, [a, a, c, c, d])
        with pytest.raises(TooManyQueuedRunsError) as exc:
            _claim(queue, printer.id, b)  # may_hold defaults to True
        assert exc.value.scope == "printer"
        slot = queue.claim_run_slot(printer.id, b, per_printer=5, per_key=20, may_hold=False)
        run_b, _jid = await _one_label_run(queue, printer.id, slot=slot)
        queue.release_run_slot(slot)
        await _until(lambda: queue.run_info(run_b) is None)
        assert _held_ids(queue, printer.id) == held  # nothing of anyone was discarded
    finally:
        await queue.stop(timeout_s=2.0)


async def test_a_full_printer_refuses_a_key_without_held_runs_and_keeps_the_others() -> None:
    """Security review 2 "cross-key held eviction": the five held places belong to other keys;
    a batch of key B that can wait is refused (scope printer), nothing is discarded."""
    printer = TapeRoll()
    queue = await _queue(printer)
    a, c, d, b = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        held = await _fill_held(queue, printer.id, [a, a, c, c, d])
        with pytest.raises(TooManyQueuedRunsError) as exc:
            _claim(queue, printer.id, b)
        assert exc.value.scope == "printer"
        with pytest.raises(TooManyQueuedRunsError):
            _claim(queue, printer.id, None)  # no key: no held run of its own either
        assert _held_ids(queue, printer.id) == held
        queue.release_run_slot(_claim(queue, printer.id, a))  # A may: it gives up its own
        await queue.discard_run(held[0])
        queue.release_run_slot(_claim(queue, printer.id, b))  # a held place is free again
    finally:
        await queue.stop(timeout_s=2.0)


async def test_the_held_limit_discards_only_the_submitting_keys_runs() -> None:
    """The printer is full; key D submits a sixth: D's own oldest goes, the older runs of the
    other keys stay."""
    printer = TapeRoll()
    queue = await _queue(printer)
    a, c, d = uuid4(), uuid4(), uuid4()
    try:
        held = await _fill_held(queue, printer.id, [a, a, c, c, d])
        d_new = await _held_run(queue, printer.id, d)
        assert _held_ids(queue, printer.id) == [*held[:4], d_new]
        assert queue._runs.get(held[4]) is None
    finally:
        await queue.stop(timeout_s=2.0)


async def test_held_runs_without_a_key_are_not_displaced_by_a_key() -> None:
    printer = TapeRoll()
    queue = await _queue(printer)
    a, c = uuid4(), uuid4()
    try:
        keyless = await _fill_held(queue, printer.id, [None, None])
        others = await _fill_held(queue, printer.id, [c, a])
        a_new = await _held_run(queue, printer.id, a)  # 5 held: under both limits
        a_third = await _held_run(queue, printer.id, a)  # A's share: A's oldest goes
        assert _held_ids(queue, printer.id) == [*keyless, others[0], a_new, a_third]
    finally:
        await queue.stop(timeout_s=2.0)


async def test_a_run_of_a_key_without_older_runs_stays_over_the_limit() -> None:
    """B was admitted while a held place was free; the printer filled meanwhile. When B's run
    then waits, nothing of another key is discarded and B keeps its own: the printer is over
    the limit by the runs that were already printing."""
    printer = TapeRoll()
    queue = await _queue(printer)
    a, c, d, b = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        first = await _fill_held(queue, printer.id, [a, a, c, c])
        printer.gate = asyncio.Event()  # hold the next sub-jobs in the printer

        async def submit(key: UUID) -> UUID:
            slot = _claim(queue, printer.id, key)  # admitted: four held, one place free
            ids = [uuid4() for _ in range(MAX_LABELS_PER_TAPE_JOB + 1)]
            run_id = await queue.enqueue_batch(
                printer_id=printer.id,
                images=[_img() for _ in ids],
                job_ids=ids,
                tape_mm=12,
                options={},
                slot=slot,
            )
            queue.release_run_slot(slot)
            return run_id

        d_run = await submit(d)
        b_run = await submit(b)
        printer.gate.set()
        await _until(lambda: len(queue.held_runs(printer.id)) == MAX_HELD_RUNS_PER_PRINTER + 1)
        assert _held_ids(queue, printer.id) == [*first, d_run, b_run]
    finally:
        await queue.stop(timeout_s=2.0)


def test_the_printer_cap_must_cover_the_held_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import ValidationError

    monkeypatch.setenv("LABELYARD_MAX_QUEUED_RUNS_PER_PRINTER", str(MAX_HELD_RUNS_PER_PRINTER - 1))
    with pytest.raises(ValidationError, match="LABELYARD_MAX_QUEUED_RUNS_PER_PRINTER"):
        Settings()
    monkeypatch.setenv("LABELYARD_MAX_QUEUED_RUNS_PER_PRINTER", str(MAX_HELD_RUNS_PER_PRINTER))
    assert Settings().max_queued_runs_per_printer == MAX_HELD_RUNS_PER_PRINTER


async def test_an_unpersisted_run_counts_until_its_end_is_written() -> None:
    printer = TapeRoll()
    queue = await _queue(printer)
    try:
        run_id, jid = await _one_label_run(queue, printer.id)
        await _until(lambda: queue.run_info(run_id) is None)
        queue._unpersisted.add(str(jid))  # the end of the label could not be written
        with pytest.raises(TooManyQueuedRunsError):
            _claim(queue, printer.id, None, per_printer=1)
        queue._unpersisted.discard(str(jid))
        _claim(queue, printer.id, None, per_printer=1)
    finally:
        await queue.stop(timeout_s=2.0)


async def test_queued_run_cap_per_key() -> None:
    a, b = TapeRoll(), TapeRoll()
    a.gate = asyncio.Event()
    b.gate = a.gate
    queue = PrintQueue([a, b], store=MemoryJobStore())
    await queue.start()
    key, other = uuid4(), uuid4()
    try:
        runs = []
        for printer in (a, b):  # the key's cap spans printers
            slot = _claim(queue, printer.id, key, per_key=2)
            runs.append(await _one_label_run(queue, printer.id, slot=slot))
            queue.release_run_slot(slot)
        with pytest.raises(TooManyQueuedRunsError) as exc:
            _claim(queue, b.id, key, per_key=2)
        assert (exc.value.scope, exc.value.limit) == ("key", 2)
        _claim(queue, b.id, other, per_key=2)  # another key is not affected
        _claim(queue, b.id, None, per_key=2)  # no key: only the printer's cap applies
        a.gate.set()
        await _until(lambda: all(queue.run_info(r) is None for r, _ in runs))
        _claim(queue, a.id, key, per_key=2)
    finally:
        await queue.stop(timeout_s=2.0)


async def test_a_recovered_run_counts_against_the_printer() -> None:
    printer = TapeRoll()
    printer.gate = asyncio.Event()
    store = MemoryJobStore()
    run_id = uuid4()
    for i in range(2):
        await store.save_queued(
            DbJob(
                id=uuid4(),
                printer_id=printer.id,
                payload={
                    "tape_mm": 12,
                    "content_type": "qr_two_lines",
                    "rendered_tape_mm": 12,
                    "label_data": {
                        "source_app": "manual",
                        "title": f"R{i}",
                        "primary_id": "1",
                        "qr_payload": "https://r.example.invalid/1",
                    },
                    "options": {},
                    "tape_run": {"run_id": str(run_id), "awaits_confirmation": False},
                },
            )
        )
    queue = await _queue(printer, store)
    try:
        with pytest.raises(TooManyQueuedRunsError):
            _claim(queue, printer.id, None, per_printer=1)
        printer.gate.set()
        await _until(lambda: printer.calls == [2])
        await _until(lambda: _free(queue, printer.id))
    finally:
        await queue.stop(timeout_s=2.0)


def _free(queue: PrintQueue, printer_id: UUID) -> bool:
    try:
        queue.release_run_slot(_claim(queue, printer_id, None, per_printer=1))
    except TooManyQueuedRunsError:
        return False
    return True


# ---------------------------------------------------------------------------- 429 at the route


@asynccontextmanager
async def batch_route_rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[dict[str, Any]]:
    """The batch route over a real queue, built inside the test body.

    It was a ``pytest_asyncio`` fixture. The tests of this module run under anyio
    (``pytest.mark.anyio``), and then the fixture's event loop is not the test's: in the full
    suite the queue worker lived on the fixture's loop and never ran while the test awaited on
    its own, so the drain after ``gate.set()`` timed out (CI: worker ``loop=...880``, test
    ``loop=...312``, worker ``done=False``). Built in the body, the worker and the test share
    the loop by construction."""
    from app.api.error_handlers import register_error_handlers
    from app.api.routes import batch as batch_module
    from app.auth.dependencies import AuthContext
    from app.auth.scope_deps import require_print
    from app.db.session import get_session
    from fastapi import FastAPI

    printer = Printer(id=uuid4(), name="P", slug="p", model="PT-P750W", backend="ptouch")
    monkeypatch.setattr(
        batch_module.printers_repo, "resolve_by_slug_or_uuid", AsyncMock(return_value=printer)
    )
    monkeypatch.setattr(batch_module.batches_repo, "create", AsyncMock())
    roll = TapeRoll()
    roll.id = printer.id
    roll.gate = asyncio.Event()
    queue = PrintQueue([roll], store=MemoryJobStore())
    await queue.start()
    backend = AsyncMock()
    backend.half_cut_supported = False
    backend.preflight_check = AsyncMock(
        return_value=PreflightStatus(hr_printer_status="idle", loaded_tape_mm=12, error_flags=[])
    )
    store = MagicMock()
    store.save_queued = AsyncMock()
    service = PrintService(
        printer_id=printer.id, backend=backend, queue=queue, store=store, engine=LayoutEngine()
    )
    router_stub = MagicMock()
    router_stub.get = lambda _slug: backend
    router_stub.service_for = lambda _slug: service
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(batch_module.router)
    app.state.backend_router = router_stub
    app.state.print_queue = queue
    key = uuid4()
    ctx = AuthContext(source="api-key", scope="print", api_key_id=key, ip="127.0.0.1")
    app.dependency_overrides[require_print] = lambda: ctx

    async def _session() -> AsyncIterator[Any]:
        yield MagicMock()

    app.dependency_overrides[get_session] = _session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        try:
            yield {"client": client, "queue": queue, "store": store, "key": key, "roll": roll}
        finally:
            roll.gate.set()
            await queue.stop(timeout_s=2.0)


def _batch() -> dict[str, Any]:
    return {"items": [{"content_type": "qr_only", "data": {"qr_payload": "https://e.invalid/1"}}]}


async def test_the_route_answers_429_too_many_queued_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with batch_route_rig(monkeypatch) as batch_route:
        await _route_answers_429(batch_route)


async def _route_answers_429(batch_route: dict[str, Any]) -> None:
    client, queue = batch_route["client"], batch_route["queue"]
    assert queue._workers[batch_route["roll"].id].get_loop() is asyncio.get_running_loop()
    for _ in range(5):
        resp = await client.post("/api/v1/print/p/batch", json=_batch())
        assert resp.status_code == 202, resp.text
    resp = await client.post("/api/v1/print/p/batch", json=_batch())
    assert resp.status_code == 429, resp.text
    detail = resp.json()["detail"]
    assert set(detail) == {"error_code", "error_message", "retry_after_seconds"}
    assert detail["error_code"] == "too-many-queued-runs"
    assert resp.headers["Retry-After"] == str(detail["retry_after_seconds"])
    assert len(queue._runs) == 5  # the refused batch was not rendered, stored or queued
    # Release path through the route: the runs print, a new batch is taken.
    batch_route["roll"].gate.set()
    await _until(lambda: not queue._runs)
    resp = await client.post("/api/v1/print/p/batch", json=_batch())
    assert resp.status_code == 202, resp.text


async def test_a_refused_batch_stores_no_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    async with batch_route_rig(monkeypatch) as batch_route:
        client = batch_route["client"]
        monkeypatch.setenv("LABELYARD_MAX_QUEUED_RUNS_PER_KEY", "1")
        from app.config import get_settings

        get_settings.cache_clear()
        try:
            assert (await client.post("/api/v1/print/p/batch", json=_batch())).status_code == 202
            saved = batch_route["store"].save_queued.await_count
            resp = await client.post("/api/v1/print/p/batch", json=_batch())
            assert resp.status_code == 429
            assert resp.json()["detail"]["error_code"] == "too-many-queued-runs"
            assert batch_route["store"].save_queued.await_count == saved  # refused before any row
        finally:
            get_settings.cache_clear()


# ---------------------------------------------------------------------------- waiting pictures


async def test_waiting_run_rerenders_after_drop() -> None:
    printer = TapeRoll()
    sizes: list[tuple[int, int]] = []
    real = printer.print_images

    async def capture(images: list[Image.Image], *, tape_mm: int, **options: Any) -> None:
        sizes.extend(i.size for i in images)
        await real(images, tape_mm=tape_mm, **options)

    printer.print_images = capture  # type: ignore[method-assign]
    queue, run_id, ids, _store = await _run(printer, MAX_LABELS_PER_TAPE_JOB + 10)
    try:
        await _until(lambda: queue.run_info(run_id).state == "awaiting_confirmation")  # type: ignore[union-attr]
        run = queue._runs[run_id]
        waiting = [str(j) for j in ids[MAX_LABELS_PER_TAPE_JOB:]]
        assert run.held_since is not None
        assert queue.drop_waiting_pictures(now=run.held_since + WAITING_RUN_PICTURES_TTL_S - 1) == 0
        assert all(k in run.payloads for k in waiting)

        assert (
            queue.drop_waiting_pictures(now=run.held_since + WAITING_RUN_PICTURES_TTL_S + 1) == 10
        )
        assert not any(k in run.payloads for k in waiting)
        assert [(await queue.get(k)).image_payload for k in waiting] == [None] * 10

        await queue.confirm_run(run_id)
        await _until(lambda: queue.run_info(run_id) is None)
        assert printer.calls == [10] * 6
        assert all(s == (80, 40) for s in sizes[:MAX_LABELS_PER_TAPE_JOB])
        # The last ten were drawn again from their stored rows, not from the dropped pictures.
        assert all(s != (80, 40) for s in sizes[MAX_LABELS_PER_TAPE_JOB:])
        assert [(await queue.get(k)).state for k in waiting] == [JobState.COMPLETED] * 10
    finally:
        await queue.stop(timeout_s=2.0)


async def test_a_run_whose_rows_are_gone_answers_on_continue() -> None:
    printer = TapeRoll()
    queue, run_id, ids, store = await _run(printer, MAX_LABELS_PER_TAPE_JOB + 2)
    try:
        await _until(lambda: queue.run_info(run_id).state == "awaiting_confirmation")  # type: ignore[union-attr]
        run = queue._runs[run_id]
        queue.drop_waiting_pictures(now=run.held_since + WAITING_RUN_PICTURES_TTL_S + 1)  # type: ignore[operator]
        store._jobs.pop(ids[-1])
        with pytest.raises(pq.RunStateError) as exc:
            await queue.confirm_run(run_id)
        assert exc.value.code == "run_pictures_lost"
        assert queue.run_info(run_id).state == "awaiting_confirmation"  # type: ignore[union-attr]
        await queue.discard_run(run_id)
    finally:
        await queue.stop(timeout_s=2.0)


def test_the_cleanup_tick_drops_waiting_pictures() -> None:
    queue = MagicMock()
    queue.finished_jobs.return_value = []
    task = CleanupTask(store=AsyncMock(), retention_days=30, queue=queue)
    task._evict_once()
    queue.drop_waiting_pictures.assert_called_once_with()


# ---------------------------------------------------------------------------- 263-78 lookups


class _GatedLookup:
    def __init__(self) -> None:
        self.current = 0
        self.peak = 0
        self.started = 0
        self.gate = asyncio.Event()

    async def lookup(self, app: str, identifier: str) -> LabelData:
        self.started += 1
        self.current += 1
        self.peak = max(self.peak, self.current)
        try:
            await self.gate.wait()
        finally:
            self.current -= 1
        return LabelData(source_app=app, title="t", primary_id=identifier, qr_payload="x")


async def test_batch_lookups_are_bounded() -> None:
    backend = AsyncMock()
    backend.preflight_check = AsyncMock(
        return_value=PreflightStatus(hr_printer_status="idle", loaded_tape_mm=12, error_flags=[])
    )
    queue = MagicMock()
    queue.enqueue_batch = AsyncMock()
    store = MagicMock()
    store.save_queued = AsyncMock()
    lookups = _GatedLookup()
    svc = PrintService(
        printer_id=uuid4(),
        backend=backend,
        queue=queue,
        store=store,
        engine=LayoutEngine(),
        lookup_service=lookups,
    )
    requests = [
        PrintRequest(
            content_type=ContentType.QR_TWO_LINES,
            lookup=PrintLookupRequest(app="grocy", identifier=str(i)),
            options=PrintOptions(),
        )
        for i in range(20)
    ]
    task = asyncio.create_task(svc.submit_batch_job(requests, half_cut=False))
    await _until(lambda: lookups.started >= MAX_BATCH_LOOKUPS)
    for _ in range(50):  # let any lookup the bound would let through start
        await asyncio.sleep(0)
    assert lookups.started == MAX_BATCH_LOOKUPS
    lookups.gate.set()
    await task
    assert lookups.started == 20
    assert lookups.peak <= MAX_BATCH_LOOKUPS


# ---------------------------------------------------------------------------- 266-07 renders


async def test_cancelled_preview_keeps_its_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.sheets import print_service as sps

    release = threading.Event()
    entered = threading.Semaphore(0)
    ended: list[int] = []

    def slow_draw(n: int) -> int:
        entered.release()
        release.wait(5.0)
        ended.append(n)
        return n

    monkeypatch.setattr(sps, "_draw_page", slow_draw)
    assert sps.MAX_CONCURRENT_RENDERS == 2
    first = asyncio.create_task(sps.draw_page_bounded(1))
    second = asyncio.create_task(sps.draw_page_bounded(2))
    for _ in range(2):
        assert await asyncio.to_thread(entered.acquire, True, 5.0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    # The client is gone but its thread still draws: the slot stays taken until it ends.
    assert sps._gate().locked()
    release.set()
    assert await second == 2
    await _until(lambda: not sps._gate().locked() and len(ended) == 2)
    assert await sps.draw_page_bounded(3) == 3  # both slots free again


async def test_preview_slot_is_one_per_key() -> None:
    from app.sheets import print_service as sps

    key = uuid4()
    with sps.preview_slot(key):
        with pytest.raises(sps.TooManyPreviewsError), sps.preview_slot(key):
            pass
        with sps.preview_slot(uuid4()):  # another key previews meanwhile
            pass
    with pytest.raises(RuntimeError), sps.preview_slot(key):  # an error frees the slot too
        raise RuntimeError("boom")
    with sps.preview_slot(key):
        pass


async def test_a_cancelled_preview_keeps_its_key_slot_until_the_render_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F3: the key's preview slot is freed with the render slot, not at the cancel; otherwise
    one key could cancel and preview again and hold both render slots."""
    from app.sheets import print_service as sps

    release = threading.Event()
    entered = threading.Event()

    def slow_draw(n: int) -> int:
        entered.set()
        release.wait(5.0)
        return n

    monkeypatch.setattr(sps, "_draw_page", slow_draw)
    key = uuid4()

    async def a_preview() -> int:
        with sps.preview_slot(key):
            return int(await sps.draw_page_bounded(1))

    task = asyncio.create_task(a_preview())
    assert await asyncio.to_thread(entered.wait, 5.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(sps.TooManyPreviewsError), sps.preview_slot(key):  # still drawing
        pass
    release.set()
    await _until(lambda: key not in sps._previews_in_progress)
    with sps.preview_slot(key):
        pass


# ---------------------------------------------------------------------------- 266-14 reserve


async def test_reserve_does_not_block_loop(
    async_session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``plan`` runs in a thread under the write lock. The stand-in plan takes ``STALL`` of CPU
    time; on the loop that is a lag of at least ``STALL``. The bound is half of it, relative to
    the stall instead of an absolute 50 ms so a loaded runner does not fail it spuriously."""
    from app.sheets import reservation
    from app.sheets import sheet_service as ss
    from app.sheets import type_service as ts

    from tests.unit.sheets.test_reservation import G48, MARGIN, _fields, existing, meta

    stall = 0.6
    real_plan = reservation.plan

    def slow_plan(*args: Any, **kwargs: Any) -> Any:
        time.sleep(stall)  # stands in for the CPU work of a large plan
        return real_plan(*args, **kwargs)

    monkeypatch.setattr(reservation, "plan", slow_plan)
    async with async_session_factory() as session:
        await ts.create_type(session, _fields(), G48, actor="t")
        sheet = await ss.create_sheet(
            session,
            type_key=_fields().key,
            version=None,
            id_placement="manual",
            used_cells=[],
            note=None,
            actor="t",
        )
        lags: list[float] = []
        done = asyncio.Event()

        async def probe() -> None:
            last = time.monotonic()
            while not done.is_set():
                await asyncio.sleep(0.005)
                now = time.monotonic()
                lags.append(now - last)
                last = now

        ticker = asyncio.create_task(probe())
        try:
            pages = await reservation.reserve(
                session,
                placements=[existing(sheet.code)],
                items=meta(3),
                expected=None,
                hw_margins_hmm=None,
                margin=MARGIN,
                required_type_key=None,
                actor="t",
            )
        finally:
            done.set()
            await ticker
    assert len(pages) == 1
    assert max(lags) < stall / 2, max(lags)


def test_the_pdf_font_is_registered_up_front() -> None:
    from app.page_render import pdf
    from reportlab.pdfbase import pdfmetrics

    name = pdf.register_pdf_font()
    assert name in pdfmetrics.getRegisteredFontNames()
    assert pdf.register_pdf_font() == name  # idempotent


@pytest.mark.parametrize(
    ("items", "copies", "may_hold"), [(5, 10, False), (6, 10, True), (51, 1, True)]
)
async def test_dispatch_marks_only_batches_of_more_than_one_sub_job_as_holdable(
    items: int, copies: int, may_hold: bool
) -> None:
    """Labels = items x copies; more than MAX_LABELS_PER_TAPE_JOB waits for a confirmation."""
    from app.schemas.print_request import RawLabelData
    from app.services.batch_dispatch import dispatch_batch

    queue = MagicMock()
    queue.claim_run_slot = MagicMock(return_value=uuid4())
    service = MagicMock()
    service.submit_batch_job = AsyncMock(return_value=[])
    batch = [
        PrintRequest(
            content_type=ContentType.QR_ONLY,
            data=RawLabelData(qr_payload=f"https://e.invalid/{i}"),
            options=PrintOptions(copies=copies),
        )
        for i in range(items)
    ]
    await dispatch_batch(
        service=service, items=batch, queue=queue, printer_id=uuid4(), api_key_id=uuid4()
    )
    assert queue.claim_run_slot.call_args.kwargs["may_hold"] is may_hold
    queue.release_run_slot.assert_called_once()


@pytest.mark.parametrize("with_queue", [True, False])
async def test_dispatch_hands_the_submitting_key_to_the_service(with_queue: bool) -> None:
    """#294: every row of the batch records the key that submitted it, queue or not."""
    from app.schemas.print_request import RawLabelData
    from app.services.batch_dispatch import dispatch_batch

    queue = MagicMock()
    queue.claim_run_slot = MagicMock(return_value=uuid4())
    service = MagicMock()
    service.submit_batch_job = AsyncMock(return_value=[])
    key_id = uuid4()
    batch = [
        PrintRequest(
            content_type=ContentType.QR_ONLY, data=RawLabelData(qr_payload="https://e.invalid/1")
        )
    ]
    await dispatch_batch(
        service=service,
        items=batch,
        queue=queue if with_queue else None,
        printer_id=uuid4(),
        api_key_id=key_id,
        source_ip="192.0.2.5",
    )
    kwargs = service.submit_batch_job.await_args.kwargs
    assert (kwargs["api_key_id"], kwargs["source_ip"]) == (key_id, "192.0.2.5")
