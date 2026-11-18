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

#393: the check after sending also **confirms** the labels: the IPP job state when the labels
went out over IPP, else the label counter (``prtMarkerLifeCount``) polled until it rose by the
labels sent. See ``check_after_send`` and ``tape_confirmation``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Final

from app.printer_backends.exceptions import (
    LabelsNotConfirmedError,
    PrinterCoverOpenError,
    PrinterOfflineError,
    PrinterReportedError,
    SnmpQueryError,
    TapeEmptyError,
)
from app.printer_backends.snmp_helper import PreflightStatus
from app.printer_backends.tape_confirmation import (
    CONFIRM_POLL_S,
    COUNTER_JUMP_SLACK,
    ConfirmationRecord,
    TapeSendState,
    confirm_timeout_s,
)

_logger = logging.getLogger(__name__)

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


async def _read(backend: Any) -> PreflightStatus:
    if getattr(type(backend), "read_status", None) is not None:
        status: PreflightStatus = await backend.read_status()
    else:
        status = await backend.preflight_check()
    return status


def _count_of(status: object) -> int | None:
    count = getattr(status, "marker_count", None)
    return count if isinstance(count, int) and not isinstance(count, bool) else None


def _labels_sent(backend: Any, state: TapeSendState | None) -> int:
    if state is not None:
        return state.labels_sent
    sent = getattr(backend, "labels_sent", 0)
    return sent if isinstance(sent, int) and not isinstance(sent, bool) else 0


async def check_after_send(
    backend: Any,
    *,
    settle_s: float = POST_SEND_SETTLE_S,
    poll_s: float | None = None,
    timeout_s: float | None = None,
) -> None:
    """Wait ``settle_s``, then confirm that the labels sent since the read before sending
    printed (#393), raising on a **new** blocking bit on every read (#389).

    The backend tells how many labels it sent (``send_state.labels_sent`` or ``labels_sent``)
    and keeps the read before sending (``last_send_status``, with the label counter).

    - **IPP jobs** of the send (``send_state.ipp_jobs``) are polled until a final state. ``9``
      counts as printed; the counter is read once more as a second witness and a disagreement
      is only logged (IPP wins). ``aborted``/``canceled``/no final state in time: a blocking bit
      raises its error, else ``LabelsNotConfirmedError(impressions completed, sent)``.
    - **Label counter:** polled every ``poll_s`` until it rose by the labels sent and the
      printer is idle (``hrPrinterStatus`` 3; a QL reports 1 while printing). A shortfall at
      the timeout raises ``LabelsNotConfirmedError(printed, sent)``. A counter that is missing
      before or after, went down, or jumped by more than the labels plus ``COUNTER_JUMP_SLACK``
      is logged and accepted: a job never fails on a counter that cannot be interpreted.
    - No label count (a backend that does not report one): one read, as before #393.

    A test print (``send_state.detecting``) also decides and stores the ``ConfirmationRecord``;
    an IPP job of it that did not complete is sent once more over TCP 9100.

    The status is read with the backend's ``read_status`` (no refusal on bits), else its
    ``preflight_check``. A read that fails raises ``PrinterOfflineError`` when nothing could be
    read at all; failures while polling are retried until the timeout.
    """
    if settle_s > 0:
        await asyncio.sleep(settle_s)
    state = getattr(backend, "send_state", None)
    if not isinstance(state, TapeSendState):
        state = None
    expected = _labels_sent(backend, state)
    before_flags = _flags_before_send(backend)
    poll = CONFIRM_POLL_S if poll_s is None else poll_s
    limit = confirm_timeout_s(expected) if timeout_s is None else timeout_s
    before = _count_of(getattr(backend, "last_send_status", None))

    def raise_new_bits(status: PreflightStatus) -> None:
        raise_for_error_flags(f for f in status.error_flags if f not in before_flags)

    ipp_completed = False
    if state is not None and state.ipp_jobs:
        outcome = await state.ipp.wait(state.ipp_jobs, timeout_s=limit, poll_s=poll)
        if outcome.completed:
            ipp_completed = True
        else:
            status = await _read(backend)
            raise_new_bits(status)
            if state.detecting and state.last_raw is not None:
                # A test print: IPP does not work for this printer; the label goes out over 9100.
                _logger.warning("IPP test job did not complete; sending it over TCP 9100")
                state.detect_ipp_failed = True
                before = _count_of(status)
                raw, labels = state.last_raw
                state.ipp_jobs = []
                await raw()
                expected = labels
            else:
                raise LabelsNotConfirmedError(outcome.printed, expected)

    if expected <= 0:
        raise_new_bits(await _read(backend))
        return

    loop = asyncio.get_running_loop()
    deadline = loop.time() + limit
    counter_exact = False
    printed: int | None = None
    while True:
        try:
            status = await _read(backend)
        except (PrinterOfflineError, SnmpQueryError):
            if loop.time() >= deadline or ipp_completed:
                await _finish(state, ipp_completed, counter_exact)
                if ipp_completed:
                    _logger.warning("Status after a confirmed IPP job not readable")
                    return
                raise
            await asyncio.sleep(poll)
            continue
        after = _count_of(status)
        if ipp_completed:
            new_bits = [f for f in status.error_flags if f not in before_flags]
            if any(f in HARD_ERROR_FLAGS for f in new_bits):
                _logger.warning("Error bits %s after a completed IPP job (printed)", new_bits)
            if before is not None and after is not None and after - before != expected:
                _logger.warning(
                    "IPP confirmed %d labels, the label counter rose by %d",
                    expected,
                    after - before,
                )
            counter_exact = before is not None and after is not None and after - before == expected
            await _finish(state, True, counter_exact)
            return
        raise_new_bits(status)
        if before is None or after is None:
            _logger.warning("No label counter before or after sending; counted as printed")
            await _finish(state, False, False)
            return
        printed = after - before
        if printed < 0 or printed > expected + COUNTER_JUMP_SLACK:
            _logger.warning(
                "Label counter moved by %d for %d labels sent; not interpretable, counted as "
                "printed",
                printed,
                expected,
            )
            await _finish(state, False, False)
            return
        if printed >= expected and status.hr_printer_status == "idle":
            await _finish(state, False, printed == expected)
            return
        if loop.time() >= deadline:
            if printed >= expected:
                # Counted, but the printer never reported idle: the labels are out.
                _logger.warning("Labels counted but the printer did not turn idle in time")
                await _finish(state, False, printed == expected)
                return
            await _finish(state, False, False)
            raise LabelsNotConfirmedError(printed, expected)
        await asyncio.sleep(poll)


async def _finish(state: TapeSendState | None, ipp_completed: bool, counter_exact: bool) -> None:
    """A test print stores what it found (#393); any other send stores nothing."""
    if state is None or not state.detecting:
        return
    state.detecting = False
    record = ConfirmationRecord(
        confirm_transport="ipp" if ipp_completed and not state.detect_ipp_failed else "raw",
        label_counter=counter_exact,
        confirmed_at=datetime.now(UTC),
    )
    await state.store(record)
