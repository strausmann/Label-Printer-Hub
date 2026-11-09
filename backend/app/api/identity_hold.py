"""The refusal for a printer whose device was flagged as swapped (#231).

Sheet prints and calibration pages are refused at submit and at retry while the flag is set.
The body is a ``ProblemDetail`` under ``detail``; its text names the printer id and nothing
else, so no identity value can reach a caller below admin.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.schemas.problem import ProblemDetail
from app.services.page_jobs import IDENTITY_MISMATCH_CODE


def identity_mismatch_error(printer_id: UUID) -> HTTPException:
    """The 409 for a held printer."""
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


def ensure_not_held(queue: Any, printer_id: UUID) -> None:
    """Raise the 409 when *queue* holds sheet and calibration jobs of *printer_id*.

    ``queue`` is the app's print queue (or ``None``: the caller's own "no queue" handling
    stays in charge).
    """
    held = getattr(queue, "is_identity_held", None)
    if held is not None and held(printer_id) is True:
        raise identity_mismatch_error(printer_id)
