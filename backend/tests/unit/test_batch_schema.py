"""BatchRequest/Response/Error Schema-Validation."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.schemas.print_batch import BatchError, BatchRequest, BatchResponse
from app.schemas.print_request import PrintRequest, RawLabelData
from pydantic import ValidationError


def _sample_item() -> PrintRequest:
    from app.schemas.content_type import ContentType

    return PrintRequest(
        content_type=ContentType.QR_TWO_LINES,
        data=RawLabelData(
            title="Kallax 10 Fach 2-3",
            primary_id="HH-AK-KX10-F0203",
            qr_payload="https://hangar.test/loc/HH-AK-KX10-F0203",
        ),
    )


def test_batch_request_accepts_items():
    req = BatchRequest(items=[_sample_item(), _sample_item()])
    assert len(req.items) == 2


def test_batch_request_rejects_empty():
    with pytest.raises(ValidationError, match="at least 1 item"):
        BatchRequest(items=[])


def test_batch_request_caps_at_500():
    items = [_sample_item() for _ in range(501)]
    with pytest.raises(ValidationError, match="at most 500"):
        BatchRequest(items=items)


def test_batch_response_with_all_succeeded():
    resp = BatchResponse(
        batch_id=uuid4(),
        printer_id=uuid4(),
        queued_at="2026-05-30T19:42:01Z",
        job_ids=[str(uuid4()) for _ in range(5)],
        errors=[],
    )
    assert len(resp.job_ids) == 5
    assert resp.errors == []


def test_batch_error_with_required_fields():
    err = BatchError(
        index=3, error_code="template_not_found", error_message="Template 'x' does not exist"
    )
    assert err.index == 3
