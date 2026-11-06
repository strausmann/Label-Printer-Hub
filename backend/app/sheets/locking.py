"""Write-lock helper for sheet transactions."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def acquire_sheet_write_lock(session: AsyncSession) -> None:
    """Take SQLite's write lock before any read of the transaction.

    Must be the first statement of every sheet write transaction. A deferred reader that
    upgrades to a writer can fail at once with ``database is locked`` in WAL mode, and
    ``busy_timeout`` only helps a writer waiting for a writer. The upsert always writes one
    row, which is what takes the lock; it also works where the schema came from ``create_all``
    and the migration's seed row is absent.
    """
    await session.execute(
        text(
            "INSERT INTO sheet_write_lock (id, seq) VALUES (1, 1) "
            "ON CONFLICT (id) DO UPDATE SET seq = seq + 1"
        )
    )
