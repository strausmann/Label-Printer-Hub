# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""One text layout engine for every TrueType font Labelyard loads.

Pillow picks its layout engine per machine: ``RAQM`` when libraqm and libfribidi are
installed, ``BASIC`` otherwise. The same label would then measure and wrap differently
on a developer machine, on the CI runner and in the container.

Engine check (``features.check("raqm")``, 2026-11-20):

- ``ghcr.io/strausmann/labelyard:1.7.0``: ``False``. The runtime stage installs no
  ``libfribidi``, so the image lays text out with ``BASIC``.
- local venv: ``True`` (RAQM).

``PINNED_LAYOUT`` is the image's engine, so what is tested is what ships. The CI runner's
engine is recorded by ``tests/unit/services/test_fonts.py``.

The spool swatch loads its own variable font with ``BASIC`` and is out of scope.
"""

from __future__ import annotations

from typing import Final

from PIL import ImageFont

PINNED_LAYOUT: Final = ImageFont.Layout.BASIC


def load_truetype(path: str, size: float) -> ImageFont.FreeTypeFont:
    """``ImageFont.truetype`` with the pinned layout engine."""
    return ImageFont.truetype(path, size, layout_engine=PINNED_LAYOUT)
