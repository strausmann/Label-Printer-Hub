"""Pydantic schemas of the sheet archive API (spec 15): sheet types and sheets.

Lengths are millimetres with at most two decimals (D16); the services store hundredths.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_serializer

from app.schemas._datetime import serialize_datetime_utc
from app.sheets.exchange import GeometryMm
from app.sheets.naming import KEY_PATTERN, PREFIX_PATTERN
from app.sheets.text import check_http_url

__all__ = [
    "CellHitRead",
    "CellNumbers",
    "CellRead",
    "GeometryMm",
    "ImportResponse",
    "MarkRequest",
    "MarkedCellIn",
    "NextCode",
    "ResolveRequest",
    "SheetCreate",
    "SheetRead",
    "SheetSummary",
    "SheetTypeCreate",
    "SheetTypeDetail",
    "SheetTypePatch",
    "SheetTypeRead",
    "VersionCreate",
    "VersionRead",
]

_Key = Annotated[str, Field(max_length=64, pattern=KEY_PATTERN.pattern)]
_Prefix = Annotated[str, Field(max_length=10, pattern=PREFIX_PATTERN.pattern)]
_Code = Annotated[str, Field(min_length=1, max_length=40)]
_PRODUCT_CODES_MAX = 50  # the export document's limit
_Url = Annotated[str, Field(max_length=500), AfterValidator(check_http_url)]


class _Body(BaseModel):
    """Request bodies refuse fields they do not know."""

    model_config = ConfigDict(extra="forbid")


def _utc(dt: datetime | None, info: Any) -> str | None:
    return None if dt is None else serialize_datetime_utc(dt, info)


class VersionRead(BaseModel):
    version: int
    geometry: GeometryMm
    geometry_hash: str
    change_note: str | None
    created_at: datetime
    sheets: int = Field(description="Sheets of any state pinned to this version.")

    @field_serializer("created_at")
    def _ser_created(self, dt: datetime, info: Any) -> str | None:
        return _utc(dt, info)


class SheetTypeRead(BaseModel):
    key: str
    prefix: str
    vendor: str | None
    product_codes: list[str]
    description: str | None
    allow_qr: bool
    verified: bool
    origin: Literal["seed", "custom", "imported"]
    source_name: str | None
    source_url: str | None
    notes: str | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    current_version: int
    geometry: GeometryMm = Field(description="Geometry of the current version.")
    hints: list[str] = Field(description="Advisory codes about the current geometry.")
    sheets_in_use: int = Field(description="Sheets of any state of this type.")

    @field_serializer("archived_at", "created_at", "updated_at")
    def _ser_dt(self, dt: datetime | None, info: Any) -> str | None:
        return _utc(dt, info)


class SheetTypeDetail(SheetTypeRead):
    versions: list[VersionRead]


class SheetTypeCreate(_Body):
    key: _Key
    prefix: _Prefix
    vendor: Annotated[str, Field(max_length=200)] | None = None
    product_codes: Annotated[list[_Code], Field(max_length=_PRODUCT_CODES_MAX)] = []
    description: Annotated[str, Field(max_length=200)] | None = None
    allow_qr: bool | None = Field(
        default=None, description="Left out: true when the shorter label side is at least 15 mm."
    )
    verified: bool = False
    source_name: Annotated[str, Field(max_length=200)] | None = None
    source_url: _Url | None = None
    notes: Annotated[str, Field(max_length=2000)] | None = None
    geometry: GeometryMm


class SheetTypePatch(_Body):
    """Only the fields the client sends change. ``null`` clears a nullable field."""

    prefix: str | None = None
    vendor: Annotated[str, Field(max_length=200)] | None = None
    product_codes: Annotated[list[_Code], Field(max_length=_PRODUCT_CODES_MAX)] | None = None
    description: Annotated[str, Field(max_length=200)] | None = None
    allow_qr: bool | None = None
    verified: bool | None = None
    source_name: Annotated[str, Field(max_length=200)] | None = None
    source_url: _Url | None = None
    notes: Annotated[str, Field(max_length=2000)] | None = None


class VersionCreate(_Body):
    geometry: GeometryMm
    change_note: str = Field(min_length=1, max_length=500)


class ImportResponse(BaseModel):
    outcome: Literal["created", "unchanged", "version_added", "created_as_new_key"]
    key: str
    version: int


# --- sheets --------------------------------------------------------------------------------

MAX_CELLS = 400  # cols x rows <= 400 (OC-7)
_Purpose = Annotated[str, Field(max_length=120, description="Plain text, at most 120 characters.")]
_CellNo = Annotated[int, Field(ge=1)]


class MarkedCellIn(_Body):
    cell: _CellNo
    purpose: _Purpose | None = Field(
        default=None, description="Left out or empty: the cell reads `marked by hand`."
    )


class MarkRequest(_Body):
    cells: list[MarkedCellIn] = Field(min_length=1, max_length=MAX_CELLS)


class CellNumbers(_Body):
    cells: list[_CellNo] = Field(min_length=1, max_length=MAX_CELLS)


class ResolveRequest(CellNumbers):
    outcome: Literal["printed", "not_printed"]


class SheetCreate(_Body):
    type: Annotated[str, Field(max_length=64, pattern=KEY_PATTERN.pattern)]
    version: int | None = Field(
        default=None, ge=1, le=1_000_000, description="Left out: the current version."
    )
    id_placement: Literal["margin", "manual"]
    used_cells: list[MarkedCellIn] = Field(default=[], max_length=MAX_CELLS)
    note: Annotated[str, Field(max_length=500)] | None = None


class CellRead(BaseModel):
    cell: int
    state: Literal["reserved", "used", "unconfirmed"]
    source: str
    purpose: str | None
    ref: str | None
    marked_by_hand: bool
    job_id: UUID | None
    updated_at: datetime

    @field_serializer("updated_at")
    def _ser_updated(self, dt: datetime, info: Any) -> str | None:
        return _utc(dt, info)


class SheetSummary(BaseModel):
    code: str
    type_key: str
    type_label: str
    version: int
    label_w: float
    label_h: float
    total: int
    used: int
    reserved: int
    unconfirmed: int
    free: int
    state: Literal["active", "discarded"]
    last_used_at: datetime | None

    @field_serializer("last_used_at")
    def _ser_last_used(self, dt: datetime | None, info: Any) -> str | None:
        return _utc(dt, info)


class SheetRead(SheetSummary):
    id_placement: Literal["cell", "margin", "manual"]
    id_printed: bool
    note: str | None
    geometry: GeometryMm = Field(description="Geometry of the version the sheet is pinned to.")
    cells: list[CellRead] = Field(description="Every cell that is not free, by cell number.")
    discarded_at: datetime | None

    @field_serializer("discarded_at")
    def _ser_discarded(self, dt: datetime | None, info: Any) -> str | None:
        return _utc(dt, info)


class NextCode(BaseModel):
    code: str
    hint: Literal["probable"] = Field(description="A hint, not a reservation (spec 10.1).")


class CellHitRead(BaseModel):
    code: str
    cell: int
    state: Literal["reserved", "used", "unconfirmed"]
    purpose: str | None
    updated_at: datetime

    @field_serializer("updated_at")
    def _ser_hit_updated(self, dt: datetime, info: Any) -> str | None:
        return _utc(dt, info)
