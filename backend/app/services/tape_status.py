# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The one status-cache schema for tape printers, and its only reader (#229).

``StatusProbeProducer`` writes it, the status, tape and capabilities routes read it through
:func:`read_tape_status`. Nothing else interprets the ``parsed`` dict of a tape row.

The printer reports no tape colour over the network (probed on a PT-P750W and a QL-820NWB), so
the schema has no colour keys; the colour comes from the operator's roll record.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypedDict

from app.schemas.tape import TapeColourName

__all__ = ["TapeColourName", "TapeStatusParsed", "read_tape_status"]


class TapeStatusParsed(TypedDict, total=False):
    """What a tape printer's cache row holds. Absent keys were never written or were malformed."""

    online: bool
    loaded_tape_mm: int | None
    # The trimmed media name text of ``prtInputMediaName`` (e.g. ``12mm(0.47")``).
    media_raw: str | None
    hr_printer_status: str
    error_flags: list[str]
    last_error: str


def read_tape_status(parsed: Mapping[str, Any]) -> TapeStatusParsed:
    """Validate a cache row's ``parsed`` dict; unknown or malformed keys are left out.

    A width of ``0`` or less is "no tape" (``None``); a blank ``media_raw`` is ``None``.
    """
    out: TapeStatusParsed = {}
    online = parsed.get("online")
    if isinstance(online, bool):
        out["online"] = online
    width = parsed.get("loaded_tape_mm", ...)
    if width is None or (isinstance(width, int) and not isinstance(width, bool)):
        out["loaded_tape_mm"] = width if width and width > 0 else None
    media_raw = parsed.get("media_raw")
    if isinstance(media_raw, str):
        out["media_raw"] = media_raw.strip() or None
    hr = parsed.get("hr_printer_status")
    if isinstance(hr, str):
        out["hr_printer_status"] = hr
    flags = parsed.get("error_flags")
    if isinstance(flags, list):
        out["error_flags"] = [f for f in flags if isinstance(f, str)]
    last_error = parsed.get("last_error")
    if isinstance(last_error, str):
        out["last_error"] = last_error
    return out
