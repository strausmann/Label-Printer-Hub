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
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Final, Literal

from app.printer_backends.exceptions import (
    ConfirmationUnknownError,
    LabelsNotConfirmedError,
    PrinterCoverOpenError,
    PrinterError,
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
    IppOutcome,
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


def _now() -> float:
    """The clock of the confirmation deadline (a test replaces it)."""
    return time.monotonic()


UNANSWERED_POLLS_LIMIT: Final = 5
"""Consecutive status reads without an SNMP answer after which the wait ends early (#393): the
labels are then counted as printed with a warning (``PrinterOfflineError``, as before #393),
instead of holding the worker for the whole timeout of an unreachable printer."""


STEADY_READS: Final = 3
"""Reads in a row with every label counted, the same count and a printer that does not report
``printing`` after which the counter wait ends without ``idle`` (final review M6): some printers
report ``other`` (a QL while it prints, too) or ``warmup`` and never ``idle``. The count has to
hold still, so a QL still printing is not cut short."""


def _raise_new_bits(
    status: PreflightStatus, before_flags: frozenset[str], printed: int | None
) -> None:
    """``raise_for_error_flags`` for the bits that are new, carrying *printed* (#393)."""
    try:
        raise_for_error_flags(f for f in status.error_flags if f not in before_flags)
    except PrinterError as exc:
        exc.printed = printed
        raise


def _has_new_bits(status: PreflightStatus, before_flags: frozenset[str]) -> bool:
    return any(f in HARD_ERROR_FLAGS and f not in before_flags for f in status.error_flags)


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
      is only logged (IPP wins). ``aborted``/``canceled``/no final state in time: a job still
      open is cancelled (best effort), a blocking bit raises its error, else
      ``LabelsNotConfirmedError(impressions completed, sent)``; a cancel that failed raises
      ``ConfirmationUnknownError`` (the labels may still print), unless the label counter rose
      by exactly the labels sent. A status that cannot be read
      then changes nothing: IPP said "not printed". An accepted job is never sent again over
      TCP 9100. A job the printer forgot after it answered for it is left to the counter.
    - **Label counter:** polled every ``poll_s`` until it rose by the labels sent and the
      printer is idle (``hrPrinterStatus`` 3; a QL reports 1 while printing), or the count held
      still for ``STEADY_READS`` reads while the printer did not report ``printing``. A shortfall at
      the timeout raises ``LabelsNotConfirmedError(printed, sent)``. A counter that is missing
      before or after, went down, or jumped by more than the labels plus ``COUNTER_JUMP_SLACK``
      is logged and accepted: a job never fails on a counter that cannot be interpreted.
      ``UNANSWERED_POLLS_LIMIT`` reads in a row without an answer end the wait early.
    - **Blocking bits** carry the printed count when it is known (``PrinterError.printed``);
      with every label counted (the last label used up the roll) it is the labels sent, and the
      queue keeps all of them done and pauses.
    - No label count (a backend that does not report one): one read, as before #393.

    A test print (``send_state.detecting``) also decides and stores the ``ConfirmationRecord``.

    The status is read with the backend's ``read_status`` (no refusal on bits), else its
    ``preflight_check``. A read that fails raises ``PrinterOfflineError`` when nothing could be
    read at all.
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

    # One budget for the whole confirmation (#393 F3): a counter wait after an IPP job that
    # vanished gets what is left of it, not a fresh timeout (plus the cancel's stop poll).
    deadline = _now() + limit
    ipp_completed = False
    if state is not None and state.ipp_jobs:
        outcome = await state.ipp.wait(state.ipp_jobs, timeout_s=limit, poll_s=poll)
        if outcome.completed:
            ipp_completed = True
        elif outcome.vanished:
            _logger.warning("The printer forgot the IPP job; the label counter decides")
            state.ipp_jobs = []
        else:
            decided = await _ipp_not_completed(
                backend, state, outcome, expected, before, before_flags, poll
            )
            if decided == "printed":
                return
            state.ipp_jobs = []  # "counter": the label counter decides

    if expected <= 0:
        _raise_new_bits(await _read(backend), before_flags, None)
        return

    unanswered = 0
    steady = 0  # reads in a row: every label counted, same count, not "printing"
    last_after: int | None = None
    while True:
        try:
            status = await _read(backend)
        except (PrinterOfflineError, SnmpQueryError):
            unanswered += 1
            if ipp_completed:
                _logger.warning("Status after a confirmed IPP job not readable")
                await _finish(state, True, False)
                return
            if _now() >= deadline or unanswered >= UNANSWERED_POLLS_LIMIT:
                await _finish(state, False, False)
                raise
            await asyncio.sleep(poll)
            continue
        unanswered = 0
        after = _count_of(status)
        if ipp_completed:
            if _has_new_bits(status, before_flags):
                _logger.warning("Error bits after a completed IPP job (printed)")
            if before is not None and after is not None and after - before != expected:
                _logger.warning(
                    "IPP confirmed %d labels, the label counter rose by %d",
                    expected,
                    after - before,
                )
            counter_exact = before is not None and after is not None and after - before == expected
            await _finish(state, True, counter_exact)
            return
        printed = after - before if before is not None and after is not None else None
        interpretable = printed is not None and 0 <= printed <= expected + COUNTER_JUMP_SLACK
        if _has_new_bits(status, before_flags):
            if interpretable and printed is not None and printed >= expected:
                # Every label came out (the last one used up the roll): all are printed, and
                # the bit pauses the printer.
                await _finish(state, False, printed == expected, fault=True)
                _raise_new_bits(status, before_flags, expected)
            _raise_new_bits(status, before_flags, printed if interpretable else None)
        if printed is None:
            _logger.warning("No label counter before or after sending; counted as printed")
            await _finish(state, False, False)
            return
        if not interpretable:
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
        if printed >= expected and status.hr_printer_status != "printing" and after == last_after:
            steady += 1
        else:
            steady = 1 if printed >= expected and status.hr_printer_status != "printing" else 0
        last_after = after
        if steady >= STEADY_READS:
            await _finish(state, False, printed == expected)
            return
        if _now() >= deadline:
            if printed >= expected:
                # Counted, but the printer never reported idle: the labels are out.
                _logger.warning("Labels counted but the printer did not turn idle in time")
                await _finish(state, False, printed == expected)
                return
            await _finish(state, False, False)
            raise LabelsNotConfirmedError(printed, expected)
        await asyncio.sleep(poll)


async def _ipp_not_completed(
    backend: Any,
    state: TapeSendState,
    outcome: IppOutcome,
    expected: int,
    before: int | None,
    before_flags: frozenset[str],
    poll: float,
) -> Literal["printed", "counter"]:
    """An IPP job of the send did not complete (#393).

    A job still open is cancelled and polled until it stopped (``TapeIppTransport.cancel``):

    - the cancel failed or the job did not stop: the labels may still print, so
      ``ConfirmationUnknownError``, whatever bits the printer reports; unless the label counter
      rose by exactly the labels sent: then they are printed (a new bit raises with
      ``printed = expected``);
    - the job is gone: ``"counter"``, the label counter decides;
    - it stopped: its last impressions count.

    Then the status is read once (a failed read changes nothing). Every label printed:
    ``"printed"``, or the blocking bit's error carrying ``printed = expected``. Otherwise the
    bit's error carrying the printed count, else ``LabelsNotConfirmedError``.
    """
    printed = outcome.printed
    if outcome.pending is not None:
        cancel = await state.ipp.cancel(outcome.pending, poll_s=poll)
        if cancel.result == "vanished":
            return "counter"
        if cancel.result == "failed":
            status = await _read_or_none(backend)
            exact = _exact(before, status, expected)
            await _finish(state, False, exact, fault=_fault(status, before_flags))
            if not exact or status is None:
                raise ConfirmationUnknownError()
            # The counter rose by exactly the labels sent: every label is out, nothing is left
            # that may still print.
            _logger.warning("IPP job could not be cancelled, but the counter shows every label")
            if _has_new_bits(status, before_flags):
                _raise_new_bits(status, before_flags, expected)
            return "printed"
        if cancel.impressions is not None:
            printed = outcome.printed_before + min(cancel.impressions, outcome.pending_labels)
    status = await _read_or_none(backend)
    await _finish(
        state, False, _exact(before, status, expected), fault=_fault(status, before_flags)
    )
    if printed >= expected:
        if status is not None and _has_new_bits(status, before_flags):
            _raise_new_bits(status, before_flags, expected)
        _logger.warning("IPP job did not complete but reports every label printed")
        return "printed"
    if status is not None:
        _raise_new_bits(status, before_flags, printed)
    raise LabelsNotConfirmedError(printed, expected)


async def _read_or_none(backend: Any) -> PreflightStatus | None:
    try:
        return await _read(backend)
    except (PrinterOfflineError, SnmpQueryError):
        _logger.warning("Status after an IPP job that did not complete not readable")
        return None


def _fault(status: PreflightStatus | None, before_flags: frozenset[str]) -> bool:
    """A new blocking bit (jam, open cover, tape end) explains why an IPP job did not complete."""
    return status is not None and _has_new_bits(status, before_flags)


def _exact(before: int | None, status: PreflightStatus | None, expected: int) -> bool:
    after = _count_of(status) if status is not None else None
    return before is not None and after is not None and after - before == expected


async def _finish(
    state: TapeSendState | None, ipp_completed: bool, counter_exact: bool, *, fault: bool = False
) -> None:
    """A test print stores what it found (#393); any other send stores nothing.

    *fault*: the printer reported a new blocking bit with the send. An IPP job it took and did
    not complete is then the printer's fault (a jam, an open cover, the tape end), not a broken
    IPP channel, so ``ipp_incomplete`` is not set and the next test print tries IPP again.
    """
    if state is None or not state.detecting:
        return
    state.detecting = False
    ipp = ipp_completed and not state.detect_ipp_failed
    # The printer took the IPP job but did not complete it without a fault to explain it (or an
    # earlier test print found that): later test prints stay on TCP 9100. A Print-Job that was
    # not taken, or one a jam or the tape end aborted, is not this.
    record = ConfirmationRecord(
        confirm_transport="ipp" if ipp else "raw",
        label_counter=counter_exact,
        confirmed_at=datetime.now(UTC),
        ipp_incomplete=not ipp
        and (state.detect_ipp_skipped or (state.detect_ipp_taken and not fault)),
    )
    await state.store(record)
