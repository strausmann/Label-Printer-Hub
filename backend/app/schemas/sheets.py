"""Pydantic schemas of the sheet archive API (spec 15), type part.

Lengths are millimetres with at most two decimals (D16); the services store hundredths.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_serializer

from app.schemas._datetime import serialize_datetime_utc
from app.sheets.exchange import GeometryMm
from app.sheets.naming import KEY_PATTERN, PREFIX_PATTERN
from app.sheets.text import check_http_url

__all__ = [
    "GeometryMm",
    "ImportResponse",
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
    product_codes: Annotated[list[_Code], Field(max_length=50)] = []
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
    vendor: str | None = None
    product_codes: list[str] | None = None
    description: str | None = None
    allow_qr: bool | None = None
    verified: bool | None = None
    source_name: str | None = None
    source_url: _Url | None = None
    notes: str | None = None


class VersionCreate(_Body):
    geometry: GeometryMm
    change_note: str = Field(min_length=1, max_length=500)


class ImportResponse(BaseModel):
    outcome: Literal["created", "unchanged", "version_added", "created_as_new_key"]
    key: str
    version: int
