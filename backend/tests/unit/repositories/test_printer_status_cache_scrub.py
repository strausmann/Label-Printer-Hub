# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Startup scrub of free-text ``last_error`` values left in the status cache by hub 1.7.0.

Addresses come from the documentation range 192.0.2.0/24.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.models.printer_status_cache import PrinterStatusCache
from app.repositories import printer_status_cache as cache_repo


async def _seed(db_session, parsed: dict | None) -> PrinterStatusCache:
    row = PrinterStatusCache(
        printer_id=uuid4(),
        parsed=parsed,
        captured_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(row)
    await db_session.commit()
    return row


@pytest.mark.asyncio
async def test_a_free_text_error_with_an_address_is_dropped(db_session) -> None:
    row = await _seed(
        db_session, {"online": False, "last_error": "cannot reach 192.0.2.1:9100", "kind": "tape"}
    )

    changed = await cache_repo.drop_free_text_errors(db_session)
    await db_session.commit()
    await db_session.refresh(row)

    assert changed == 1
    assert "192.0.2.1" not in str(row.parsed)
    assert row.parsed == {"online": False, "kind": "tape"}


@pytest.mark.asyncio
async def test_a_bare_class_name_and_rows_without_an_error_are_kept(db_session) -> None:
    kept = await _seed(db_session, {"online": False, "last_error": "PrinterOfflineError"})
    clean = await _seed(db_session, {"online": True})
    empty = await _seed(db_session, None)

    changed = await cache_repo.drop_free_text_errors(db_session)
    await db_session.commit()
    for row in (kept, clean, empty):
        await db_session.refresh(row)

    assert changed == 0
    assert kept.parsed == {"online": False, "last_error": "PrinterOfflineError"}
    assert clean.parsed == {"online": True}
    assert empty.parsed is None
