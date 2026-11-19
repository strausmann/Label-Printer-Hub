# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The one bound on integration lookups that fan out from a single request (263-78, #285).

Tape batch prints and render checks look up many items per request. Their lookups together run
at most ``MAX_BATCH_LOOKUPS`` at once, whatever the number of requests. The single-item GET
lookup routes are not part of it: one request is one lookup there.
"""

from __future__ import annotations

import asyncio
import weakref

MAX_BATCH_LOOKUPS = 8
"""Integration lookups of fan-out requests that run at once, all requests together."""

_gates: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


def lookup_gate() -> asyncio.Semaphore:
    """The process-wide lookup bound. A semaphore belongs to one event loop, so there is one
    per running loop (exactly one in production)."""
    loop = asyncio.get_running_loop()
    gate = _gates.get(loop)
    if gate is None:
        gate = _gates[loop] = asyncio.Semaphore(MAX_BATCH_LOOKUPS)
    return gate
