"""Helper to build StatusBlock instances in tests with minimal boilerplate.

The real StatusBlock has 18 fields. Most tests only care about three:
loaded media width, tape-empty / cover-open flags. `make_status_block`
takes those as kwargs and fills the rest with neutral defaults.
"""

from __future__ import annotations

from app.services.status_block import (
    MediaType,
    NotificationCode,
    PhaseType,
    PrinterError,
    StatusBlock,
    StatusType,
    TapeColor,
    TextColor,
)


def make_status_block(
    *,
    loaded_tape_mm: int = 24,
    media_type: MediaType = MediaType.LAMINATED,
    tape_empty: bool = False,
    cover_open: bool = False,
    extra_errors: PrinterError = PrinterError.NONE,
) -> StatusBlock:
    """Build a StatusBlock with neutral defaults and a small derived-error API."""
    errors = extra_errors
    if tape_empty:
        errors |= PrinterError.NO_MEDIA
    if cover_open:
        errors |= PrinterError.COVER_OPEN
    return StatusBlock(
        raw=b"\x00" * 32,
        print_head_mark=0x80,
        size=0x20,
        brother_code=ord("B"),
        series_code=0,
        model_code=0,
        country_code=0x30,
        media_width_mm=loaded_tape_mm,
        media_type=media_type,
        media_length_mm=0,
        mode=0,
        status_type=StatusType.REPLY,
        phase_type=PhaseType.EDITING,
        phase_number=0,
        notification=NotificationCode.NOT_AVAILABLE,
        tape_color=TapeColor.UNKNOWN,
        text_color=TextColor.UNKNOWN,
        errors=errors,
    )
