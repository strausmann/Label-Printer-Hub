"""Unit-Tests für den Batch-Dispatcher (best-effort, pro-Item-Validation).

Phase 1k.2: dispatch_batch queued ONE BatchJob statt N PrintJobs.
Bestehende Tests wurden refactored — _FakePrintService hat jetzt
get_template_tape_mm() + submit_batch_job() statt submit_print_job().
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from app.schemas.print_request import PrintRequest, RawLabelData
from app.services.batch_dispatch import MixedTapeSizesError, dispatch_batch
from app.services.template_loader import TemplateNotFoundError

# Default tape_mm für alle "normal" Test-Items
_DEFAULT_TAPE_MM = 12
_OTHER_TAPE_MM = 24


class _FakePrintService:
    """Fake PrintService für dispatch_batch Unit-Tests (Phase 1k.2 Interface).

    - get_template_tape_mm(template_id) → int (simuliert TemplateLoader)
    - submit_batch_job(requests, half_cut) → list[UUID]

    fail_at_template: set of template_ids die TemplateNotFoundError werfen.
    tape_mm_for: dict template_id → tape_mm (default: _DEFAULT_TAPE_MM)
    """

    def __init__(
        self,
        *,
        fail_at_template: set[str] | None = None,
        tape_mm_for: dict[str, int] | None = None,
        batch_fail: type[Exception] | None = None,
    ) -> None:
        self.fail_at_template: set[str] = fail_at_template or set()
        self.tape_mm_for: dict[str, int] = tape_mm_for or {}
        self.batch_fail = batch_fail

        # Captured calls for assertion
        self.submit_batch_calls: list[tuple[list[PrintRequest], bool]] = []

    async def get_template_tape_mm(self, template_id: str) -> int:
        if template_id in self.fail_at_template:
            raise TemplateNotFoundError(template_id)
        return self.tape_mm_for.get(template_id, _DEFAULT_TAPE_MM)

    async def submit_batch_job(
        self,
        requests: list[PrintRequest],
        *,
        half_cut: bool,
    ) -> list[UUID]:
        self.submit_batch_calls.append((list(requests), half_cut))
        if self.batch_fail is not None:
            raise self.batch_fail("simulated batch failure")
        return [uuid4() for _ in requests]


class _FakeBackend:
    """Minimal PrinterBackend-Stub für half_cut_supported-Tests."""

    def __init__(self, half_cut_supported: bool = True) -> None:
        self.half_cut_supported = half_cut_supported


def _item(template_id: str = "hangar-furniture-12mm") -> PrintRequest:
    return PrintRequest(
        template_id=template_id,
        data=RawLabelData(title="t", primary_id="p", qr_payload="q"),
    )


# ---------------------------------------------------------------------------
# Basic batch success / partial-failure
# ---------------------------------------------------------------------------


async def test_dispatch_all_succeed():
    service = _FakePrintService()
    items = [_item() for _ in range(3)]
    job_ids, errors = await dispatch_batch(service, items)
    assert len(job_ids) == 3
    assert errors == []
    # submit_batch_job called exactly once
    assert len(service.submit_batch_calls) == 1
    batch_requests, _half_cut = service.submit_batch_calls[0]
    assert len(batch_requests) == 3


async def test_dispatch_partial_failure_keeps_going():
    """Template-not-found für Item 1 → das Item landet in errors[], rest wird gequeued."""
    service = _FakePrintService(fail_at_template={"typo"})
    items = [_item(), _item("typo"), _item()]
    job_ids, errors = await dispatch_batch(service, items)

    # 2 valide items → 2 job_ids
    assert len(job_ids) == 2
    assert len(errors) == 1
    assert errors[0].index == 1
    assert errors[0].error_code == "template_not_found"

    # submit_batch_job called once with 2 requests (not 3)
    assert len(service.submit_batch_calls) == 1
    batch_requests, _ = service.submit_batch_calls[0]
    assert len(batch_requests) == 2


async def test_dispatch_all_fail_no_batch_submitted():
    """Alle Items template_not_found → submit_batch_job wird NICHT aufgerufen."""
    service = _FakePrintService(fail_at_template={"tmpl-a", "tmpl-b"})
    items = [_item("tmpl-a"), _item("tmpl-b")]
    job_ids, errors = await dispatch_batch(service, items)

    assert job_ids == []
    assert len(errors) == 2
    assert service.submit_batch_calls == []


# ---------------------------------------------------------------------------
# Phase 1k.2: half_cut logic — jetzt als batch-global flag, nicht per-item
# ---------------------------------------------------------------------------


async def test_dispatch_half_cut_passed_to_submit_batch_job_when_backend_supports():
    """Backend supports half_cut → submit_batch_job bekommt half_cut=True."""
    service = _FakePrintService()
    backend = _FakeBackend(half_cut_supported=True)
    items = [_item() for _ in range(3)]

    await dispatch_batch(service, items, backend=backend)

    assert len(service.submit_batch_calls) == 1
    _, half_cut = service.submit_batch_calls[0]
    assert half_cut is True


async def test_dispatch_half_cut_false_when_backend_not_supported():
    """Backend half_cut_supported=False → submit_batch_job bekommt half_cut=False."""
    service = _FakePrintService()
    backend = _FakeBackend(half_cut_supported=False)
    items = [_item() for _ in range(3)]

    await dispatch_batch(service, items, backend=backend)

    assert len(service.submit_batch_calls) == 1
    _, half_cut = service.submit_batch_calls[0]
    assert half_cut is False


async def test_dispatch_half_cut_override_false_disables_half_cut():
    """half_cut_override=False erzwingt half_cut=False unabhängig vom Backend."""
    service = _FakePrintService()
    backend = _FakeBackend(half_cut_supported=True)
    items = [_item() for _ in range(3)]

    await dispatch_batch(service, items, half_cut_override=False, backend=backend)

    assert len(service.submit_batch_calls) == 1
    _, half_cut = service.submit_batch_calls[0]
    assert half_cut is False


async def test_dispatch_half_cut_override_true_with_backend_support():
    """half_cut_override=True + backend supported → half_cut=True."""
    service = _FakePrintService()
    backend = _FakeBackend(half_cut_supported=True)
    items = [_item()]

    await dispatch_batch(service, items, half_cut_override=True, backend=backend)

    assert len(service.submit_batch_calls) == 1
    _, half_cut = service.submit_batch_calls[0]
    assert half_cut is True


# ---------------------------------------------------------------------------
# Phase 1k.2: MixedTapeSizesError
# ---------------------------------------------------------------------------


async def test_dispatch_batch_uses_enqueue_batch_path():
    """dispatch_batch mit validen Items ruft submit_batch_job genau einmal auf."""
    service = _FakePrintService()
    items = [_item(), _item(), _item()]

    job_ids, errors = await dispatch_batch(service, items)

    assert len(job_ids) == 3
    assert errors == []
    assert len(service.submit_batch_calls) == 1


async def test_dispatch_batch_rejects_mixed_tape_sizes():
    """Items mit unterschiedlichen tape_mm werfen MixedTapeSizesError vor Queue."""
    service = _FakePrintService(
        tape_mm_for={
            "tmpl-12mm": 12,
            "tmpl-24mm": 24,
        }
    )
    items = [_item("tmpl-12mm"), _item("tmpl-24mm")]

    with pytest.raises(MixedTapeSizesError) as exc_info:
        await dispatch_batch(service, items)

    # submit_batch_job should NOT have been called
    assert service.submit_batch_calls == []
    # Error message includes the differing sizes
    err = exc_info.value
    assert 12 in err.tape_mm_values or 24 in err.tape_mm_values


async def test_dispatch_batch_mixed_tape_sizes_partial_valid():
    """Wenn ein Item fehlschlägt + rest mixed tape → MixedTapeSizesError für valide Items."""
    service = _FakePrintService(
        fail_at_template={"tmpl-bad"},
        tape_mm_for={
            "tmpl-12mm": 12,
            "tmpl-24mm": 24,
        },
    )
    # tmpl-bad → filtered out, tmpl-12mm + tmpl-24mm → mixed tape → raises
    items = [_item("tmpl-bad"), _item("tmpl-12mm"), _item("tmpl-24mm")]

    with pytest.raises(MixedTapeSizesError):
        await dispatch_batch(service, items)

    assert service.submit_batch_calls == []


async def test_dispatch_batch_same_tape_mm_not_rejected():
    """Alle Items mit gleicher tape_mm → kein Fehler, ONE batch."""
    service = _FakePrintService(
        tape_mm_for={
            "tmpl-a": 24,
            "tmpl-b": 24,
        }
    )
    items = [_item("tmpl-a"), _item("tmpl-b")]

    job_ids, errors = await dispatch_batch(service, items)

    assert len(job_ids) == 2
    assert errors == []
    assert len(service.submit_batch_calls) == 1
