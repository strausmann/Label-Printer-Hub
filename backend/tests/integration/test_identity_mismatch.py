"""A different device behind a printer's address is flagged, never stored over (#231).

Two layers, both on a real temp database:

- ``record_identity`` alone (the columns, the transitions, the lost-race fallback);
- the full app (status flag for every scope, the event on ``printer:{id}:state``, the queue's
  hold, and the hold surviving a restart).

Identity values never appear in an event; the stored identity is never overwritten by a
``different`` reading.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import app.db.engine as _eng
import app.models  # noqa: F401
import pytest
import pytest_asyncio
from app.models.printer import Printer
from app.models.printer_identity import PrinterIdentity
from app.printer_backends.snmp_helper import ObservedIdentity
from app.repositories import printer_identity as identity_repo
from app.services.hardware_identity import record_identity
from app.services.job_lifecycle import JobState
from app.services.print_queue import PrintQueue
from sqlalchemy import select

from tests.integration.api.test_sheet_print_api import (
    TIMEOUT_S,
    Rig,
    _body,
    _cells,
    _printer,
    _sheet,
    running,
)

pytestmark = pytest.mark.asyncio

SERIAL_A = "E1234567ABC"
SERIAL_B = "E7654321XYZ"
SERIAL_C = "E1111111CCC"
T0 = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def _serial(value: str | None) -> ObservedIdentity:
    return ObservedIdentity(serial=value, ipp_uuid=None, mac=None)


@pytest_asyncio.fixture
async def printer_id() -> UUID:
    async with _eng.async_session() as s:
        p = Printer(
            name="mismatch-test",
            model="PT-P750W",
            backend="ptouch",
            connection={"host": "192.0.2.10", "port": 9100},
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)
        return p.id


async def _row(pid: UUID) -> PrinterIdentity:
    async with _eng.async_session() as s:
        row = await s.get(PrinterIdentity, pid)
    assert row is not None
    return row


class Transitions:
    """The ``on_mismatch`` callback of ``record_identity``: remembers every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[UUID, datetime | None]] = []

    async def __call__(self, printer_id: UUID, since: datetime | None) -> None:
        self.calls.append((printer_id, since))


async def _record(
    pid: UUID, observed: ObservedIdentity, now: datetime, hook: Transitions | None = None
) -> str:
    return await record_identity(
        pid, observed, now, session_factory=_eng.async_session, on_mismatch=hook
    )


# ---------------------------------------------------------------------------- the columns


async def test_different_identity_sets_mismatch_columns(printer_id: UUID) -> None:
    hook = Transitions()
    await _record(printer_id, _serial(SERIAL_A), T0, hook)

    outcome = await _record(printer_id, _serial(SERIAL_B), T0 + timedelta(seconds=30), hook)

    assert outcome == "different"
    row = await _row(printer_id)
    assert (row.hardware_id, row.hardware_id_kind) == (SERIAL_A, "serial")  # untouched
    assert (row.observed_id, row.observed_kind) == (SERIAL_B, "serial")
    assert row.mismatch_since is not None
    assert hook.calls == [(printer_id, T0 + timedelta(seconds=30))]
    assert row.mismatch_since.replace(tzinfo=UTC) == T0 + timedelta(seconds=30)


async def test_a_second_different_reading_keeps_the_start_and_calls_back_once(
    printer_id: UUID,
) -> None:
    hook = Transitions()
    await _record(printer_id, _serial(SERIAL_A), T0, hook)
    await _record(printer_id, _serial(SERIAL_B), T0 + timedelta(seconds=30), hook)
    first = (await _row(printer_id)).mismatch_since

    await _record(printer_id, _serial(SERIAL_C), T0 + timedelta(seconds=90), hook)

    row = await _row(printer_id)
    assert row.mismatch_since == first  # kept while the mismatch lasts
    assert row.observed_id == SERIAL_C  # the latest device that answered
    assert row.hardware_id == SERIAL_A
    assert len(hook.calls) == 1  # the transition, not every probe


async def test_an_unchanged_different_reading_writes_nothing(
    printer_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _record(printer_id, _serial(SERIAL_A), T0)
    await _record(printer_id, _serial(SERIAL_B), T0 + timedelta(seconds=30))
    real = identity_repo.mark_mismatch
    writes = {"n": 0}

    async def counting(*args: Any, **kwargs: Any) -> Any:
        writes["n"] += 1
        return await real(*args, **kwargs)

    monkeypatch.setattr(identity_repo, "mark_mismatch", counting)

    for i in range(1, 4):  # the same other device, probe after probe
        outcome = await _record(printer_id, _serial(SERIAL_B), T0 + timedelta(seconds=30 + 30 * i))
        assert outcome == "different"
    assert writes["n"] == 0

    await _record(printer_id, _serial(SERIAL_C), T0 + timedelta(seconds=300))  # a third device
    assert writes["n"] == 1
    assert (await _row(printer_id)).observed_id == SERIAL_C


async def test_missing_identity_never_mismatches(printer_id: UUID) -> None:
    hook = Transitions()
    await _record(printer_id, _serial(SERIAL_A), T0, hook)

    nothing = await _record(printer_id, _serial(None), T0 + timedelta(seconds=30), hook)
    other_kind = await _record(
        printer_id,
        ObservedIdentity(serial=None, ipp_uuid=None, mac="00:80:77:12:34:56"),
        T0 + timedelta(seconds=60),
        hook,
    )

    assert (nothing, other_kind) == ("none", "kept")
    row = await _row(printer_id)
    assert (row.hardware_id, row.observed_id, row.mismatch_since) == (SERIAL_A, None, None)
    assert hook.calls == []


async def test_a_probe_without_identity_does_not_clear_a_mismatch(printer_id: UUID) -> None:
    hook = Transitions()
    await _record(printer_id, _serial(SERIAL_A), T0, hook)
    await _record(printer_id, _serial(SERIAL_B), T0 + timedelta(seconds=30), hook)

    await _record(printer_id, _serial(None), T0 + timedelta(seconds=60), hook)

    assert (await _row(printer_id)).mismatch_since is not None
    assert len(hook.calls) == 1


async def test_stored_identity_back_clears_mismatch(printer_id: UUID) -> None:
    hook = Transitions()
    await _record(printer_id, _serial(SERIAL_A), T0, hook)
    await _record(printer_id, _serial(SERIAL_B), T0 + timedelta(seconds=30), hook)

    outcome = await _record(printer_id, _serial(SERIAL_A), T0 + timedelta(seconds=60), hook)

    assert outcome == "seen"
    row = await _row(printer_id)
    assert (row.observed_id, row.observed_kind, row.mismatch_since) == (None, None, None)
    assert row.hardware_id == SERIAL_A
    assert [since is None for _pid, since in hook.calls] == [False, True]  # set, then cleared


async def test_a_higher_kind_upgrade_also_clears_a_mismatch(printer_id: UUID) -> None:
    hook = Transitions()
    mac = "00:80:77:12:34:56"
    await _record(printer_id, ObservedIdentity(None, None, mac), T0, hook)
    await _record(
        printer_id,
        ObservedIdentity(None, None, "00:80:77:aa:bb:cc"),
        T0 + timedelta(seconds=30),
        hook,
    )
    assert (await _row(printer_id)).mismatch_since is not None

    outcome = await _record(
        printer_id, ObservedIdentity(SERIAL_A, None, mac), T0 + timedelta(seconds=60), hook
    )

    assert outcome == "kind_upgraded"
    row = await _row(printer_id)
    assert (row.hardware_id, row.hardware_id_kind) == (SERIAL_A, "serial")
    assert (row.observed_id, row.mismatch_since) == (None, None)
    assert hook.calls[-1][1] is None


# ---------------------------------------------------------------------------- the fallback (M7)


async def test_a_different_reading_is_not_reported_as_kept_when_the_write_loses(
    printer_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lost-race fallback answers ``kept``; it must not swallow a ``different`` reading."""
    await _record(printer_id, _serial(SERIAL_A), T0)

    async def lose(*_a: Any, **_k: Any) -> bool:
        return False

    monkeypatch.setattr(identity_repo, "mark_mismatch", lose)
    hook = Transitions()

    outcome = await _record(printer_id, _serial(SERIAL_B), T0 + timedelta(seconds=30), hook)

    assert outcome == "different"
    assert hook.calls == []  # nothing was written, so nothing is announced
    assert (await _row(printer_id)).mismatch_since is None  # the next probe tries again


async def test_a_write_that_loses_once_is_retried(
    printer_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _record(printer_id, _serial(SERIAL_A), T0)
    real = identity_repo.mark_mismatch
    attempts = {"n": 0}

    async def lose_once(*args: Any, **kwargs: Any) -> Any:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return False
        return await real(*args, **kwargs)

    monkeypatch.setattr(identity_repo, "mark_mismatch", lose_once)
    hook = Transitions()

    outcome = await _record(printer_id, _serial(SERIAL_B), T0 + timedelta(seconds=30), hook)

    assert outcome == "different"
    assert attempts["n"] == 2
    assert (await _row(printer_id)).mismatch_since is not None
    assert len(hook.calls) == 1


# ---------------------------------------------------------------------------- the full app


def _sink(rig: Rig) -> Any:
    return rig.app.state.printer_runtime._identity_sink


async def _status(rig: Rig, pid: UUID | None = None, headers: dict[str, str] | None = None) -> Any:
    resp = await rig.client.get(
        f"/api/v1/printers/{pid or rig.printer_id}/status", headers=headers or rig.reader
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _drain(queue: Any, event_type: str) -> list[Any]:
    out = []
    while not queue.empty():
        event = queue.get_nowait()
        if event is not None and event.event_type == event_type:
            out.append(event)
    return out


async def test_different_identity_sets_mismatch() -> None:
    async with running() as rig:
        bus = rig.app.state.event_bus
        events = bus.subscribe(f"printer:{rig.printer_id}:state", "t-mismatch")
        sink = _sink(rig)
        assert await sink(rig.printer_id, _serial(SERIAL_A)) == "stored"
        assert (await _status(rig))["identity_mismatch"] is False
        assert not rig.app.state.print_queue.is_identity_held(rig.printer_id)

        assert await sink(rig.printer_id, _serial(SERIAL_B)) == "different"

        status = await _status(rig)  # the read key: every scope sees the flag
        assert status["identity_mismatch"] is True
        row = await _row(rig.printer_id)
        assert row.hardware_id == SERIAL_A  # the stored identity stays
        assert row.observed_id == SERIAL_B
        assert rig.app.state.print_queue.is_identity_held(rig.printer_id)
        [event] = _drain(events, "printer.identity_mismatch")
        assert set(event.data) == {"mismatch", "since"}
        assert event.data["mismatch"] is True
        assert event.data["since"] == row.mismatch_since.replace(tzinfo=UTC).isoformat()
        text = json.dumps(event.data)
        assert SERIAL_A not in text and SERIAL_B not in text
        assert SERIAL_A not in json.dumps(status) and SERIAL_B not in json.dumps(status)

        await sink(rig.printer_id, _serial(SERIAL_C))  # still different: no second event
        assert _drain(events, "printer.identity_mismatch") == []
        bus.unsubscribe(f"printer:{rig.printer_id}:state", "t-mismatch")


async def test_missing_identity_never_mismatches_in_the_app() -> None:
    async with running() as rig:
        events = rig.app.state.event_bus.subscribe(f"printer:{rig.printer_id}:state", "t-none")
        sink = _sink(rig)
        await sink(rig.printer_id, _serial(SERIAL_A))

        assert await sink(rig.printer_id, _serial(None)) == "none"
        assert (
            await sink(rig.printer_id, ObservedIdentity(None, None, "00:80:77:12:34:56")) == "kept"
        )

        assert (await _status(rig))["identity_mismatch"] is False
        assert not rig.app.state.print_queue.is_identity_held(rig.printer_id)
        assert _drain(events, "printer.identity_mismatch") == []


async def test_stored_identity_back_clears_mismatch_in_the_app() -> None:
    async with running() as rig:
        events = rig.app.state.event_bus.subscribe(f"printer:{rig.printer_id}:state", "t-back")
        sink = _sink(rig)
        await sink(rig.printer_id, _serial(SERIAL_A))
        await sink(rig.printer_id, _serial(SERIAL_B))
        assert len(_drain(events, "printer.identity_mismatch")) == 1

        assert await sink(rig.printer_id, _serial(SERIAL_A)) == "seen"

        assert (await _status(rig))["identity_mismatch"] is False
        assert not rig.app.state.print_queue.is_identity_held(rig.printer_id)
        [event] = _drain(events, "printer.identity_mismatch")
        assert event.data == {"mismatch": False}


async def test_the_hook_sets_the_hold_from_the_database() -> None:
    """Interleaved hooks cannot leave the hold and the database disagreeing."""
    async with running() as rig:
        runtime = rig.app.state.printer_runtime
        queue = rig.app.state.print_queue
        sink = runtime._identity_sink
        await sink(rig.printer_id, _serial(SERIAL_A))
        await sink(rig.printer_id, _serial(SERIAL_B))
        assert queue.is_identity_held(rig.printer_id)

        await runtime._mismatch_changed(rig.printer_id, None)  # a stale "cleared" arrives late
        assert queue.is_identity_held(rig.printer_id)  # the database still says mismatch

        await sink(rig.printer_id, _serial(SERIAL_A))
        assert not queue.is_identity_held(rig.printer_id)
        await runtime._mismatch_changed(rig.printer_id, T0)  # a stale "started" arrives late
        assert not queue.is_identity_held(rig.printer_id)


async def test_the_hold_fails_closed_when_the_reread_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with running() as rig:
        runtime = rig.app.state.printer_runtime
        queue = rig.app.state.print_queue

        async def broken(_pid: UUID) -> Any:
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(runtime, "_read_mismatch_since", broken)

        await runtime._mismatch_changed(rig.printer_id, T0)  # a mismatch started
        assert queue.is_identity_held(rig.printer_id)  # never left unheld

        await runtime._mismatch_changed(rig.printer_id, None)  # unverified: may set, never release
        assert queue.is_identity_held(rig.printer_id)

        monkeypatch.undo()  # the database is back; the swap is over
        sink = runtime._identity_sink
        await sink(rig.printer_id, _serial(SERIAL_A))
        await sink(rig.printer_id, _serial(SERIAL_B))
        assert queue.is_identity_held(rig.printer_id)
        await sink(rig.printer_id, _serial(SERIAL_A))  # a verified clear releases it
        assert not queue.is_identity_held(rig.printer_id)


async def test_a_lost_hold_is_restored_by_the_next_different_probe() -> None:
    """The unchanged-reading shortcut must not leave a mismatched printer unheld."""
    async with running() as rig:
        queue = rig.app.state.print_queue
        events = rig.app.state.event_bus.subscribe(f"printer:{rig.printer_id}:state", "t-lost")
        sink = rig.app.state.printer_runtime._identity_sink
        await sink(rig.printer_id, _serial(SERIAL_A))
        await sink(rig.printer_id, _serial(SERIAL_B))
        assert queue.is_identity_held(rig.printer_id)
        assert len(_drain(events, "printer.identity_mismatch")) == 1
        queue.set_identity_hold(rig.printer_id, False)  # the queue lost it; the database did not

        assert await sink(rig.printer_id, _serial(SERIAL_B)) == "different"  # nothing new to store

        assert queue.is_identity_held(rig.printer_id)
        await sink(rig.printer_id, _serial(SERIAL_B))  # held again: no event storm
        assert len(_drain(events, "printer.identity_mismatch")) == 1


async def test_seen_probe_lifts_a_stale_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    """263-48: the clear of a mismatch reached the database, but the hook could not verify it
    (the re-read failed), so the queue kept its hold (fail closed). The next probe that sees the
    stored device again finds no mismatch to clear and used to stay silent: the hold stuck until
    a restart. A ``seen`` probe re-syncs a hold the database no longer backs, with one event."""
    async with running() as rig:
        runtime = rig.app.state.printer_runtime
        queue = rig.app.state.print_queue
        events = rig.app.state.event_bus.subscribe(f"printer:{rig.printer_id}:state", "t-stale")
        sink = runtime._identity_sink
        await sink(rig.printer_id, _serial(SERIAL_A))
        await sink(rig.printer_id, _serial(SERIAL_B))
        assert queue.is_identity_held(rig.printer_id)
        assert len(_drain(events, "printer.identity_mismatch")) == 1

        async def broken(_pid: UUID) -> datetime | None:
            raise RuntimeError("database is locked")

        monkeypatch.setattr(runtime, "_read_mismatch_since", broken)
        assert await sink(rig.printer_id, _serial(SERIAL_A)) == "seen"  # cleared in the DB
        assert (await _row(rig.printer_id)).mismatch_since is None
        assert queue.is_identity_held(rig.printer_id)  # unverified: the hold stays
        monkeypatch.undo()

        assert await sink(rig.printer_id, _serial(SERIAL_A)) == "seen"

        assert not queue.is_identity_held(rig.printer_id)
        [event] = _drain(events, "printer.identity_mismatch")
        assert event.data == {"mismatch": False}
        await sink(rig.printer_id, _serial(SERIAL_A))  # unheld now: no further event
        assert _drain(events, "printer.identity_mismatch") == []


async def _seed_mismatch() -> None:
    """A printer that was flagged before the hub was stopped, and one that never was."""
    async with _eng.async_session() as s:
        printer = (await s.execute(select(Printer).where(Printer.slug == "page-1"))).scalar_one()
        s.add(
            PrinterIdentity(
                printer_id=printer.id,
                hardware_id=SERIAL_A,
                hardware_id_kind="serial",
                hardware_id_seen_at=T0,
                observed_id=SERIAL_B,
                observed_kind="serial",
                mismatch_since=T0,
            )
        )
        await s.commit()


async def test_mismatch_survives_restart() -> None:
    """The hold is reloaded from ``printer_identity`` when the printer is attached."""
    async with running(seeds=_seed_mismatch) as rig:
        assert rig.app.state.print_queue.is_identity_held(rig.printer_id)
        assert (await _status(rig))["identity_mismatch"] is True


async def test_the_flag_is_on_every_status_branch() -> None:
    """A printer nobody probed (no cache row) still says that its device changed."""

    async def seed() -> None:
        pid = await _printer("page-2", enabled=False)
        async with _eng.async_session() as s:
            s.add(
                PrinterIdentity(
                    printer_id=pid,
                    hardware_id=SERIAL_A,
                    hardware_id_kind="serial",
                    observed_id=SERIAL_B,
                    observed_kind="serial",
                    mismatch_since=T0,
                )
            )
            await s.commit()

    async with running(seeds=seed) as rig:
        async with _eng.async_session() as s:
            other = (await s.execute(select(Printer).where(Printer.slug == "page-2"))).scalar_one()
        status = await _status(rig, other.id)
        assert status["identity_mismatch"] is True
        assert status["online"] is None  # the branch without a probe
        assert (await _status(rig))["identity_mismatch"] is False


# ---------------------------------------------------------------------------- held jobs


async def test_mismatch_failure_does_not_strand_held_job(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """263-47: ending a held job raises (its failure write fails). The job still ends in
    memory (its waiters are released, nothing prints it) and the failure is logged; it is
    never evicted, because its row could not be written. Its cells stay reserved: the row still
    says ``queued``, and freed cells could be reserved by another print that the restarted job
    would then print over."""
    async with running() as rig:
        queue: PrintQueue = rig.app.state.print_queue
        code = await _sheet()
        await queue.pause_printer(rig.printer_id, reason="test", source="user")
        resp = await rig.print(_body(code, 3))
        assert resp.status_code == 202, resp.text
        (page,) = resp.json()["pages"]
        assert len(await _cells()) == 3
        queue.set_identity_hold(rig.printer_id, True)

        async def broken(*_a: Any, **_k: Any) -> None:
            raise RuntimeError("database is locked")

        monkeypatch.setattr(queue._page_runner._store, "mark_failed_code", broken)
        caplog.set_level(logging.ERROR, logger="app.services.print_queue")
        await queue.resume_printer(rig.printer_id)

        job = await queue.wait_for_job(page["job_id"], timeout_s=TIMEOUT_S)
        assert job.state == JobState.FAILED
        assert job.error_code == "printer-identity-mismatch"
        await asyncio.sleep(0.1)  # an outcome call would have settled the cells by now
        assert {c.state for c in await _cells()} == {"reserved"} and len(await _cells()) == 3
        assert queue.forget_job(UUID(page["job_id"])) is False  # unpersisted: kept
        assert sum(1 for r in rig.fake.received if r.operation == "Print-Job") == 0
        assert any(page["job_id"] in r.getMessage() for r in caplog.records)
