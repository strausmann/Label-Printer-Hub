# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for PrintService with LayoutEngine integration.

Phase 1k.1a Task 15: Replaces all template_id / TapeMismatchError / PAUSED-path
tests with new LayoutEngine-based tests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from app.printer_backends.exceptions import (
    NoTapeLoadedError,
    PrinterCoverOpenError,
    PrinterDisabledError,
    PrinterOfflineError,
    TapeEmptyError,
    UnsupportedTapeError,
)
from app.printer_backends.snmp_helper import PreflightStatus
from app.schemas.content_type import ContentType
from app.schemas.print_request import (
    PrintLookupRequest,
    PrintOptions,
    PrintRequest,
    RawLabelData,
)
from app.services.layout_engine import LayoutEngine
from app.services.lookup_service import AppLookupService
from app.services.print_service import PrintService
from app.services.test_label import TapeTestText
from app.services.test_label import test_label_band as band_of

_PRINTER_ID = UUID("bbbbbbbb-0000-0000-0000-000000000001")


def _preflight(loaded_tape_mm: int | None = 12) -> PreflightStatus:
    return PreflightStatus(
        hr_printer_status="idle",
        loaded_tape_mm=loaded_tape_mm,
        error_flags=[],
    )


@pytest.fixture
def make_service():
    """Factory: returns (svc, queue_mock, store_mock, backend_mock)."""

    def _make(
        loaded_tape_mm: int | None = 12,
    ) -> tuple[PrintService, MagicMock, MagicMock, MagicMock]:
        backend = AsyncMock()
        backend.preflight_check = AsyncMock(return_value=_preflight(loaded_tape_mm))

        queue = MagicMock()
        queue.submit_with_id = AsyncMock()

        store = MagicMock()
        store.save_queued = AsyncMock()

        engine = LayoutEngine()

        svc = PrintService(
            printer_id=_PRINTER_ID,
            backend=backend,
            queue=queue,
            store=store,
            engine=engine,
        )
        return svc, queue, store, backend

    return _make


# ---------------------------------------------------------------------------
# Happy-path: submit_print_job
# ---------------------------------------------------------------------------


class TestSubmitPrintJob:
    @pytest.mark.asyncio
    async def test_label_transform_and_source_app_reach_the_stored_payload(
        self, make_service
    ) -> None:
        """The transform runs on the resolved data before it is rendered and stored (#284)."""
        svc, _queue, store, _backend = make_service()
        request = PrintRequest(
            content_type=ContentType.QR_THREE_LINES,
            data=RawLabelData(
                primary_id="K02", title="Workshop", qr_payload="https://example.com/x"
            ),
        )
        await svc.submit_print_job(
            request,
            source_app="spoolman",
            label_transform=lambda label: label.model_copy(update={"secondary": ("851g",)}),
        )
        label = store.save_queued.await_args.args[0].payload["label_data"]
        assert (label["source_app"], label["secondary"]) == ("spoolman", ("851g",))

    @pytest.mark.asyncio
    async def test_without_a_transform_the_data_is_unchanged_and_manual(self, make_service) -> None:
        svc, _queue, store, _backend = make_service()
        request = PrintRequest(
            content_type=ContentType.QR_TWO_LINES,
            data=RawLabelData(
                primary_id="K02", title="Workshop", qr_payload="https://example.com/x"
            ),
        )
        await svc.submit_print_job(request)
        label = store.save_queued.await_args.args[0].payload["label_data"]
        assert (label["source_app"], label["secondary"]) == ("manual", ())

    @pytest.mark.asyncio
    async def test_renders_on_loaded_tape_mm_18(self, make_service) -> None:
        """Happy path: 18mm tape, QR_TWO_LINES — returns UUID, queue.submit called."""
        svc, queue, _store, _backend = make_service(loaded_tape_mm=18)
        request = PrintRequest(
            content_type=ContentType.QR_TWO_LINES,
            data=RawLabelData(
                primary_id="K02",
                title="Workshop",
                qr_payload="https://example.com/x",
            ),
        )
        job_id = await svc.submit_print_job(request)
        assert isinstance(job_id, UUID)
        queue.submit_with_id.assert_awaited_once()
        kwargs = queue.submit_with_id.await_args.kwargs
        assert kwargs.get("tape_mm") == 18

    @pytest.mark.asyncio
    async def test_renders_on_loaded_tape_mm_12(self, make_service) -> None:
        """Happy path: 12mm tape, QR_ONE_LINE."""
        svc, queue, _store, _backend = make_service(loaded_tape_mm=12)
        request = PrintRequest(
            content_type=ContentType.QR_ONE_LINE,
            data=RawLabelData(
                primary_id="A01",
                qr_payload="https://example.com/a",
            ),
        )
        job_id = await svc.submit_print_job(request)
        assert isinstance(job_id, UUID)
        queue.submit_with_id.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_qr_only_renders_minimally(self, make_service) -> None:
        """QR_ONLY: only qr_payload required — renders and queues."""
        svc, queue, _store, _backend = make_service(loaded_tape_mm=12)
        request = PrintRequest(
            content_type=ContentType.QR_ONLY,
            data=RawLabelData(qr_payload="https://example.com/x"),
        )
        await svc.submit_print_job(request)
        queue.submit_with_id.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_uuid(self, make_service) -> None:
        """submit_print_job always returns a fresh UUID."""
        svc, _queue, _store, _backend = make_service(loaded_tape_mm=24)
        request = PrintRequest(
            content_type=ContentType.QR_ONLY,
            data=RawLabelData(qr_payload="https://example.com/x"),
        )
        job_id = await svc.submit_print_job(request)
        assert isinstance(job_id, UUID)

    @pytest.mark.asyncio
    async def test_store_save_queued_called(self, make_service) -> None:
        """store.save_queued is called once before queue.submit."""
        svc, _queue, store, _backend = make_service(loaded_tape_mm=12)
        request = PrintRequest(
            content_type=ContentType.QR_ONLY,
            data=RawLabelData(qr_payload="https://example.com/x"),
        )
        await svc.submit_print_job(request)
        store.save_queued.assert_called_once()

    @pytest.mark.asyncio
    async def test_options_forwarded_to_queue(self, make_service) -> None:
        """PrintOptions fields are forwarded to queue.submit as kwargs."""
        svc, queue, _store, _backend = make_service(loaded_tape_mm=12)
        request = PrintRequest(
            content_type=ContentType.QR_ONLY,
            data=RawLabelData(qr_payload="https://example.com/x"),
            options=PrintOptions(auto_cut=False, high_resolution=True),
        )
        await svc.submit_print_job(request)
        queue.submit_with_id.assert_awaited_once()
        kwargs = queue.submit_with_id.await_args.kwargs
        assert kwargs["auto_cut"] is False
        assert kwargs["high_resolution"] is True
        assert kwargs["tape_mm"] == 12
        assert "copies" not in kwargs


# ---------------------------------------------------------------------------
# Copies-Replikation in submit_batch_job (Bug 2026-06-14)
# ---------------------------------------------------------------------------


class TestSubmitBatchJobCopies:
    """Verifiziert dass PrintOptions.copies > 1 in enqueue_batch zu N Images
    repliziert wird. Bug 2026-06-14: zuvor wurde copies in der DB gespeichert
    aber nie an print_multi() weitergereicht → User-Report nur 1 Etikett
    statt N. Refs Hangar Issue #109."""

    @pytest.mark.asyncio
    async def test_copies_3_yields_three_images(self, make_service) -> None:
        svc, queue, _store, _backend = make_service(loaded_tape_mm=12)
        queue.enqueue_batch = AsyncMock()
        request = PrintRequest(
            content_type=ContentType.QR_TWO_LINES,
            data=RawLabelData(
                primary_id="SMA-022-003",
                title="Samla 22L Box 3",
                qr_payload="https://example.com/loc/SMA-022-003",
            ),
            options=PrintOptions(copies=3),
        )
        master_ids = await svc.submit_batch_job([request], half_cut=True)
        queue.enqueue_batch.assert_awaited_once()
        kwargs = queue.enqueue_batch.await_args.kwargs
        assert len(kwargs["images"]) == 3, "copies=3 must yield 3 images"
        assert len(kwargs["job_ids"]) == 3, "job_ids must match images length"
        # Bug Round 2: jeder Copy braucht eine eigene job_id, sonst skippt
        # der BatchWorker die 2. und 3. Etiketten als "already printing".
        assert len(set(kwargs["job_ids"])) == 3, "each copy needs unique job_id"
        # Hangar-API: trotzdem nur 1 master-ID pro Request zurueck (1:1 mit
        # Hangar-Bestellung), der erste der drei Hub-internen job_ids.
        assert len(master_ids) == 1
        assert master_ids[0] in kwargs["job_ids"], "master id must be one of the enqueued job_ids"

    @pytest.mark.asyncio
    async def test_batch_cut_mode_is_stored_in_every_row(self, make_service) -> None:
        """A recovery after a restart reads the cut mode from the rows: the batch-level
        half_cut must be there, not the item default (False)."""
        svc, queue, store, _backend = make_service(loaded_tape_mm=12)
        queue.enqueue_batch = AsyncMock()
        request = PrintRequest(
            content_type=ContentType.QR_ONLY,
            data=RawLabelData(qr_payload="https://example.com/x"),
            options=PrintOptions(copies=2),
        )
        await svc.submit_batch_job([request], half_cut=True)
        rows = [c.args[0] for c in store.save_queued.await_args_list]
        assert [r.payload["options"]["half_cut"] for r in rows] == [True, True]

    @pytest.mark.asyncio
    async def test_copies_1_yields_single_image(self, make_service) -> None:
        svc, queue, _store, _backend = make_service(loaded_tape_mm=12)
        queue.enqueue_batch = AsyncMock()
        request = PrintRequest(
            content_type=ContentType.QR_ONLY,
            data=RawLabelData(qr_payload="https://example.com/x"),
            options=PrintOptions(copies=1),
        )
        await svc.submit_batch_job([request], half_cut=False)
        kwargs = queue.enqueue_batch.await_args.kwargs
        assert len(kwargs["images"]) == 1
        assert len(kwargs["job_ids"]) == 1

    @pytest.mark.asyncio
    async def test_mixed_copies_per_request(self, make_service) -> None:
        """Mehrere Requests mit unterschiedlichem copies-Wert: total images = Summe."""
        svc, queue, _store, _backend = make_service(loaded_tape_mm=12)
        queue.enqueue_batch = AsyncMock()
        req1 = PrintRequest(
            content_type=ContentType.QR_ONLY,
            data=RawLabelData(qr_payload="https://example.com/a"),
            options=PrintOptions(copies=2),
        )
        req2 = PrintRequest(
            content_type=ContentType.QR_ONLY,
            data=RawLabelData(qr_payload="https://example.com/b"),
            options=PrintOptions(copies=1),
        )
        master_ids = await svc.submit_batch_job([req1, req2], half_cut=False)
        kwargs = queue.enqueue_batch.await_args.kwargs
        assert len(kwargs["images"]) == 3, "copies=2 + copies=1 = 3 images"
        assert len(kwargs["job_ids"]) == 3
        # Bug Round 2: 3 unique job_ids — 2 fuer req1 (copies=2) + 1 fuer req2.
        assert len(set(kwargs["job_ids"])) == 3, "all 3 copy jobs must be unique"
        # 1 master_id pro Request (Hangar-API): 2 Requests → 2 master ids.
        assert len(master_ids) == 2

    @pytest.mark.asyncio
    async def test_labels_past_the_first_sub_job_await_a_confirmation(self, make_service) -> None:
        """#277: the run id goes to the queue; label 51 on waits for a confirmation."""
        svc, queue, store, _backend = make_service(loaded_tape_mm=12)
        queue.enqueue_batch = AsyncMock()
        run_id = uuid4()
        request = PrintRequest(
            content_type=ContentType.QR_ONLY,
            data=RawLabelData(qr_payload="https://example.com/x"),
            options=PrintOptions(copies=10),
        )
        labels: list[UUID] = []
        masters = await svc.submit_batch_job(
            [request] * 6, half_cut=False, run_id=run_id, label_ids=labels
        )
        kwargs = queue.enqueue_batch.await_args.kwargs
        assert kwargs["run_id"] == run_id
        assert labels == kwargs["job_ids"] and len(labels) == 60 and len(masters) == 6
        rows = [c.args[0] for c in store.save_queued.await_args_list]
        waits = [r.payload["tape_run"]["awaits_confirmation"] for r in rows]
        assert waits == [False] * 50 + [True] * 10
        assert {r.payload["tape_run"]["run_id"] for r in rows} == {str(run_id)}


# ---------------------------------------------------------------------------
# NoTapeLoadedError when preflight returns loaded_tape_mm=None
# ---------------------------------------------------------------------------


class TestNoTapeLoaded:
    @pytest.mark.asyncio
    async def test_no_tape_loaded_raises(self, make_service) -> None:
        """loaded_tape_mm=None → NoTapeLoadedError, queue never called."""
        svc, queue, _store, _backend = make_service(loaded_tape_mm=None)
        request = PrintRequest(
            content_type=ContentType.QR_ONLY,
            data=RawLabelData(qr_payload="https://example.com/x"),
        )
        with pytest.raises(NoTapeLoadedError):
            await svc.submit_print_job(request)
        queue.submit_with_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_tape_store_not_called(self, make_service) -> None:
        """When no tape loaded, store.save_queued must NOT be called."""
        svc, _queue, store, _backend = make_service(loaded_tape_mm=None)
        request = PrintRequest(
            content_type=ContentType.QR_ONLY,
            data=RawLabelData(qr_payload="https://example.com/x"),
        )
        with pytest.raises(NoTapeLoadedError):
            await svc.submit_print_job(request)
        store.save_queued.assert_not_called()


# ---------------------------------------------------------------------------
# Preflight: other printer errors
# ---------------------------------------------------------------------------


class TestPreflightErrors:
    @pytest.mark.asyncio
    async def test_preflight_offline_raises(self, make_service) -> None:
        """PrinterOfflineError from preflight propagates, queue never called."""
        svc, queue, _store, backend = make_service(loaded_tape_mm=12)
        backend.preflight_check.side_effect = PrinterOfflineError("unreachable")
        request = PrintRequest(
            content_type=ContentType.QR_ONLY,
            data=RawLabelData(qr_payload="https://example.com/x"),
        )
        with pytest.raises(PrinterOfflineError):
            await svc.submit_print_job(request)
        queue.submit_with_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_preflight_tape_empty_raises(self, make_service) -> None:
        """TapeEmptyError from preflight propagates, queue never called."""
        svc, queue, _store, backend = make_service(loaded_tape_mm=12)
        backend.preflight_check.side_effect = TapeEmptyError()
        request = PrintRequest(
            content_type=ContentType.QR_ONLY,
            data=RawLabelData(qr_payload="https://example.com/x"),
        )
        with pytest.raises(TapeEmptyError):
            await svc.submit_print_job(request)
        queue.submit_with_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_preflight_cover_open_raises(self, make_service) -> None:
        """PrinterCoverOpenError from preflight propagates, queue never called."""
        svc, queue, _store, backend = make_service(loaded_tape_mm=12)
        backend.preflight_check.side_effect = PrinterCoverOpenError()
        request = PrintRequest(
            content_type=ContentType.QR_ONLY,
            data=RawLabelData(qr_payload="https://example.com/x"),
        )
        with pytest.raises(PrinterCoverOpenError):
            await svc.submit_print_job(request)
        queue.submit_with_id.assert_not_awaited()


# ---------------------------------------------------------------------------
# Lookup path
# ---------------------------------------------------------------------------


class TestLookupPath:
    @pytest.mark.asyncio
    async def test_lookup_path_calls_lookup_service(self, make_service) -> None:
        """lookup request resolves via lookup_service, then renders + queues."""
        from app.schemas.label_data import LabelData

        # spec= makes a call to a method AppLookupService does not have fail, as in production.
        lookup_svc = AsyncMock(spec=AppLookupService)
        lookup_svc.lookup = AsyncMock(
            return_value=LabelData(
                title="Workshop",
                primary_id="K02",
                qr_payload="https://example.com/x",
                source_app="hangar",
            )
        )

        backend = AsyncMock()
        backend.preflight_check = AsyncMock(return_value=_preflight(18))
        queue = MagicMock()
        queue.submit_with_id = AsyncMock()
        store = MagicMock()
        store.save_queued = AsyncMock()
        engine = LayoutEngine()

        svc = PrintService(
            printer_id=_PRINTER_ID,
            backend=backend,
            queue=queue,
            store=store,
            engine=engine,
            lookup_service=lookup_svc,
        )

        request = PrintRequest(
            content_type=ContentType.QR_TWO_LINES,
            lookup=PrintLookupRequest(app="hangar", identifier="K02"),
        )
        job_id = await svc.submit_print_job(request)
        assert isinstance(job_id, UUID)
        lookup_svc.lookup.assert_awaited_once_with("hangar", "K02")
        queue.submit_with_id.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_data_path_bypasses_lookup(self, make_service) -> None:
        """data path: lookup_service.lookup is never called."""
        lookup_svc = AsyncMock(spec=AppLookupService)
        lookup_svc.lookup = AsyncMock()

        backend = AsyncMock()
        backend.preflight_check = AsyncMock(return_value=_preflight(12))
        queue = MagicMock()
        queue.submit_with_id = AsyncMock()
        store = MagicMock()
        store.save_queued = AsyncMock()
        engine = LayoutEngine()

        svc = PrintService(
            printer_id=_PRINTER_ID,
            backend=backend,
            queue=queue,
            store=store,
            engine=engine,
            lookup_service=lookup_svc,
        )

        request = PrintRequest(
            content_type=ContentType.QR_ONLY,
            data=RawLabelData(qr_payload="https://example.com/x"),
        )
        await svc.submit_print_job(request)
        lookup_svc.lookup.assert_not_awaited()


# ---------------------------------------------------------------------------
# Phase 4 — PrinterDisabledError (enabled-Check)
# ---------------------------------------------------------------------------


def _make_disabled_service() -> tuple[PrintService, MagicMock, MagicMock]:
    """Hilfsfunktion: PrintService mit printer_enabled=False."""
    backend = AsyncMock()
    backend.preflight_check = AsyncMock(return_value=_preflight(12))

    queue = MagicMock()
    queue.submit_with_id = AsyncMock()

    store = MagicMock()
    store.save_queued = AsyncMock()

    svc = PrintService(
        printer_id=_PRINTER_ID,
        printer_slug="brother-p750w",
        printer_enabled=False,
        backend=backend,
        queue=queue,
        store=store,
        engine=LayoutEngine(),
    )
    return svc, queue, store


class TestPrinterDisabledCheck:
    """PrintService wirft PrinterDisabledError bei deaktiviertem Drucker."""

    @pytest.mark.asyncio
    async def test_disabled_printer_raises_printer_disabled_error(self) -> None:
        """submit_print_job mit disabled Drucker → PrinterDisabledError."""
        svc, _queue, _store = _make_disabled_service()
        request = PrintRequest(
            content_type=ContentType.QR_ONE_LINE,
            data=RawLabelData(
                primary_id="K01",
                title="Regal",
                qr_payload="https://example.com/k01",
            ),
        )
        with pytest.raises(PrinterDisabledError) as exc_info:
            await svc.submit_print_job(request)
        assert exc_info.value.slug == "brother-p750w"
        assert exc_info.value.printer_id == _PRINTER_ID

    @pytest.mark.asyncio
    async def test_disabled_printer_queue_never_called(self) -> None:
        """Bei disabled Drucker wird queue.submit_with_id NICHT aufgerufen."""
        svc, queue, _store = _make_disabled_service()
        request = PrintRequest(
            content_type=ContentType.QR_ONLY,
            data=RawLabelData(qr_payload="https://example.com/x"),
        )
        with pytest.raises(PrinterDisabledError):
            await svc.submit_print_job(request)
        queue.submit_with_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_disabled_printer_store_never_called(self) -> None:
        """Bei disabled Drucker wird store.save_queued NICHT aufgerufen."""
        svc, _queue, store = _make_disabled_service()
        request = PrintRequest(
            content_type=ContentType.QR_ONLY,
            data=RawLabelData(qr_payload="https://example.com/x"),
        )
        with pytest.raises(PrinterDisabledError):
            await svc.submit_print_job(request)
        store.save_queued.assert_not_called()

    @pytest.mark.asyncio
    async def test_enabled_printer_succeeds(self, make_service) -> None:
        """printer_enabled=True (Default) — kein Fehler, Job wird eingereicht."""
        svc, queue, _store, _backend = make_service(loaded_tape_mm=12)
        request = PrintRequest(
            content_type=ContentType.QR_ONE_LINE,
            data=RawLabelData(
                primary_id="K02",
                title="Lager",
                qr_payload="https://example.com/k02",
            ),
        )
        job_id = await svc.submit_print_job(request)
        assert isinstance(job_id, UUID)
        queue.submit_with_id.assert_awaited_once()


# ---------------------------------------------------------------------------
# Deferred jobs (#281): a failing end-of-job write must not break a stop
# ---------------------------------------------------------------------------


async def _interrupted_jobs(svc: PrintService, backend: MagicMock, count: int) -> list[UUID]:
    """``count`` deferred jobs whose preflight never returns."""
    import asyncio

    started = asyncio.Semaphore(0)

    async def slow_preflight() -> PreflightStatus:
        started.release()
        await asyncio.sleep(60)
        return _preflight()

    backend.preflight_check = slow_preflight
    ids = [
        await svc.accept_deferred_job(
            RawLabelData(title="Oat milk", primary_id=str(n), qr_payload=f"grcy:p:{n}"),
            content_type=ContentType.QR_TWO_LINES,
            source_app="grocy",
            api_key_id=None,
            source_ip=None,
        )
        for n in range(count)
    ]
    for _ in ids:
        await asyncio.wait_for(started.acquire(), 2)
    return ids


class TestCancelDeferred:
    async def test_a_store_error_while_ending_the_jobs_does_not_raise(self, make_service) -> None:
        svc, queue, store, backend = make_service()
        store.mark_queued_many_failed_restart = AsyncMock(
            side_effect=RuntimeError("database is locked")
        )
        ids = await _interrupted_jobs(svc, backend, 2)
        await svc.cancel_deferred()  # must not raise: the recovery ends the rows later
        store.mark_queued_many_failed_restart.assert_awaited_once()
        assert sorted(store.mark_queued_many_failed_restart.await_args.args[0]) == sorted(ids)
        queue.submit_with_id.assert_not_called()

    async def test_many_jobs_end_in_one_bounded_write(self, make_service) -> None:
        """Review N1: one store call for all of them, and a stuck store cannot hold the stop."""
        import asyncio
        import time

        from app.services.print_service import DEFERRED_STOP_BUDGET_S

        svc, _queue, store, backend = make_service()

        async def locked(_ids: list[UUID], _error: str) -> list[UUID]:
            await asyncio.sleep(30)  # the database lock never clears
            return []

        store.mark_queued_many_failed_restart = AsyncMock(side_effect=locked)
        await _interrupted_jobs(svc, backend, 20)
        started = time.monotonic()
        await svc.cancel_deferred()
        elapsed = time.monotonic() - started
        assert store.mark_queued_many_failed_restart.await_count == 1
        assert elapsed < DEFERRED_STOP_BUDGET_S + 0.5

    async def test_ended_jobs_are_announced_failed_restart(self, make_service) -> None:
        """Review N4: a watcher sees the job leave ``queued``."""
        from app.services.event_bus import EventBus

        svc, _queue, store, backend = make_service()
        bus = EventBus()
        svc._event_bus = bus
        events = bus.subscribe(f"printer:{_PRINTER_ID}:queue", "t")
        ids = await _interrupted_jobs(svc, backend, 2)
        # The store ended only the first one (the second was cancelled meanwhile).
        store.mark_queued_many_failed_restart = AsyncMock(return_value=[ids[0]])
        await svc.cancel_deferred()
        frames = []
        while not events.empty():
            frames.append(events.get_nowait())
        assert [(f.data["job_id"], f.data["from_state"], f.data["to_state"]) for f in frames] == [
            (str(ids[0]), "queued", "failed_restart")
        ]
        assert frames[0].data["error_code"] == "deferred_interrupted"


# ---------------------------------------------------------------------------
# The test label on every tape width (#377)
# ---------------------------------------------------------------------------

_TEST_LABEL_CASES = [
    *(("brother_ql", "QL-820NWB", mm) for mm in (12, 29, 38, 50, 54, 62)),
    *(("ptouch", "PT-E550W", mm) for mm in (4, 6, 9, 12, 18, 24)),
    ("ptouch", "PT-P900", 36),
]


def _test_text(width_mm: int) -> TapeTestText:
    return TapeTestText(
        printer="Workshop",
        width_mm=width_mm,
        printed_at="2026-11-17 14:03",
        version="1.7.0",
        qr_payload="https://hub.example.invalid/printers/0d5c6b1e-8f6a-4f4e-9d61-3a2b9c1f7e42",
    )


class TestTestLabel:
    @pytest.mark.parametrize(
        ("backend_name", "model", "mm"),
        _TEST_LABEL_CASES,
        ids=[f"{m}-{mm}" for _b, m, mm in _TEST_LABEL_CASES],
    )
    async def test_test_label_prints_on_every_tape_width(
        self, make_service, backend_name: str, model: str, mm: int
    ) -> None:
        svc, queue, store, backend = make_service(loaded_tape_mm=mm)
        band = band_of(backend_name, model, mm)
        job_id = await svc.submit_test_label(
            _test_text, lambda width: band_of(backend_name, model, width)
        )
        queue.submit_with_id.assert_awaited_once()
        args, kwargs = queue.submit_with_id.await_args
        assert args[0] == job_id
        assert args[2].height == band.px
        assert (kwargs["tape_mm"], kwargs["orientation"]) == (mm, "along")
        job = store.save_queued.await_args.args[0]
        assert job.template_key == "test_label"
        assert job.payload["options"]["orientation"] == "along"
        assert job.payload["test_label"]["px"] == band.px
        assert job.payload["test_label"]["dpi"] == band.dpi
        assert job.payload["label_data"]["title"] == f"{mm} mm · 2026-11-17 14:03"
        assert backend.preflight_check.await_count == 1

    async def test_test_label_payload_names_no_connection(self, make_service) -> None:
        svc, _queue, store, _backend = make_service(loaded_tape_mm=24)
        await svc.submit_test_label(_test_text, lambda width: band_of("ptouch", "PT-E550W", width))
        stored = str(store.save_queued.await_args.args[0].payload)
        for leak in ("192.0.2", "community", "ptouch", "brother_ql", "PT-E550W", "snmp"):
            assert leak not in stored

    async def test_a_width_the_model_lacks_refuses_before_rendering(self, make_service) -> None:
        svc, queue, store, _backend = make_service(loaded_tape_mm=36)
        with pytest.raises(UnsupportedTapeError):
            await svc.submit_test_label(
                _test_text, lambda width: band_of("ptouch", "PT-E550W", width)
            )
        queue.submit_with_id.assert_not_awaited()
        store.save_queued.assert_not_awaited()

    async def test_no_tape_is_refused(self, make_service) -> None:
        svc, _queue, _store, _backend = make_service(loaded_tape_mm=None)
        with pytest.raises(NoTapeLoadedError):
            await svc.submit_test_label(
                _test_text, lambda width: band_of("ptouch", "PT-E550W", width)
            )

    async def test_a_disabled_printer_is_refused(self, make_service) -> None:
        svc, _queue, _store, backend = make_service()
        svc._printer_enabled = False
        with pytest.raises(PrinterDisabledError):
            await svc.submit_test_label(
                _test_text, lambda width: band_of("ptouch", "PT-E550W", width)
            )
        backend.preflight_check.assert_not_awaited()

    async def test_an_offline_printer_is_refused(self, make_service) -> None:
        svc, queue, _store, backend = make_service()
        backend.preflight_check.side_effect = PrinterOfflineError("unreachable")
        with pytest.raises(PrinterOfflineError):
            await svc.submit_test_label(
                _test_text, lambda width: band_of("ptouch", "PT-E550W", width)
            )
        queue.submit_with_id.assert_not_awaited()
