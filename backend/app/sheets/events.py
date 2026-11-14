# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``sheet.updated`` events on the ``sheets`` channel (spec 16).

Published by the sheet service after a write has committed, so a client that reacts by reading
the sheet sees the new state. Sheets carry no printer restriction (OC-11): every event stream
subscribes to this channel.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from app.services.event_bus import BusEvent, EventBus
from app.sheets.text import log_value

logger = logging.getLogger(__name__)

SHEETS_CHANNEL = "sheets"
SHEET_UPDATED = "sheet.updated"


def publish_sheet_updated(
    bus: EventBus | None, *, code: str, free: int, total: int, changed: list[int], state: str
) -> None:
    if bus is None:
        return
    bus.publish(
        SHEETS_CHANNEL,
        BusEvent(
            channel=SHEETS_CHANNEL,
            event_id=bus.next_event_id(SHEETS_CHANNEL),
            event_type=SHEET_UPDATED,
            timestamp=datetime.now(UTC),
            data={
                "code": code,
                "free": free,
                "total": total,
                "changed": sorted(changed),
                "state": state,
            },
        ),
    )


@dataclass
class SheetTouched:
    """One sheet changed by a committed write: what ``sheet.updated`` is built from."""

    code: str
    total: int
    free: int
    changed: list[int]
    state: str = "active"


def publish_touched(bus: EventBus | None, touched: Sequence[SheetTouched]) -> None:
    """Publish after the commit. A failing subscriber must not hide a committed write."""
    for t in touched:
        try:
            publish_sheet_updated(
                bus, code=t.code, free=t.free, total=t.total, changed=t.changed, state=t.state
            )
        except Exception:
            logger.exception("sheet.updated for %s could not be published", log_value(t.code))
