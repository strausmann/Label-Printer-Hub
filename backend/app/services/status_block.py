"""Brother PT/QL Series 32-byte status block parser.

This module decodes the binary status block that Brother label printers return
in response to ``ESC i S`` (TCP/9100) and that they emit unprompted during
print jobs (phase changes, completion, errors).

The block layout is shared between PT-Series and QL-Series with a few
family-specific quirks. PT-Series populates tape and text colour bytes
(24, 25); QL-Series leaves those reserved. PT-Series uses media-type codes
0x01/0x03/0x11/0x17; QL-Series uses 0x4A/0x4B. Both families parse cleanly
through this single parser; downstream consumers (printer-model plugins) can
ignore fields that don't apply to their hardware.

References:
    - Brother PT-E550W/P750W/P710BT Raster Command Reference v1.02, section 4
    - Brother QL-800/810W/820NWB Raster Command Reference v1.01, section 4

See also:
    docs/decisions/0006-status-sources-by-phase.md — when this is consulted
    docs/decisions/0004-plugin-architecture-for-printer-models.md — who uses it
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, IntFlag

STATUS_BLOCK_SIZE: int = 32


class StatusBlockError(Exception):
    """Raised when a status block cannot be parsed."""


class MediaType(IntEnum):
    """Media type at status-block offset 11.

    PT-Series and QL-Series use disjoint code sets here. Unknown values map to
    :attr:`UNKNOWN` so unfamiliar hardware doesn't crash the parser.
    """

    NONE = 0x00
    LAMINATED = 0x01  # PT-Series TZe
    NON_LAMINATED = 0x03  # PT-Series TZe
    HEAT_SHRINK_2_1 = 0x11  # PT-Series HS 2:1
    HEAT_SHRINK_3_1 = 0x17  # PT-Series HS 3:1
    CONTINUOUS_LENGTH_TAPE = 0x4A  # QL-Series
    DIE_CUT_LABEL = 0x4B  # QL-Series
    INCOMPATIBLE = 0xFF
    UNKNOWN = -1  # placeholder when value isn't in the spec


class StatusType(IntEnum):
    """Status type at offset 18 — what kind of message the printer is sending."""

    REPLY = 0x00  # response to a status-information-request
    PRINTING_COMPLETED = 0x01  # printer finished a page
    ERROR = 0x02  # error occurred (consult error flags)
    TURNED_OFF = 0x04
    NOTIFICATION = 0x05
    PHASE_CHANGE = 0x06  # transitioning between phases (printing/receiving)
    UNKNOWN = -1


class PhaseType(IntEnum):
    """Phase type at offset 19."""

    EDITING = 0x00  # also "receiving" on QL-Series
    PRINTING = 0x01
    UNKNOWN = -1


class NotificationCode(IntEnum):
    """Notification at offset 22."""

    NOT_AVAILABLE = 0x00
    COVER_OPEN = 0x01  # PT-Series
    COVER_CLOSED = 0x02  # PT-Series
    COOLING_STARTED = 0x03  # QL-Series
    COOLING_FINISHED = 0x04  # QL-Series
    UNKNOWN = -1


class TapeColor(IntEnum):
    """Tape colour at offset 24 — PT-Series only.

    QL-Series does not populate this byte; the value lands on :attr:`UNKNOWN`.
    """

    UNKNOWN = 0x00
    WHITE = 0x01
    OTHER = 0x02
    CLEAR = 0x03
    RED = 0x04
    BLUE = 0x05
    YELLOW = 0x06
    GREEN = 0x07
    BLACK = 0x08
    CLEAR_WHITE_TEXT = 0x09
    MATTE_WHITE = 0x20
    MATTE_CLEAR = 0x21
    MATTE_SILVER = 0x22
    SATIN_GOLD = 0x23
    SATIN_SILVER = 0x24
    BLUE_D = 0x30
    RED_D = 0x31
    FLUORESCENT_ORANGE = 0x40
    FLUORESCENT_YELLOW = 0x41
    BERRY_PINK_S = 0x50
    LIGHT_GRAY_S = 0x51
    LIME_GREEN_S = 0x52
    YELLOW_F = 0x60
    PINK_F = 0x61
    BLUE_F = 0x62
    HEAT_SHRINK_WHITE = 0x70
    FLEX_WHITE = 0x90
    FLEX_YELLOW = 0x91
    CLEANING = 0xF0
    STENCIL = 0xF1
    INCOMPATIBLE = 0xFF


class TextColor(IntEnum):
    """Text colour at offset 25 — PT-Series only."""

    UNKNOWN = 0x00
    WHITE = 0x01
    OTHER = 0x02
    RED = 0x04
    BLUE = 0x05
    BLACK = 0x08
    GOLD = 0x0A
    BLUE_F = 0x62
    CLEANING = 0xF0
    STENCIL = 0xF1
    INCOMPATIBLE = 0xFF


class PrinterError(IntFlag):
    """Aggregated error flags from offsets 8 (info1) and 9 (info2).

    Some flags are PT-only or QL-only; both sets are exposed here. Consumers
    should treat unfamiliar flags gracefully — a future Brother firmware may
    add or repurpose bits.
    """

    NONE = 0
    # Error info 1 (offset 8)
    NO_MEDIA = 1 << 0
    END_OF_MEDIA = 1 << 1  # QL die-cut only
    CUTTER_JAM = 1 << 2
    WEAK_BATTERIES = 1 << 3  # PT only
    PRINTER_IN_USE = 1 << 4  # QL
    PRINTER_TURNED_OFF = 1 << 5  # QL
    HIGH_VOLTAGE_ADAPTER = 1 << 6  # PT
    FAN_MOTOR_ERROR = 1 << 7  # QL
    # Error info 2 (offset 9), shifted into upper byte
    REPLACE_MEDIA = 1 << 8
    EXPANSION_BUFFER_FULL = 1 << 9  # QL
    COMMUNICATION_ERROR = 1 << 10  # QL
    COVER_OPEN = 1 << 12  # bit 4 of error info 2
    OVERHEATING = 1 << 13  # bit 5 (PT) — QL has cooling notifications instead
    MEDIA_CANNOT_BE_FED = 1 << 14  # QL
    SYSTEM_ERROR = 1 << 15  # QL


@dataclass(frozen=True, slots=True)
class StatusBlock:
    """Parsed Brother status block.

    Field names mirror the Brother spec column names where reasonable.
    Unknown enum values land on the ``UNKNOWN`` member so consumers don't
    have to defend against ValueError on every field access.
    """

    raw: bytes
    print_head_mark: int
    size: int
    brother_code: int
    series_code: int
    model_code: int
    country_code: int
    error_flags_1: int
    error_flags_2: int
    media_width_mm: int
    media_type: MediaType
    media_length_mm: int
    mode: int
    status_type: StatusType
    phase_type: PhaseType
    phase_number: int
    notification: NotificationCode
    tape_color: TapeColor
    text_color: TextColor

    errors: list[PrinterError] = field(default_factory=list)

    @property
    def is_ready(self) -> bool:
        """True if the printer is idle, no errors, and waiting to receive data."""
        return (
            self.status_type == StatusType.REPLY
            and self.phase_type == PhaseType.EDITING
            and not self.errors
        )

    @property
    def is_printing(self) -> bool:
        """True if the printer is mid-print."""
        return self.phase_type == PhaseType.PRINTING


def _safe_enum[E: IntEnum](enum_cls: type[E], value: int, default: E) -> E:
    """Map a raw byte to an enum member, falling back to ``default`` on misses."""
    try:
        return enum_cls(value)
    except ValueError:
        return default


def _decode_errors(error_flags_1: int, error_flags_2: int) -> list[PrinterError]:
    """Translate Brother error info 1+2 into a list of distinct flags."""
    flags: list[PrinterError] = []
    bit_map_1: list[tuple[int, PrinterError]] = [
        (0x01, PrinterError.NO_MEDIA),
        (0x02, PrinterError.END_OF_MEDIA),
        (0x04, PrinterError.CUTTER_JAM),
        (0x08, PrinterError.WEAK_BATTERIES),
        (0x10, PrinterError.PRINTER_IN_USE),
        (0x20, PrinterError.PRINTER_TURNED_OFF),
        (0x40, PrinterError.HIGH_VOLTAGE_ADAPTER),
        (0x80, PrinterError.FAN_MOTOR_ERROR),
    ]
    bit_map_2: list[tuple[int, PrinterError]] = [
        (0x01, PrinterError.REPLACE_MEDIA),
        (0x02, PrinterError.EXPANSION_BUFFER_FULL),
        (0x04, PrinterError.COMMUNICATION_ERROR),
        (0x10, PrinterError.COVER_OPEN),
        (0x20, PrinterError.OVERHEATING),
        (0x40, PrinterError.MEDIA_CANNOT_BE_FED),
        (0x80, PrinterError.SYSTEM_ERROR),
    ]
    for mask, flag in bit_map_1:
        if error_flags_1 & mask:
            flags.append(flag)
    for mask, flag in bit_map_2:
        if error_flags_2 & mask:
            flags.append(flag)
    return flags


class StatusBlockParser:
    """Decodes the Brother 32-byte status block.

    Use :meth:`parse` from outside; the class itself holds no state.
    """

    @staticmethod
    def parse(raw: bytes) -> StatusBlock:
        """Decode a 32-byte block.

        Raises:
            StatusBlockError: if the input is not exactly 32 bytes.
        """
        if len(raw) != STATUS_BLOCK_SIZE:
            raise StatusBlockError(
                f"Status block must be exactly {STATUS_BLOCK_SIZE} bytes, got {len(raw)}"
            )

        error_flags_1 = raw[8]
        error_flags_2 = raw[9]
        return StatusBlock(
            raw=raw,
            print_head_mark=raw[0],
            size=raw[1],
            brother_code=raw[2],
            series_code=raw[3],
            model_code=raw[4],
            country_code=raw[5],
            error_flags_1=error_flags_1,
            error_flags_2=error_flags_2,
            media_width_mm=raw[10],
            media_type=_safe_enum(MediaType, raw[11], MediaType.UNKNOWN),
            media_length_mm=raw[17],
            mode=raw[15],
            status_type=_safe_enum(StatusType, raw[18], StatusType.UNKNOWN),
            phase_type=_safe_enum(PhaseType, raw[19], PhaseType.UNKNOWN),
            phase_number=(raw[20] << 8) | raw[21],
            notification=_safe_enum(NotificationCode, raw[22], NotificationCode.UNKNOWN),
            tape_color=_safe_enum(TapeColor, raw[24], TapeColor.UNKNOWN),
            text_color=_safe_enum(TextColor, raw[25], TextColor.UNKNOWN),
            errors=_decode_errors(error_flags_1, error_flags_2),
        )
