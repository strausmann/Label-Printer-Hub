# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The notices the hub leaves for the notification centre (spec 10i, I4).

They are not part of ``GET /api/v1/info``: that endpoint stays public and carries build info
and booleans only. This one needs a read key and returns the records of the last 30 days.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_read
from app.db.session import get_session
from app.models.app_setting import AppSetting
from app.schemas.notices import SheetTypeNotice
from app.seed.sheet_seed import NOTICE_MAX_AGE, NOTICES_KEY

router = APIRouter(prefix="/api/v1", tags=["notices"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadDep = Annotated[AuthContext, Depends(require_read)]


def _parse(records: list[Any]) -> list[SheetTypeNotice]:
    notices: list[SheetTypeNotice] = []
    for record in records:
        try:
            notices.append(SheetTypeNotice.model_validate(record))
        except ValidationError:  # a record this version cannot read is skipped, not an error
            continue
    return notices


@router.get(
    "/notices",
    response_model=list[SheetTypeNotice],
    summary="List the hub's recent notices",
)
async def list_notices(_auth: ReadDep, db: SessionDep) -> list[SheetTypeNotice]:
    """Notices of the last 30 days, newest first (sheet types marked verified or updated)."""
    row = await db.get(AppSetting, NOTICES_KEY)
    if row is None or row.value_json is None:
        return []
    try:
        records = json.loads(row.value_json)
    except ValueError:
        return []
    if not isinstance(records, list):
        return []
    cutoff = datetime.now(UTC) - NOTICE_MAX_AGE
    recent = [
        n for n in _parse(records) if (n.at if n.at.tzinfo else n.at.replace(tzinfo=UTC)) >= cutoff
    ]
    return sorted(recent, key=lambda n: (n.at, n.id), reverse=True)
