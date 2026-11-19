# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#393 re-review round 2, F3: after an IPP job vanished on its cancel, the label counter only
gets what is left of the confirmation timeout."""

from __future__ import annotations

import asyncio

import pytest
from app.printer_backends import post_send
from app.printer_backends.exceptions import LabelsNotConfirmedError
from app.printer_backends.snmp_helper import PreflightStatus
from app.printer_backends.tape_confirmation import (
    CancelOutcome,
    IppOutcome,
    TapeIppTransport,
    TapeSendState,
)

pytestmark = pytest.mark.anyio

TIMEOUT_S = 100.0
LEFT_S = 5.0


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Ipp(TapeIppTransport):
    """The wait times out at ``timeout - LEFT_S``; the cancel finds the job gone."""

    def __init__(self, clock: _Clock) -> None:
        super().__init__("192.0.2.70")
        self.clock = clock

    async def wait(self, jobs, *, timeout_s, poll_s=1.0, **_):  # type: ignore[no-untyped-def,override]
        self.clock.now += timeout_s - LEFT_S
        return IppOutcome(False, 0, pending=7, pending_labels=2)

    async def cancel(self, job_id, *, poll_s=None):  # type: ignore[no-untyped-def,override]
        return CancelOutcome("vanished")


class _Backend:
    def __init__(self, clock: _Clock) -> None:
        self.clock = clock
        self.last_send_status = PreflightStatus(
            hr_printer_status="idle", loaded_tape_mm=29, marker_count=10
        )
        self.send_state = TapeSendState("192.0.2.70", _Ipp(clock))
        self.send_state.labels_sent = 2
        self.send_state.ipp_jobs = [(7, 2)]
        self.reads = 0

    @property
    def flags_before_send(self) -> frozenset[str]:
        return frozenset()

    async def read_status(self) -> PreflightStatus:
        self.reads += 1
        self.clock.now += 1.0  # each read takes a second
        return PreflightStatus(hr_printer_status="other", loaded_tape_mm=29, marker_count=10)


async def test_the_counter_after_a_vanished_cancel_gets_only_the_rest_of_the_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    monkeypatch.setattr(post_send, "_now", clock, raising=False)
    backend = _Backend(clock)
    start = clock.now

    async with asyncio.timeout(3):  # a fresh full timeout would run far past this
        with pytest.raises(LabelsNotConfirmedError):
            await post_send.check_after_send(backend, settle_s=0, poll_s=0.0, timeout_s=TIMEOUT_S)

    assert backend.reads <= LEFT_S + 1
    assert clock.now - start <= TIMEOUT_S + 1
