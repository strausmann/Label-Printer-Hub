# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Schema of ``GET /api/v1/notices``: one-time notes the hub leaves for the notification centre."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.schemas._datetime import serialize_datetime_utc


class SheetTypeNotice(BaseModel):
    """A shipped sheet type was marked verified or got new dimensions (spec 10i, R-334-4).

    Information only: it carries no secret and no write path. ``code`` is the type's product
    code without its pack-size suffix, as it stood when the notice was written.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(description="Stable id of the notice; a browser keeps its read state under it.")
    kind: Literal["sheet_type_verified", "sheet_type_updated"]
    key: str = Field(description="Key of the sheet type the notice is about.")
    code: str = Field(description="Product code of the type, or its key when it has none.")
    at: datetime

    @field_serializer("at")
    def _serialise_at(self, dt: datetime, _info: object) -> str:
        return serialize_datetime_utc(dt, _info)
