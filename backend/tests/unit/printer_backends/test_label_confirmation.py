# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#393: after sending, the label counter has to rise by the labels sent before a job is done."""

from __future__ import annotations

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
    CONFIRM_BASE_S,
    CONFIRM_PER_LABEL_S,
    confirm_timeout_s,
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
    """A backend that sent *labels* labels after a read with counter *before*; each status read
    returns the next of *reads* (the last one sticks)."""

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


async def _check(backend: _Backend, timeout_s: float = 0.2) -> None:
    await check_after_send(backend, settle_s=0, poll_s=0.001, timeout_s=timeout_s)


def test_the_timeout_grows_with_the_labels() -> None:
    assert CONFIRM_BASE_S == 15.0
    assert CONFIRM_PER_LABEL_S == 8.0
    assert confirm_timeout_s(10) == 95.0


async def test_the_counter_reaching_before_plus_the_labels_with_idle_confirms() -> None:
    backend = _Backend(256, 3, [_status(257, "other"), _status(259, "idle")])
    await _check(backend)
    assert backend.count == 2


async def test_a_counter_that_never_gets_there_fails_with_printed_and_expected() -> None:
    backend = _Backend(256, 5, [_status(259, "idle")])
    with pytest.raises(LabelsNotConfirmedError) as err:
        await _check(backend, timeout_s=0.02)
    assert (err.value.printed, err.value.expected) == (3, 5)
    assert str(err.value) == "3 of 5 labels printed"


async def test_a_printer_still_printing_is_waited_for_although_the_count_is_there() -> None:
    # The QL reports ``other`` (1) while it prints, not ``printing`` (4): only ``idle`` ends it.
    backend = _Backend(10, 2, [_status(12, "other"), _status(12, "other"), _status(12, "idle")])
    await _check(backend)
    assert backend.count == 3


async def test_a_missing_counter_counts_as_printed_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    backend = _Backend(None, 2, [_status(None, "other")])
    with caplog.at_level(logging.WARNING, logger="app.printer_backends.post_send"):
        await _check(backend)
    assert backend.count == 1
    assert any("No label counter" in r.message for r in caplog.records)


async def test_a_counter_that_went_down_counts_as_printed_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    backend = _Backend(500, 2, [_status(3, "idle")])
    with caplog.at_level(logging.WARNING, logger="app.printer_backends.post_send"):
        await _check(backend)
    assert any("not interpretable" in r.message for r in caplog.records)


async def test_a_counter_that_jumped_far_counts_as_printed_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    backend = _Backend(100, 2, [_status(100 + 2 + 51, "idle")])
    with caplog.at_level(logging.WARNING, logger="app.printer_backends.post_send"):
        await _check(backend)
    assert any("not interpretable" in r.message for r in caplog.records)


async def test_a_new_error_bit_while_waiting_raises_that_error() -> None:
    backend = _Backend(10, 3, [_status(11, "other"), _status(11, "other", ["noPaper"])])
    with pytest.raises(TapeEmptyError):
        await _check(backend)


async def test_a_read_that_fails_once_while_polling_is_retried() -> None:
    backend = _Backend(10, 1, [PrinterOfflineError("timeout"), _status(11, "idle")])
    await _check(backend)
    assert backend.count == 2


async def test_no_answer_at_all_until_the_timeout_raises_offline() -> None:
    # The queue counts that as printed (status unreadable), as before #393.
    backend = _Backend(10, 1, [PrinterOfflineError("timeout")])
    with pytest.raises(PrinterOfflineError):
        await _check(backend, timeout_s=0.01)


async def test_a_backend_that_reports_no_label_count_is_read_once() -> None:
    backend = _Backend(10, 0, [_status(10, "other")])
    await _check(backend)
    assert backend.count == 1


async def test_labels_counted_without_idle_until_the_timeout_count_as_printed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    backend = _Backend(10, 2, [_status(12, "other")])
    with caplog.at_level(logging.WARNING, logger="app.printer_backends.post_send"):
        await _check(backend, timeout_s=0.02)
    assert any("did not turn idle" in r.message for r in caplog.records)
