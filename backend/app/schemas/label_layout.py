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

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


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
