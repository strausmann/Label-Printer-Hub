"""Best-effort Batch-Dispatcher: validiert + queued als atomic BatchJob.

Phase 1k.2: Statt N PrintJobs (einer pro Item) wird genau EINE BatchJob
in die Queue gegeben. Der Backend (PT-Series) verwendet ptouch.print_multi
für atomic batch printing mit 5mm Half-Cut zwischen Labels.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.printer_backends.exceptions import (
    PrinterCoverOpenError,
    PrinterOfflineError,
    SnmpQueryError,
    TapeEmptyError,
    TapeMismatchError,
)
from app.schemas.print_batch import BatchError
from app.schemas.print_request import PrintRequest
from app.services.lookup_service import LookupFailedError
from app.services.template_loader import TemplateNotFoundError

if TYPE_CHECKING:
    from app.printer_backends.base import PrinterBackend
    from app.services.print_service import PrintService

_log = logging.getLogger(__name__)


class MixedTapeSizesError(Exception):
    """Batch enthält Items mit unterschiedlichen template.tape_mm.

    Phase 1k.2: ptouch.print_multi unterstützt nur ein tape pro Call.
    Vor Queue abfangen → 400 Response.
    """

    def __init__(self, tape_mm_values: list[int]) -> None:
        super().__init__(f"Mixed tape sizes in batch: {sorted(set(tape_mm_values))}")
        self.tape_mm_values = tape_mm_values


# Per-item errors → collected into BatchError list (best-effort)
_PER_ITEM_ERRORS: dict[type[Exception], str] = {
    TemplateNotFoundError: "template_not_found",
    LookupFailedError: "integration_lookup_failed",
    TapeEmptyError: "tape_empty",
}

# Hardware preconditions → propagate (caller returns 409 or 400)
_BATCH_FATAL_ERRORS: tuple[type[Exception], ...] = (
    PrinterCoverOpenError,
    PrinterOfflineError,
    SnmpQueryError,
    TapeMismatchError,  # atomic per Phase 1k.2 Spec
    MixedTapeSizesError,
)


async def dispatch_batch(
    service: PrintService,
    items: list[PrintRequest],
    *,
    half_cut_override: bool | None = None,
    backend: PrinterBackend | None = None,
) -> tuple[list[str], list[BatchError]]:
    """Render N items, queue ONE BatchJob via PrintService.submit_batch_job.

    Phase 1k.2 architecture:
    - Per-item validation (template_not_found, lookup_failed) collected in errors[]
    - Hardware errors (printer_offline, cover_open, tape_mismatch) propagated to caller
    - Mixed tape_mm → MixedTapeSizesError (400)
    - Successful items → ONE BatchJob mit allen Images, gemeinsamer half_cut Logic

    Returns:
        (job_ids_str, errors): job_ids im Erfolgsfall, BatchError list für skipped items.
        Bei BatchJob-Submit: alle job_ids gehören zu einer atomar-failed/atomar-success Batch.
    """
    errors: list[BatchError] = []
    valid_items: list[tuple[int, PrintRequest, int]] = []  # (orig_index, request, tape_mm)

    # 1. Per-item validation: collect tape_mm + flag failures.
    for index, item in enumerate(items):
        try:
            # Copilot-Review C7: public get_template_tape_mm statt _loader private access
            tape_mm = await _validate_item_get_tape_mm(service, item)
            valid_items.append((index, item, tape_mm))
        except _BATCH_FATAL_ERRORS:
            raise
        except tuple(_PER_ITEM_ERRORS) as exc:
            code = _PER_ITEM_ERRORS[type(exc)]
            errors.append(BatchError(index=index, error_code=code, error_message=str(exc)))
        except Exception as exc:  # unknown sync failure
            _log.exception("unexpected error validating batch item %d", index)
            errors.append(
                BatchError(index=index, error_code="internal_error", error_message=str(exc))
            )

    if not valid_items:
        return [], errors

    # 2. Mixed tape_mm check
    tape_mm_set = {tm for _, _, tm in valid_items}
    if len(tape_mm_set) > 1:
        raise MixedTapeSizesError([tm for _, _, tm in valid_items])

    # 3. Backend half_cut capability
    backend_supports_half_cut: bool = getattr(backend, "half_cut_supported", False)
    if half_cut_override is not None:
        use_half_cut = half_cut_override and backend_supports_half_cut
    else:
        use_half_cut = backend_supports_half_cut

    # 4. Submit as single BatchJob
    requests = [req for _, req, _ in valid_items]
    job_ids = await service.submit_batch_job(
        requests,
        half_cut=use_half_cut,
    )

    return [str(jid) for jid in job_ids], errors


async def _validate_item_get_tape_mm(
    service: PrintService,
    item: PrintRequest,
) -> int:
    """Load template via public PrintService API, return tape_mm.

    Raises TemplateNotFoundError on miss.

    Copilot-Review C7 (PR #106): vorher hat dieser helper auf das private
    Attribut service._loader zugegriffen. Pläne auf Internals brechen bei
    Refactors. Stattdessen wird ein public Helper get_template_tape_mm auf
    PrintService aufgerufen (Task 9 Step 4a ergänzt diese Methode).
    """
    return await service.get_template_tape_mm(item.template_id)
