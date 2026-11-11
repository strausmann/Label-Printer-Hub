"""Label orientation and QL layout presets (#258).

``orientation`` says how the content runs on endless tape:

- ``across``: the text block sits beside a fixed-size QR code and runs across the tape
  width; the label length follows the content. Only defined for QL 62 mm DK endless tape.
- ``along``: the content runs along the tape (the PT convention and the 1.4.1 QL output);
  the band across the tape is the printable width and the label grows with the text.

``preset`` picks one of the three approved QL 62 mm across-width layouts. It has no effect
on ``along`` labels.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError


class LabelOrientation(StrEnum):
    """How the label content runs on endless tape."""

    ACROSS = "across"
    ALONG = "along"


class QlLayoutPreset(StrEnum):
    """The built-in QL 62 mm across-width layouts (``docs/design/ql-layout-presets``)."""

    COMPACT = "compact"
    """Preferred: 6 px modules, 2-module quiet zone along the feed, no layout margin."""

    SMALL_QR = "small_qr"
    """6 px modules, 4-module quiet zone along the feed, 0.5 mm layout margin."""

    STANDARD = "standard"
    """QR budget 42 % of the width (7 px modules), 4-module quiet zone, 2 mm margin."""


class LayoutDefault(BaseModel):
    """A stored layout default for one tape width of one printer.

    ``None`` fields fall back to the built-in default for the tape (62 mm: across, compact;
    every other width: along).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    orientation: LabelOrientation | None = None
    preset: QlLayoutPreset | None = None


ACROSS_TAPE_WIDTHS_MM: frozenset[int] = frozenset({62})
"""Tape widths with an across-width layout (#258); other DK widths follow later."""


MAX_LAYOUT_DEFAULTS: int = 16
"""Stored defaults per printer: more tape widths than any Brother tape family has."""
MAX_TAPE_WIDTH_MM: int = 62
"""Widest tape the hub supports (QL DK 62 mm)."""


def check_layout_defaults(value: dict[int, LayoutDefault]) -> dict[int, LayoutDefault]:
    """Validate stored defaults: at most 16 widths, each 1-62 mm; ``across`` and a preset
    exist for 62 mm only (review: the admin boundary bounds the stored JSON)."""
    if len(value) > MAX_LAYOUT_DEFAULTS:
        raise ValueError(f"at most {MAX_LAYOUT_DEFAULTS} tape widths, got {len(value)}")
    for width, default in value.items():
        if not 1 <= width <= MAX_TAPE_WIDTH_MM:
            raise ValueError(f"tape width must be 1-{MAX_TAPE_WIDTH_MM} mm, got {width}")
        if width in ACROSS_TAPE_WIDTHS_MM:
            continue
        if default.orientation is LabelOrientation.ACROSS:
            raise ValueError(f"the across layout is only available for 62 mm, not {width} mm")
        if default.preset is not None:
            raise ValueError(f"layout presets exist for 62 mm only, not {width} mm")
    return value


def parse_layout_defaults(raw: Mapping[str, Any] | None) -> dict[int, LayoutDefault]:
    """The stored JSON column (``{"62": {...}}``) as ``{62: LayoutDefault}``.

    Values were validated when they were written; an entry that no longer validates (e.g. a
    preset removed in a later release) is skipped, so the tape default applies instead.
    """
    out: dict[int, LayoutDefault] = {}
    for key, value in (raw or {}).items():
        try:
            out[int(key)] = LayoutDefault.model_validate(value)
        except (ValueError, TypeError, ValidationError):
            continue
    return out
