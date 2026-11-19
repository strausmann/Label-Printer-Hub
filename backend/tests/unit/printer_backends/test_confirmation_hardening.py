# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#398: hardening of the tape print confirmation from the 1.7.0 audits.

Finding 1 (IPP decode off the event loop) is in ``ipp/test_client_decode_thread.py``; the
other six are here: a failed record write is retried (2), a test print and a restart do not
leave ``counter_off`` stored (3, 4), the QL tape length follows the scaling of ``convert`` (5),
an address change between the read and the write of a record is not overwritten (6), and a
``TimeoutError`` raised by the sink itself is not logged as a slow write (7).
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import app.models  # noqa: F401 — registers all models with SQLModel.metadata
import pytest
import pytest_asyncio
from app.db.engine import _apply_pragmas
from app.models.printer import Printer
from app.printer_backends import brother_ql_backend
from app.printer_backends.brother_ql_backend import BrotherQLBackend
from app.printer_backends.exceptions import PrinterOfflineError
from app.printer_backends.ptouch_backend import PTouchBackend
from app.printer_backends.snmp_helper import PreflightStatus, SnmpQueryError
from app.printer_backends.tape_confirmation import ConfirmationRecord
from app.schemas.label_layout import LabelOrientation
from app.services.printer_runtime import PrinterRuntime
from app.services.status_block import MediaType
from app.services.tape_registry import TapeRegistry
from PIL import Image
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

pytestmark = pytest.mark.anyio

_AT = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)
_OFF = ConfirmationRecord("raw", True, _AT, counter_off=True)
_ON = ConfirmationRecord("raw", True, _AT, counter_off=False)
_MODULES = {
    "ql": "app.printer_backends.brother_ql_backend",
    "pt": "app.printer_backends.ptouch_backend",
}


def _make(kind: str) -> Any:
    return BrotherQLBackend(host="192.0.2.41") if kind == "ql" else PTouchBackend(host="192.0.2.42")


class _Sink:
    """Records every record it stores; raises *fail* for the first *failures* calls."""

    def __init__(self, failures: int = 0, fail: BaseException | None = None) -> None:
        self.failures = failures
        self.fail = fail or OSError("database is locked")
        self.calls: list[ConfirmationRecord] = []
        self.stored: list[ConfirmationRecord] = []

    async def __call__(self, record: ConfirmationRecord) -> None:
        self.calls.append(record)
        if len(self.calls) <= self.failures:
            raise self.fail
        self.stored.append(record)


def _neutral(monkeypatch: pytest.MonkeyPatch, module: str) -> None:
    """A read that neither answers nor refuses the counter (it changes no record itself)."""

    async def preflight(host: str, **_: Any) -> PreflightStatus:
        return PreflightStatus(hr_printer_status="idle", loaded_tape_mm=12, media_raw="12mm")

    monkeypatch.setattr(f"{module}.query_preflight", preflight)


def _offline(monkeypatch: pytest.MonkeyPatch, module: str) -> None:
    async def preflight(host: str, **_: Any) -> PreflightStatus:
        raise SnmpQueryError("timeout")

    monkeypatch.setattr(f"{module}.query_preflight", preflight)


# ---------------------------------------------------------------------------- finding 2


@pytest.mark.parametrize("kind", ["ql", "pt"])
async def test_failed_store_is_retried_on_the_next_read(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    _neutral(monkeypatch, _MODULES[kind])
    backend = _make(kind)
    sink = _Sink(failures=1)
    backend.send_state.sink = sink
    new = ConfirmationRecord("ipp", True, _AT)

    await backend.send_state.store(new)  # the database is busy: not stored
    assert sink.stored == []
    await backend.read_status()

    assert sink.stored == [new]
    await backend.read_status()  # stored now: no further write
    assert sink.calls == [new, new]


# ---------------------------------------------------------------------------- finding 3


@pytest.mark.parametrize("kind", ["ql", "pt"])
@pytest.mark.usefixtures("real_ql_media_check")
async def test_failed_test_print_does_not_leave_counter_off_stored(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    _offline(monkeypatch, _MODULES[kind])  # the test print's read refuses the print
    backend = _make(kind)
    sink = _Sink()
    backend.send_state.record = _OFF
    backend.send_state.sink = sink
    image = Image.new("1", (300, 76), 1)
    spec = (
        TapeRegistry.lookup_ql(62, MediaType.CONTINUOUS_LENGTH_TAPE)
        if kind == "ql"
        else TapeRegistry.lookup_pt(12, MediaType.LAMINATED)
    )

    with pytest.raises(PrinterOfflineError):
        await backend.print_image(image, spec, detect_confirmation=True)

    assert sink.stored == [_ON]
    assert backend.send_state.record == _ON


# ---------------------------------------------------------------------------- finding 4


class _Runtime:
    def __init__(self, sink: _Sink) -> None:
        self.sink = sink

    async def _store_confirmation(
        self, printer_id: Any, record: ConfirmationRecord, *, address: Any = None
    ) -> None:
        await self.sink(record)


@pytest.mark.parametrize("kind", ["ql", "pt"])
async def test_restart_clears_a_stored_counter_off(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    _offline(monkeypatch, _MODULES[kind])  # the read itself fails: the counter decides nothing
    sink = _Sink()
    backend = _make(kind)
    row = Printer(
        id=uuid4(),
        name="Shelf",
        model="QL-820NWB" if kind == "ql" else "PT-P750W",
        backend="brother_ql" if kind == "ql" else "ptouch",
        connection={"host": backend.host},
        print_confirmation=_OFF.to_json(),
    )

    PrinterRuntime._wire_confirmation(_Runtime(sink), backend, row)  # type: ignore[arg-type]
    assert sink.stored == []  # wiring itself writes nothing (it is synchronous)
    with pytest.raises(PrinterOfflineError):
        await backend.read_status()

    assert sink.stored == [_ON]


# ---------------------------------------------------------------------------- finding 5


async def _sent_length(
    monkeypatch: pytest.MonkeyPatch, image: Image.Image, *, high_resolution: bool
) -> float:
    backend = BrotherQLBackend(host="192.0.2.43")
    seen: list[float] = []

    async def send(data: bytes, labels: int, raw: Any, length_mm: float = 0.0) -> None:
        seen.append(length_mm)

    monkeypatch.setattr(backend.send_state, "send", send)
    await backend.print_image(
        image,
        TapeRegistry.lookup_ql(62, MediaType.CONTINUOUS_LENGTH_TAPE),
        high_resolution=high_resolution,
        orientation=LabelOrientation.ACROSS,
        media_checked=True,
    )
    assert len(seen) == 1
    return seen[0]


@pytest.mark.parametrize(
    ("high_resolution", "size", "expected_mm"),
    [
        # 1400 x 600 is scaled to 696 wide by convert: 600 * 696 / 1400 = 298.3 dots = 25.25 mm.
        (False, (1400, 600), 25.25),
        (True, (1400, 600), 25.25),
        # 1400 x 300 at 300 dpi scales to 149 dots, under the QL-820NWB minimum of 150: padded
        # to 303 rows, which scale to 150.6 dots = 12.75 mm. The padding is fed, so it counts.
        (False, (1400, 300), 12.75),
        # At 600 dpi it is 298.3 dots of 600 dpi, over the minimum: 12.63 mm, no padding.
        (True, (1400, 300), 12.63),
    ],
    ids=["300dpi", "600dpi", "300dpi-padded", "600dpi-short"],
)
async def test_wide_ql_label_length_is_the_scaled_feed_length(
    monkeypatch: pytest.MonkeyPatch,
    high_resolution: bool,
    size: tuple[int, int],
    expected_mm: float,
) -> None:
    length = await _sent_length(
        monkeypatch, Image.new("1", size, 1), high_resolution=high_resolution
    )
    assert length == pytest.approx(expected_mm, abs=0.05)


async def test_normal_ql_label_length_at_600_dpi(monkeypatch: pytest.MonkeyPatch) -> None:
    """(guard) A 62 mm x 100 mm label is 100 mm at both resolutions."""
    image = Image.new("1", (696, 1181), 1)
    assert await _sent_length(monkeypatch, image, high_resolution=False) == pytest.approx(
        100.0, abs=0.05
    )
    assert await _sent_length(monkeypatch, image, high_resolution=True) == pytest.approx(
        100.0, abs=0.05
    )


def test_ql_length_formula_doubles_the_printable_width_at_600_dpi() -> None:
    fitted = Image.new("1", (2800, 600), 1)  # 1400 x 300 fitted for 600 dpi
    assert brother_ql_backend._ql_length_mm(fitted, "62", True) == pytest.approx(12.63, abs=0.05)
    fitted = Image.new("1", (1392, 2362), 1)  # 696 x 1181 fitted for 600 dpi
    assert brother_ql_backend._ql_length_mm(fitted, "62", True) == pytest.approx(100.0, abs=0.05)


# ---------------------------------------------------------------------------- finding 6


@pytest_asyncio.fixture
async def factory(tmp_path: pathlib.Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A real SQLite file in WAL mode: in-memory SQLite has no second connection to race."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'hub.db'}")
    event.listen(engine.sync_engine, "connect", _apply_pragmas)  # WAL + busy_timeout
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


class _DbRuntime:
    def __init__(self, maker: async_sessionmaker[AsyncSession]) -> None:
        self._maker = maker

    def _sessions(self) -> async_sessionmaker[AsyncSession]:
        return self._maker


async def test_address_change_between_read_and_write_is_not_overwritten(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    pid = uuid4()
    async with factory() as s:
        s.add(
            Printer(
                id=pid,
                name="Shelf",
                slug="shelf",
                model="QL-820NWB",
                backend="brother_ql",
                connection={"host": "192.0.2.50"},
                print_confirmation=None,
            )
        )
        await s.commit()

    # The admin's host change holds the write lock, uncommitted, while the writer runs.
    admin = factory()
    await admin.execute(
        text("UPDATE printers SET connection = :conn, print_confirmation = NULL WHERE id = :id"),
        {"conn": '{"host": "192.0.2.51"}', "id": pid.hex},
    )
    writer = asyncio.create_task(
        PrinterRuntime._store_confirmation(
            _DbRuntime(factory),  # type: ignore[arg-type]
            pid,
            ConfirmationRecord("ipp", True, _AT),
            address=("192.0.2.50", 9100),
        )
    )
    await asyncio.sleep(0.3)  # the writer has read (or waits on the lock)
    await admin.commit()
    await admin.close()
    await writer

    async with factory() as s:
        row = await s.get(Printer, pid)
        assert row is not None
        assert row.connection == {"host": "192.0.2.51"}
        assert row.print_confirmation is None


# ---------------------------------------------------------------------------- finding 7


async def test_timeout_inside_the_sink_is_logged_as_a_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    backend = BrotherQLBackend(host="192.0.2.44")
    backend.send_state.sink = _Sink(failures=1, fail=TimeoutError())
    with caplog.at_level(logging.WARNING, logger="app.printer_backends.tape_confirmation"):
        await backend.send_state.store(ConfirmationRecord("ipp", True, _AT))
    messages = [r.getMessage() for r in caplog.records]
    assert any("could not be stored" in m for m in messages)
    assert not any("in time" in m for m in messages)
