# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""PTouchBackend — wraps the `ptouch` Python library for Brother PT-Series.

Status queries go through query_status_over_socket (the library does not
expose them). Print calls go through ptouch.LabelPrinter.print() inside
asyncio.to_thread (the library is synchronous). All ptouch exceptions are
caught and rewrapped as our PrinterError subtypes.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import ptouch
from PIL import Image

if TYPE_CHECKING:
    import httpx

from app.models.tape import TapeSpec
from app.printer_backends.exceptions import (
    PrinterError,
    PrinterOfflineError,
    PrintFailedError,
    SnmpQueryError,
    TapeMismatchError,
    refused_before_sending,
)
from app.printer_backends.post_send import raise_for_error_flags
from app.printer_backends.snmp_helper import PreflightStatus, query_preflight, roll_record
from app.printer_backends.status_query import query_status_over_socket
from app.printer_backends.tape_confirmation import (
    TapeIppTransport,
    TapeSendState,
    check_label_lengths,
    label_length_mm,
)
from app.services.status_block import StatusBlock

_logger = logging.getLogger(__name__)

PT_DPI = 180
"""The resolution the hub renders P-touch labels at (``printer_models/pt.py``: 180 dpi); a
high-resolution print doubles the dots, not the length."""

_RETRY_BACKOFFS: tuple[float, ...] = (0.0, 1.0, 2.0)

_PTOUCH_PRINTER_CLASSES: dict[str, type] = {
    "PT-P750W": ptouch.PTP750W,
    "PT-E550W": ptouch.PTE550W,
    "PT-P900": ptouch.PTP900,
    "PT-P900W": ptouch.PTP900W,
    "PT-P910BT": ptouch.PTP910BT,
    "PT-P950NW": ptouch.PTP950NW,
}

_PTOUCH_TAPE_CLASSES: dict[int, type] = {
    4: ptouch.Tape3_5mm,  # 3.5mm tape — closest match for "4mm" lookups
    6: ptouch.Tape6mm,
    9: ptouch.Tape9mm,
    12: ptouch.Tape12mm,
    18: ptouch.Tape18mm,
    24: ptouch.Tape24mm,
    36: ptouch.Tape36mm,
}


def _ptouch_print(  # pragma: no cover - real-hardware-only, tests monkeypatch this
    host: str,
    port: int,
    image: Image.Image,
    tape_mm: int,
    *,
    model_id: str,
    auto_cut: bool,
    high_resolution: bool,
    half_cut: bool = False,
    last_page: bool = True,
    connection: Any = None,
) -> None:
    """Synchronous helper — module-level so tests can monkeypatch it.

    *connection* (#393): where the bytes go; ``None`` is TCP to *host*:*port*. The IPP path
    passes a ``_CaptureConnection`` and sends what it collected.

    Model-aware: uses _PTOUCH_PRINTER_CLASSES[model_id] so the same code
    serves PT-P750W, PT-P900, PT-E550W, etc.

    last_page maps to ptouch-py LabelPrinter.print(feed=last_page):
      - feed=True  (last_page=True, default)  → voller Tape-Feed (~22.5mm Pre-Roll)
      - feed=False (last_page=False)           → minimaler Feed (~5mm) für Batch-Items

    Excluded from coverage: the function only runs against the real ptouch
    library against actual hardware. Every unit test in
    `tests/unit/printer_backends/test_ptouch_backend.py` replaces it via
    monkeypatch on `app.printer_backends.ptouch_backend._ptouch_print`.
    Hardware verification lives in `tests/hardware/` and the manual
    `scripts/smoke_first_print.py`.
    """
    try:
        tape_cls = _PTOUCH_TAPE_CLASSES[tape_mm]
    except KeyError as exc:
        raise PrintFailedError(f"No ptouch tape class for {tape_mm}mm") from exc
    try:
        printer_cls = _PTOUCH_PRINTER_CLASSES[model_id]
    except KeyError as exc:
        raise PrintFailedError(f"No ptouch printer class for model {model_id!r}") from exc
    if connection is None:
        connection = ptouch.ConnectionNetwork(host, port=port, timeout=10.0)
    printer = printer_cls(connection=connection, high_resolution=high_resolution)
    label = ptouch.Label(image=image, tape=tape_cls)
    try:
        printer.print(
            label,
            auto_cut=auto_cut,
            high_resolution=high_resolution,
            half_cut=half_cut,
            feed=last_page,
        )
    except TypeError:
        # Älterer ptouch-Lib (<1.1) unterstützt weder half_cut NOCH feed: beide
        # werden im Fallback verworfen. half_cut → immer Voll-Cut; feed → immer
        # Default True (= 22.5mm Pre-Roll pro Print, kein 5mm-Batch-Half-Cut).
        # Phase 1i Batch-Half-Cut wird auf Legacy-ptouch stillschweigend zur
        # Pre-Phase-1i-Semantik degradiert. (Copilot PR #100)
        printer.print(label, auto_cut=auto_cut, high_resolution=high_resolution)


def _ptouch_print_multi(  # pragma: no cover - real-hardware-only, tests monkeypatch this
    host: str,
    port: int,
    images: list[Image.Image],
    tape_mm: int,
    *,
    model_id: str,
    auto_cut: bool,
    high_resolution: bool,
    half_cut: bool,
    connection: Any = None,
) -> None:
    """Synchronous helper for batch printing via ptouch.LabelPrinter.print_multi.

    *connection* (#393): as in ``_ptouch_print``.

    ptouch-py 1.1.0: LabelPrinter.print_multi(labels, margin_mm=None,
    high_resolution=None, half_cut=True) — 1 Connection, 1 Init (=1 Pre-Roll),
    5mm Half-Cut zwischen Labels, voller Cut am Ende.

    Excluded from coverage: real-hardware-only. Tests monkeypatch this module-level
    function. Hardware verification per scripts/smoke_first_print_batch.py (Task 11).
    """
    try:
        tape_cls = _PTOUCH_TAPE_CLASSES[tape_mm]
    except KeyError as exc:
        raise PrintFailedError(f"No ptouch tape class for {tape_mm}mm") from exc
    try:
        printer_cls = _PTOUCH_PRINTER_CLASSES[model_id]
    except KeyError as exc:
        raise PrintFailedError(f"No ptouch printer class for model {model_id!r}") from exc

    if connection is None:
        connection = ptouch.ConnectionNetwork(host, port=port, timeout=10.0)
    printer = printer_cls(connection=connection, high_resolution=high_resolution)
    labels = [ptouch.Label(image=img, tape=tape_cls) for img in images]
    try:
        printer.print_multi(
            labels,
            high_resolution=high_resolution,
            half_cut=half_cut,
        )
    except TypeError:
        # Älterer ptouch-Lib (<1.1) hat kein print_multi — Fallback: per-Item-Loop
        # mit print(). Degraded zu Phase-1i-Verhalten (22.5mm Pre-Roll pro Item).
        for i, label in enumerate(labels):
            is_last = i == len(labels) - 1
            try:
                printer.print(
                    label,
                    auto_cut=auto_cut,
                    high_resolution=high_resolution,
                    half_cut=half_cut and not is_last,
                    feed=is_last,
                )
            except TypeError:
                printer.print(label, auto_cut=auto_cut, high_resolution=high_resolution)


# The helpers as written, for ``_ptouch_render``: a test that replaces the network helpers keeps
# the real byte building of the IPP path.
_WRITE_ONE = _ptouch_print
_WRITE_MULTI = _ptouch_print_multi


class _CaptureConnection(ptouch.Connection):  # type: ignore[misc]
    """A ptouch connection that sends nothing and keeps every byte written (#393).

    ``ptouch`` builds the raster stream by writing to its connection (the initialisation in the
    printer's constructor, then each label). Collected here, the same bytes the 9100 path sends
    go out as one IPP Print-Job.
    """

    def __init__(self) -> None:
        self.buf = bytearray()

    def connect(self, printer: Any) -> None:  # noqa: ARG002
        return None

    def write(self, payload: bytes) -> None:
        self.buf += payload

    def close(self) -> None:
        return None


def _ptouch_render(
    images: list[Image.Image],
    tape_mm: int,
    *,
    model_id: str,
    auto_cut: bool,
    high_resolution: bool,
    half_cut: bool,
    last_page: bool = True,
    multi: bool,
) -> bytes:
    """The raster bytes ``_ptouch_print`` (one image) or ``_ptouch_print_multi`` would send."""
    capture = _CaptureConnection()
    if multi:
        _WRITE_MULTI(
            "",
            0,
            images,
            tape_mm,
            model_id=model_id,
            auto_cut=auto_cut,
            high_resolution=high_resolution,
            half_cut=half_cut,
            connection=capture,
        )
    else:
        _WRITE_ONE(
            "",
            0,
            images[0],
            tape_mm,
            model_id=model_id,
            auto_cut=auto_cut,
            high_resolution=high_resolution,
            half_cut=half_cut,
            last_page=last_page,
            connection=capture,
        )
    return bytes(capture.buf)


def _require_tape_class(tape_mm: int) -> None:
    """The check ``_ptouch_print_multi`` would fail on, made before anything is sent (#277)."""
    if tape_mm not in _PTOUCH_TAPE_CLASSES:
        raise PrintFailedError(f"No ptouch tape class for {tape_mm}mm")


class PTouchBackend:
    """PrinterBackend backed by the ptouch library."""

    backend_id = "ptouch"
    half_cut_supported: bool = True

    def __init__(
        self,
        host: str,
        *,
        port: int = 9100,
        model_id: str = "PT-P750W",
        community: str = "public",
        ipp_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not host:
            raise ValueError("PTouchBackend requires a non-empty host")
        if model_id not in _PTOUCH_PRINTER_CLASSES:
            raise ValueError(
                f"Unknown printer_model {model_id!r}; known: {sorted(_PTOUCH_PRINTER_CLASSES)}"
            )
        self.host = host
        self._port = port
        self._model_id = model_id
        # The stored SNMP community (#296): the preflight asks with it, like discovery does.
        self._community = community
        # #389: the status read right before the last send (``None``: none was read for it).
        self.last_send_status: PreflightStatus | None = None
        # #393: IPP or TCP 9100, the labels sent and the IPP jobs to confirm after sending.
        self.send_state = TapeSendState(host, TapeIppTransport(host, transport=ipp_transport))

    @classmethod
    def from_settings(cls, settings: Any) -> PTouchBackend:
        host = getattr(settings, "pt750w_host", "") or ""
        if not host:
            raise ValueError(
                "Empty pt750w_host with printer_backend=ptouch — "
                "set LABELYARD_PT750W_HOST to the printer's IP/hostname."
            )
        return cls(
            host=host,
            port=int(getattr(settings, "pt750w_port", 9100)),
            model_id=str(getattr(settings, "printer_model", "PT-P750W")),
        )

    async def query_status(self) -> StatusBlock:
        last_exc: Exception | None = None
        for delay in _RETRY_BACKOFFS:
            if delay:
                _logger.warning("retrying status query in %.1fs", delay)
                await asyncio.sleep(delay)
            try:
                return await query_status_over_socket(self.host, self._port, timeout_s=5.0)
            except PrinterOfflineError as exc:
                last_exc = exc
        assert last_exc is not None
        raise last_exc

    async def read_status(
        self,
        *,
        community: str | None = None,
        timeout_s: float = 3.0,
    ) -> PreflightStatus:
        """One SNMP read: hrPrinterStatus, error bitmap, loaded tape. Never refuses on a bit.

        ESC i S (used by query_status) is unreliable on PT-Series in idle state — SNMP runs in
        parallel on UDP/161 and returns reliably. Raises ``PrinterOfflineError`` when the
        printer does not answer.
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
            raise PrinterOfflineError(f"preflight SNMP failed: {exc}") from exc
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
        """SNMP-based preflight: ``read_status`` plus a refusal on every blocking error bit.

        Use this BEFORE submitting a print job to validate the printer is
        ready and the loaded tape matches the requested width.

        Raises:
            PrinterOfflineError: SNMP query failed (host unreachable or timeout)
            TapeEmptyError: hrPrinterDetectedErrorState has noPaper bit
            PrinterCoverOpenError: hrPrinterDetectedErrorState has doorOpen bit
            PrinterReportedError: any other bit of ``post_send.HARD_ERROR_FLAGS`` (#389)

        Does NOT raise TapeMismatchError — the caller compares
        `preflight.loaded_tape_mm` to the request's tape_mm and raises if
        needed. This keeps PTouchBackend agnostic of what's being printed.
        """
        preflight = await self.read_status(community=community, timeout_s=timeout_s)
        raise_for_error_flags(preflight.error_flags)
        return preflight

    async def _check_before_send(self, tape_spec: TapeSpec) -> None:
        """#389: one status read right before sending; kept for the check after sending and the
        job record. Refuses on a blocking bit or a different tape width."""
        status = await self.preflight_check()  # refuses on every blocking bit
        self.last_send_status = status
        if status.loaded_tape_mm != tape_spec.width_mm:
            raise TapeMismatchError(
                expected_mm=tape_spec.width_mm,
                loaded_mm=status.loaded_tape_mm,
            )

    @property
    def flags_before_send(self) -> frozenset[str]:
        """The error bits of the read before the last send (``post_send.check_after_send``)."""
        status = self.last_send_status
        return frozenset(status.error_flags) if status is not None else frozenset()

    def roll_at_send(self) -> dict[str, object] | None:
        """The tape the last send was checked against (#389), for the job record."""
        return roll_record(self.last_send_status)

    async def print_image(
        self,
        image: Image.Image,
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
        half_cut: bool = False,
        last_page: bool = True,
        detect_confirmation: bool = False,
    ) -> None:
        """Pre-print validation via SNMP, then dispatch ptouch.print.

        #393: the raster bytes go out as an IPP Print-Job when the printer takes them that way
        (``TapeSendState``), else over TCP 9100 as before; ``detect_confirmation`` (the test
        print) tries IPP and lets the check after sending store what works.

        Uses preflight_check() (SNMP-based, reliable on PT-P750W in idle)
        instead of the broken ESC i S query_status() path. preflight_check
        raises TapeEmptyError / PrinterCoverOpenError / PrinterOfflineError on
        detected issues. TapeMismatchError is raised here after comparing the
        loaded tape to the requested tape_spec.

        Phase 1i C-Fix:
        - half_cut: passed through to _ptouch_print (PT-Series supports it).
        - last_page: maps to ptouch-py feed= parameter.
            last_page=True  → feed=True  → voller Tape-Feed (~22.5mm Pre-Roll)
            last_page=False → feed=False → minimaler Feed (~5mm) zwischen Batch-Items
        """
        # SNMP preflight — replaces the broken ESC i S query_status path for
        # PT-Series. preflight_check raises TapeEmptyError / PrinterCoverOpenError
        # / PrinterOfflineError on detected issues.
        self.last_send_status = None
        length = label_length_mm(image, PT_DPI)
        check_label_lengths([length], tape_spec.max_length_mm)  # R26-2, before any SNMP
        try:
            await self._check_before_send(tape_spec)
        except PrinterError as exc:
            refused_before_sending(exc)  # #277: the preflight refused, nothing was sent
            raise

        self.send_state.begin(detect=detect_confirmation)

        async def raw() -> None:
            with _ptouch_errors():
                await asyncio.to_thread(
                    _ptouch_print,
                    self.host,
                    self._port,
                    image,
                    tape_spec.width_mm,
                    model_id=self._model_id,
                    auto_cut=auto_cut,
                    high_resolution=high_resolution,
                    half_cut=half_cut,
                    last_page=last_page,
                )

        data = b""
        if await self.send_state.use_ipp():
            data = await self._render(
                [image],
                tape_spec.width_mm,
                auto_cut=auto_cut,
                high_resolution=high_resolution,
                half_cut=half_cut,
                last_page=last_page,
                multi=False,
            )
        await self.send_state.send(data, 1, raw, length_mm=length)

    async def _render(
        self,
        images: list[Image.Image],
        tape_mm: int,
        *,
        auto_cut: bool,
        high_resolution: bool,
        half_cut: bool,
        last_page: bool = True,
        multi: bool,
    ) -> bytes:
        """#393: the raster bytes of the IPP path, built by ``ptouch`` without sending."""
        try:
            return await asyncio.to_thread(
                _ptouch_render,
                images,
                tape_mm,
                model_id=self._model_id,
                auto_cut=auto_cut,
                high_resolution=high_resolution,
                half_cut=half_cut,
                last_page=last_page,
                multi=multi,
            )
        except PrinterError as exc:
            refused_before_sending(exc)  # nothing was sent
            raise

    async def print_images(
        self,
        images: list[Image.Image],
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
        half_cut: bool = True,
    ) -> None:
        """Batch-print via ptouch.LabelPrinter.print_multi — atomic.

        Pre-Print: SNMP preflight 1x am Batch-Anfang. Bei Tape-Mismatch wird
        TapeMismatchError sofort geworfen, kein print_multi-Call.

        Phase 1k.2: ersetzt N separate ptouch.print() Calls durch 1 print_multi.
        Resultat: 5mm Half-Cut zwischen Labels statt 22.5mm Pre-Roll.
        """
        if not images:
            raise ValueError("print_images requires at least one image")

        self.last_send_status = None
        lengths = [label_length_mm(image, PT_DPI) for image in images]
        check_label_lengths(lengths, tape_spec.max_length_mm)  # R26-2: the whole batch or none
        try:
            _require_tape_class(tape_spec.width_mm)
            await self._check_before_send(tape_spec)
        except PrinterError as exc:
            # #277: refused before sending (no tape class, or the preflight said no): nothing
            # was sent, the labels did not print.
            refused_before_sending(exc)
            raise

        self.send_state.begin()

        async def raw() -> None:
            with _ptouch_errors():
                await asyncio.to_thread(
                    _ptouch_print_multi,
                    self.host,
                    self._port,
                    images,
                    tape_spec.width_mm,
                    model_id=self._model_id,
                    auto_cut=auto_cut,
                    high_resolution=high_resolution,
                    half_cut=half_cut,
                )

        data = b""
        if await self.send_state.use_ipp():
            data = await self._render(
                images,
                tape_spec.width_mm,
                auto_cut=auto_cut,
                high_resolution=high_resolution,
                half_cut=half_cut,
                multi=True,
            )
        await self.send_state.send(data, len(images), raw, length_mm=sum(lengths))


@contextlib.contextmanager
def _ptouch_errors() -> Iterator[None]:
    """The ptouch connection errors as the hub's printer errors."""
    try:
        yield
    except (ptouch.PrinterWriteError, ptouch.PrinterPermissionError) as exc:
        # These are subclasses of PrinterConnectionError — must be caught first.
        raise PrintFailedError(str(exc)) from exc
    except (
        ptouch.PrinterNetworkError,
        ptouch.PrinterTimeoutError,
        ptouch.PrinterNotFoundError,
        ptouch.PrinterConnectionError,
    ) as exc:
        raise PrinterOfflineError(str(exc)) from exc
