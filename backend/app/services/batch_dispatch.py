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
from app.schemas.print_request import PrintOptions, PrintRequest
from app.services.lookup_service import LookupFailedError
from app.services.template_loader import TemplateNotFoundError

if TYPE_CHECKING:
    from app.printer_backends.base import PrinterBackend
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
    *,
    half_cut_override: bool | None = None,
    backend: PrinterBackend | None = None,
) -> tuple[list[str], list[BatchError]]:
    """Queue each item individually. Collect per-item errors.
    Hardware errors propagate.

    Phase 1i C-Fix:
    - half_cut_override: None=Hub-Default (False), True/False=explizit.
      Bei backend ohne half_cut_supported wird half_cut=False erzwungen.
    - backend: PrinterBackend-Instanz für half_cut_supported Check.
    - Pre-Compute last_page + half_cut per Item vor dem Submit.
      KEIN model_copy auf frozen PrintOptions — explizit neues Objekt bauen.
    """
    job_ids: list[str] = []
    errors: list[BatchError] = []

    last_index = len(items) - 1
    # Determine whether backend supports half_cut (default to False if unknown)
    backend_supports_half_cut: bool = getattr(backend, "half_cut_supported", False)

    for index, item in enumerate(items):
        try:
            is_last = index == last_index
            # last_page=True only for last item → full cut at end
            # last_page=False for intermediate items → no cut between
            use_last_page = is_last

            # half_cut logic:
            # - For non-last items: use half_cut_override (if set) or True
            #   (taktile Separation zwischen Labels) — but only if backend supports it.
            # - For last item: always False (Voll-Cut übernimmt die Trennung).
            if is_last:
                use_half_cut = False
            elif half_cut_override is not None:
                use_half_cut = half_cut_override and backend_supports_half_cut
            else:
                # Default: half_cut=True between items if backend supports it
                use_half_cut = backend_supports_half_cut

            # Build patched PrintOptions explicitly (frozen=True → no model_copy!)
            patched_options = PrintOptions(
                copies=item.options.copies,
                auto_cut=item.options.auto_cut,
                high_resolution=item.options.high_resolution,
                half_cut=use_half_cut,
                last_page=use_last_page,
            )
            # PrintRequest is NOT frozen → model_copy is safe here
            patched_item = item.model_copy(update={"options": patched_options})

            job_id = await service.submit_print_job(patched_item)
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
