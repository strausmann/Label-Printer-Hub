# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Exception hierarchy raised by PrinterBackend implementations.

PrinterError is the root; HTTP-mapping is done in app.api.routes.print.
"""

from __future__ import annotations

from uuid import UUID


class PrinterError(Exception):
    """Base class for any backend / hardware failure.

    ``nothing_sent`` (#277): the backend refused before any byte of the job reached the
    printer (its own preflight said no). The print queue then knows the labels did not print;
    without the flag a failure may have happened while sending, and the outcome is unknown.
    """

    nothing_sent: bool = False


def refused_before_sending[E: PrinterError](exc: E) -> E:
    """Mark *exc* as raised before anything was sent (see ``PrinterError.nothing_sent``)."""
    exc.nothing_sent = True
    return exc


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


class UnsupportedTapeError(PrinterError):
    """Raised when the preflight-detected tape_mm is not in TAPE_GEOMETRY.

    Inherits from PrinterError to keep the exception hierarchy consistent:
    all hardware/tape precondition failures share the same base class and
    can be caught with a single ``except PrinterError`` if needed.

    HTTP-Status: 409 (Conflict) — same family as TapeEmptyError, CoverOpenError.
    The user must switch to a supported tape; retrying with the same loaded
    tape will fail again.

    Defensive: with 7 supported sizes (4/6/9/12/18/24/62mm) this should not
    occur in typical hardware setups (PT-Serie + QL-820NWB). Die bestehende
    TapeRegistry kennt zusätzliche QL-DK-Breiten (29/38/50/54mm), die in
    1k.1 bewusst noch nicht abgedeckt sind — Erweiterung als Folge-Phase
    möglich.
    """

    def __init__(self, *, tape_mm: int, orientation: str | None = None) -> None:
        self.tape_mm = tape_mm
        self.orientation = orientation
        if orientation is not None:
            # #258: the across-width layout exists for QL 62 mm only (other DK widths follow).
            super().__init__(
                f"The {orientation} layout is not available for {tape_mm}mm tape "
                f"(only for 62mm QL tape)."
            )
            return
        supported = (4, 6, 9, 12, 18, 24, 62)
        super().__init__(
            f"Tape width {tape_mm}mm is not supported by the layout engine. Supported: {supported}"
        )


class NoTapeLoadedError(PrinterError):
    """Raised when preflight returns loaded_tape_mm=None (no tape inserted).

    Inherits from PrinterError to keep the exception hierarchy consistent:
    all hardware/tape precondition failures share the same base class and
    can be caught with a single ``except PrinterError`` if needed.

    HTTP-Status: 409 (Conflict) — physical hardware state, retry needed
    after user inserts tape.
    """

    def __init__(self) -> None:
        super().__init__("No tape loaded — insert a Brother TZe or DK cartridge.")


class PrinterDisabledError(PrinterError):
    """Drucker existiert in DB, ist aber deaktiviert (Soft-Delete-Status).

    Mappt in der HTTP-Schicht auf 409 (nicht 404), weil der Drucker
    semantisch existiert — er ist nur vorübergehend nicht verwendbar.
    """

    def __init__(self, printer_id: UUID, slug: str) -> None:
        self.printer_id = printer_id
        self.slug = slug
        super().__init__(f"Printer {slug} ({printer_id}) is disabled")


class QrPayloadTooLongError(Exception):
    """The QR payload does not fit the fixed QR code of the tape and orientation (#258).

    The QR size is fixed per tape width so every label of a roll looks the same; a payload
    that does not fit is refused instead of shrinking the modules or growing the code.

    HTTP-Status: 422 (Unprocessable Entity) — the client must shorten the payload.
    """

    def __init__(self, *, length: int, max_bytes: int) -> None:
        self.length = length
        self.max_bytes = max_bytes
        super().__init__(
            f"QR payload of {length} bytes does not fit the fixed QR code of this tape "
            f"(at most {max_bytes} bytes)."
        )


class ConflictingOrientationError(Exception):
    """A batch names different explicit orientations for its items (#258).

    A batch prints with one orientation (the QL backend rotates every image on one flag), so
    items that ask for ``across`` and ``along`` cannot be honoured together.

    HTTP-Status: 422 (Unprocessable Entity) — split the batch or align the orientations.
    """

    def __init__(self, orientations: tuple[str, ...]) -> None:
        self.orientations = orientations
        super().__init__(
            f"Batch items ask for different orientations {list(orientations)}; "
            "a batch prints with one orientation."
        )


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
