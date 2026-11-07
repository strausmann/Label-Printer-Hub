"""Manual calibration of a page printer's tray (spec 7.1, 13.1).

All values are integers so stored values stay exact on SQLite (plan decision):
offsets in hundredths of a millimetre (D16), scale in parts per million
(``1.000000`` is ``1000000``), rotation in micro-degrees. The row stores the
printer's measured deviation; the hub applies the inverse when it renders.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String, Uuid
from sqlmodel import Column, Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


class PrinterCalibration(SQLModel, table=True):
    __tablename__ = "printer_calibrations"
    __table_args__ = (
        CheckConstraint("method IN ('manual','photo')", name="ck_printer_calibrations_method"),
    )

    printer_id: UUID = Field(sa_column=Column(Uuid, ForeignKey("printers.id"), primary_key=True))
    tray_key: str = Field(sa_column=Column(String, primary_key=True))
    method: str = Field(sa_column=Column(String, nullable=False))
    offset_x_hmm: int = Field(sa_column=Column(Integer, nullable=False))  # D16
    offset_y_hmm: int = Field(sa_column=Column(Integer, nullable=False))  # D16
    scale_x_ppm: int = Field(sa_column=Column(Integer, nullable=False))
    scale_y_ppm: int = Field(sa_column=Column(Integer, nullable=False))
    rotation_udeg: int = Field(sa_column=Column(Integer, nullable=False))
    corrections: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    """Reserved for row/column corrections (Part B); null in Part A."""
    measured_on_type_version_id: UUID | None = Field(
        default=None, sa_column=Column(Uuid, nullable=True)
    )
    """Informational: the sheet type version the page was measured on."""
    updated_at: datetime = Field(
        default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_by: str | None = Field(default=None, sa_column=Column(String, nullable=True))
