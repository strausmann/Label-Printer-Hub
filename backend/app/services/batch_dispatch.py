"""Best-effort Batch-Dispatcher: validiert + queued pro Item, sammelt Errors."""

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
    from app.services.print_service import PrintService

_log = logging.getLogger(__name__)

# Per-item errors → collected into BatchError list (best-effort)
_PER_ITEM_ERRORS: dict[type[Exception], str] = {
    TemplateNotFoundError: "template_not_found",
    LookupFailedError: "integration_lookup_failed",
    TapeMismatchError: "tape_mismatch",
    TapeEmptyError: "tape_empty",
}

# Hardware preconditions → propagate (caller returns 409)
_BATCH_FATAL_ERRORS: tuple[type[Exception], ...] = (
    PrinterCoverOpenError,
    PrinterOfflineError,
    SnmpQueryError,
)


async def dispatch_batch(
    service: PrintService,
    items: list[PrintRequest],
) -> tuple[list[str], list[BatchError]]:
    """Queue each item individually. Collect per-item errors.
    Hardware errors propagate."""
    job_ids: list[str] = []
    errors: list[BatchError] = []

    for index, item in enumerate(items):
        try:
            job_id = await service.submit_print_job(item)
            job_ids.append(str(job_id))
        except _BATCH_FATAL_ERRORS:
            raise
        except tuple(_PER_ITEM_ERRORS) as exc:
            code = _PER_ITEM_ERRORS[type(exc)]
            detail: dict[str, object] | None = None
            if isinstance(exc, TapeMismatchError):
                detail = {"expected_mm": exc.expected_mm, "loaded_mm": exc.loaded_mm}
            errors.append(
                BatchError(
                    index=index,
                    error_code=code,
                    error_message=str(exc),
                    error_detail=detail,
                )
            )
        except Exception as exc:  # unknown sync failure
            _log.exception("unexpected error in batch item %d", index)
            errors.append(
                BatchError(
                    index=index,
                    error_code="internal_error",
                    error_message=str(exc),
                )
            )

    return job_ids, errors
