# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#393 review round 1: the confirmation after sending, edge cases.

- I1: an IPP job that did not complete stays "not printed" when the status cannot be read then.
- I4: a blocking bit with a known printed count carries the count; a counter that reached all
  labels with a bit set counts them as printed.
- M2: a printer that stops answering SNMP ends the wait after five polls, not at the timeout.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

import pytest
from app.printer_backends.exceptions import (
    LabelsNotConfirmedError,
    PrinterOfflineError,
    TapeEmptyError,
)
from app.printer_backends.post_send import check_after_send
from app.printer_backends.snmp_helper import PreflightStatus
from app.printer_backends.tape_confirmation import (
    IppOutcome,
    TapeIppTransport,
    TapeSendState,
)

pytestmark = pytest.mark.anyio


def _status(count: int | None, printer: str = "idle", flags: Iterable[str] = ()) -> PreflightStatus:
    return PreflightStatus(
        hr_printer_status=printer,  # type: ignore[arg-type]
        loaded_tape_mm=29,
        error_flags=list(flags),
        marker_count=count,
    )


class _Backend:
    """Counter *before* at the read before sending; each later read returns the next of *reads*."""

    def __init__(self, before: int | None, labels: int, reads: list[PreflightStatus | Exception]):
        self.last_send_status = _status(before)
        self.labels_sent = labels
        self.reads = reads
        self.count = 0

    @property
    def flags_before_send(self) -> frozenset[str]:
        return frozenset()

    async def read_status(self) -> PreflightStatus:
        item = self.reads[min(self.count, len(self.reads) - 1)]
        self.count += 1
        if isinstance(item, Exception):
            raise item
        return item


class _Ipp(TapeIppTransport):
    """An IPP side whose wait returns *outcome*."""

    def __init__(self, outcome: IppOutcome) -> None:
        super().__init__("192.0.2.40")
        self.outcome = outcome
        self.cancelled: list[int] = []

    async def wait(self, jobs, *, timeout_s, poll_s=1.0):  # type: ignore[no-untyped-def,override]
        return self.outcome

    async def cancel(self, job_id: int) -> bool:
        self.cancelled.append(job_id)
        return True


class _IppBackend(_Backend):
    def __init__(self, outcome: IppOutcome, labels: int, reads: list[PreflightStatus | Exception]):
        super().__init__(100, labels, reads)
        self.send_state = TapeSendState("192.0.2.40", _Ipp(outcome))
        self.send_state.labels_sent = labels
        self.send_state.ipp_jobs = [(7, labels)]


async def _check(backend: object, timeout_s: float = 0.2) -> None:
    await check_after_send(backend, settle_s=0, poll_s=0.001, timeout_s=timeout_s)


# ---------------------------------------------------------------------------- I1


async def test_an_aborted_ipp_job_with_an_unreadable_status_is_not_printed() -> None:
    backend = _IppBackend(IppOutcome(False, 2), 5, [PrinterOfflineError("timeout")])
    with pytest.raises(LabelsNotConfirmedError) as err:
        await _check(backend)
    assert (err.value.printed, err.value.expected) == (2, 5)


# ---------------------------------------------------------------------------- I4


async def test_a_bit_with_a_counted_shortfall_carries_the_printed_count() -> None:
    backend = _Backend(10, 5, [_status(13, "other", ["noPaper"])])
    with pytest.raises(TapeEmptyError) as err:
        await _check(backend)
    assert err.value.printed == 3


async def test_a_bit_after_all_labels_were_counted_carries_all_of_them() -> None:
    # The last label used up the roll: all five printed (round 2: the error says so, and the
    # queue keeps them done and pauses).
    backend = _Backend(10, 5, [_status(15, "other", ["noPaper"])])
    with pytest.raises(TapeEmptyError) as err:
        await _check(backend)
    assert err.value.printed == 5


async def test_a_bit_without_a_counter_has_no_printed_count() -> None:
    backend = _Backend(None, 5, [_status(None, "other", ["noPaper"])])
    with pytest.raises(TapeEmptyError) as err:
        await _check(backend)
    assert err.value.printed is None


async def test_a_bit_after_an_aborted_ipp_job_carries_its_impressions() -> None:
    backend = _IppBackend(IppOutcome(False, 3), 5, [_status(103, "other", ["noPaper"])])
    with pytest.raises(TapeEmptyError) as err:
        await _check(backend)
    assert err.value.printed == 3


# ---------------------------------------------------------------------------- M2


async def test_five_unanswered_polls_end_the_wait_early(caplog: pytest.LogCaptureFixture) -> None:
    backend = _Backend(10, 5, [PrinterOfflineError("timeout")])
    with caplog.at_level(logging.WARNING, logger="app.printer_backends.post_send"):
        async with asyncio.timeout(5):
            with pytest.raises(PrinterOfflineError):
                await _check(backend, timeout_s=600)
    assert backend.count == 5
