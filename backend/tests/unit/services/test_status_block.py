"""Tests for the Brother 32-byte status block parser.

Reference: Brother Raster Command Reference v1.02 (PT-E550W/P750W/P710BT) and
v1.01 (QL-800/810W/820NWB), section 4 — Status information request.

The PT-Series and QL-Series share the same overall layout but differ in:
- byte [3] series code: PT 0x30, QL 0x34
- byte [4] model code: PT-P750W 0x68, QL-820NWB 0x41, etc.
- byte [11] media type values: PT 0x01/0x03/0x11/0x17 vs QL 0x4A/0x4B
- byte [14] reserved value: PT 0x00 vs QL 0x3F
- bytes [24-25] tape/text colour: PT only (QL reserves these)
"""

from __future__ import annotations

import pytest
from app.services.status_block import (
    MediaType,
    NotificationCode,
    PhaseType,
    PrinterError,
    StatusBlock,
    StatusBlockError,
    StatusBlockParser,
    StatusType,
    TapeColor,
    TextColor,
)

# Synthetic 32-byte sample matching what the PT-P750W replies in READY state
# with a 12mm laminated white tape and black text. Values follow the v1.02 spec.
PT_READY_12MM_WHITE_BLACK = bytes(
    [
        0x80,
        0x20,
        0x42,
        0x30,
        0x68,
        0x30,
        0x00,
        0x00,  # 0-7: header (PT-P750W)
        0x00,
        0x00,  # 8-9: no errors
        0x0C,
        0x01,  # 10-11: 12mm laminated TZe
        0x00,
        0x00,
        0x00,
        0x00,  # 12-15: defaults
        0x00,
        0x00,  # 16-17: density / continuous
        0x00,  # 18: status reply
        0x00,
        0x00,
        0x00,  # 19-21: editing phase, phase 0
        0x00,  # 22: no notification
        0x00,  # 23: expansion area
        0x01,
        0x08,  # 24-25: white tape, black text
        0x00,
        0x00,
        0x00,
        0x00,  # 26-29: hardware
        0x00,
        0x00,  # 30-31: reserved
    ]
)

# Synthetic QL-820NWB status block — same READY-on-12mm-continuous shape.
QL_READY_12MM_CONTINUOUS = bytes(
    [
        0x80,
        0x20,
        0x42,
        0x34,
        0x41,
        0x30,
        0x00,
        0x00,  # 0-7: header (QL-820NWB)
        0x00,
        0x00,  # 8-9: no errors
        0x0C,
        0x4A,  # 10-11: 12mm continuous
        0x00,
        0x00,
        0x3F,
        0x00,  # 12-15: QL fixes [14] = 0x3F
        0x00,
        0x00,  # 16-17: density / continuous
        0x00,  # 18: status reply
        0x00,
        0x00,
        0x00,  # 19-21: receiving phase
        0x00,  # 22: no notification
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,  # 23-30: reserved (8 bytes)
        0x00,  # 31: reserved
    ]
)


class TestSize:
    def test_rejects_too_short(self) -> None:
        with pytest.raises(StatusBlockError, match="32 bytes"):
            StatusBlockParser.parse(b"\x00" * 31)

    def test_rejects_too_long(self) -> None:
        with pytest.raises(StatusBlockError, match="32 bytes"):
            StatusBlockParser.parse(b"\x00" * 33)

    def test_accepts_exactly_32(self) -> None:
        # Bare zero block parses without raising — fields land at default enum values
        result = StatusBlockParser.parse(b"\x00" * 32)
        assert isinstance(result, StatusBlock)


class TestPtSeriesParsing:
    def test_decodes_header_fields(self) -> None:
        sb = StatusBlockParser.parse(PT_READY_12MM_WHITE_BLACK)
        assert sb.print_head_mark == 0x80
        assert sb.size == 0x20
        assert sb.brother_code == 0x42
        assert sb.series_code == 0x30
        assert sb.model_code == 0x68

    def test_decodes_media(self) -> None:
        sb = StatusBlockParser.parse(PT_READY_12MM_WHITE_BLACK)
        assert sb.media_width_mm == 12
        assert sb.media_type == MediaType.LAMINATED
        assert sb.media_length_mm == 0  # continuous

    def test_decodes_status_phase(self) -> None:
        sb = StatusBlockParser.parse(PT_READY_12MM_WHITE_BLACK)
        assert sb.status_type == StatusType.REPLY
        assert sb.phase_type == PhaseType.EDITING
        assert sb.phase_number == 0
        assert sb.notification == NotificationCode.NOT_AVAILABLE

    def test_decodes_colours(self) -> None:
        sb = StatusBlockParser.parse(PT_READY_12MM_WHITE_BLACK)
        assert sb.tape_color == TapeColor.WHITE
        assert sb.text_color == TextColor.BLACK

    def test_no_errors(self) -> None:
        sb = StatusBlockParser.parse(PT_READY_12MM_WHITE_BLACK)
        assert sb.errors == []
        assert sb.is_ready is True
        assert sb.is_printing is False


class TestQlSeriesParsing:
    def test_decodes_qlseries_codes(self) -> None:
        sb = StatusBlockParser.parse(QL_READY_12MM_CONTINUOUS)
        assert sb.series_code == 0x34
        assert sb.model_code == 0x41  # QL-820NWB

    def test_decodes_continuous_media(self) -> None:
        sb = StatusBlockParser.parse(QL_READY_12MM_CONTINUOUS)
        assert sb.media_width_mm == 12
        assert sb.media_type == MediaType.CONTINUOUS_LENGTH_TAPE

    def test_qlseries_has_no_tape_colour(self) -> None:
        sb = StatusBlockParser.parse(QL_READY_12MM_CONTINUOUS)
        # QL doesn't populate these — bytes should land on zero/unknown
        assert sb.tape_color in (TapeColor.UNKNOWN, TapeColor.WHITE) or sb.tape_color is None


class TestErrorFlags:
    def test_no_media_error(self) -> None:
        raw = bytearray(PT_READY_12MM_WHITE_BLACK)
        raw[8] = 0x01
        raw[10] = 0  # no media → width 0
        raw[18] = 0x02  # status type = error
        sb = StatusBlockParser.parse(bytes(raw))
        assert PrinterError.NO_MEDIA in sb.errors
        assert sb.media_width_mm == 0
        assert sb.status_type == StatusType.ERROR
        assert sb.is_ready is False

    def test_cover_open_error(self) -> None:
        raw = bytearray(PT_READY_12MM_WHITE_BLACK)
        raw[9] = 0x10
        raw[18] = 0x02
        sb = StatusBlockParser.parse(bytes(raw))
        assert PrinterError.COVER_OPEN in sb.errors

    def test_cutter_jam_error(self) -> None:
        raw = bytearray(PT_READY_12MM_WHITE_BLACK)
        raw[8] = 0x04
        raw[18] = 0x02
        sb = StatusBlockParser.parse(bytes(raw))
        assert PrinterError.CUTTER_JAM in sb.errors

    def test_overheating_error(self) -> None:
        raw = bytearray(PT_READY_12MM_WHITE_BLACK)
        raw[9] = 0x20
        raw[18] = 0x02
        sb = StatusBlockParser.parse(bytes(raw))
        assert PrinterError.OVERHEATING in sb.errors

    def test_multiple_errors(self) -> None:
        raw = bytearray(PT_READY_12MM_WHITE_BLACK)
        raw[8] = 0x09  # NO_MEDIA + WEAK_BATTERIES (0x01 | 0x08)
        raw[9] = 0x10  # COVER_OPEN
        raw[18] = 0x02
        sb = StatusBlockParser.parse(bytes(raw))
        assert PrinterError.NO_MEDIA in sb.errors
        assert PrinterError.WEAK_BATTERIES in sb.errors
        assert PrinterError.COVER_OPEN in sb.errors


class TestPhaseTransitions:
    def test_printing_phase(self) -> None:
        raw = bytearray(PT_READY_12MM_WHITE_BLACK)
        raw[18] = 0x06  # phase change
        raw[19] = 0x01  # printing phase
        sb = StatusBlockParser.parse(bytes(raw))
        assert sb.status_type == StatusType.PHASE_CHANGE
        assert sb.phase_type == PhaseType.PRINTING
        assert sb.is_printing is True
        assert sb.is_ready is False

    def test_print_complete(self) -> None:
        raw = bytearray(PT_READY_12MM_WHITE_BLACK)
        raw[18] = 0x01
        sb = StatusBlockParser.parse(bytes(raw))
        assert sb.status_type == StatusType.PRINTING_COMPLETED

    def test_phase_number_decoded_big_endian(self) -> None:
        # PT spec: cover-open-while-receiving = phase 20 → 0x00 0x14
        raw = bytearray(PT_READY_12MM_WHITE_BLACK)
        raw[18] = 0x06
        raw[19] = 0x01
        raw[20] = 0x00
        raw[21] = 0x14
        sb = StatusBlockParser.parse(bytes(raw))
        assert sb.phase_number == 20


class TestUnknownEnums:
    """Unknown values fall back to safe defaults rather than raising."""

    def test_unknown_media_type(self) -> None:
        raw = bytearray(PT_READY_12MM_WHITE_BLACK)
        raw[11] = 0x99  # not in spec
        sb = StatusBlockParser.parse(bytes(raw))
        assert sb.media_type == MediaType.UNKNOWN

    def test_unknown_status_type(self) -> None:
        raw = bytearray(PT_READY_12MM_WHITE_BLACK)
        raw[18] = 0x99
        sb = StatusBlockParser.parse(bytes(raw))
        assert sb.status_type == StatusType.UNKNOWN

    def test_incompatible_media_explicitly_supported(self) -> None:
        raw = bytearray(PT_READY_12MM_WHITE_BLACK)
        raw[11] = 0xFF
        sb = StatusBlockParser.parse(bytes(raw))
        assert sb.media_type == MediaType.INCOMPATIBLE


class TestRoundtrip:
    def test_raw_bytes_preserved(self) -> None:
        sb = StatusBlockParser.parse(PT_READY_12MM_WHITE_BLACK)
        assert sb.raw == PT_READY_12MM_WHITE_BLACK

    def test_dataclass_is_frozen(self) -> None:
        sb = StatusBlockParser.parse(PT_READY_12MM_WHITE_BLACK)
        with pytest.raises((AttributeError, Exception)):  # FrozenInstanceError or similar
            sb.media_width_mm = 99  # type: ignore[misc]
