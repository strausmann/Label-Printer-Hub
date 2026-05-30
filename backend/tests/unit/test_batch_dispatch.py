"""Unit-Tests für den Batch-Dispatcher (best-effort, pro-Item-Validation)."""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.schemas.print_batch import BatchError
from app.schemas.print_request import PrintRequest, RawLabelData
from app.services.batch_dispatch import dispatch_batch
from app.services.template_loader import TemplateNotFoundError


class _FakePrintService:
    def __init__(self, fail_at: dict[int, type[Exception]] | None = None):
        self.fail_at = fail_at or {}
        self.calls = 0

    async def submit_print_job(self, req: PrintRequest):
        idx = self.calls
        self.calls += 1
        if idx in self.fail_at:
            raise self.fail_at[idx]("simulated")
        return str(uuid4())


def _item(template_id="hangar-furniture-12mm"):
    return PrintRequest(template_id=template_id,
                        data=RawLabelData(title="t", primary_id="p", qr_payload="q"))


@pytest.mark.asyncio
async def test_dispatch_all_succeed():
    service = _FakePrintService()
    items = [_item() for _ in range(3)]
    job_ids, errors = await dispatch_batch(service, items)
    assert len(job_ids) == 3
    assert errors == []


@pytest.mark.asyncio
async def test_dispatch_partial_failure_keeps_going():
    service = _FakePrintService(fail_at={1: TemplateNotFoundError})
    items = [_item(), _item("typo"), _item()]
    job_ids, errors = await dispatch_batch(service, items)
    assert len(job_ids) == 2
    assert len(errors) == 1
    assert errors[0].index == 1
    assert errors[0].error_code == "template_not_found"
