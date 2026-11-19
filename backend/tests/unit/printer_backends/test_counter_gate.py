# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Security audit run 26, R26-1: one forged "no such counter" answer must not switch off the
label-counter confirmation of a tape printer for good, and the printer view must say when the
counter is not read."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from app.printer_backends import tape_confirmation
from app.printer_backends.brother_ql_backend import BrotherQLBackend
from app.printer_backends.ptouch_backend import PTouchBackend
from app.printer_backends.snmp_helper import PreflightStatus
from app.printer_backends.tape_confirmation import COUNTER_REFUSALS_TO_STOP, ConfirmationRecord
from app.schemas.printer import PrintConfirmationRead

pytestmark = pytest.mark.anyio

_AT = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
_BACKENDS: list[tuple[str, Callable[[], Any]]] = [
    ("app.printer_backends.brother_ql_backend", lambda: BrotherQLBackend(host="192.0.2.31")),
    ("app.printer_backends.ptouch_backend", lambda: PTouchBackend(host="192.0.2.32")),
]


class _Agent:
    """A printer's SNMP agent: each read answers the next of ``answers`` (``True``: refuses the
    counter, ``False``: answers it); the last one sticks."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, module: str, answers: list[bool]) -> None:
        self.answers = answers
        self.asked: list[bool] = []

        async def preflight(host: str, **kw: Any) -> PreflightStatus:
            asked = kw.get("ask_counter", True)
            self.asked.append(asked)
            refuse = self.answers[min(len(self.asked) - 1, len(self.answers) - 1)]
            return PreflightStatus(
                hr_printer_status="idle",
                loaded_tape_mm=12,
                media_raw="12mm",
                marker_count=None if (refuse or not asked) else 100,
                counter_refused=asked and refuse,
            )

        monkeypatch.setattr(f"{module}.query_preflight", preflight)


class _Sink:
    def __init__(self) -> None:
        self.records: list[ConfirmationRecord] = []

    async def __call__(self, record: ConfirmationRecord) -> None:
        self.records.append(record)


@pytest.fixture(params=_BACKENDS, ids=["ql", "pt"])
def backend_kind(request: pytest.FixtureRequest) -> tuple[str, Callable[[], Any]]:
    return request.param  # type: ignore[no-any-return]


async def _reads(backend: Any, n: int) -> None:
    for _ in range(n):
        await backend.read_status()


async def test_one_refusal_does_not_switch_the_counter_off(
    monkeypatch: pytest.MonkeyPatch, backend_kind: tuple[str, Callable[[], Any]]
) -> None:
    module, make = backend_kind
    agent = _Agent(monkeypatch, module, [True, False])
    backend = make()
    await _reads(backend, 4)
    assert agent.asked == [True] * 4


async def test_consecutive_refusals_switch_it_off(
    monkeypatch: pytest.MonkeyPatch, backend_kind: tuple[str, Callable[[], Any]]
) -> None:
    module, make = backend_kind
    agent = _Agent(monkeypatch, module, [True])
    backend = make()
    await _reads(backend, COUNTER_REFUSALS_TO_STOP + 2)
    assert agent.asked == [True] * COUNTER_REFUSALS_TO_STOP + [False, False]


async def test_an_answer_between_refusals_starts_the_count_again(
    monkeypatch: pytest.MonkeyPatch, backend_kind: tuple[str, Callable[[], Any]]
) -> None:
    module, make = backend_kind
    pattern = [True] * (COUNTER_REFUSALS_TO_STOP - 1) + [False]
    agent = _Agent(monkeypatch, module, pattern * 3)
    backend = make()
    await _reads(backend, len(pattern) * 3)
    assert all(agent.asked)


async def test_a_test_print_asks_for_the_counter_again(
    monkeypatch: pytest.MonkeyPatch, backend_kind: tuple[str, Callable[[], Any]]
) -> None:
    module, make = backend_kind
    agent = _Agent(monkeypatch, module, [True])
    backend = make()
    await _reads(backend, COUNTER_REFUSALS_TO_STOP + 1)
    assert agent.asked[-1] is False
    backend.send_state.begin(detect=True)
    await backend.read_status()
    assert agent.asked[-1] is True


async def test_the_counter_is_asked_again_after_the_retry_window(
    monkeypatch: pytest.MonkeyPatch, backend_kind: tuple[str, Callable[[], Any]]
) -> None:
    module, make = backend_kind
    now = [1000.0]
    monkeypatch.setattr(tape_confirmation, "_monotonic", lambda: now[0])
    agent = _Agent(monkeypatch, module, [True] * COUNTER_REFUSALS_TO_STOP + [False])
    backend = make()
    await _reads(backend, COUNTER_REFUSALS_TO_STOP + 1)
    assert agent.asked[-1] is False
    now[0] += tape_confirmation.COUNTER_RETRY_S
    await backend.read_status()
    assert agent.asked[-1] is True


async def test_switching_the_counter_off_and_on_is_stored_and_shown(
    monkeypatch: pytest.MonkeyPatch, backend_kind: tuple[str, Callable[[], Any]]
) -> None:
    module, make = backend_kind
    agent = _Agent(monkeypatch, module, [True] * COUNTER_REFUSALS_TO_STOP + [False])
    backend = make()
    sink = _Sink()
    backend.send_state.record = ConfirmationRecord("raw", True, _AT)
    backend.send_state.sink = sink
    await _reads(backend, COUNTER_REFUSALS_TO_STOP)
    assert [r.counter_off for r in sink.records] == [True]
    shown = PrintConfirmationRead.from_stored(sink.records[-1].to_json())
    assert shown is not None
    assert (shown.channel, shown.counter_read, shown.label_counter) == ("none", False, True)

    backend.send_state.begin(detect=True)  # a test print asks again, the agent answers
    await backend.read_status()
    assert [r.counter_off for r in sink.records] == [True, False]
    shown = PrintConfirmationRead.from_stored(sink.records[-1].to_json())
    assert shown is not None and (shown.channel, shown.counter_read) == ("label_counter", True)
    assert agent.asked[-1] is True


def test_a_record_reads_back_with_its_counter_state() -> None:
    record = ConfirmationRecord("raw", True, _AT, counter_off=True)
    assert ConfirmationRecord.from_json(record.to_json()) == record
    assert record.channel == "none"
    legacy = {"confirm_transport": "raw", "label_counter": True, "confirmed_at": _AT.isoformat()}
    assert ConfirmationRecord.from_json(legacy) == ConfirmationRecord("raw", True, _AT)
    assert ConfirmationRecord.from_json({**legacy, "counter_off": 1}) is None


def test_the_printer_view_shows_why_ipp_is_not_tried() -> None:
    # Hardening note 3 of run 26: the sticky flag is visible, not hidden.
    shown = PrintConfirmationRead.from_stored(
        ConfirmationRecord("raw", True, _AT, ipp_incomplete=True).to_json()
    )
    assert shown is not None and shown.ipp_incomplete is True
