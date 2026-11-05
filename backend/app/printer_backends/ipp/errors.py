"""Typed errors of the hub's own IPP client.

``IppDecodeError`` carries a stable, machine-readable ``reason`` so callers and
tests can tell which check rejected a message; the human-readable text never
contains printer-supplied bytes beyond lengths and offsets.
"""

from __future__ import annotations


class IppError(Exception):
    """Root of every IPP error raised by ``app.printer_backends.ipp``."""


class IppDecodeError(IppError):
    """Bytes received from a printer are not a well-formed, bounded IPP message."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


class IppEncodeError(IppError, ValueError):
    """A ``Message`` cannot be encoded (value out of range, length over 32767, bad tag)."""
