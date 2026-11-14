# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Write-lock helper for sheet transactions."""

from __future__ import annotations

from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

STATEMENT_COUNT_KEY = "stmt_count"
"""``connection.info`` key: the statements run so far in the connection's transaction."""


def _count_statement(conn: Any, *_args: Any) -> None:
    conn.info[STATEMENT_COUNT_KEY] = conn.info.get(STATEMENT_COUNT_KEY, 0) + 1


def _reset_statement_count(conn: Any) -> None:
    conn.info[STATEMENT_COUNT_KEY] = 0


def install_statement_counter(target: Any) -> None:
    """Count the statements of each transaction in ``connection.info`` (264-01).

    ``target`` is a sync ``Engine`` (``AsyncEngine.sync_engine``) or the ``Engine`` class. A
    transaction belongs to the connection, not to the session: the count is reset when the
    connection begins one and raised before every statement it runs. Installing twice is a
    no-op.
    """
    if not event.contains(target, "before_cursor_execute", _count_statement):
        event.listen(target, "before_cursor_execute", _count_statement)
    if not event.contains(target, "begin", _reset_statement_count):
        event.listen(target, "begin", _reset_statement_count)


def uninstall_statement_counter(target: Any) -> None:
    """Undo ``install_statement_counter`` (tests of an engine without it)."""
    if event.contains(target, "before_cursor_execute", _count_statement):
        event.remove(target, "before_cursor_execute", _count_statement)
    if event.contains(target, "begin", _reset_statement_count):
        event.remove(target, "begin", _reset_statement_count)


async def acquire_sheet_write_lock(session: AsyncSession) -> None:
    """Take SQLite's write lock before any read of the transaction.

    Must be the first statement of every sheet write transaction. A deferred reader that
    upgrades to a writer can fail at once with ``database is locked`` in WAL mode, and
    ``busy_timeout`` only helps a writer waiting for a writer. The upsert always writes one
    row, which is what takes the lock; it also works where the schema came from ``create_all``
    and the migration's seed row is absent.

    The order is enforced, not only documented (264-01): the engine counts the statements of
    each transaction (``install_statement_counter``), and a count above zero raises
    ``RuntimeError`` before SQLite is asked. An engine without the counter raises too, instead
    of passing as zero.
    """
    conn = await session.connection()  # begins the transaction (count 0), runs no statement
    count = conn.sync_connection.info.get(STATEMENT_COUNT_KEY) if conn.sync_connection else None
    if count is None:
        raise RuntimeError("statement counter not installed")
    if count > 0:
        raise RuntimeError("sheet write lock must be the first statement of the transaction")
    await session.execute(
        text(
            "INSERT INTO sheet_write_lock (id, seq) VALUES (1, 1) "
            "ON CONFLICT (id) DO UPDATE SET seq = seq + 1"
        )
    )
