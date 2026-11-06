"""``sheet.updated`` events on the ``sheets`` channel (spec 16).

Published by the sheet service after a write has committed, so a client that reacts by reading
the sheet sees the new state. Sheets carry no printer restriction (OC-11): every event stream
subscribes to this channel.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.event_bus import BusEvent, EventBus

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
