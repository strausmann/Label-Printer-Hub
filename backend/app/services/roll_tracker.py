"""Detects a roll (tape cassette) change from the probe and keeps the roll record (#229).

The printer reports no tape colour over the network, so the colour is asked of the operator
whenever the roll changes. The roll identity is ``(width_mm, media_raw)``: SNMP gives no media
type code, so the raw media text stands for it and any text change counts as a change. Taking
the cassette out and putting it back passes through ``(None, None)`` and prompts again, because
the same cassette cannot be proven.

A probe that sees no tape is not believed at once: taking the cassette out clears the recorded
colour only after ``NO_TAPE_PROBES_TO_CLEAR`` such probes in a row, so one failed or half-read
poll cannot make the operator answer the colour question again. A different cassette is found on
the first probe.

The first observation after a start is compared with the stored row, so a swap while the hub
was down is found, and found once. A printer seen for the first time counts as a change.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
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


_MAX_ATTEMPTS = 3
NO_TAPE_PROBES_TO_CLEAR = 2
MEDIA_RAW_MAX = 64


def _is(column: Any, value: Any) -> Any:
    return column.is_(None) if value is None else column == value


async def _swap(
    s: AsyncSession,
    printer_id: UUID,
    old: tuple[int | None, str | None] | None,
    width_mm: int | None,
    media_raw: str | None,
    prompt: bool,
) -> bool:
    """Compare-and-swap the roll identity: write only if the row still holds ``old``.

    Every column is set explicitly, so a value equal to what a concurrent writer left is still
    written (an ORM flush would omit it). ``old`` None means no row existed.
    """
    now = datetime.now(UTC)
    if old is None:
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
        try:
            await s.commit()
        except IntegrityError:
            await s.rollback()
            return False
        return True
    result = await s.execute(
        update(PrinterRoll)
        .where(
            PrinterRoll.printer_id == printer_id,  # type: ignore[arg-type]
            _is(PrinterRoll.width_mm, old[0]),
            _is(PrinterRoll.media_raw, old[1]),
        )
        .values(
            width_mm=width_mm,
            media_raw=media_raw,
            colour=None,
            set_at=None,
            prompt_pending=prompt,
            changed_at=now,
        )
    )
    await s.commit()
    return bool(result.rowcount)  # type: ignore[attr-defined]


class RollTracker:
    """Compares each successful probe's roll identity with the stored one."""

    def __init__(self, bus: EventBus | None, session_factory: SessionFactory | None = None) -> None:
        self._bus = bus
        self._session_factory = session_factory
        self._locks: dict[UUID, asyncio.Lock] = {}
        # Consecutive probes without a tape, per printer (in memory: a restart starts again).
        self._no_tape_streak: dict[UUID, int] = {}
        # Test seam: runs between the read and the write of ``observe``.
        self._after_read: Callable[[], Awaitable[None]] | None = None

    def forget(self, printer_id: UUID) -> None:
        """Drop what this tracker keeps for a printer that is detached or deleted (T10).

        Called after its producer has stopped, so no ``observe`` for it runs any more; the
        stored roll row stays (the printer's delete removes it, a re-attach compares with it).
        """
        self._no_tape_streak.pop(printer_id, None)
        lock = self._locks.get(printer_id)
        if lock is not None and not lock.locked():
            del self._locks[printer_id]

    def _session(self) -> AsyncSession:
        if self._session_factory is not None:
            return self._session_factory()  # type: ignore[no-any-return]
        from app.db.engine import async_session

        return async_session()

    async def observe(
        self, printer_id: UUID, width_mm: int | None, media_raw: str | None
    ) -> RollChange | None:
        """Store the identity if it differs from the stored one; return the change or None."""
        media_raw = (media_raw or "").strip()[:MEDIA_RAW_MAX].strip() or None
        if width_mm is not None and width_mm <= 0:
            width_mm = None
        lock = self._locks.setdefault(printer_id, asyncio.Lock())
        prompt = width_mm is not None
        async with lock:
            if width_mm is None:
                streak = self._no_tape_streak.get(printer_id, 0) + 1
                self._no_tape_streak[printer_id] = streak
            else:
                streak = 0
                self._no_tape_streak.pop(printer_id, None)
            for _attempt in range(_MAX_ATTEMPTS):
                async with self._session() as s:
                    row = await s.get(PrinterRoll, printer_id)
                    if width_mm is None and (row is None or row.width_mm is None):
                        # Nothing stored to clear: the count only debounces clearing a roll.
                        self._no_tape_streak.pop(printer_id, None)
                    if row is not None and (row.width_mm, row.media_raw) == (width_mm, media_raw):
                        return None
                    if (
                        width_mm is None
                        and row is not None
                        and row.width_mm is not None
                        and streak < NO_TAPE_PROBES_TO_CLEAR
                    ):
                        # One probe without a tape: keep the roll and its colour for now.
                        return None
                    old = None if row is None else (row.width_mm, row.media_raw)
                    if self._after_read is not None:
                        await self._after_read()
                    if await _swap(s, printer_id, old, width_mm, media_raw, prompt):
                        break
            else:
                # Lost the race every time; the next probe compares again.
                _log.warning("RollTracker: roll of printer=%s kept changing under us", printer_id)
                return None
        publish_roll_event(
            self._bus, printer_id, width_mm=width_mm, media_raw=media_raw, prompt_pending=prompt
        )
        return RollChange(width_mm=width_mm, media_raw=media_raw, prompt_pending=prompt)
