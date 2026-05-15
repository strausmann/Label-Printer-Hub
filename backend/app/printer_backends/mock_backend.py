"""In-memory PrinterBackend used by tests and local development.

Satisfies the PrinterBackend Protocol without touching the network. Failure
modes are configurable via the constructor so integration tests can drive
every error path (offline, tape empty, cover open, tape mismatch).
"""

from __future__ import annotations

from typing import Any

from PIL import Image

from app.models.tape import TapeSpec
from app.printer_backends.exceptions import (
    PrinterCoverOpenError,
    PrinterOfflineError,
    TapeEmptyError,
    TapeMismatchError,
)
from app.printer_backends.snmp_helper import PreflightStatus
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


def _neutral_status_block(
    *,
    loaded_tape_mm: int,
    media_type: MediaType,
    tape_empty: bool,
    cover_open: bool,
) -> StatusBlock:
    errors = PrinterError.NONE
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


class MockPrinterBackend:
    """No-I/O PrinterBackend for tests + local dev.

    Construct with failure-mode flags to exercise error paths. Use
    ``printed_images`` to assert what was actually sent.
    """

    backend_id = "mock"

    def __init__(
        self,
        host: str = "mock://test",
        *,
        loaded_tape_mm: int = 24,
        loaded_media_type: MediaType = MediaType.LAMINATED,
        tape_empty: bool = False,
        cover_open: bool = False,
        offline: bool = False,
    ) -> None:
        self.host = host
        self._loaded_tape_mm = loaded_tape_mm
        self._loaded_media_type = loaded_media_type
        self._tape_empty = tape_empty
        self._cover_open = cover_open
        self._offline = offline
        self.printed_images: list[Image.Image] = []
        self.status_query_count: int = 0

    @classmethod
    def from_settings(cls, settings: Any) -> MockPrinterBackend:  # noqa: ARG003
        """Settings are ignored — mock is environment-agnostic."""
        return cls()

    async def query_status(self) -> StatusBlock:
        self.status_query_count += 1
        if self._offline:
            raise PrinterOfflineError(f"mock backend marked offline at {self.host!r}")
        return _neutral_status_block(
            loaded_tape_mm=self._loaded_tape_mm,
            media_type=self._loaded_media_type,
            tape_empty=self._tape_empty,
            cover_open=self._cover_open,
        )

    async def preflight_check(self) -> PreflightStatus:
        """Mock SNMP preflight — raises the same errors as PTouchBackend."""
        if self._offline:
            raise PrinterOfflineError(f"mock backend marked offline at {self.host!r}")
        error_flags: list[str] = []
        if self._tape_empty:
            error_flags.append("noPaper")
        if self._cover_open:
            error_flags.append("doorOpen")
        if self._tape_empty:
            raise TapeEmptyError()
        if self._cover_open:
            raise PrinterCoverOpenError()
        return PreflightStatus(
            hr_printer_status="idle",
            loaded_tape_mm=self._loaded_tape_mm,
            error_flags=error_flags,
        )

    async def print_image(
        self,
        image: Image.Image,
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,  # noqa: ARG002
        high_resolution: bool = False,  # noqa: ARG002
    ) -> None:
        status = await self.query_status()
        if status.tape_empty:
            raise TapeEmptyError()
        if status.cover_open:
            raise PrinterCoverOpenError()
        if status.loaded_tape_mm != tape_spec.width_mm:
            raise TapeMismatchError(
                expected_mm=tape_spec.width_mm,
                loaded_mm=status.loaded_tape_mm,
            )
        self.printed_images.append(image.copy())
