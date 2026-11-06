"""Storage of the manual calibration per page printer and tray.

The row stores the printer's deviation around the page centre; the hub applies the inverse
when it renders (D17).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.calibration.model import (
    CalibrationIn,
    CalibrationRead,
    MeasuredOn,
    deviation_to_values,
    to_deviation,
)
from app.models.printer import Printer
from app.models.printer_calibration import PrinterCalibration
from app.models.printer_tray import PrinterTray
from app.models.sheet import SheetType, SheetTypeVersion
from app.services.page_jobs import CalibrationSnapshot
from app.sheets import type_service as ts
from app.sheets.errors import MediaKindMismatchError, PrinterNotFoundError, TrayUnknownError


async def _page_printer(session: AsyncSession, printer_id: UUID) -> Printer:
    printer = await session.get(Printer, printer_id)
    if printer is None:
        raise PrinterNotFoundError()
    if printer.backend != "ipp":
        raise MediaKindMismatchError()
    return printer


async def _enabled_trays(session: AsyncSession, printer_id: UUID) -> list[PrinterTray]:
    rows = await session.execute(
        select(PrinterTray)
        .where(col(PrinterTray.printer_id) == printer_id, col(PrinterTray.enabled).is_(True))
        .order_by(PrinterTray.tray_key)
    )
    return list(rows.scalars())


async def _check_tray(session: AsyncSession, printer_id: UUID, tray: str) -> None:
    if tray not in {t.tray_key for t in await _enabled_trays(session, printer_id)}:
        raise TrayUnknownError([tray])


async def _measured_on(session: AsyncSession, version_id: UUID | None) -> MeasuredOn | None:
    if version_id is None:
        return None
    found = (
        await session.execute(
            select(col(SheetType.key), col(SheetTypeVersion.version))
            .join(SheetTypeVersion, col(SheetTypeVersion.type_id) == col(SheetType.id))
            .where(col(SheetTypeVersion.id) == version_id)
        )
    ).first()
    return MeasuredOn(type_key=found[0], version=found[1]) if found else None


async def _read(
    session: AsyncSession, tray: str, row: PrinterCalibration | None
) -> CalibrationRead:
    if row is None:
        return CalibrationRead(tray=tray)
    v = deviation_to_values(to_deviation(row))
    # SQLite hands back naive datetimes; every stored time is UTC.
    updated_at = row.updated_at if row.updated_at.tzinfo else row.updated_at.replace(tzinfo=UTC)
    return CalibrationRead(
        tray=tray,
        method=row.method,
        offset_x_mm=v.offset_x_mm,
        offset_y_mm=v.offset_y_mm,
        scale_x=v.scale_x,
        scale_y=v.scale_y,
        rotation_deg=v.rotation_deg,
        measured_on=await _measured_on(session, row.measured_on_type_version_id),
        updated_at=updated_at,
        updated_by=row.updated_by,
    )


async def get_all(session: AsyncSession, printer_id: UUID) -> list[CalibrationRead]:
    """One entry per enabled tray; a tray without a row has ``None`` values (identity)."""
    await _page_printer(session, printer_id)
    rows = {
        r.tray_key: r
        for r in (
            await session.execute(
                select(PrinterCalibration).where(col(PrinterCalibration.printer_id) == printer_id)
            )
        ).scalars()
    }
    return [
        await _read(session, t.tray_key, rows.get(t.tray_key))
        for t in await _enabled_trays(session, printer_id)
    ]


async def put(
    session: AsyncSession,
    printer_id: UUID,
    tray: str,
    values: CalibrationIn,
    *,
    measured_on: tuple[str, int] | None,
    actor: str,
) -> CalibrationRead:
    """Store (replace) the manual calibration of a tray. Nothing is stored on any error."""
    await _page_printer(session, printer_id)
    dev = to_deviation(values)  # raises calibration_out_of_range before any write
    await _check_tray(session, printer_id, tray)
    version_id = (
        (await ts.get_version(session, measured_on[0], measured_on[1])).id if measured_on else None
    )
    async with ts.write_transaction(session):
        row = await session.get(PrinterCalibration, (printer_id, tray))
        if row is None:
            row = PrinterCalibration(
                printer_id=printer_id,
                tray_key=tray,
                method="manual",
                offset_x_hmm=0,
                offset_y_hmm=0,
                scale_x_ppm=1_000_000,
                scale_y_ppm=1_000_000,
                rotation_udeg=0,
            )
            session.add(row)
        row.method = "manual"  # D17: the row is the printer's deviation, not the correction
        row.offset_x_hmm = dev.offset_x_hmm  # D16
        row.offset_y_hmm = dev.offset_y_hmm  # D16
        row.scale_x_ppm = dev.scale_x_ppm
        row.scale_y_ppm = dev.scale_y_ppm
        row.rotation_udeg = dev.rotation_udeg
        row.measured_on_type_version_id = version_id
        row.updated_at = datetime.now(UTC)
        row.updated_by = actor
        await session.commit()
    return await _read(session, tray, row)


async def delete(session: AsyncSession, printer_id: UUID, tray: str, *, actor: str) -> None:  # noqa: ARG001 - kept for the call contract; not logged
    """Reset a tray to the identity. A tray without a calibration is left as it is."""
    await _page_printer(session, printer_id)
    await _check_tray(session, printer_id, tray)
    async with ts.write_transaction(session):
        row = await session.get(PrinterCalibration, (printer_id, tray))
        if row is not None:
            await session.delete(row)
        await session.commit()


async def snapshot(session: AsyncSession, printer_id: UUID, tray: str) -> CalibrationSnapshot:
    """The calibration a page job records; a tray without one is the identity."""
    await _page_printer(session, printer_id)
    await _check_tray(session, printer_id, tray)
    row = await session.get(PrinterCalibration, (printer_id, tray))
    if row is None:
        return CalibrationSnapshot(method="none")
    return CalibrationSnapshot(
        method=row.method,
        dx_hmm=row.offset_x_hmm,
        dy_hmm=row.offset_y_hmm,
        sx_ppm=row.scale_x_ppm,
        sy_ppm=row.scale_y_ppm,
        rotation_udeg=row.rotation_udeg,
    )
