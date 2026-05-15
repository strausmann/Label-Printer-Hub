"""PTouchBackend — wraps the `ptouch` Python library for Brother PT-Series.

Status queries go through query_status_over_socket (the library does not
expose them). Print calls go through ptouch.LabelPrinter.print() inside
asyncio.to_thread (the library is synchronous). All ptouch exceptions are
caught and rewrapped as our PrinterError subtypes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import ptouch
from PIL import Image

from app.models.tape import TapeSpec
from app.printer_backends.exceptions import (
    PrinterCoverOpenError,
    PrinterOfflineError,
    PrintFailedError,
    TapeEmptyError,
    TapeMismatchError,
)
from app.printer_backends.status_query import query_status_over_socket
from app.services.status_block import StatusBlock

_logger = logging.getLogger(__name__)

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
    4: ptouch.LaminatedTape3_5mm,
    6: ptouch.LaminatedTape6mm,
    9: ptouch.LaminatedTape9mm,
    12: ptouch.LaminatedTape12mm,
    18: ptouch.LaminatedTape18mm,
    24: ptouch.LaminatedTape24mm,
    36: ptouch.LaminatedTape36mm,
}


def _ptouch_print(
    host: str,
    port: int,
    image: Image.Image,
    tape_mm: int,
    *,
    model_id: str,
    auto_cut: bool,
    high_resolution: bool,
) -> None:
    """Synchronous helper — module-level so tests can monkeypatch it.

    Model-aware: uses _PTOUCH_PRINTER_CLASSES[model_id] so the same code
    serves PT-P750W, PT-P900, PT-E550W, etc.
    """
    try:
        tape_cls = _PTOUCH_TAPE_CLASSES[tape_mm]
    except KeyError as exc:
        raise PrintFailedError(f"No ptouch tape class for {tape_mm}mm") from exc
    try:
        printer_cls = _PTOUCH_PRINTER_CLASSES[model_id]
    except KeyError as exc:
        raise PrintFailedError(f"No ptouch printer class for model {model_id!r}") from exc
    connection = ptouch.ConnectionNetwork(host, port=port, timeout=10.0)
    printer = printer_cls(connection=connection, high_resolution=high_resolution)
    label = ptouch.Label(image=image, tape=tape_cls)
    printer.print(label, auto_cut=auto_cut, high_resolution=high_resolution)


class PTouchBackend:
    """PrinterBackend backed by the ptouch library."""

    backend_id = "ptouch"

    def __init__(self, host: str, *, port: int = 9100, model_id: str = "PT-P750W") -> None:
        if not host:
            raise ValueError("PTouchBackend requires a non-empty host")
        if model_id not in _PTOUCH_PRINTER_CLASSES:
            raise ValueError(
                f"Unknown printer_model {model_id!r}; known: {sorted(_PTOUCH_PRINTER_CLASSES)}"
            )
        self.host = host
        self._port = port
        self._model_id = model_id

    @classmethod
    def from_settings(cls, settings: Any) -> PTouchBackend:
        host = getattr(settings, "pt750w_host", "") or ""
        if not host:
            raise ValueError(
                "Empty pt750w_host with printer_backend=ptouch — "
                "set PRINTER_HUB_PT750W_HOST to the printer's IP/hostname."
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

    async def print_image(
        self,
        image: Image.Image,
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
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

        try:
            await asyncio.to_thread(
                _ptouch_print,
                self.host,
                self._port,
                image,
                tape_spec.width_mm,
                model_id=self._model_id,
                auto_cut=auto_cut,
                high_resolution=high_resolution,
            )
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
