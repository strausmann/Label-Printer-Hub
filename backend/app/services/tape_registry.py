"""Lookup of Brother tape specifications by physical width + media type.

QL-Series die-cut labels will be added once Phase 2 hardware tests confirm the
status-block byte sequence — see `docs/superpowers/plans/2026-05-11-label-printer-hub.md`.
"""

from __future__ import annotations

from app.services.status_block import MediaType
from app.services.tape_specs_pt import (
    PT_HS_2_1_TAPES,
    PT_TZE_TAPES,
    TapeSpec,
)


class UnknownTapeError(Exception):
    """Raised when a (width_mm, media_type) combination has no registered spec."""


class TapeRegistry:
    @staticmethod
    def lookup_pt(width_mm: int, media_type: MediaType) -> TapeSpec:
        """Return the PT-Series tape spec for the given width + media type.

        Non-laminated TZe-N tapes share TZe laminated dimensions, so both
        MediaType.LAMINATED and MediaType.NON_LAMINATED resolve to the same
        PT_TZE_TAPES table.
        """
        if media_type in (MediaType.LAMINATED, MediaType.NON_LAMINATED):
            table = PT_TZE_TAPES
        elif media_type == MediaType.HEAT_SHRINK_2_1:
            table = PT_HS_2_1_TAPES
        else:
            # MediaType.HEAT_SHRINK_3_1 and QL-Series types are intentionally
            # unregistered — add a new table and branch here when supported.
            raise UnknownTapeError(f"No PT-Series tape table for media_type={media_type.name}")

        for spec in table:
            if spec.width_mm == width_mm:
                return spec

        raise UnknownTapeError(
            f"No PT-Series tape spec for width={width_mm}mm, media={media_type.name}"
        )
