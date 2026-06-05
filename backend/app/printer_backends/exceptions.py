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


class UnsupportedTapeError(Exception):
    """Raised when the preflight-detected tape_mm is not in TAPE_GEOMETRY.

    HTTP-Status: 409 (Conflict) — same family as TapeEmptyError, CoverOpenError.
    The user must switch to a supported tape; retrying with the same loaded
    tape will fail again.

    Defensive: with 7 supported sizes (4/6/9/12/18/24/62mm) this should not
    occur in typical hardware setups (PT-Serie + QL-820NWB). Die bestehende
    TapeRegistry kennt zusätzliche QL-DK-Breiten (29/38/50/54mm), die in
    1k.1 bewusst noch nicht abgedeckt sind — Erweiterung als Folge-Phase
    möglich.
    """

    def __init__(self, *, tape_mm: int) -> None:
        self.tape_mm = tape_mm
        supported = (4, 6, 9, 12, 18, 24, 62)
        super().__init__(
            f"Tape width {tape_mm}mm is not supported by the layout engine. Supported: {supported}"
        )


class NoTapeLoadedError(Exception):
    """Raised when preflight returns loaded_tape_mm=None (no tape inserted).

    HTTP-Status: 409 (Conflict) — physical hardware state, retry needed
    after user inserts tape.
    """

    def __init__(self) -> None:
        super().__init__("No tape loaded — insert a Brother TZe or DK cartridge.")


class ContentTypeDataMismatchError(Exception):
    """Raised when LabelData lacks fields required by the chosen ContentType.

    HTTP-Status: 422 (Unprocessable Entity) — client can correct the
    request payload and retry without changing hardware state.
    """

    def __init__(
        self,
        *,
        content_type: str,
        missing_fields: tuple[str, ...],
    ) -> None:
        self.content_type = content_type
        self.missing_fields = missing_fields
        super().__init__(
            f"ContentType '{content_type}' requires fields {list(missing_fields)} "
            f"in LabelData — please populate them and retry."
        )
