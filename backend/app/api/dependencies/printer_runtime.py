# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The ``PrinterRuntime`` of the running hub, as a request dependency.

Overridable in tests with ``app.dependency_overrides[get_printer_runtime]``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from app.services.printer_runtime import PrinterRuntime


def get_printer_runtime(request: Request) -> PrinterRuntime | None:
    """``app.state.printer_runtime``, or ``None`` when the app runs without a lifespan.

    Without a runtime no status producer can exist, so callers treat every printer as unpolled.
    """
    runtime: PrinterRuntime | None = getattr(request.app.state, "printer_runtime", None)
    return runtime
