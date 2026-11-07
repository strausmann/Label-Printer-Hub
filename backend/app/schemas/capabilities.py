"""Printer capabilities: what a tape or page printer can do, from cached facts only."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.calibration.model import CalibrationRead


class TapeResolution(BaseModel):
    x: int = Field(description="Dots per inch across the print head.")
    y: int = Field(description="Dots per inch along the tape.")


class PageResolution(BaseModel):
    max: int | None = Field(description="Highest resolution the printer reports; None if unknown.")
    supported: list[int] = Field(description="Every reported resolution in dpi, as reported.")


class TapeMedia(BaseModel):
    width_mm: int
    type: str | None = Field(
        description="Tape type; None while the status cache does not carry it."
    )
    printable_px: int
    printable_mm: float = Field(description="printable_px / dpi_y * 25.4, two decimals.")


class PageSize(BaseModel):
    name: str
    width_mm: float
    height_mm: float


class HardwareMargins(BaseModel):
    top: float
    left: float
    bottom: float
    right: float


class PageMedia(BaseModel):
    page_sizes: list[PageSize]
    media_type_settable: bool
    media_types: list[str]
    hardware_margins_mm: HardwareMargins | None


class TrayCapability(BaseModel):
    key: str
    label: str
    load_hint: str | None
    enabled: bool
    is_default: bool
    media: str | None = Field(description="Media the printer reports in this tray, if any.")
    calibration: CalibrationRead | None = Field(
        description="Stored calibration; None while the tray has none or is disabled."
    )


class Capabilities(BaseModel):
    """Served from the status cache; the printer is never contacted."""

    kind: Literal["tape", "page"]
    resolution_dpi: TapeResolution | PageResolution
    media: TapeMedia | PageMedia | None = Field(
        description=(
            "None while nothing is known (page printer that never answered), when no tape "
            "is loaded, or when the loaded tape width has no geometry entry (tape)."
        )
    )
    trays: list[TrayCapability] | None = Field(description="Page printers only.")
    document_formats: list[str] | None = Field(description="Page printers only.")
    captured_at: datetime | None = Field(
        description=(
            "When the values were read. A page printer that went offline keeps the time of "
            "its last successful reading."
        )
    )
