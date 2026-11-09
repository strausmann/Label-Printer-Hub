"""Detects a roll (tape cassette) change from the probe and keeps the roll record (#229).

The printer reports no tape colour over the network, so the colour is asked of the operator
whenever the roll changes. The roll identity is ``(width_mm, media_raw)``: SNMP gives no media
type code, so the raw media text stands for it and any text change counts as a change. Taking
the cassette out and putting it back passes through ``(None, None)`` and prompts again, because
the same cassette cannot be proven.

The first observation after a start is compared with the stored row, so a swap while the hub
was down is found, and found once. A printer seen for the first time counts as a change.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.printer_roll import PrinterRoll
from app.services.event_bus import BusEvent, EventBus

_log = logging.getLogger(__name__)

SessionFactory = Callable[[], Any]


@dataclass(frozen=True)
class RollChange:
    """What changed: the new identity and whether the operator is to be asked."""

    width_mm: int | None
    media_raw: str | None
    prompt_pending: bool


def publish_roll_event(
    bus: EventBus | None,
    printer_id: UUID,
    *,
    width_mm: int | None,
    media_raw: str | None,
    prompt_pending: bool,
) -> None:
    """Publish ``printer.roll_changed`` on the printer's tape channel."""
    if bus is None:
        return
    channel = f"printer:{printer_id}:tape"
    bus.publish(
        channel,
        BusEvent(
            channel=channel,
            event_id=bus.next_event_id(channel),
            event_type="printer.roll_changed",
            timestamp=datetime.now(UTC),
            data={
                "width_mm": width_mm,
                "media_raw": media_raw,
                "prompt_pending": prompt_pending,
            },
        ),
    )


class RollTracker:
    """Compares each successful probe's roll identity with the stored one."""

    def __init__(self, bus: EventBus | None, session_factory: SessionFactory | None = None) -> None:
        self._bus = bus
        self._session_factory = session_factory
        self._locks: dict[UUID, asyncio.Lock] = {}

    def _session(self) -> AsyncSession:
        if self._session_factory is not None:
            return self._session_factory()  # type: ignore[no-any-return]
        from app.db.engine import async_session

        return async_session()

    async def observe(
        self, printer_id: UUID, width_mm: int | None, media_raw: str | None
    ) -> RollChange | None:
        """Store the identity if it differs from the stored one; return the change or None."""
        media_raw = (media_raw or "").strip() or None
        if width_mm is not None and width_mm <= 0:
            width_mm = None
        lock = self._locks.setdefault(printer_id, asyncio.Lock())
        async with lock, self._session() as s:
            row = await s.get(PrinterRoll, printer_id)
            if row is not None and (row.width_mm, row.media_raw) == (width_mm, media_raw):
                return None
            now = datetime.now(UTC)
            prompt = width_mm is not None
            if row is None:
                s.add(
                    PrinterRoll(
                        printer_id=printer_id,
                        width_mm=width_mm,
                        media_raw=media_raw,
                        colour=None,
                        set_at=None,
                        prompt_pending=prompt,
                        changed_at=now,
                    )
                )
            else:
                row.width_mm = width_mm
                row.media_raw = media_raw
                row.colour = None
                row.set_at = None
                row.prompt_pending = prompt
                row.changed_at = now
            await s.commit()
        publish_roll_event(
            self._bus, printer_id, width_mm=width_mm, media_raw=media_raw, prompt_pending=prompt
        )
        return RollChange(width_mm=width_mm, media_raw=media_raw, prompt_pending=prompt)
