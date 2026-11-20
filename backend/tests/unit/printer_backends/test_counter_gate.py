# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Security audit run 26, R26-1: one forged "no such counter" answer must not switch off the
label-counter confirmation of a tape printer for good, and the printer view must say when the
counter is not read."""

from __future__ import annotations

import dataclasses
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
    counter, ``False``: answers it, ``None``: neither, e.g. a garbled value); the last one
    sticks."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, module: str, answers: list[bool | None]
    ) -> None:
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
                marker_count=None if (refuse is not False or not asked) else 100,
                counter_refused=asked and refuse is True,
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
    await backend.send_state.flushed()  # #398: the read stores the cleared flag beside itself
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


def _refusing_ipp() -> Any:
    import httpx

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    return httpx.MockTransport(refuse)


@pytest.mark.usefixtures("real_ql_media_check")
async def test_a_test_print_asks_for_the_counter_in_its_own_read_before_sending(
    monkeypatch: pytest.MonkeyPatch, backend_kind: tuple[str, Callable[[], Any]]
) -> None:
    """Review round 3, R3-2: through the real call order (read before sending, then the send),
    not by calling ``begin`` first."""
    from app.services.status_block import MediaType
    from app.services.tape_registry import TapeRegistry
    from PIL import Image

    module, _make = backend_kind
    agent = _Agent(monkeypatch, module, [True] * COUNTER_REFUSALS_TO_STOP + [False])
    monkeypatch.setattr(f"{module}.query_preflight", _with_media(agent, module))
    if module.endswith("ptouch_backend"):
        monkeypatch.setattr(f"{module}._ptouch_print", lambda *a, **k: None)
        backend = PTouchBackend(host="192.0.2.33", ipp_transport=_refusing_ipp())
        spec = TapeRegistry.lookup_pt(12, MediaType.LAMINATED)
        image = Image.new("1", (300, 76), 1)
    else:
        monkeypatch.setattr(f"{module}._helpers_send", lambda *a, **k: {"outcome": "sent"})
        backend = BrotherQLBackend(host="192.0.2.34", ipp_transport=_refusing_ipp())
        spec = TapeRegistry.lookup_ql(12, MediaType.CONTINUOUS_LENGTH_TAPE)
        image = Image.new("1", (300, 106), 1)
    await _reads(backend, COUNTER_REFUSALS_TO_STOP)
    assert agent.asked[-1] is True and not backend.send_state.ask_counter()
    before = len(agent.asked)
    await backend.print_image(image, spec, detect_confirmation=True)
    assert agent.asked[before] is True  # the test print's own read before sending
    assert backend.last_send_status is not None
    assert backend.last_send_status.marker_count == 100


def _with_media(agent: _Agent, module: str) -> Callable[..., Any]:
    """The agent's answers with a 12 mm roll that both backends accept."""
    import importlib

    inner = importlib.import_module(module).query_preflight

    async def preflight(host: str, **kw: Any) -> PreflightStatus:
        status = await inner(host, **kw)
        return dataclasses.replace(status, media_raw="12mm", loaded_tape_mm=12)

    return preflight


# ---------------------------------------------------------------------------- R27-1


async def test_a_test_print_stores_the_counter_state_it_ends_with(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit run 27, R27-1: a test print whose counter is switched off while it runs stores
    ``counter_off`` true, not the default."""
    from app.printer_backends import post_send

    state = tape_confirmation.TapeSendState("192.0.2.35", tape_confirmation.TapeIppTransport("x"))
    sink = _Sink()
    state.sink = sink
    state.begin(detect=True)
    state.counter_off_at = 1.0  # switched off by reads that ran meanwhile
    await post_send._finish(state, False, True)
    assert [(r.label_counter, r.counter_off) for r in sink.records] == [(True, True)]
    assert PrintConfirmationRead.from_stored(sink.records[-1].to_json()).channel == "none"  # type: ignore[union-attr]


class _SlowFirstWrite:
    """A sink whose first write takes longer than the next: what a database commits last wins."""

    def __init__(self) -> None:
        self.committed: list[ConfirmationRecord] = []
        self.calls = 0

    async def __call__(self, record: ConfirmationRecord) -> None:
        import asyncio

        self.calls += 1
        if self.calls == 1:
            await asyncio.sleep(0.05)
        self.committed.append(record)


async def test_record_writes_commit_in_the_order_they_were_made() -> None:
    """Audit run 27, R27-1: the flip back on and a switch-off right after it must not commit in
    the opposite order, or the stored record says the counter is read while it is not."""
    import asyncio

    state = tape_confirmation.TapeSendState("192.0.2.36", tape_confirmation.TapeIppTransport("x"))
    state.record = ConfirmationRecord("raw", True, _AT, counter_off=True)
    sink = _SlowFirstWrite()
    state.sink = sink
    on = asyncio.create_task(state.note_counter(refused=False, answered=True))
    await asyncio.sleep(0)  # the flip back on has started its write
    for _ in range(COUNTER_REFUSALS_TO_STOP):
        await state.note_counter(refused=True, answered=False)
    await on
    assert [r.counter_off for r in sink.committed] == [False, True]


# ---------------------------------------------------------------------------- streak rules


async def test_any_other_answer_of_the_counter_breaks_the_streak(
    monkeypatch: pytest.MonkeyPatch, backend_kind: tuple[str, Callable[[], Any]]
) -> None:
    """Review round 3, R3-6: a read that asked and was not refused (here a garbled value) starts
    the count again, so "in a row" is exact."""
    module, make = backend_kind
    pattern: list[bool | None] = [True] * (COUNTER_REFUSALS_TO_STOP - 1) + [None]
    agent = _Agent(monkeypatch, module, pattern * 3)
    backend = make()
    await _reads(backend, len(pattern) * 3)
    assert all(agent.asked)


async def test_a_streak_older_than_the_retry_window_starts_again(
    monkeypatch: pytest.MonkeyPatch, backend_kind: tuple[str, Callable[[], Any]]
) -> None:
    """Audit run 27, note 1: two refusals and a third one hours later are not "in a row"."""
    module, make = backend_kind
    now = [1000.0]
    monkeypatch.setattr(tape_confirmation, "_monotonic", lambda: now[0])
    agent = _Agent(monkeypatch, module, [True])
    backend = make()
    await _reads(backend, COUNTER_REFUSALS_TO_STOP - 1)
    now[0] += tape_confirmation.COUNTER_RETRY_S
    await _reads(backend, 2)
    assert all(agent.asked)


async def test_after_the_retry_window_one_refusal_does_not_switch_it_off_again(
    monkeypatch: pytest.MonkeyPatch, backend_kind: tuple[str, Callable[[], Any]]
) -> None:
    """Audit run 27, note 1: the window opens a fresh streak, not the old one plus one."""
    module, make = backend_kind
    now = [1000.0]
    monkeypatch.setattr(tape_confirmation, "_monotonic", lambda: now[0])
    agent = _Agent(monkeypatch, module, [True])
    backend = make()
    await _reads(backend, COUNTER_REFUSALS_TO_STOP)
    now[0] += tape_confirmation.COUNTER_RETRY_S
    await _reads(backend, COUNTER_REFUSALS_TO_STOP)
    assert agent.asked[-COUNTER_REFUSALS_TO_STOP:] == [True] * COUNTER_REFUSALS_TO_STOP
    await backend.read_status()
    assert agent.asked[-1] is False  # three fresh refusals switched it off again


async def test_a_read_that_did_not_ask_for_the_counter_does_not_break_the_streak() -> None:
    """Review round 4, L1: a read that left the counter out has no answer about it. One that was
    started while the counter was off and ends after it is asked again must not count as
    "another answer" and break the fresh streak."""
    state = tape_confirmation.TapeSendState("192.0.2.37", tape_confirmation.TapeIppTransport("x"))
    for _ in range(COUNTER_REFUSALS_TO_STOP - 1):
        await state.note_counter(refused=True, answered=False)
    await state.note_counter(refused=False, answered=False, asked=False)
    await state.note_counter(refused=True, answered=False)
    assert state.counter_off_at is not None


async def test_a_stuck_record_write_does_not_hold_the_next_one(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Review round 4, L3: writes are serialised, so a write that never ends would hold every
    later writer of the printer. It is given up after ``STORE_TIMEOUT_S`` and logged."""
    import asyncio

    monkeypatch.setattr(tape_confirmation, "STORE_TIMEOUT_S", 0.05)
    written: list[bool] = []
    hang = asyncio.Event()

    async def sink(record: ConfirmationRecord) -> None:
        if not written and not hang.is_set():
            hang.set()
            await asyncio.Event().wait()  # never ends
        written.append(record.counter_off)

    state = tape_confirmation.TapeSendState("192.0.2.38", tape_confirmation.TapeIppTransport("x"))
    state.sink = sink
    async with asyncio.timeout(2):
        with caplog.at_level("WARNING", logger="app.printer_backends.tape_confirmation"):
            await state.store(ConfirmationRecord("raw", True, _AT))
            await state.store(ConfirmationRecord("raw", True, _AT, counter_off=True))
    assert written == [True]
    assert any("not stored in time" in r.message for r in caplog.records)
    assert not any("192.0.2" in r.getMessage() for r in caplog.records)
