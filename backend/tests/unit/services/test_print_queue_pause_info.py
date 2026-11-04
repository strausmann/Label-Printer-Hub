"""PrintQueue keeps the reason for each pause (E-11)."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID

import pytest
from app.services.print_queue import PauseInfo, PrinterAlreadyActiveError, PrintQueue

_ID = UUID("00000000-0000-0000-0000-0000000000a1")


def _queue(events: list) -> PrintQueue:
    p = MagicMock()
    p.id = _ID
    return PrintQueue([p], on_pause_change=lambda pid, info: events.append((pid, info)))


@pytest.mark.asyncio
async def test_pause_records_reason_and_resume_clears() -> None:
    events: list = []
    q = _queue(events)
    assert q.pause_info(_ID) is None

    await q.pause_printer(_ID, reason="cover_open")
    info = q.pause_info(_ID)
    assert isinstance(info, PauseInfo)
    assert (info.source, info.reason_code) == ("printer_error", "cover_open")

    await q.resume_printer(_ID)
    assert q.pause_info(_ID) is None
    assert [e[1] is None for e in events] == [False, True]


@pytest.mark.asyncio
async def test_user_pause_overrides_and_repeat_keeps_since() -> None:
    events: list = []
    q = _queue(events)
    await q.pause_printer(_ID, reason="offline")
    await q.pause_printer(_ID, source="user")
    first = q.pause_info(_ID)
    assert first is not None and first.source == "user" and first.reason_code == "user"
    await q.pause_printer(_ID, source="user")
    assert q.pause_info(_ID) == first
    assert len(events) == 2


@pytest.mark.asyncio
async def test_resume_active_still_raises() -> None:
    q = _queue([])
    with pytest.raises(PrinterAlreadyActiveError):
        await q.resume_printer(_ID)


@pytest.mark.asyncio
async def test_failing_callback_does_not_break_pause() -> None:
    p = MagicMock()
    p.id = _ID

    def boom(*_a: object) -> None:
        raise RuntimeError("x")

    q = PrintQueue([p], on_pause_change=boom)
    await q.pause_printer(_ID, reason="offline")
    assert q.is_paused(_ID)
