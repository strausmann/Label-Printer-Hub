# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The shared SQLite test fixture runs like the hub's database (#213)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text


async def test_shared_fixture_runs_in_wal(async_session_factory: Any) -> None:
    """A reader cancelled half way must not lock the next writer, so the shared fixture uses WAL
    and a busy timeout like ``app/db/engine.py``. Foreign keys stay off on purpose (the tests use
    printer ids that have no row)."""
    async with async_session_factory() as session:
        journal_mode = (await session.execute(text("PRAGMA journal_mode"))).scalar_one()
        busy_timeout = (await session.execute(text("PRAGMA busy_timeout"))).scalar_one()
        foreign_keys = (await session.execute(text("PRAGMA foreign_keys"))).scalar_one()
    assert journal_mode == "wal"
    assert busy_timeout == 5000
    assert foreign_keys == 0
