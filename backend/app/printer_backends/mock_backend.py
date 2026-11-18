# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""In-memory PrinterBackend used by tests and local development.

Satisfies the PrinterBackend Protocol without touching the network. Failure
modes are configurable via the constructor so integration tests can drive
every error path (offline, tape empty, cover open, tape mismatch).
"""

from __future__ import annotations

from typing import Any

from PIL import Image

from app.models.tape import TapeSpec
from app.printer_backends.batch_helper import default_print_images_loop
from app.printer_backends.exceptions import (
    PrinterCoverOpenError,
    PrinterOfflineError,
    TapeEmptyError,
    TapeMismatchError,
    refused_before_sending,
)
from app.printer_backends.snmp_helper import PreflightStatus
from app.schemas.label_layout import LabelOrientation
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
    half_cut_supported: bool = False

    # #389: no hardware to wait for after sending (``post_send.check_after_send``).
    post_send_settle_s: float = 0.0

    def __init__(
        self,
        host: str = "mock://test",
        *,
        loaded_tape_mm: int = 24,
        loaded_media_type: MediaType = MediaType.LAMINATED,
        tape_empty: bool = False,
        cover_open: bool = False,
        offline: bool = False,
        tape_runs_out_after: int | None = None,
        label_counter: int | None = 0,
    ) -> None:
        self.host = host
        self._loaded_tape_mm = loaded_tape_mm
        self._loaded_media_type = loaded_media_type
        self._tape_empty = tape_empty
        self._cover_open = cover_open
        self._offline = offline
        # #277: the tape ends after this many printed labels; afterwards every print and every
        # preflight says the tape is empty (the SNMP ``noPaper`` bit).
        self.tape_runs_out_after = tape_runs_out_after
        self.printed_images: list[Image.Image] = []
        self.printed_orientations: list[LabelOrientation | None] = []
        """The ``orientation`` the queue passed for each printed image (#346)."""
        self.status_query_count: int = 0
        # #393: a fake ``prtMarkerLifeCount`` that rises with every printed label (``None``: the
        # printer reports no counter), the read before the last send and the labels sent since.
        self.label_counter: int | None = label_counter
        self.last_send_status: PreflightStatus | None = None
        self.labels_sent: int = 0
        self._in_batch = False

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

    async def read_status(self) -> PreflightStatus:
        """Mock SNMP read — the status with its error bits, never a refusal on a bit (#389).

        Like the real backends, the check after sending reads this, not ``preflight_check``.
        """
        if self._offline:
            raise PrinterOfflineError(f"mock backend marked offline at {self.host!r}")
        error_flags: list[str] = []
        if self._tape_empty:
            error_flags.append("noPaper")
        if self._cover_open:
            error_flags.append("doorOpen")
        return PreflightStatus(
            hr_printer_status="idle",
            loaded_tape_mm=self._loaded_tape_mm,
            error_flags=error_flags,
            marker_count=self.label_counter,
        )

    async def preflight_check(self) -> PreflightStatus:
        """Mock SNMP preflight — raises the same errors as PTouchBackend."""
        status = await self.read_status()
        if self._tape_empty:
            raise TapeEmptyError()
        if self._cover_open:
            raise PrinterCoverOpenError()
        return status

    async def print_image(
        self,
        image: Image.Image,
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,  # noqa: ARG002
        high_resolution: bool = False,  # noqa: ARG002
        half_cut: bool = False,  # noqa: ARG002
        last_page: bool = True,  # noqa: ARG002
        orientation: LabelOrientation | None = None,
        detect_confirmation: bool = False,  # noqa: ARG002 - the mock has nothing to detect
    ) -> None:
        # Like the PT backend's preflight: a refusal here means nothing was sent (#277).
        if not self._in_batch:
            await self._begin_send()
        status = await self.query_status()
        if status.tape_empty:
            raise refused_before_sending(TapeEmptyError())
        if status.cover_open:
            raise refused_before_sending(PrinterCoverOpenError())
        if status.loaded_tape_mm != tape_spec.width_mm:
            raise refused_before_sending(
                TapeMismatchError(
                    expected_mm=tape_spec.width_mm,
                    loaded_mm=status.loaded_tape_mm,
                )
            )
        self.printed_images.append(image.copy())
        self.printed_orientations.append(orientation)
        self.labels_sent += 1
        if self.label_counter is not None:
            self.label_counter += 1
        if (
            self.tape_runs_out_after is not None
            and len(self.printed_images) >= self.tape_runs_out_after
        ):
            self._tape_empty = True

    async def print_images(
        self,
        images: list[Image.Image],
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
        half_cut: bool = True,
        orientation: LabelOrientation | None = None,
    ) -> None:
        """Test-friendly Mock-Implementation via default_print_images_loop.

        Records each print_image call (because self.print_image is the existing
        Mock recording method). Phase 1k.2 Task 5: replaces NotImplementedError
        stub from Task 2 fix-up commit.
        """
        await self._begin_send()
        self._in_batch = True
        try:
            await default_print_images_loop(
                self,
                images,
                tape_spec,
                auto_cut=auto_cut,
                high_resolution=high_resolution,
                half_cut=half_cut,
                orientation=orientation,
            )
        finally:
            self._in_batch = False

    async def _begin_send(self) -> None:
        """#393: the read before sending (with the counter) and a fresh label count."""
        self.labels_sent = 0
        try:
            self.last_send_status = await self.read_status()
        except PrinterOfflineError:
            self.last_send_status = None
