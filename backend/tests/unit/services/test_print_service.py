"""Unit tests for PrintService with LayoutEngine integration.

Phase 1k.1a Task 15: Replaces all template_id / TapeMismatchError / PAUSED-path
tests with new LayoutEngine-based tests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from app.printer_backends.exceptions import (
    NoTapeLoadedError,
    PrinterCoverOpenError,
    PrinterOfflineError,
    TapeEmptyError,
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
from app.services.print_service import PrintService

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
        await svc.submit_batch_job([request], half_cut=True)
        queue.enqueue_batch.assert_awaited_once()
        kwargs = queue.enqueue_batch.await_args.kwargs
        assert len(kwargs["images"]) == 3, "copies=3 must yield 3 images"
        assert len(kwargs["job_ids"]) == 3, "job_ids must match images length"
        # Alle drei job_ids zeigen auf den gleichen Hangar-Request-Job
        assert len(set(kwargs["job_ids"])) == 1, "same job_id replicated 3x"

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
        await svc.submit_batch_job([req1, req2], half_cut=False)
        kwargs = queue.enqueue_batch.await_args.kwargs
        assert len(kwargs["images"]) == 3, "copies=2 + copies=1 = 3 images"
        assert len(kwargs["job_ids"]) == 3
        assert len(set(kwargs["job_ids"])) == 2, "two distinct request-jobs"


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

        lookup_svc = AsyncMock()
        lookup_svc.resolve = AsyncMock(
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
        lookup_svc.resolve.assert_awaited_once_with("hangar", "K02")
        queue.submit_with_id.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_data_path_bypasses_lookup(self, make_service) -> None:
        """data path: lookup_service.resolve is never called."""
        lookup_svc = AsyncMock()
        lookup_svc.resolve = AsyncMock()

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
        lookup_svc.resolve.assert_not_awaited()
