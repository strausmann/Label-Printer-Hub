# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Request and response of POST /api/v1/render/check (#285): will these cart items print?"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.content_type import ContentType
from app.schemas.label_layout import LabelOrientation, QlLayoutPreset

MAX_RENDER_CHECK_ITEMS = 50


class RenderCheckLookup(BaseModel):
    """The integration item a label is drawn from."""

    model_config = ConfigDict(extra="forbid")

    app: str = Field(max_length=32)
    identifier: str = Field(min_length=1, max_length=256)


class RenderCheckItem(BaseModel):
    """One cart item: how it is drawn and which integration item feeds it."""

    model_config = ConfigDict(extra="forbid")

    content_type: ContentType
    lookup: RenderCheckLookup


class RenderCheckRequest(BaseModel):
    """Cart items to check against one tape width and layout."""

    model_config = ConfigDict(extra="forbid")

    tape_mm: int
    orientation: LabelOrientation | None = None
    layout_preset: QlLayoutPreset | None = None
    items: list[RenderCheckItem] = Field(min_length=1, max_length=MAX_RENDER_CHECK_ITEMS)


class RenderCheckResult(BaseModel):
    """Verdict for the item at ``index`` of the request."""

    index: int
    ok: bool
    error_code: str | None = None
    error_message: str | None = None
    error_detail: dict[str, object] | None = None


class RenderCheckResponse(BaseModel):
    """One result per request item, in request order."""

    results: list[RenderCheckResult]
