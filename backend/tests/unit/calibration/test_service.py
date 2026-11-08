"""Calibration service: values, ranges, storage roundtrip, tray and printer-kind checks."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.calibration import service
from app.calibration.model import CalibrationIn, deviation_to_values, to_deviation
from app.models.printer import Printer
from app.models.printer_calibration import PrinterCalibration
from app.models.printer_tray import PrinterTray
from app.page_render.transform import IDENTITY, Deviation
from app.sheets import type_service as ts
from app.sheets.errors import (
    CalibrationOutOfRangeError,
    MediaKindMismatchError,
    PrinterNotFoundError,
    SheetTypeNotFoundError,
    TrayUnknownError,
)
from app.sheets.geometry import Geometry
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

G48 = Geometry("A4", 21000, 29700, 4570, 2120, 4, 12, 4820, 2120, 2130, 985, None, "rectangle")


@pytest_asyncio.fixture
async def session(async_session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[Any]:
    async with async_session_factory() as s:
        yield s


async def _printer(session: AsyncSession, backend: str = "ipp") -> UUID:
    p = Printer(
        name=f"p-{uuid4().hex[:6]}", slug=f"p-{uuid4().hex[:6]}", model="m", backend=backend
    )
    session.add(p)
    session.add(PrinterTray(printer_id=p.id, tray_key="auto", label="Auto", is_default=True))
    session.add(PrinterTray(printer_id=p.id, tray_key="tray-2", label="Tray 2", enabled=True))
    session.add(PrinterTray(printer_id=p.id, tray_key="off", label="Off", enabled=False))
    await session.commit()
    return p.id


VALUES = CalibrationIn(
    offset_x_mm=1.2, offset_y_mm=-0.4, scale_x=1.001, scale_y=0.999, rotation_deg=0.3
)


def test_to_deviation_converts_units() -> None:
    assert to_deviation(VALUES) == Deviation(120, -40, 1_001_000, 999_000, 300_000)
    assert to_deviation(None) == IDENTITY


def test_values_roundtrip_through_deviation() -> None:
    assert deviation_to_values(to_deviation(VALUES)) == VALUES


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("offset_x_mm", 10.01),
        ("offset_y_mm", -10.01),
        ("scale_x", 1.0501),
        ("scale_y", 0.9499),
        ("rotation_deg", 2.000001),
        ("rotation_deg", float("nan")),
        ("offset_x_mm", float("inf")),
    ],
)
def test_ranges_enforced(field: str, value: float) -> None:
    # ``model_construct``: the schema refuses NaN and Infinity itself (R12-1); the service keeps
    # its own check for a value that got past it.
    with pytest.raises(CalibrationOutOfRangeError) as err:
        to_deviation(CalibrationIn.model_construct(**{field: value}))
    assert err.value.error_code == "calibration_out_of_range"
    assert err.value.status == 422
    assert err.value.detail is not None and err.value.detail["field"] == field


def test_bounds_are_inclusive() -> None:
    dev = to_deviation(
        CalibrationIn(offset_x_mm=10, offset_y_mm=-10, scale_x=1.05, scale_y=0.95, rotation_deg=-2)
    )
    assert dev == Deviation(1000, -1000, 1_050_000, 950_000, -2_000_000)


def test_too_many_decimals_refused() -> None:
    with pytest.raises(CalibrationOutOfRangeError) as err:
        to_deviation(CalibrationIn(offset_x_mm=1.234))
    assert err.value.detail is not None and err.value.detail["reason"] == "too_many_decimals"


@pytest.mark.asyncio
async def test_put_get_delete_roundtrip(session: AsyncSession) -> None:
    pid = await _printer(session)
    await ts.create_type(
        session,
        ts.TypeFields("avery-l4736rev", "L4736", "Avery", [], None, None),
        G48,
        actor="t",
    )
    before = await service.get_all(session, pid)
    assert [r.tray for r in before] == ["auto", "tray-2"]  # the disabled tray is not listed
    assert all(r.method is None and r.offset_x_mm is None for r in before)

    saved = await service.put(
        session, pid, "tray-2", VALUES, measured_on=("avery-l4736rev", 1), actor="alice"
    )
    assert saved.method == "manual"
    assert saved.offset_x_mm == 1.2 and saved.scale_x == 1.001 and saved.rotation_deg == 0.3
    assert saved.measured_on is not None and saved.measured_on.type_key == "avery-l4736rev"
    assert saved.updated_by == "alice" and saved.updated_at is not None

    listed = {r.tray: r for r in await service.get_all(session, pid)}
    assert listed["tray-2"] == saved
    assert listed["auto"].method is None

    snap = await service.snapshot(session, pid, "tray-2")
    assert (snap.method, snap.dx_hmm, snap.dy_hmm) == ("manual", 120, -40)
    assert (snap.sx_ppm, snap.sy_ppm, snap.rotation_udeg) == (1_001_000, 999_000, 300_000)

    replaced = await service.put(
        session, pid, "tray-2", CalibrationIn(offset_x_mm=0.5), measured_on=None, actor="bob"
    )
    assert replaced.offset_x_mm == 0.5 and replaced.measured_on is None
    assert replaced.updated_by == "bob"

    await service.delete(session, pid, "tray-2", actor="bob")
    after = {r.tray: r for r in await service.get_all(session, pid)}
    assert after["tray-2"].method is None
    assert (await service.snapshot(session, pid, "tray-2")).method == "none"
    await service.delete(session, pid, "tray-2", actor="bob")  # already identity: no error


@pytest.mark.asyncio
async def test_put_out_of_range_stores_nothing(session: AsyncSession) -> None:
    pid = await _printer(session)
    with pytest.raises(CalibrationOutOfRangeError):
        await service.put(
            session, pid, "auto", CalibrationIn(offset_x_mm=10.01), measured_on=None, actor="a"
        )
    assert await session.get(PrinterCalibration, (pid, "auto")) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("tray", ["missing", "off"])
async def test_unknown_or_disabled_tray(session: AsyncSession, tray: str) -> None:
    pid = await _printer(session)
    with pytest.raises(TrayUnknownError) as err:
        await service.put(session, pid, tray, VALUES, measured_on=None, actor="a")
    assert err.value.detail == {"trays": []}  # C19: the caller's key is not echoed
    with pytest.raises(TrayUnknownError):
        await service.delete(session, pid, tray, actor="a")
    with pytest.raises(TrayUnknownError):
        await service.snapshot(session, pid, tray)
    assert await session.get(PrinterCalibration, (pid, tray)) is None


@pytest.mark.asyncio
async def test_tape_printer_is_a_media_kind_mismatch(session: AsyncSession) -> None:
    pid = await _printer(session, backend="brother_ql")
    for call in (
        service.get_all(session, pid),
        service.put(session, pid, "auto", VALUES, measured_on=None, actor="a"),
        service.delete(session, pid, "auto", actor="a"),
        service.snapshot(session, pid, "auto"),
    ):
        with pytest.raises(MediaKindMismatchError):
            await call


@pytest.mark.asyncio
async def test_unknown_printer_and_unknown_measured_type(session: AsyncSession) -> None:
    with pytest.raises(PrinterNotFoundError):
        await service.get_all(session, uuid4())
    pid = await _printer(session)
    with pytest.raises(SheetTypeNotFoundError):
        await service.put(session, pid, "auto", VALUES, measured_on=("nope", 1), actor="a")
    assert await session.get(PrinterCalibration, (pid, "auto")) is None


@pytest.mark.asyncio
async def test_delete_clears_a_row_whose_tray_is_now_disabled(session: AsyncSession) -> None:
    pid = await _printer(session)
    await service.put(session, pid, "tray-2", VALUES, measured_on=None, actor="a")
    tray = await session.get(PrinterTray, (pid, "tray-2"))
    assert tray is not None
    tray.enabled = False
    await session.commit()
    await service.delete(session, pid, "tray-2", actor="a")
    assert await session.get(PrinterCalibration, (pid, "tray-2")) is None


@pytest.mark.asyncio
async def test_delete_clears_a_row_whose_tray_was_removed(session: AsyncSession) -> None:
    pid = await _printer(session)
    await service.put(session, pid, "tray-2", VALUES, measured_on=None, actor="a")
    tray = await session.get(PrinterTray, (pid, "tray-2"))
    assert tray is not None
    await session.delete(tray)
    await session.commit()
    await service.delete(session, pid, "tray-2", actor="a")
    assert await session.get(PrinterCalibration, (pid, "tray-2")) is None
    with pytest.raises(TrayUnknownError):  # no row and no tray: still an error
        await service.delete(session, pid, "tray-2", actor="a")


def test_measured_on_is_bounded() -> None:
    from app.calibration.model import MeasuredOn
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MeasuredOn(type_key="k" * 201, version=1)
    with pytest.raises(ValidationError):
        MeasuredOn(type_key="k", version=0)
    assert MeasuredOn(type_key="k" * 200, version=1).version == 1


def test_schema_states_the_bounds_without_enforcing_them() -> None:
    props = CalibrationIn.model_json_schema()["properties"]
    assert (props["offset_x_mm"]["minimum"], props["offset_x_mm"]["maximum"]) == (-10.0, 10.0)
    assert props["scale_x"]["x-decimals"] == 6
    assert CalibrationIn(offset_x_mm=50).offset_x_mm == 50  # the fit may return such values
