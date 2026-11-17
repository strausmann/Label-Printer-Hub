# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The error bits of a tape printer before and after a job is sent (#389).

Neither library reads anything back over the network: ``brother_ql.backends.helpers.send``
returns as soon as the bytes are written when the backend is ``network`` ("The network backend
doesn't support readback"), and ``ptouch`` only writes. A printer that refuses the job (wrong
roll, open cover, no tape) would leave it ``done``.

So the same set of blocking bits is used twice:

- **Before sending** (``raise_for_error_flags`` in every backend's ``preflight_check``): any
  blocking bit refuses the job, nothing is sent.
- **After sending** (``check_after_send``): the queue printer waits a short moment, reads the
  status once and fails the job only on blocking bits that are **new** compared with the read
  before sending. A bit that was there all along refused up front; it never turns a printed label
  into a failed one that a retry prints again.

Not verified on hardware: which ``hrPrinterDetectedErrorState`` bit a QL printer sets for a
wrong roll type, and how soon after the job the bit is visible. ``POST_SEND_SETTLE_S`` is a
first value, not a measured one.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any, Final

from app.printer_backends.exceptions import (
    PrinterCoverOpenError,
    PrinterReportedError,
    TapeEmptyError,
)

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
warnings and never refuse or fail a job."""


def raise_for_error_flags(flags: Iterable[str]) -> None:
    """Raise for the first blocking bit in *flags*; warnings pass.

    ``noPaper`` → ``TapeEmptyError``, ``doorOpen`` → ``PrinterCoverOpenError`` (their own #378
    codes), any other blocking bit → ``PrinterReportedError`` with all of them (``printer_error``).
    """
    blocking = [f for f in flags if f in HARD_ERROR_FLAGS]
    if "noPaper" in blocking:
        raise TapeEmptyError()
    if "doorOpen" in blocking:
        raise PrinterCoverOpenError()
    if blocking:
        raise PrinterReportedError(blocking)


def _flags_before_send(backend: Any) -> frozenset[str]:
    flags = getattr(backend, "flags_before_send", None)
    if isinstance(flags, (set, frozenset, list, tuple)):
        return frozenset(f for f in flags if isinstance(f, str))
    return frozenset()


async def check_after_send(backend: Any, *, settle_s: float = POST_SEND_SETTLE_S) -> None:
    """Wait ``settle_s``, read the status once and raise on a **new** blocking bit.

    The status is read with the backend's ``read_status`` (no refusal on bits), else its
    ``preflight_check``. Raises ``PrinterOfflineError`` when it cannot be read, else what
    ``raise_for_error_flags`` raises for the bits not in ``backend.flags_before_send``.
    """
    if settle_s > 0:
        await asyncio.sleep(settle_s)
    if getattr(type(backend), "read_status", None) is not None:
        status = await backend.read_status()
    else:
        status = await backend.preflight_check()
    before = _flags_before_send(backend)
    raise_for_error_flags(f for f in status.error_flags if f not in before)
