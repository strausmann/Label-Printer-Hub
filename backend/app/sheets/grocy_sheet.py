# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Grocy labels onto sheets of a page printer (#281, spec R-281-13 to R-281-17).

One Grocy label takes one cell: the lowest free cell of the type's fullest started sheet, else
cell 1 of a new sheet with the sheet ID in the margin.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import sheet_types as types_repo
from app.repositories import sheets as repo


async def choose_grocy_sheet(session: AsyncSession, type_key: str) -> str | None:
    """The code of the sheet a Grocy label of ``type_key`` goes to; ``None``: a new sheet.

    Among the type's ``active`` sheets with at least one free cell (free: not used, reserved
    or unconfirmed), every version counted, the one with the **fewest** free cells; equal
    counts by ``(len(code), code)``. That is the print page's rule (``fittingFirst``) for one
    label. An unknown type has no sheets.
    """
    sheet_type = await types_repo.get_by_key(session, type_key)
    if sheet_type is None:
        return None
    rows = await repo.list_with_counts(session, type_id=sheet_type.id, sheet_state="active")
    candidates: list[tuple[int, int, str]] = []
    for sheet, _type, version, used, reserved, unconfirmed in rows:
        free = version.cols * version.rows - used - reserved - unconfirmed
        if free > 0:
            candidates.append((free, len(sheet.code), sheet.code))
    return min(candidates)[2] if candidates else None
