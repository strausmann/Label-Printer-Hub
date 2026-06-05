"""Unit-Tests für den Batch-Dispatcher.

Phase 1k.1a Task 17: MixedTapeSizesError + tape-consistency-Check entfernt.
dispatch_batch nimmt jetzt gemischte ContentTypes entgegen und delegiert
sofort an service.submit_batch_job(items, half_cut=...).
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.schemas.content_type import ContentType
from app.schemas.print_request import PrintRequest, RawLabelData
from app.services.batch_dispatch import dispatch_batch


class TestBatchDispatch:
    @pytest.mark.asyncio
    async def test_mixed_content_types_all_accepted(self) -> None:
        """Gemischte ContentTypes dürfen in einem Batch kombiniert werden."""
        service = AsyncMock()
        job_ids = [uuid4(), uuid4()]
        service.submit_batch_job = AsyncMock(return_value=job_ids)
        items = [
            PrintRequest(
                content_type=ContentType.QR_TWO_LINES,
                data=RawLabelData(
                    primary_id="A",
                    title="T",
                    qr_payload="https://example.com/a",
                ),
            ),
            PrintRequest(
                content_type=ContentType.QR_ONLY,
                data=RawLabelData(qr_payload="https://example.com/b"),
            ),
        ]
        await dispatch_batch(service=service, items=items)
        service.submit_batch_job.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_items_rejected(self) -> None:
        """Leere Item-Liste löst ValueError aus."""
        service = AsyncMock()
        with pytest.raises(ValueError, match="at least one"):
            await dispatch_batch(service=service, items=[])

    @pytest.mark.asyncio
    async def test_single_item_dispatched(self) -> None:
        """Ein einzelnes Item wird korrekt an submit_batch_job weitergeleitet."""
        service = AsyncMock()
        job_ids = [uuid4()]
        service.submit_batch_job = AsyncMock(return_value=job_ids)
        items = [
            PrintRequest(
                content_type=ContentType.TEXT_ONE_LINE,
                data=RawLabelData(primary_id="X"),
            ),
        ]
        await dispatch_batch(service=service, items=items)
        service.submit_batch_job.assert_awaited_once()
        call_args = service.submit_batch_job.call_args
        # Erstes Positional-Argument sind unsere Items
        assert call_args.args[0] == items

    @pytest.mark.asyncio
    async def test_return_value_forwarded(self) -> None:
        """Rückgabe von submit_batch_job wird 1:1 weitergereicht."""
        service = AsyncMock()
        expected_job_ids = [uuid4(), uuid4(), uuid4()]
        service.submit_batch_job = AsyncMock(return_value=expected_job_ids)
        items = [
            PrintRequest(
                content_type=ContentType.QR_ONE_LINE,
                data=RawLabelData(primary_id="Y", qr_payload="https://example.com"),
            )
            for _ in range(3)
        ]
        result = await dispatch_batch(service=service, items=items)
        assert result == expected_job_ids

    @pytest.mark.asyncio
    async def test_half_cut_default_is_false(self) -> None:
        """half_cut defaults to False when not explicitly passed."""
        service = AsyncMock()
        service.submit_batch_job = AsyncMock(return_value=[uuid4()])
        items = [
            PrintRequest(
                content_type=ContentType.QR_ONLY,
                data=RawLabelData(qr_payload="https://example.com"),
            ),
        ]
        await dispatch_batch(service=service, items=items)
        _, kwargs = service.submit_batch_job.call_args
        assert kwargs["half_cut"] is False

    @pytest.mark.asyncio
    async def test_half_cut_forwarded_when_true(self) -> None:
        """half_cut=True wird an submit_batch_job weitergeleitet."""
        service = AsyncMock()
        service.submit_batch_job = AsyncMock(return_value=[uuid4()])
        items = [
            PrintRequest(
                content_type=ContentType.QR_ONLY,
                data=RawLabelData(qr_payload="https://example.com"),
            ),
        ]
        await dispatch_batch(service=service, items=items, half_cut=True)
        _, kwargs = service.submit_batch_job.call_args
        assert kwargs["half_cut"] is True
