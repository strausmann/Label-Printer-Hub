"""Exception hierarchy raised by PrinterBackend implementations.

PrinterError is the root; HTTP-mapping is done in app.api.routes.print.
"""

from __future__ import annotations


class PrinterError(Exception):
    """Base class for any backend / hardware failure."""


class PrinterOfflineError(PrinterError):
    """Cannot reach the printer's TCP endpoint after retries."""


class TapeMismatchError(PrinterError):
    """Loaded tape width does not match the requested tape."""

    def __init__(self, *, expected_mm: int, loaded_mm: int | None) -> None:
        self.expected_mm = expected_mm
        self.loaded_mm = loaded_mm
        if loaded_mm is None:
            super().__init__(f"Expected {expected_mm}mm tape, no tape loaded")
        else:
            super().__init__(f"Expected {expected_mm}mm tape, loaded {loaded_mm}mm")


class TapeEmptyError(PrinterError):
    """Status block reports tape end / no media."""


class PrinterCoverOpenError(PrinterError):
    """Status block reports cover open."""


class PrintFailedError(PrinterError):
    """Encoding or transport failure during print()."""


class StatusQueryFailedError(PrinterError):
    """The 32-byte ESC i S reply could not be parsed."""


class SnmpDiscoveryError(PrinterError):
    """SNMP model-discovery query at lifespan startup failed."""


class SnmpQueryError(PrinterError):
    """Live-status SNMP query failed at request time. Non-fatal — the live
    block is omitted from the response.
    """
