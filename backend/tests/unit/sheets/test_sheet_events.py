# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``sheet.updated`` publisher on the ``sheets`` channel (Plan 1, Task 6, spec 16)."""

from __future__ import annotations

import asyncio
from datetime import datetime

from app.services.event_bus import EventBus
from app.sheets.events import SHEETS_CHANNEL, publish_sheet_updated


async def test_publishes_on_the_sheets_channel() -> None:
    bus = EventBus()
    queue = bus.subscribe("sheets", "sub-1")
    other = bus.subscribe("hub", "sub-1")
    publish_sheet_updated(bus, code="L4736-0002", free=31, total=48, changed=[7, 3], state="active")
    event = await asyncio.wait_for(queue.get(), 1)
    assert event is not None
    assert SHEETS_CHANNEL == "sheets"
    assert (event.channel, event.event_type) == ("sheets", "sheet.updated")
    assert event.data == {
        "code": "L4736-0002",
        "free": 31,
        "total": 48,
        "changed": [3, 7],
        "state": "active",
    }
    assert isinstance(event.timestamp, datetime) and event.timestamp.tzinfo is not None
    assert event.event_id == 1
    assert other.empty()
    publish_sheet_updated(bus, code="L4736-0002", free=30, total=48, changed=[8], state="active")
    second = await asyncio.wait_for(queue.get(), 1)
    assert second is not None and second.event_id == 2


def test_no_bus_is_a_no_op() -> None:
    publish_sheet_updated(None, code="L4736-0002", free=1, total=2, changed=[], state="active")
