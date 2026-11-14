# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Publishes ``printer.status`` on the printer state channel when the queue
pauses or resumes a printer, so the UI shows the stuck state live."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from app.services.event_bus import BusEvent, EventBus
from app.services.print_queue import PauseInfo

_log = logging.getLogger(__name__)


class PrinterPauseProducer:
    """Converts PrintQueue pause/resume transitions into EventBus events."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    def handle_change(self, printer_id: UUID, info: PauseInfo | None) -> None:
        """Publish a ``printer.status`` event. Must not raise (called by the queue)."""
        channel = f"printer:{printer_id}:state"
        try:
            self._bus.publish(
                channel,
                BusEvent(
                    channel=channel,
                    event_id=self._bus.next_event_id(channel),
                    event_type="printer.status",
                    timestamp=datetime.now(UTC),
                    data={
                        "paused": info is not None,
                        "pause": None
                        if info is None
                        else {
                            "source": info.source,
                            "reason_code": info.reason_code,
                            "since": info.since.isoformat(),
                        },
                    },
                ),
            )
        except Exception:
            _log.exception("PrinterPauseProducer failed for printer=%s", printer_id)
