# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Phase 1i Sub-Task G: BrotherQLBackend.

C1-Fix: brother_ql v0.9.4 API (convert + helpers.send).
C8-Fix: model bleibt "QL-820NWB" (library kennt kein "c"-Suffix).
M6-Fix: red=False für Monochrome auf two_color=True Library-Modellen.
R3-Zusatz: helpers.send ist synchron mit blocking=True -> asyncio.to_thread wrapping.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

# Must run before brother_ql is used: restores Image.ANTIALIAS (removed in Pillow 10),
# which brother_ql 0.9.x calls in its resize branch. See _pillow_compat and issue #254.
from app.printer_backends import _pillow_compat  # noqa: F401  # isort: skip
from brother_ql.backends.helpers import (
    send as _helpers_send,
)
from brother_ql.conversion import convert
from brother_ql.labels import ALL_LABELS
from brother_ql.raster import BrotherQLRaster
from PIL import Image

if TYPE_CHECKING:
    import httpx

from app.models.tape import TapeSpec
from app.printer_backends.batch_helper import default_print_images_loop
from app.printer_backends.exceptions import (
    MediaTypeMismatchError,
    NoTapeLoadedError,
    PrinterError,
    PrinterOfflineError,
    PrintFailedError,
    TapeMismatchError,
    refused_before_sending,
)
from app.printer_backends.post_send import raise_for_error_flags
from app.printer_backends.snmp_helper import (
    PreflightStatus,
    SnmpQueryError,
    query_preflight,
    roll_record,
)
from app.printer_backends.tape_confirmation import (
    TapeIppTransport,
    TapeSendState,
    check_label_lengths,
    label_length_mm,
)
from app.schemas.label_layout import LabelOrientation
from app.services.status_block import StatusBlock

_logger = logging.getLogger(__name__)

# Mapping from tape width (mm) to brother_ql label identifier string.
# Only endless (continuous-length) DK labels are listed here; die-cut
# label support can be added in a future phase.
_TAPE_MM_TO_QL_LABEL: dict[int, str] = {
    12: "12",
    29: "29",
    38: "38",
    50: "50",
    54: "54",
    62: "62",
}


def _fit_to_printable_width(
    image: Image.Image,
    ql_label: str,
    *,
    dpi_600: bool,
    orientation: LabelOrientation | None = None,
) -> Image.Image:
    """Prepare *image* so ``brother_ql.convert`` never has to resize it (issues #254, #258).

    ``convert`` wants, for endless labels, an image whose *width* equals the label's
    ``dots_printable[0]`` (rows span the tape; the image grows along the feed direction).

    1. Orientation (#258): the renderer says how the image is laid out.
       - ``across``: the image is already in convert's orientation (rows span the tape) and
         is never rotated.
       - ``along``: the image is a landscape band (PT convention: height = band across the
         tape, width = label length) and is always rotated 90 degrees clockwise, so the left
         edge (start of text) becomes row 0 and is printed first.
       - no flag (an image from a caller that predates #258): the 1.4.1 size heuristic stays
         as a safety net. An image whose height does not exceed the printable width is taken
         as a band and rotated; one whose width already equals the printable width is taken
         as ready-made. The heuristic is ambiguous for images narrower than the tape (a
         500x300 across image on 62 mm would be rotated by mistake), hence the flag.
    2. An image narrower than the printable width is centred on white padding, never
       stretched.
    3. With ``dpi_600`` convert halves the width again before checking it, so the 300 dpi
       source is doubled on both axes (same physical size, printed at 600 dpi).

    Anything still wider than the printable width is left alone: convert's own resize
    fallback handles (and logs) it.
    """
    matches = [x for x in ALL_LABELS if x.identifier == ql_label]
    if not matches:
        return image
    printable = int(matches[0].dots_printable[0])

    if image.mode not in ("1", "L", "RGB", "RGBA"):
        image = image.convert("RGB")
    if orientation is None:
        rotate = image.height <= printable and image.width != printable
    else:
        rotate = orientation is LabelOrientation.ALONG
    if rotate:
        image = image.transpose(Image.Transpose.ROTATE_270)
    if image.width < printable:
        padded = Image.new(image.mode, (printable, image.height), (255,) * len(image.mode))
        padded.paste(image, ((printable - image.width) // 2, 0))
        image = padded
    if dpi_600:
        image = image.resize((image.width * 2, image.height * 2), Image.Resampling.NEAREST)
    return image


def _ql_dpi(high_resolution: bool) -> int:
    """The resolution of a fitted QL raster image along the tape (R26-2): 300 dpi, doubled for a
    600 dpi print (``_fit_to_printable_width`` doubles both axes)."""
    return 600 if high_resolution else 300


def _ql_label_of(tape_spec: TapeSpec) -> str:
    """The brother_ql label identifier of the tape; a width without one is refused before
    anything is sent (#277)."""
    try:
        return _TAPE_MM_TO_QL_LABEL[tape_spec.width_mm]
    except KeyError as exc:
        raise refused_before_sending(
            PrintFailedError(
                f"No QL label mapping for {tape_spec.width_mm}mm — "
                f"supported widths: {sorted(_TAPE_MM_TO_QL_LABEL)}"
            )
        ) from exc


class BrotherQLBackend:
    """PrinterBackend backed by the brother_ql library (v0.9.x).

    Wraps the synchronous ``brother_ql.backends.helpers.send`` in
    ``asyncio.to_thread`` so the async caller is not blocked.
    """

    backend_id = "brother_ql"
    half_cut_supported: bool = False

    def __init__(
        self,
        host: str,
        *,
        port: int = 9100,
        model_id: str = "QL-820NWB",
        community: str = "public",
        ipp_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not host:
            raise ValueError("BrotherQLBackend requires a non-empty host")
        self.host = host
        self._port = port
        self._model_id = model_id
        # The stored SNMP community (#296): the preflight asks with it, like discovery does.
        self._community = community
        self._identifier = f"tcp://{host}:{port}"
        # #389: the status read right before the last send (``None``: none was read for it).
        self.last_send_status: PreflightStatus | None = None
        # #393: IPP or TCP 9100, the labels sent and the IPP jobs to confirm after sending.
        self.send_state = TapeSendState(host, TapeIppTransport(host, transport=ipp_transport))

    def check_label_lengths(
        self,
        images: list[Image.Image],
        tape_spec: TapeSpec,
        *,
        high_resolution: bool = False,
        orientation: LabelOrientation | None = None,
        **_options: Any,
    ) -> list[float]:
        """The tape length of each label as it would be sent (fitted to the roll); raises
        ``TapeLabelTooLongError`` (``nothing_sent``) for one longer than the tape allows
        (R26-2). The print service calls it when a job is submitted, the send checks again."""
        ql_label = _ql_label_of(tape_spec)
        lengths = [
            label_length_mm(
                _fit_to_printable_width(
                    image, ql_label, dpi_600=high_resolution, orientation=orientation
                ),
                _ql_dpi(high_resolution),
            )
            for image in images
        ]
        check_label_lengths(lengths, tape_spec.max_length_mm)
        return lengths

    async def print_image(
        self,
        image: Image.Image,
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
        half_cut: bool = False,
        last_page: bool = True,  # noqa: ARG002
        orientation: LabelOrientation | None = None,
        media_checked: bool = False,
        detect_confirmation: bool = False,
    ) -> None:
        """Check the loaded roll, convert *image* to QL raster data and send it to the printer.

        #389: before anything is sent, one SNMP preflight checks that the loaded roll is the
        one the image was drawn for (``TapeMismatchError``) and is not die-cut
        (``MediaTypeMismatchError``); both are refusals before sending. ``media_checked`` skips
        the check when the caller (``print_images``) made it for the whole batch already.

        ``half_cut`` is silently ignored with a WARNING — QL-Series hardware
        does not support half-cut (PT-Series only).
        ``high_resolution`` is passed through as ``dpi_600`` to ``convert``.
        ``last_page`` is accepted for protocol compatibility but has no effect
        on the QL wire format (cut is controlled by the ``cut`` kwarg in
        ``convert``).
        ``orientation`` (#258) decides the rotation: ``along`` rotates, ``across`` never
        does, ``None`` falls back to the 1.4.1 size heuristic.

        #393: the raster bytes go out as an IPP Print-Job when the printer takes them that way
        (``TapeSendState``), else over TCP 9100 as before. ``detect_confirmation`` (the test
        print) tries IPP and lets the check after sending store what works.
        """
        if half_cut:
            _logger.warning(
                "BrotherQLBackend(host=%s): half_cut=True requested but QL-Series "
                "does not support half-cut — ignoring (using full-cut only).",
                self.host,
            )

        if not media_checked:
            self.last_send_status = None
        ql_label = _ql_label_of(tape_spec)
        image = _fit_to_printable_width(
            image, ql_label, dpi_600=high_resolution, orientation=orientation
        )
        length = label_length_mm(image, _ql_dpi(high_resolution))
        check_label_lengths([length], tape_spec.max_length_mm)  # R26-2, before any SNMP
        if not media_checked:
            if detect_confirmation:
                self.send_state.reset_counter_gate()  # R3-2: the read below asks for the counter
            await self._check_loaded_media(tape_spec)
            self.send_state.begin(detect=detect_confirmation)

        # Build raster instructions. convert() populates qlr.data.
        # M6-Fix: red=False for monochrome; two_color capable models (QL-820NWB)
        # accept this without error — they only require red=False not to raise.
        qlr = BrotherQLRaster(self._model_id)
        convert(
            qlr,
            [image],
            ql_label,
            cut=auto_cut,
            red=False,
            dpi_600=high_resolution,
        )

        await self.send_state.send(
            qlr.data,
            1,
            lambda: self._send_raw(qlr.data),
            length_mm=length,
        )

    async def _send_raw(self, data: bytes) -> None:
        """Send *data* over TCP 9100 (``brother_ql.backends.helpers.send``), as before #393."""
        # _helpers_send is synchronous and performs blocking I/O.
        # Wrap in to_thread to avoid blocking the event loop.
        result = await asyncio.to_thread(
            _helpers_send,
            data,
            self._identifier,
            blocking=True,
        )
        # #389: brother_ql 0.9.4 reads nothing back over the network backend (``outcome`` stays
        # ``sent``); a backend that does read back reports ``error``. The queue's status check
        # after sending covers the network case.
        if isinstance(result, dict) and result.get("outcome") == "error":
            raise PrintFailedError("The printer reported an error while printing")

    async def _check_loaded_media(self, tape_spec: TapeSpec) -> None:
        """One status read right before sending: no blocking error bit, a roll is loaded, it is
        continuous and of ``tape_spec``'s width.

        The read is kept (``last_send_status``, ``flags_before_send``): the check after sending
        counts only bits that are new, and the job records the roll it was sent to. Every error
        is a refusal before sending (#277): nothing of the job reached the printer.
        """
        try:
            status = await self.preflight_check()  # refuses on every blocking bit
            self.last_send_status = status
            if status.loaded_tape_mm is None:
                raise NoTapeLoadedError()
            if status.media_kind == "die_cut":
                raise MediaTypeMismatchError(loaded_kind="die_cut", media_raw=status.media_raw)
            if status.loaded_tape_mm != tape_spec.width_mm:
                raise TapeMismatchError(
                    expected_mm=tape_spec.width_mm, loaded_mm=status.loaded_tape_mm
                )
        except PrinterError as exc:
            refused_before_sending(exc)
            raise

    @property
    def flags_before_send(self) -> frozenset[str]:
        """The error bits of the read before the last send (``post_send.check_after_send``)."""
        status = self.last_send_status
        return frozenset(status.error_flags) if status is not None else frozenset()

    def roll_at_send(self) -> dict[str, object] | None:
        """The roll the last send was checked against (#389), for the job record."""
        return roll_record(self.last_send_status)

    async def print_images(
        self,
        images: list[Image.Image],
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
        half_cut: bool = True,  # noqa: ARG002
        orientation: LabelOrientation | None = None,
    ) -> None:
        """Batch-print N images via per-item Loop.

        brother_ql Lib hat kein print_multi-Equivalent — QL ist Endless-Tape,
        kein Half-Cut-Konzept zwischen Labels (jedes Label wird vom Druckkopf
        ausgegeben und manuell abgeschnitten). Delegiert an
        default_print_images_loop mit half_cut=False (QL ignoriert das Argument).
        ``orientation`` (#258) applies to every image of the batch.
        """
        # #389: one media check for the whole batch, not one per label (no probe storm).
        self.last_send_status = None
        ql_label = _ql_label_of(tape_spec)
        fitted = [
            _fit_to_printable_width(
                image, ql_label, dpi_600=high_resolution, orientation=orientation
            )
            for image in images
        ]
        lengths = [label_length_mm(image, _ql_dpi(high_resolution)) for image in fitted]
        check_label_lengths(lengths, tape_spec.max_length_mm)  # R26-2: the whole batch or none
        await self._check_loaded_media(tape_spec)
        self.send_state.begin()
        if images and await self.send_state.use_ipp():
            # #393: one IPP job for the whole batch; the printer reports its impressions.
            qlr = BrotherQLRaster(self._model_id)
            convert(qlr, fitted, ql_label, cut=auto_cut, red=False, dpi_600=high_resolution)
            try:
                await self.send_state.send(
                    qlr.data,
                    len(images),
                    lambda: self._send_raw(qlr.data),
                    length_mm=sum(lengths),
                )
            except PrinterError as exc:
                exc.nothing_sent = False
                raise
            return
        # QL-Series: half_cut existiert nicht. Backend-Capability-Flag erzwingt False.
        await default_print_images_loop(
            self,
            images,
            tape_spec,
            auto_cut=auto_cut,
            high_resolution=high_resolution,
            half_cut=False,
            orientation=orientation,
            media_checked=True,
        )

    async def read_status(
        self,
        *,
        community: str | None = None,
        timeout_s: float = 3.0,
    ) -> PreflightStatus:
        """One SNMP read: hrPrinterStatus, error bitmap, loaded tape. Never refuses on a bit.

        QL-820NWB nutzt dieselbe Printer MIB wie PT-Series — query_preflight()
        funktioniert identisch auf beiden Gerätereihen.

        Raises ``PrinterOfflineError`` when the printer does not answer.
        """
        try:
            status = await query_preflight(
                self.host,
                community=self._community if community is None else community,
                timeout_s=timeout_s,
                # Only passed once it is off: older callers' fakes take no such argument.
                **({} if self.send_state.ask_counter() else {"ask_counter": False}),
            )
        except SnmpQueryError as exc:
            # Issue #105: query_preflight() kann bereits "preflight SNMP failed: …"
            # im SnmpQueryError enthalten — doppeltes Prefixen vermeiden.
            msg = str(exc)
            if not msg.startswith("preflight SNMP failed:"):
                msg = f"preflight SNMP failed: {msg}"
            raise PrinterOfflineError(msg) from exc
        # #393, R26-1: consecutive refusals stop asking for the label counter; an answer turns
        # it back on.
        await self.send_state.note_counter(
            refused=status.counter_refused, answered=status.marker_count is not None
        )
        return status

    async def preflight_check(
        self,
        *,
        community: str | None = None,
        timeout_s: float = 3.0,
    ) -> PreflightStatus:
        """``read_status`` plus a refusal on every blocking error bit (#389, ``post_send``).

        Raises:
            PrinterOfflineError: SNMP query failed (host unreachable or timeout)
            TapeEmptyError: hrPrinterDetectedErrorState has noPaper bit
            PrinterCoverOpenError: hrPrinterDetectedErrorState has doorOpen bit
            PrinterReportedError: any other bit of ``post_send.HARD_ERROR_FLAGS``

        Does NOT raise TapeMismatchError — caller compares loaded_tape_mm.
        """
        preflight = await self.read_status(community=community, timeout_s=timeout_s)
        raise_for_error_flags(preflight.error_flags)
        return preflight

    async def query_status(self) -> StatusBlock:
        """QL-Series uses SNMP-Probe via StatusProbeProducer, no synchronous path.

        Full implementation deferred to Phase 1j (SNMP status for QL-Series).
        """
        raise NotImplementedError(
            "BrotherQLBackend.query_status: QL-Series uses SNMP-Probe via "
            "StatusProbeProducer, no synchronous status path in Phase 1i."
        )
