# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The status check after a tape job was sent (#389).

Neither library reads anything back over the network: ``brother_ql.backends.helpers.send``
returns as soon as the bytes are written when the backend is ``network`` ("The network backend
doesn't support readback"), and ``ptouch`` only writes. A printer that refuses the job (wrong
roll, open cover, no tape) would leave it ``done``. So after sending, the queue printer waits a
short moment and asks the printer's status over SNMP once; an error state there fails the job.

Not verified on hardware: which ``hrPrinterDetectedErrorState`` bit a QL printer sets for a
wrong roll type, and how soon after the job the bit is visible. ``POST_SEND_SETTLE_S`` is a
first value, not a measured one.
"""

from __future__ import annotations

import asyncio
from typing import Any, Final

from app.printer_backends.exceptions import PrinterReportedError

POST_SEND_SETTLE_S: Final = 1.0
"""Seconds between sending a job and reading the status (the printer needs a moment)."""

HARD_ERROR_FLAGS: Final = frozenset(
    {
        "noPaper",
        "doorOpen",
        "jammed",
        "offline",
        "serviceRequested",
        "inputTrayMissing",
        "outputTrayMissing",
        "markerSupplyMissing",
        "outputFull",
        "inputTrayEmpty",
    }
)
"""The error bits that stop a print. ``lowPaper``, ``lowToner`` and ``overduePreventMaint`` are
warnings and never fail a job."""


async def check_after_send(backend: Any, *, settle_s: float = POST_SEND_SETTLE_S) -> None:
    """Wait ``settle_s``, read the status once and raise on an error state.

    Raises what the backend's ``preflight_check`` raises (``TapeEmptyError``,
    ``PrinterCoverOpenError``, ``PrinterOfflineError`` when the status cannot be read) and
    ``PrinterReportedError`` for any other bit of ``HARD_ERROR_FLAGS``.
    """
    if settle_s > 0:
        await asyncio.sleep(settle_s)
    status = await backend.preflight_check()
    flags = [f for f in status.error_flags if f in HARD_ERROR_FLAGS]
    if flags:
        raise PrinterReportedError(flags)
