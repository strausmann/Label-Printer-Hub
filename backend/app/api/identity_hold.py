"""The refusal for a printer whose device was flagged as swapped (#231).

Sheet prints and calibration pages are refused at submit and at retry while the flag is set.
The sheet routes keep their documented ``SheetApiError`` envelope; the calibration and job
routes answer with a ``ProblemDetail`` under ``detail``. Either names the printer id and
nothing else, so no identity value can reach a caller below admin.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status

from app.schemas.problem import ProblemDetail
from app.services.page_jobs import IDENTITY_MISMATCH_CODE
from app.services.print_queue import PrintQueue
from app.sheets.errors import PrinterIdentityMismatchError


def identity_mismatch_error(printer_id: UUID) -> HTTPException:
    """The ``ProblemDetail`` 409 for a held printer."""
    problem = ProblemDetail(
        type=IDENTITY_MISMATCH_CODE,
        title="The device behind this printer changed",
        status=status.HTTP_409_CONFLICT,
        detail=(
            f"Printer {printer_id}: sheet and calibration jobs are held until the device "
            "is confirmed"
        ),
    )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail=problem.model_dump(exclude_none=True)
    )


def _held(queue: PrintQueue | None, printer_id: UUID) -> bool:
    # ``is True``: a stand-in queue in a test must not read as held by accident.
    return queue is not None and queue.is_identity_held(printer_id) is True


def ensure_not_held(queue: PrintQueue | None, printer_id: UUID) -> None:
    """Raise the ``ProblemDetail`` 409 when *queue* holds sheet and calibration jobs."""
    if _held(queue, printer_id):
        raise identity_mismatch_error(printer_id)


def ensure_sheet_not_held(queue: PrintQueue | None, printer_id: UUID) -> None:
    """The same refusal in the sheet routes' ``SheetApiError`` envelope."""
    if _held(queue, printer_id):
        raise PrinterIdentityMismatchError(printer_id).to_http()
