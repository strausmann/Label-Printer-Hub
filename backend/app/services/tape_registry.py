"""Lookup of Brother tape specifications by physical width + media type.

Phase 1i Sub-Task G: QL-Series endless (continuous-length) DK tapes added.
Die-cut labels will be added once their byte-sequence reproducible fixtures
are in place — see docs/decisions/0004-plugin-architecture-for-printer-models.md.
"""

from __future__ import annotations

import dataclasses

from app.models.tape import TapeSpec
from app.printer_models.pt import PT_HS_2_1_TAPES, PT_TZE_TAPES
from app.printer_models.ql import QL_DK_ENDLESS_TAPES
from app.services.status_block import MediaType


class UnknownTapeError(Exception):
    """Raised when a (width_mm, media_type) combination has no registered spec."""


class TapeRegistry:
    @staticmethod
    def lookup_pt(width_mm: int, media_type: MediaType) -> TapeSpec:
        """Return the PT-Series tape spec for the given width + media type.

        Non-laminated TZe-N tapes share TZe laminated dimensions, so both
        MediaType.LAMINATED and MediaType.NON_LAMINATED resolve to the same
        PT_TZE_TAPES table. The returned spec always carries the queried
        media_type so callers see the media_type they asked for.
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
                if spec.media_type != media_type:
                    return dataclasses.replace(spec, media_type=media_type)
                return spec

        raise UnknownTapeError(
            f"No PT-Series tape spec for width={width_mm}mm, media={media_type.name}"
        )

    @staticmethod
    def lookup_ql(width_mm: int, media_type: MediaType) -> TapeSpec:
        """Return the QL-Series tape spec for the given width + media type.

        Phase 1i: only CONTINUOUS_LENGTH_TAPE (endless DK) tapes are registered.
        DIE_CUT_LABEL support will be added in a future phase.
        """
        if media_type == MediaType.CONTINUOUS_LENGTH_TAPE:
            table = QL_DK_ENDLESS_TAPES
        else:
            raise UnknownTapeError(
                f"No QL-Series tape table for media_type={media_type.name} — "
                f"only CONTINUOUS_LENGTH_TAPE is supported in Phase 1i"
            )

        for spec in table:
            if spec.width_mm == width_mm:
                return spec

        raise UnknownTapeError(
            f"No QL-Series tape spec for width={width_mm}mm, media={media_type.name}"
        )
