"""Request and response models of the sheet print preview (spec 12.6, 15).

Request bodies refuse fields they do not know, so ``options`` (copies, cut) is not accepted:
a sheet job has no copies (OC-3). Validation errors on these paths name field paths only; the
handler in ``error_handlers`` strips the input.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.schemas._datetime import serialize_datetime_utc
from app.schemas.content_type import ContentType
from app.schemas.label_data_item import LabelDataItem
from app.schemas.print_request import PrintLookupRequest, RawLabelData
from app.sheets.exchange import GeometryMm
from app.sheets.naming import KEY_PATTERN

__all__ = [
    "QR_PAYLOAD_MAX",
    "ExpectedPageModel",
    "NewSheetModel",
    "PlacementInModel",
    "PreviewCell",
    "PreviewPage",
    "PrintedPage",
    "ReprintHint",
    "SheetItem",
    "SheetPreview",
    "SheetPrintRequest",
    "SheetPrintResponse",
    "SheetRawLabelData",
]

MAX_ITEMS = 500
MAX_PLACEMENTS = 50
MAX_CELLS = 400
MAX_TYPE_VERSION = 1_000_000  # far above any real count; keeps the value inside SQLite's integer
TEXT_MAX = 120

QR_PAYLOAD_MAX = 512  # keeps a preview's cost bounded; a scan URL is far shorter
RAW_TEXT_MAX = 512  # one raw text field (title, id, a secondary line, a listing row)
RAW_SECONDARY_MAX = 10  # secondary lines per label
RAW_LISTING_MAX = 100  # listing rows per label

_Cell = Annotated[int, Field(ge=1, le=MAX_CELLS)]
_SOURCE_PATTERN = r"^[a-z][a-z0-9_-]{0,31}$"
RESERVED_SOURCE = "hub"  # the source of the sheet ID label (a cell with it counts as the ID)


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


_RawText = Annotated[str, Field(max_length=RAW_TEXT_MAX)]


class SheetRawListingItem(LabelDataItem):
    """One listing row of a raw item, with bounded text."""

    item: _RawText
    qr_payload: str | None = Field(default=None, max_length=QR_PAYLOAD_MAX)


class SheetRawLabelData(RawLabelData):
    """Raw label data of a sheet item: the same fields, every free text bounded.

    A page job stores its labels in the job row, and a preview renders them, so the sizes are
    capped at the request: ``qr_payload`` at 512 characters, every other text at 512, at most
    10 ``secondary`` lines and 100 ``items`` (listing rows). A cell shows far less than that;
    the renderer shortens what does not fit.
    """

    title: _RawText | None = None
    primary_id: _RawText | None = None
    qr_payload: str | None = Field(default=None, max_length=QR_PAYLOAD_MAX)
    secondary: tuple[_RawText, ...] = Field(default=(), max_length=RAW_SECONDARY_MAX)
    items: tuple[SheetRawListingItem, ...] = Field(default=(), max_length=RAW_LISTING_MAX)


class SheetItem(_Body):
    """One label to print: a content type plus raw data or an integration lookup.

    ``purpose`` is what the cell is recorded as (default: the label's title, else its primary
    id). ``source`` names the origin of raw data (default ``api``); a lookup is recorded under
    the integration's name and its identifier as ``ref``.
    """

    content_type: ContentType
    data: SheetRawLabelData | None = None
    lookup: PrintLookupRequest | None = None
    purpose: str | None = Field(default=None, max_length=TEXT_MAX)
    source: str | None = Field(default=None, pattern=_SOURCE_PATTERN)
    ref: str | None = Field(default=None, max_length=TEXT_MAX)

    @model_validator(mode="after")
    def _one_data_source(self) -> Self:
        if (self.data is None) == (self.lookup is None):
            raise ValueError("exactly one of data or lookup must be set")
        if self.source == RESERVED_SOURCE:
            raise ValueError("source is reserved for the sheet ID label")
        if self.lookup is not None and len(self.lookup.identifier) > TEXT_MAX:
            raise ValueError("lookup identifier is longer than 120 characters")
        return self


class NewSheetModel(_Body):
    type: str = Field(max_length=64, pattern=KEY_PATTERN.pattern, description="Sheet type key.")
    version: int | None = Field(
        default=None,
        ge=1,
        le=MAX_TYPE_VERSION,
        description="Defaults to the current version.",
    )
    id_placement: Literal["cell", "margin", "manual"] = Field(
        default="margin", description="Where the sheet ID is printed; `margin` if left out."
    )


class PlacementInModel(_Body):
    """Either an existing sheet (``sheet``) or a new one (``new_sheet``), never both.

    Items fill the placements in order; the last placement may leave ``count`` out and takes
    the rest. ``cells`` and ``skip`` belong to an existing sheet only.
    """

    sheet: str | None = Field(default=None, max_length=24, description="Sheet code.")
    new_sheet: NewSheetModel | None = None
    cells: Literal["first_free"] | Annotated[list[_Cell], Field(max_length=MAX_CELLS)] = Field(
        default="first_free",
        description="`first_free`, or the cell numbers, in the order the items fill them.",
    )
    skip: list[_Cell] = Field(
        default_factory=list,
        max_length=MAX_CELLS,
        description="Cells `first_free` leaves out for this request (never stored).",
    )
    count: int | None = Field(default=None, ge=1, le=MAX_ITEMS)

    @model_validator(mode="after")
    def _one_target(self) -> Self:
        if (self.sheet is None) == (self.new_sheet is None):
            raise ValueError("exactly one of sheet or new_sheet must be set")
        if self.new_sheet is not None and (self.cells != "first_free" or self.skip):
            raise ValueError("cells and skip are for an existing sheet")
        return self


class ExpectedPageModel(_Body):
    """What a preview promised for one page; the print refuses a different plan."""

    sheet: str = Field(max_length=24, description="Sheet code, or `new`.")
    cells: list[_Cell] = Field(max_length=MAX_CELLS)
    id_cell: int | None = Field(default=None, ge=1, le=MAX_CELLS)


class SheetPrintRequest(_Body):
    items: list[SheetItem] = Field(min_length=1, max_length=MAX_ITEMS)
    placements: list[PlacementInModel] = Field(min_length=1, max_length=MAX_PLACEMENTS)
    tray: str | None = Field(default=None, min_length=1, max_length=100)
    expected_cells: list[ExpectedPageModel] | None = Field(default=None, max_length=50)


class PreviewCell(BaseModel):
    cell: int
    state: Literal["used", "reserved", "unconfirmed", "new", "free"]
    is_id: bool = Field(description="The sheet ID label of a `cell` sheet.")
    purpose: str | None
    item_index: int | None = Field(description="Index into the request's items; new cells only.")
    truncated: bool = Field(description="Text had to be shortened to fit.")
    mapped: bool = Field(description="Drawn as text because the sheet type has no QR (spec 12.5).")
    hw_margin: bool = Field(
        description="New cells only: may be cut off by this printer's hardware margins."
    )


class PreviewPage(BaseModel):
    sheet_code: str | None = Field(description="Null for a sheet this request creates.")
    new_code_hint: str | None = Field(description="The probable code of a new sheet.")
    type_key: str
    version: int
    geometry: GeometryMm
    cells: list[PreviewCell]
    png_base64: str = Field(description="1-bit PNG, 150 dpi, page size: only the new content.")
    margin_id: bool = Field(description="The sheet ID is printed in a margin band on this page.")
    margin_band: Literal["top", "bottom", "right", "left"] | None
    id_not_printed: bool = Field(description="No margin band is deep enough: no ID on this page.")
    feed_mark: bool = Field(description="The feed-direction mark is printed on this page.")
    load_hint: str | None = Field(description="How to load the tray, if the printer has a hint.")


class ReprintHint(BaseModel):
    item_index: int
    sheet_code: str
    cell: int
    printed_at: datetime

    @field_serializer("printed_at")
    def _ser_printed(self, dt: datetime, info: Any) -> str:
        return serialize_datetime_utc(dt, info)


class SheetPreview(BaseModel):
    pages: list[PreviewPage]
    free_after: list[int] = Field(description="Free cells left on each page's sheet afterwards.")
    expected_cells: list[ExpectedPageModel] = Field(
        description="Send this back as `expected_cells` when printing."
    )
    reprint_hints: list[ReprintHint]


class PrintedPage(BaseModel):
    """One page job of a sheet print (the counterpart of ``PreviewPage``)."""

    job_id: UUID
    sheet_code: str
    cells: list[int] = Field(description="The cells the request's items take, in item order.")
    id_cell: int | None = Field(description="The cell of a `cell` sheet's ID label, if any.")
    margin_id: bool = Field(description="The sheet ID is printed in a margin band on this page.")
    margin_band: Literal["top", "bottom", "right", "left"] | None = Field(
        description="The band stored for this job; it can differ from the preview's."
    )
    id_not_printed: bool = Field(description="No margin band is deep enough: no ID on this page.")
    feed_mark: bool = Field(description="The feed-direction mark is printed on this page.")


class SheetPrintResponse(BaseModel):
    """The accepted print: one batch of page jobs, one per planned page, in plan order."""

    batch_id: UUID
    pages: list[PrintedPage]
