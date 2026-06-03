"""Unit-Tests für den Batch-Dispatcher (best-effort, pro-Item-Validation)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.schemas.print_request import PrintOptions, PrintRequest, RawLabelData
from app.services.batch_dispatch import dispatch_batch
from app.services.template_loader import TemplateNotFoundError


class _FakePrintService:
    def __init__(self, fail_at: dict[int, type[Exception]] | None = None):
        self.fail_at = fail_at or {}
        self.calls: int = 0
        self.submitted: list[PrintRequest] = []

    async def submit_print_job(self, req: PrintRequest):
        idx = self.calls
        self.calls += 1
        self.submitted.append(req)
        if idx in self.fail_at:
            raise self.fail_at[idx]("simulated")
        return str(uuid4())


class _FakeBackend:
    """Minimal PrinterBackend-Stub für half_cut_supported-Tests."""

    def __init__(self, half_cut_supported: bool = True) -> None:
        self.half_cut_supported = half_cut_supported


def _item(template_id="hangar-furniture-12mm"):
    return PrintRequest(
        template_id=template_id, data=RawLabelData(title="t", primary_id="p", qr_payload="q")
    )


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


# --- Phase 1i C-Fix: half_cut / last_page Pre-Compute Tests ---


@pytest.mark.asyncio
async def test_dispatch_last_item_gets_full_cut_no_half_cut():
    """Letztes Item bekommt last_page=True, half_cut=False (Voll-Cut)."""
    service = _FakePrintService()
    backend = _FakeBackend(half_cut_supported=True)
    items = [_item() for _ in range(3)]

    await dispatch_batch(service, items, backend=backend)

    assert len(service.submitted) == 3
    # intermediate items: half_cut=True (backend supports it), last_page=False
    assert service.submitted[0].options.half_cut is True
    assert service.submitted[0].options.last_page is False
    assert service.submitted[1].options.half_cut is True
    assert service.submitted[1].options.last_page is False
    # last item: half_cut=False, last_page=True
    assert service.submitted[2].options.half_cut is False
    assert service.submitted[2].options.last_page is True


@pytest.mark.asyncio
async def test_dispatch_single_item_last_page_true_no_half_cut():
    """Ein einzelnes Item ist immer last, also last_page=True, half_cut=False."""
    service = _FakePrintService()
    backend = _FakeBackend(half_cut_supported=True)
    items = [_item()]

    await dispatch_batch(service, items, backend=backend)

    assert service.submitted[0].options.half_cut is False
    assert service.submitted[0].options.last_page is True


@pytest.mark.asyncio
async def test_dispatch_half_cut_override_false_disables_half_cut():
    """half_cut_override=False unterdrückt half_cut auch für mittlere Items."""
    service = _FakePrintService()
    backend = _FakeBackend(half_cut_supported=True)
    items = [_item() for _ in range(3)]

    await dispatch_batch(service, items, half_cut_override=False, backend=backend)

    # All items should have half_cut=False since override=False
    for req in service.submitted:
        assert req.options.half_cut is False
    # last item still last_page=True
    assert service.submitted[-1].options.last_page is True


@pytest.mark.asyncio
async def test_dispatch_half_cut_suppressed_when_backend_not_supported():
    """half_cut=False wenn Backend half_cut_supported=False (z.B. QL-Series)."""
    service = _FakePrintService()
    backend = _FakeBackend(half_cut_supported=False)
    items = [_item() for _ in range(3)]

    await dispatch_batch(service, items, backend=backend)

    # Backend doesn't support half_cut — all items get half_cut=False
    for req in service.submitted:
        assert req.options.half_cut is False


@pytest.mark.asyncio
async def test_dispatch_print_options_stays_frozen():
    """PrintOptions ist frozen=True — dispatched options müssen immutable sein.

    dispatch_batch baut neue PrintOptions-Instanzen explizit (KEIN model_copy
    auf frozen PrintOptions). Dieser Test verifiziert dass:
    1. Die dispatched Options eine PrintOptions-Instanz sind.
    2. frozen=True gilt — direktes Setzen via setattr löst TypeError/ValidationError aus.
    """
    from pydantic import ValidationError

    service = _FakePrintService()
    backend = _FakeBackend(half_cut_supported=True)
    items = [_item()]

    await dispatch_batch(service, items, backend=backend)

    # Verify the submitted options are a fresh PrintOptions instance (frozen works)
    opts = service.submitted[0].options
    assert isinstance(opts, PrintOptions)
    # frozen=True — attempting to set an attribute via __setattr__ raises TypeError
    # (Pydantic V2 frozen models raise TypeError for direct attribute mutation)
    with pytest.raises((TypeError, ValidationError)):
        opts.half_cut = True  # type: ignore[misc]
