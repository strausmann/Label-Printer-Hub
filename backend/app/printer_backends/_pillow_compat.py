"""Pillow compatibility for the unmaintained ``brother_ql`` 0.9.x.

``brother_ql/conversion.py`` resizes mis-sized endless-label images with
``Image.ANTIALIAS``. Pillow 10 removed that constant (``Image.Resampling.LANCZOS`` is the
identical filter, which is what ``ANTIALIAS`` always aliased), so the call raises
``AttributeError`` and aborts the print (issue #254). Upstream ``brother_ql`` is unmaintained,
hence this alias. It is behaviour-neutral: it only fills in a name that no longer exists.
"""

from __future__ import annotations

from PIL import Image


def ensure_antialias_alias() -> None:
    """Define ``Image.ANTIALIAS`` as ``Image.Resampling.LANCZOS`` if Pillow dropped it."""
    if not hasattr(Image, "ANTIALIAS"):
        Image.ANTIALIAS = Image.Resampling.LANCZOS  # type: ignore[attr-defined]


ensure_antialias_alias()
