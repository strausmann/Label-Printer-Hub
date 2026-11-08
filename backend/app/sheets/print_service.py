"""Printing onto sheets: item resolution, the read-only preview and the print (spec 12.6, 15).

``resolve_items`` turns each requested item into label data, by an integration lookup or from
the raw data of the request. It runs before anything is written and outside any lock.

``preview`` plans with the planner on views built the way a reservation builds them, but never
takes the write lock and never writes: a sheet that does not exist yet is a view with a
``code_hint``, and the counter is only read. The result is a plan plus a 150 dpi PNG of the new
content per page. Calibration is not applied to the picture; the tray's deviation only decides
the margin band, as it does for the job (OC-50).

``print_sheets`` is the print: it resolves the items, checks every one against the cell it would
get (nothing is reserved for an item the cell cannot show), takes the tray's calibration once,
reserves the cells in one transaction (``reservation.reserve``), builds one ``sheet_page``
payload per planned page and submits the page jobs to the queue. Whatever fails after the
reservation releases the reservations of the pages that were not submitted; the outcome handler
settles the rest (D15).
"""

from __future__ import annotations

import asyncio
import base64
import logging
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

from PIL import Image, ImageDraw
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.calibration import service as calibration_service
from app.config import get_settings
from app.models.job import Job
from app.models.print_batch import PrintBatch
from app.models.printer import Printer
from app.models.printer_tray import PrinterTray
from app.models.sheet import SheetType, SheetTypeVersion
from app.printer_backends.exceptions import ContentTypeDataMismatchError
from app.repositories import print_batches as batches_repo
from app.repositories import sheet_types as types_repo
from app.repositories import sheets as repo
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.print_request import PrintLookupRequest
from app.schemas.sheet_print import (
    QR_PAYLOAD_MAX,
    RAW_LISTING_MAX,
    RAW_SECONDARY_MAX,
    RAW_TEXT_MAX,
    ExpectedPageModel,
    PlacementInModel,
    PreviewCell,
    PreviewPage,
    PrintedPage,
    ReprintHint,
    SheetItem,
    SheetPreview,
    SheetPrintRequest,
    SheetPrintResponse,
)
from app.services.errors import AppLookupNotFoundError, IntegrationNotConfiguredError
from app.services.lookup_service import AppLookupService, LookupFailedError, UnknownAppError
from app.services.page_jobs import PagePayload, snapshot_to_deviation
from app.settings_store import SettingsStore
from app.sheets import sheet_service as ss
from app.sheets.cell_render import (
    PREVIEW_QR_MASK,
    BoxHmm,
    CellImage,
    CellRenderer,
    box_fits_a_line,
    build_qr_preview,
    check_required,
    content_box,
    load_cell_font,
    map_content_type,
    qr_edge_px,
    qr_version,
)
from app.sheets.errors import (
    CellsUnconfirmedError,
    ItemContentMismatchError,
    ItemLookupFailedError,
    MediaKindMismatchError,
    PreviewTooLargeError,
    PrinterUnavailableError,
    PrintInterruptedError,
    SheetApiError,
    SheetIdJobFailedError,
    SheetTypeArchivedError,
    SheetTypeNotFoundError,
    SheetTypeVersionNotFoundError,
)
from app.sheets.exchange import geometry_to_doc
from app.sheets.geometry import Geometry, cell_count, hmm_to_mm
from app.sheets.planner import (
    MARGIN_TEXT_GAP_HMM,
    FeedMarkPlacement,
    MarginBand,
    MarginContext,
    MarginCorner,
    MarginPlacement,
    PagePlan,
    PlacementIn,
    SheetView,
    choose_feed_mark,
    choose_margin_placement,
    feed_mark_text,
    feed_mark_top_taken_hmm,
    margin_bands_hmm,
    plan,
)
from app.sheets.printer_facts import PrinterFacts, load_printer_facts
from app.sheets.reservation import (
    ID_CELL_PURPOSE,
    ExpectedPage,
    ItemMeta,
    NewSheetIn,
    PlacementRequest,
    ReservedPage,
    expected_of,
    load_sheet_view,
    release,
    reserve,
    reserve_exact,
)
from app.sheets.sheet_page import (
    PREVIEW_DPI,
    FeedMarkPayload,
    MarginIdPayload,
    SheetCellPayload,
    SheetPageDetail,
    feed_mark_payload,
    margin_id_payload,
    render_preview_png,
)
from app.sheets.text import sanitise_text
from app.sheets.type_service import version_geometry

__all__ = [
    "LOOKUP_CONCURRENCY",
    "MAX_PREVIEW_PAGES",
    "NO_MARGIN_BAND_REASON",
    "MarginCheck",
    "ResolvedItem",
    "create_sheet_with_id_label",
    "id_cell_label",
    "margin_check",
    "margin_id_text",
    "page_margin_id_payload",
    "preview",
    "print_sheets",
    "reserved_margin_id_payload",
    "resolve_items",
    "retry_sheet_page",
    "scan_payload_builder",
    "sheet_type_label",
]

logger = logging.getLogger(__name__)

LOOKUP_CONCURRENCY: Final = 8
MAX_QR_PAYLOAD: Final = QR_PAYLOAD_MAX  # request-level cap on a cell's QR payload
MAX_CONCURRENT_RENDERS: Final = 2  # preview renders at once, process-wide (spec 18, CPU)
MAX_PREVIEW_PAGES: Final = 10  # a plan decision, not the spec's (spec 18, CPU)
PREVIEW_QR_MAX_MODULES: Final = 65  # version 12; a denser symbol is a placeholder in the preview
MAX_HINTS_PER_ITEM: Final = 5
PURPOSE_MAX: Final = 120
_DEFAULT_PURPOSE_SCAN: Final = 480  # a default purpose is cut, never refused (OC-43)
_FALLBACK_PURPOSE: Final = "Label"  # plan decision: OC-43 names no fallback
_DEFAULT_SOURCE: Final = "api"

# The status, code and message of each lookup failure (pre-flight C10). The text is fixed: the
# lookup's own message can carry URLs and upstream detail. UnknownAppError is a LookupFailedError,
# so it comes first.
_LOOKUP_ERRORS: Final[tuple[tuple[type[Exception], int, str, str], ...]] = (
    (
        UnknownAppError,
        422,
        "integration_unknown_app",
        "The requested integration is not available.",
    ),
    (
        LookupFailedError,
        502,
        "integration_lookup_failed",
        "The integration failed or could not be reached.",
    ),
    (AppLookupNotFoundError, 404, "app-lookup-not-found", "The integration has no such item."),
    (
        IntegrationNotConfiguredError,
        503,
        "integration_not_configured",
        "The integration is not configured.",
    ),
)


# ---------------------------------------------------------------------------- scan payload


def scan_payload_builder(public_url: str) -> Callable[[str], str]:
    """``code -> text the sheet's QR encodes`` (OC-15): the hub's own sheet URL, or the short
    form ``sheet:{code}`` when no public URL is given (a test setup)."""
    from app.integrations.urls import base_url  # local: keeps the module import light

    root = base_url(public_url) if public_url.strip() else ""

    def build(code: str) -> str:
        return f"{root}/sheet/{code}" if root else f"sheet:{code}"

    return build


def sheet_type_label(vendor: str | None, product_codes: Sequence[str], key: str) -> str:
    """``"<vendor> <first product code>"``, as the sheet list shows a type."""
    if vendor and product_codes:
        return f"{vendor} {product_codes[0]}"
    return product_codes[0] if product_codes else key


def margin_id_text(code: str, type_label: str) -> str:
    """The text of the margin ID: the code, then the type (spec 10.2)."""
    return f"{code} · {type_label}"


def id_cell_label(code: str, type_label: str, scan_payload: str) -> LabelData:
    """The label of the sheet ID cell: `qr_two_lines`, the code and the type (spec 10.2)."""
    return LabelData(
        source_app="hub",
        primary_id=code,
        title=f"{type_label} · sheet ID",
        qr_payload=scan_payload,
    )


# ---------------------------------------------------------------------------- items


@dataclass(frozen=True)
class ResolvedItem:
    label: LabelData
    content_type: ContentType
    meta: ItemMeta
    lookup: PrintLookupRequest | None


def default_purpose(title: str | None, primary_id: str | None) -> str:
    """A cell's purpose when the request gave none: the title, else the primary id, cleaned and
    cut to 120, never refused (OC-43). One rule for the print and for the retry of an old
    payload."""
    for candidate in (title, primary_id):
        if candidate:
            cleaned = sanitise_text(
                candidate[:_DEFAULT_PURPOSE_SCAN], max_len=_DEFAULT_PURPOSE_SCAN
            )
            if cleaned:
                return cleaned[:PURPOSE_MAX]
    return _FALLBACK_PURPOSE


def _purpose(item: SheetItem, label: LabelData) -> str:
    """The request's purpose, cleaned; else the title, else the primary id, cut to 120."""
    if item.purpose is not None:
        cleaned = sanitise_text(item.purpose, max_len=PURPOSE_MAX)
        if cleaned:
            return cleaned
    return default_purpose(label.title, label.primary_id)


def _capped_lookup_label(label: LabelData, index: int) -> LabelData:
    """A lookup's answer held to the caps of a raw item (``SheetRawLabelData``).

    Text is cut (``RAW_TEXT_MAX``), the lists keep their first ``RAW_SECONDARY_MAX`` lines and
    ``RAW_LISTING_MAX`` rows: a cell shows far less, and the renderer shortens the rest anyway.
    A QR payload is never cut, a cut payload is another code: one above ``MAX_QR_PAYLOAD``
    (the label's or a listing row's) is refused with the item's index. The integration is not
    trusted to stay small: a hostile one returned megabytes that the job row stored whole and
    every read key could fetch.
    """
    if len(label.qr_payload or "") > MAX_QR_PAYLOAD:
        # A scan URL is short, so this only fires on an odd integration base URL.
        raise ItemContentMismatchError(index, ("qr_payload",))
    rows = label.items[:RAW_LISTING_MAX]
    if any(len(row.qr_payload or "") > MAX_QR_PAYLOAD for row in rows):
        raise ItemContentMismatchError(index, ("qr_payload",))
    return label.model_copy(
        update={
            "source_app": label.source_app[:RAW_TEXT_MAX],
            "title": None if label.title is None else label.title[:RAW_TEXT_MAX],
            "primary_id": None if label.primary_id is None else label.primary_id[:RAW_TEXT_MAX],
            "secondary": tuple(line[:RAW_TEXT_MAX] for line in label.secondary[:RAW_SECONDARY_MAX]),
            "items": tuple(
                row.model_copy(update={"item": row.item[:RAW_TEXT_MAX]}) for row in rows
            ),
        }
    )


def _lookup_error(exc: Exception, index: int) -> ItemLookupFailedError | None:
    for cls, status, code, message in _LOOKUP_ERRORS:
        if isinstance(exc, cls):
            return ItemLookupFailedError(
                status=status, code=code, message=message, item_index=index
            )
    return None


async def resolve_items(items: Sequence[SheetItem], lookup: AppLookupService) -> list[ResolvedItem]:
    """Label data and record keeping per item, in request order.

    Identical lookups (same app and identifier) run once. Lookups run with at most
    ``LOOKUP_CONCURRENCY`` in flight. All of them finish before the
    answer: when several fail, the lowest index is reported, not the first to come back
    (pre-flight C11). An error that is none of the four lookup classes is a bug and propagates.
    """
    gate = asyncio.Semaphore(LOOKUP_CONCURRENCY)

    async def fetch(request: PrintLookupRequest) -> LabelData:
        async with gate:
            return await lookup.lookup(request.app, request.identifier)

    # One lookup per distinct (app, identifier); the answer fans out to every item that asked.
    wanted: dict[tuple[str, str], PrintLookupRequest] = {}
    for item in items:
        if item.lookup is not None:
            wanted.setdefault((item.lookup.app, item.lookup.identifier), item.lookup)
    fetched = dict(
        zip(
            wanted,
            await asyncio.gather(*(fetch(r) for r in wanted.values()), return_exceptions=True),
            strict=True,
        )
    )

    def raw_label(item: SheetItem) -> LabelData:
        assert item.data is not None  # the schema: exactly one of data and lookup
        raw = item.data
        return LabelData(
            source_app="manual",
            title=raw.title,
            primary_id=raw.primary_id,
            qr_payload=raw.qr_payload,
            secondary=raw.secondary,
            items=raw.items,
        )

    results: list[LabelData | BaseException] = [
        raw_label(it) if it.lookup is None else fetched[(it.lookup.app, it.lookup.identifier)]
        for it in items
    ]
    resolved: list[ResolvedItem] = []
    for index, (item, result) in enumerate(zip(items, results, strict=True)):
        if isinstance(result, BaseException):
            if isinstance(result, Exception):
                mapped = _lookup_error(result, index)
                if mapped is not None:
                    raise mapped from None
            raise result
        ref: str | None
        if item.lookup is not None:
            source = item.lookup.app
            ref = sanitise_text(item.lookup.identifier, max_len=PURPOSE_MAX) or None
        else:
            source = item.source or _DEFAULT_SOURCE
            ref = (sanitise_text(item.ref, max_len=PURPOSE_MAX) or None) if item.ref else None
        if item.lookup is not None:
            # A raw item is capped by the schema; a lookup's answer is capped here, before
            # the job row stores it whole (R10-6).
            result = _capped_lookup_label(result, index)
        resolved.append(
            ResolvedItem(
                label=result,
                content_type=item.content_type,
                meta=ItemMeta(source=source, purpose=_purpose(item, result), ref=ref),
                lookup=item.lookup,
            )
        )
    return resolved


# ---------------------------------------------------------------------------- views


@dataclass(frozen=True)
class _SheetInfo:
    """What the preview needs about a sheet beyond its ``SheetView``."""

    type_key: str
    version: int
    type_label: str
    hint: str | None  # the probable code of a sheet that does not exist yet


async def _info_of_existing(session: AsyncSession, view: SheetView) -> _SheetInfo:
    t = await repo.get_type_by_key(session, view.type_key)
    v = await session.get(SheetTypeVersion, view.type_version_id)
    if t is None or v is None:  # foreign keys make this unreachable
        raise SheetTypeNotFoundError()
    return _SheetInfo(t.key, v.version, sheet_type_label(t.vendor, t.product_codes, t.key), None)


def _next_hint(code: str, ahead: int) -> str:
    prefix, _, number = code.rpartition("-")
    return ss.format_code(prefix, int(number) + ahead)


async def _new_view(
    session: AsyncSession, placement: PlacementInModel, ahead: dict[str, int]
) -> tuple[SheetView, _SheetInfo]:
    """The view of a sheet this request would create, without creating it."""
    new = placement.new_sheet
    assert new is not None
    t: SheetType | None = await repo.get_type_by_key(session, new.type)
    if t is None:
        raise SheetTypeNotFoundError()
    if t.archived_at is not None:
        raise SheetTypeArchivedError()
    v = (
        await types_repo.current_version(session, t.id)
        if new.version is None
        else await types_repo.get_version(session, t.id, new.version)
    )
    if v is None:
        raise SheetTypeVersionNotFoundError()
    # Two new sheets of one type get consecutive hints (pre-flight C35).
    hint = _next_hint(await ss.peek_next_code(session, t.key), ahead.get(t.key, 0))
    ahead[t.key] = ahead.get(t.key, 0) + 1
    view = SheetView(
        code=None,
        type_key=t.key,
        type_version_id=v.id,
        geometry=version_geometry(v),
        allow_qr=t.allow_qr,
        non_free={},
        id_placement=new.id_placement,
        id_printed=False,
        has_hub_cell=False,
        margin_id_in_flight=False,
        state="active",
        code_hint=hint,
    )
    return view, _SheetInfo(
        t.key, v.version, sheet_type_label(t.vendor, t.product_codes, t.key), hint
    )


async def _placements(
    session: AsyncSession, request: SheetPrintRequest
) -> tuple[list[PlacementIn], dict[int, _SheetInfo], set[int]]:
    """Views for every placement. One sheet is one object (the planner's caller contract)."""
    by_code: dict[str, SheetView] = {}
    infos: dict[int, _SheetInfo] = {}
    new_views: set[int] = set()
    ahead: dict[str, int] = {}
    out: list[PlacementIn] = []
    for p in request.placements:
        if p.sheet is not None:
            view = by_code.get(p.sheet)
            if view is None:
                view = await load_sheet_view(session, p.sheet)
                by_code[p.sheet] = view
                infos[id(view)] = await _info_of_existing(session, view)
        else:
            view, info = await _new_view(session, p, ahead)
            infos[id(view)] = info
            new_views.add(id(view))
        cells = p.cells if isinstance(p.cells, str) else list(p.cells)
        out.append(PlacementIn(sheet=view, cells=cells, skip=list(p.skip), count=p.count))
    return out, infos, new_views


# ---------------------------------------------------------------------------- drawing


@dataclass(frozen=True)
class _CellJob:
    cell: int
    content_type: ContentType
    data: LabelData
    item_index: int | None  # None for the sheet ID cell


@dataclass
class _Drawn:
    images: list[tuple[int, CellImage]]
    truncated: set[int]
    png: bytes


def _px(mm: float, dpi: int) -> int:
    return max(1, round(mm / 25.4 * dpi))


def _qr_placeholder(image: Image.Image, edge_px: int) -> None:
    """Hatch the QR square of a cell image and write "QR" in it (the preview's stand-in for a
    symbol too fine for 150 dpi). Drawn on a square of its own and pasted, so nothing reaches
    the text beside it."""
    square = Image.new("1", (edge_px, edge_px), 1)
    draw = ImageDraw.Draw(square)
    draw.rectangle((0, 0, edge_px - 1, edge_px - 1), outline=0)
    step = max(4, edge_px // 10)
    for offset in range(-edge_px, edge_px, step):
        draw.line((offset, edge_px, offset + edge_px, 0), fill=0)
    font = load_cell_font(max(8, edge_px // 4))
    label = "QR"
    w = round(font.getlength(label))
    x, y = (edge_px - w) // 2, edge_px // 2
    draw.rectangle((x - 2, y - edge_px // 6, x + w + 2, y + edge_px // 6), fill=1)
    draw.text((x, y), label, font=font, fill=0, anchor="lm")
    image.paste(square, (0, 0))


def _qr_modules(payload: str) -> int | None:
    """Modules per side of the symbol ``build_qr`` makes for ``payload``; ``None`` if no QR
    holds it. Shares the version cache with ``build_qr``, so a payload is sized once."""
    version = qr_version(payload)
    return None if version is None else 17 + 4 * version


def _qr_fits_at(payload: str, w_mm: float, h_mm: float, dpi: int) -> bool:
    """The rule of ``build_qr`` by arithmetic: a whole-pixel module of at least one pixel
    inside four quiet modules per side."""
    modules = _qr_modules(payload)
    return modules is not None and qr_edge_px(w_mm, h_mm, dpi) >= modules + 8


def _render_cell(renderer: CellRenderer, box: BoxHmm, job: _CellJob, render_dpi: int) -> CellImage:
    """One cell at preview resolution (150 dpi, never more).

    The text is drawn by the renderer. A QR is drawn by ``build_qr_preview``: the symbol of the
    job, at the size the job prints it (whole-pixel modules at the job's resolution), scaled to
    150 dpi. A symbol too fine for 150 dpi gets a hatched "QR" box of the same size instead.
    Whether the job could draw it at all is arithmetic: if not even the job's resolution can, the
    item is drawn normally, which refuses it as a content mismatch (spec 12.5).
    """
    w_mm, h_mm = box.w / 100, box.h / 100

    def draw(data: LabelData) -> CellImage:
        return renderer.render(
            box_w_mm=w_mm,
            box_h_mm=h_mm,
            dpi=PREVIEW_DPI,
            content_type=job.content_type,
            data=data,
        )

    payload = job.data.qr_payload
    if (
        not payload
        or not job.content_type.value.startswith("qr_")
        or not _qr_fits_at(payload, w_mm, h_mm, render_dpi)
    ):
        return draw(job.data)
    cell = draw(job.data.model_copy(update={"qr_payload": "QR"}))  # the text, and the checks
    modules = _qr_modules(payload)
    if (
        modules is not None
        and modules <= PREVIEW_QR_MAX_MODULES
        and _qr_fits_at(payload, w_mm, h_mm, PREVIEW_DPI)
    ):
        symbol = build_qr_preview(payload, w_mm, h_mm, render_dpi, PREVIEW_DPI)
        assert symbol is not None  # the arithmetic above said it fits
        cell.image.paste(symbol, (0, 0))
    else:
        _qr_placeholder(cell.image, qr_edge_px(w_mm, h_mm, PREVIEW_DPI))
    return cell


def _draw_page(
    renderer: CellRenderer,
    geometry: Geometry,
    jobs: Sequence[_CellJob],
    margin: MarginIdPayload | None,
    feed_mark: FeedMarkPayload | None,
    render_dpi: int,
) -> _Drawn:
    """Everything CPU-bound for one page (run in a thread)."""
    token = PREVIEW_QR_MASK.set(0)  # a picture needs no mask search; the job's renderer has it
    try:
        images: list[tuple[int, CellImage]] = []
        truncated: set[int] = set()
        for job in jobs:
            try:
                image = _render_cell(renderer, content_box(geometry, job.cell), job, render_dpi)
            except ContentTypeDataMismatchError as exc:
                if job.item_index is None:
                    raise
                raise ItemContentMismatchError(job.item_index, exc.missing_fields) from None
            images.append((job.cell, image))
            if image.truncated:
                truncated.add(job.cell)
        png = render_preview_png(
            geometry, images, margin, render_dpi=render_dpi, feed_mark=feed_mark
        )
        return _Drawn(images, truncated, png)
    finally:
        PREVIEW_QR_MASK.reset(token)


# ---------------------------------------------------------------------------- preview

_render_gate: asyncio.Semaphore | None = None
_render_gate_loop: asyncio.AbstractEventLoop | None = None


def _gate() -> asyncio.Semaphore:
    """The process-wide cap on preview renders; rebuilt if the event loop changed (tests)."""
    global _render_gate, _render_gate_loop
    loop = asyncio.get_running_loop()
    if _render_gate is None or _render_gate_loop is not loop:
        _render_gate, _render_gate_loop = asyncio.Semaphore(MAX_CONCURRENT_RENDERS), loop
    return _render_gate


async def draw_page_bounded(*args: Any) -> Any:
    """``_draw_page`` in a thread, at most ``MAX_CONCURRENT_RENDERS`` at once in the process."""
    async with _gate():
        return await asyncio.to_thread(_draw_page, *args)


def _margin_payload(
    *,
    code: str,
    margin_id: bool,
    placement: MarginPlacement | None,
    feed_mark: FeedMarkPlacement | None,
    type_label: str,
    scan: Callable[[str], str],
) -> MarginIdPayload | None:
    """The one rule for a margin ID (OC-50), whoever asks.

    The text is ``margin_id_text``, the QR encodes ``scan(code)``, and when the feed-direction
    mark shares the top band the text ends ``MARGIN_TEXT_GAP_HMM`` before it. ``None`` when the
    page carries no margin ID.
    """
    if not margin_id or placement is None:
        return None
    text_end = (
        feed_mark.x_hmm - MARGIN_TEXT_GAP_HMM
        if feed_mark is not None and placement.band == "top"
        else None
    )
    return margin_id_payload(
        margin_id_text(code, type_label), scan(code), placement, text_end_hmm=text_end
    )


def page_margin_id_payload(
    page: PagePlan, type_label: str, scan: Callable[[str], str]
) -> MarginIdPayload | None:
    """The margin ID of a planned page, as the preview draws it.

    A sheet not created yet is named by its hint. The job builds the same payload from the
    reservation with ``reserved_margin_id_payload``; both go through one rule.
    """
    code = page.sheet.code or page.sheet.code_hint
    assert code is not None  # a view without a code carries its hint
    return _margin_payload(
        code=code,
        margin_id=page.margin_id,
        placement=page.margin_placement,
        feed_mark=page.feed_mark,
        type_label=type_label,
        scan=scan,
    )


def reserved_margin_id_payload(
    page: ReservedPage, type_label: str, scan: Callable[[str], str]
) -> MarginIdPayload | None:
    """The margin ID a job stores: the same rule as ``page_margin_id_payload``, applied to the
    reservation's decision (the sheet's code is known by now)."""
    return _margin_payload(
        code=page.sheet_code,
        margin_id=page.margin_id,
        placement=page.margin_placement,
        feed_mark=page.feed_mark,
        type_label=type_label,
        scan=scan,
    )


async def _reprint_hints(session: AsyncSession, items: Sequence[ResolvedItem]) -> list[ReprintHint]:
    """Where lookup items were printed before: ``used`` cells only (pre-flight C32)."""
    found: dict[tuple[str, str], list[ss.CellHit]] = {}
    hints: list[ReprintHint] = []
    for index, item in enumerate(items):
        if item.lookup is None:
            continue
        if item.meta.ref is None:
            continue
        key = (item.meta.source, item.meta.ref)
        if key not in found:
            found[key] = [
                h
                for h in await ss.find_cells(session, source=key[0], ref=key[1])
                if h.state == "used"
            ]
        hints.extend(
            ReprintHint(item_index=index, sheet_code=h.code, cell=h.cell, printed_at=h.updated_at)
            for h in found[key][:MAX_HINTS_PER_ITEM]
        )
    return hints


async def preview(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    printer: Printer,
    request: SheetPrintRequest,
    lookup: AppLookupService,
    renderer: CellRenderer,
    language: str | None,
) -> SheetPreview:
    """The plan and the pictures of a sheet print, written nowhere.

    Order: printer kind, the page bound (a plan has one page per placement, so it is known
    before anything is read or planned), tray, sheets and the plan (only the item count is
    needed), then the integration lookups, then the pictures. A refused request makes no lookup.
    ``language`` is the hub's ``general.language``; it picks the feed-direction mark's text.

    No database connection is held while the lookups run or the pictures are drawn (R10-1): the
    reads happen in one short session before them, the reprint hints in another one after.
    """
    if printer.backend != "ipp":
        raise MediaKindMismatchError()
    if len(request.placements) > MAX_PREVIEW_PAGES:  # R10-5: before any planning
        raise PreviewTooLargeError(len(request.placements), MAX_PREVIEW_PAGES)
    scan = scan_payload_builder(str(get_settings().public_url))
    async with session_factory() as session:
        tray = await calibration_service.resolve_tray(session, printer.id, request.tray)
        snapshot = await calibration_service.snapshot(session, printer.id, tray)
        facts: PrinterFacts = await load_printer_facts(session, printer.id)

        # Everything that needs only the item count comes before any integration call: a refused
        # request must not fire up to 500 lookups first.
        placements, infos, new_views = await _placements(session, request)
        margin = MarginContext(
            deviation=snapshot_to_deviation(snapshot),
            scan_payload=scan,
            render_dpi=facts.render_dpi,
            language=language,
        )
        # Planning is CPU work (margin and feed-mark geometry per page): off the event loop.
        result = await asyncio.to_thread(
            plan, placements, len(request.items), hw_margins_hmm=facts.margins_hmm, margin=margin
        )
        if len(result.pages) > MAX_PREVIEW_PAGES:  # one page per placement; kept as a guard
            raise PreviewTooLargeError(len(result.pages), MAX_PREVIEW_PAGES)

        tray_row = await session.get(PrinterTray, (printer.id, tray))
        load_hint = tray_row.load_hint if tray_row is not None else None
        # The cells of each existing sheet, read now so that the drawing needs no connection.
        sheet_cells: dict[UUID, dict[int, tuple[str, str | None]]] = {}
        for page in result.pages:
            sheet_id = page.sheet.sheet_id
            if sheet_id is not None and sheet_id not in sheet_cells:
                sheet_cells[sheet_id] = {
                    row.cell_no: (row.state, row.purpose)
                    for row in await repo.cells_of(session, sheet_id)
                }
    items = await resolve_items(request.items, lookup)

    pages: list[PreviewPage] = []
    taken_here: dict[int, dict[int, tuple[str, str | None]]] = {}  # earlier pages, same sheet
    next_item = 0
    for page in result.pages:
        view = page.sheet
        info = infos[id(view)]
        code = view.code or view.code_hint
        assert code is not None
        existing: dict[int, tuple[str, str | None]] = {}
        if view.sheet_id is not None:
            existing.update(sheet_cells[view.sheet_id])
        existing.update(taken_here.setdefault(id(view), {}))

        jobs: list[_CellJob] = []
        purposes: dict[int, tuple[int | None, str]] = {}
        mapped_cells: set[int] = set()
        if page.id_cell is not None:
            id_type, _ = map_content_type(ContentType.QR_TWO_LINES, view.allow_qr)
            id_label = id_cell_label(code, info.type_label, scan(code))
            jobs.append(_CellJob(page.id_cell, id_type, id_label, None))
            purposes[page.id_cell] = (None, ID_CELL_PURPOSE)
        for cell in page.item_cells:
            item = items[next_item]
            content_type, was_mapped = map_content_type(item.content_type, view.allow_qr)
            jobs.append(_CellJob(cell, content_type, item.label, next_item))
            purposes[cell] = (next_item, item.meta.purpose)
            if was_mapped:
                mapped_cells.add(cell)
            next_item += 1

        margin_payload = page_margin_id_payload(page, info.type_label, scan)
        mark = feed_mark_payload(page.feed_mark) if page.feed_mark is not None else None
        drawn = await draw_page_bounded(
            renderer, view.geometry, jobs, margin_payload, mark, facts.render_dpi
        )
        flagged = set(page.hw_margin_cells)
        cells: list[PreviewCell] = []
        for n in range(1, cell_count(view.geometry) + 1):
            if n in purposes:
                item_index, purpose = purposes[n]
                cells.append(
                    PreviewCell(
                        cell=n,
                        state="new",
                        is_id=n == page.id_cell,
                        purpose=purpose,
                        item_index=item_index,
                        truncated=n in drawn.truncated,
                        mapped=n in mapped_cells,
                        hw_margin=n in flagged,
                    )
                )
            else:
                cell_state, cell_purpose = existing.get(n, ("free", None))
                cells.append(
                    PreviewCell(
                        cell=n,
                        state=cell_state,  # type: ignore[arg-type]
                        is_id=False,
                        purpose=cell_purpose,
                        item_index=None,
                        truncated=False,
                        mapped=False,
                        hw_margin=False,
                    )
                )
        for n, (_item_index, purpose) in purposes.items():
            # What this page takes shows as reserved on a later page of the same sheet.
            taken_here[id(view)][n] = ("reserved", purpose)
        pages.append(
            PreviewPage(
                sheet_code=view.code,
                new_code_hint=info.hint,
                type_key=info.type_key,
                version=info.version,
                geometry=geometry_to_doc(view.geometry),
                cells=cells,
                png_base64=base64.b64encode(drawn.png).decode("ascii"),
                margin_id=page.margin_id,
                margin_band=page.margin_placement.band if page.margin_placement else None,
                id_not_printed=page.id_not_printed,
                feed_mark=page.feed_mark is not None,
                load_hint=load_hint,
            )
        )

    async with session_factory() as session:
        hints = await _reprint_hints(session, items)
    return SheetPreview(
        pages=pages,
        free_after=list(result.free_after),
        expected_cells=[
            ExpectedPageModel(sheet=e.sheet, cells=e.cells, id_cell=e.id_cell)
            for e in expected_of(result, new_views)
        ],
        reprint_hints=hints,
    )


# ---------------------------------------------------------------------------- print


class PageQueue(Protocol):
    """What the print needs of the print queue."""

    async def submit_page_job(
        self,
        printer_id: UUID,
        payload: PagePayload,
        *,
        api_key_id: UUID | None,
        source_ip: str | None,
        job_id: UUID | None = None,
    ) -> UUID: ...


def check_item_fits(
    item: ResolvedItem,
    index: int,
    *,
    allow_qr: bool,
    geometry: Geometry,
    cell: int,
    render_dpi: int,
) -> None:
    """Whether ``item`` can be drawn in ``cell`` of a sheet of this geometry (spec 12.5, C16).

    Maps the content type for the sheet type, checks the required fields exactly as the renderer
    does, and for a QR content type asks whether a symbol fits the cell's content box at the
    job's resolution. A failure names the item; the renderer would raise the same later, after
    the cells were reserved. The ID cell is not checked: the hub makes its label, and its QR
    is a short URL.
    """
    content_type, _ = map_content_type(item.content_type, allow_qr)
    try:
        check_required(content_type, item.label)
    except ContentTypeDataMismatchError as exc:
        raise ItemContentMismatchError(index, exc.missing_fields) from None
    box = content_box(geometry, cell)
    if not box_fits_a_line(box):  # a label too small to hold a line (or a negative box)
        raise ItemContentMismatchError(index, ("label_size",))
    qr_does_not_fit = content_type.value.startswith("qr_") and not _qr_fits_at(
        item.label.qr_payload or "", box.w / 100, box.h / 100, render_dpi
    )
    if qr_does_not_fit:
        raise ItemContentMismatchError(index, ("qr_payload",))


def _check_plan_items(
    plan_pages: Sequence[PagePlan], items: Sequence[ResolvedItem], dpi: int
) -> None:
    """``check_item_fits`` for every item at the cell the plan gives it (CPU: run in a thread)."""
    index = 0
    for page in plan_pages:
        for cell in page.item_cells:
            check_item_fits(
                items[index],
                index,
                allow_qr=page.sheet.allow_qr,
                geometry=page.sheet.geometry,
                cell=cell,
                render_dpi=dpi,
            )
            index += 1


def _placement_request(p: PlacementInModel, version: int | None = None) -> PlacementRequest:
    """The reservation's placement. ``version``: the concrete version of a new sheet, resolved
    and checked by the caller; a request that left it out is not allowed to get whatever is
    current when the reservation runs."""
    new = p.new_sheet
    return PlacementRequest(
        sheet_code=p.sheet,
        new_sheet=None
        if new is None
        else NewSheetIn(
            type_key=new.type,
            version=new.version if version is None else version,
            id_placement=new.id_placement,
        ),
        cells=p.cells if isinstance(p.cells, str) else list(p.cells),
        skip=list(p.skip),
        count=p.count,
    )


@dataclass(frozen=True)
class _TypeInfo:
    key: str
    label: str
    allow_qr: bool
    geometry: Geometry


async def _type_info(
    session: AsyncSession, version_id: UUID, cache: dict[UUID, _TypeInfo]
) -> _TypeInfo:
    """Type key, label and the **pinned** version's geometry (D14: never the current one)."""
    found = cache.get(version_id)
    if found is not None:
        return found
    version = await session.get(SheetTypeVersion, version_id)
    sheet_type = None if version is None else await session.get(SheetType, version.type_id)
    if version is None or sheet_type is None:  # foreign keys make this unreachable
        raise SheetTypeNotFoundError()
    info = _TypeInfo(
        sheet_type.key,
        sheet_type_label(sheet_type.vendor, sheet_type.product_codes, sheet_type.key),
        sheet_type.allow_qr,
        version_geometry(version),
    )
    cache[version_id] = info
    return info


def _cell_payload(
    item: ResolvedItem, index: int, cell: int, info: _TypeInfo, render_dpi: int
) -> SheetCellPayload:
    check_item_fits(
        item,
        index,
        allow_qr=info.allow_qr,
        geometry=info.geometry,
        cell=cell,
        render_dpi=render_dpi,
    )
    content_type, mapped = map_content_type(item.content_type, info.allow_qr)
    return SheetCellPayload(
        cell=cell,
        content_type=content_type,
        label_data=item.label.model_dump(mode="json"),
        mapped=mapped,
        source=item.meta.source,
        purpose=item.meta.purpose,
        ref=item.meta.ref,
    )


def _page_payload(
    page: ReservedPage,
    items: Sequence[ResolvedItem],
    info: _TypeInfo,
    *,
    tray: str,
    render_dpi: int,
    calibration: Any,
    scan: Callable[[str], str],
) -> PagePayload:
    """The ``sheet_page`` payload of one reserved page: everything the runner draws from."""
    cells: list[SheetCellPayload] = []
    id_cell: SheetCellPayload | None = None
    for a in page.assignments:
        if a.item_index is None:
            id_type, mapped = map_content_type(ContentType.QR_TWO_LINES, info.allow_qr)
            label = id_cell_label(page.sheet_code, info.label, scan(page.sheet_code))
            id_cell = SheetCellPayload(
                cell=a.cell,
                content_type=id_type,
                label_data=label.model_dump(mode="json"),
                mapped=mapped,
            )
        else:
            cells.append(_cell_payload(items[a.item_index], a.item_index, a.cell, info, render_dpi))
    mark = feed_mark_payload(page.feed_mark) if page.feed_mark is not None else None
    detail = SheetPageDetail(
        sheet_id=page.sheet_id,
        sheet_code=page.sheet_code,
        type_key=info.key,
        type_version_id=page.type_version_id,
        geometry=asdict(info.geometry),
        allow_qr=info.allow_qr,
        cells=cells,
        id_cell=id_cell,
        margin_id=reserved_margin_id_payload(page, info.label, scan),
        feed_mark=mark,
        job_summary={"sheet_code": page.sheet_code, "cell_count": len(cells)},
    )
    return PagePayload(
        kind="sheet_page",
        media=info.geometry.page_size,
        tray=tray,
        render_dpi=render_dpi,
        job_name=f"Sheet {page.sheet_code} · {len(cells)} labels",
        calibration=calibration,
        detail=detail.model_dump(mode="json"),
    )


async def _release_all(
    session_factory: async_sessionmaker[AsyncSession], job_ids: Sequence[UUID], bus: Any
) -> None:
    """Free the reservations of jobs that never reached the queue. One session each, so a
    failed one cannot hold up the next; a release that fails is logged (the startup sweep
    repairs what is left)."""
    for job_id in job_ids:
        try:
            async with session_factory() as session:
                await release(session, job_id, bus=bus)
        except Exception:
            logger.exception("could not release the reservation of job %s", job_id)


async def _job_row_exists(session_factory: async_sessionmaker[AsyncSession], job_id: UUID) -> bool:
    """Whether the jobs table holds the job. The queue's memory is not the answer: a submit that
    fails after its commit forgets the job, and the next start re-enqueues the row."""
    try:
        async with session_factory() as session:
            return await session.get(Job, job_id) is not None
    except Exception:
        logger.exception("could not look up job %s", job_id)
        return True  # unknown: keep the cells, the startup sweep settles them


async def _settle_batch(
    session_factory: async_sessionmaker[AsyncSession], batch_id: UUID, job_ids: list[str]
) -> None:
    """Rewrite the batch to the jobs that exist; a batch without any job is deleted."""
    try:
        async with session_factory() as session:
            row = await session.get(PrintBatch, batch_id)
            if row is None:
                return
            if job_ids:
                row.job_ids = job_ids
            else:
                await session.delete(row)
            await session.commit()
    except Exception:
        logger.exception("could not settle batch %s", batch_id)


async def _undo_partial_print(
    session_factory: async_sessionmaker[AsyncSession],
    reserved: Sequence[ReservedPage],
    submitted: list[UUID],
    batch_id: UUID | None,
    bus: Any,
    exc: BaseException,
) -> None:
    """After a failure: free the cells of pages that have no job, shrink the batch to the pages
    that do, and tell the client which those are (ruling T7-2).

    The failing page counts as queued if its ``jobs`` row exists (ruling T7-1)."""
    queued = list(submitted)
    pending = list(reserved[len(submitted) :])
    if pending and await _job_row_exists(session_factory, pending[0].job_id):
        queued.append(pending.pop(0).job_id)
    await _release_all(session_factory, [p.job_id for p in pending], bus)
    if batch_id is None:
        return
    ids = [str(j) for j in queued]
    await _settle_batch(session_factory, batch_id, ids)
    if not ids or not isinstance(exc, Exception):
        return
    if isinstance(exc, SheetApiError):
        exc.detail = {**(exc.detail or {}), "batch_id": str(batch_id), "job_ids": ids}
        return
    raise PrintInterruptedError(str(batch_id), ids) from exc


def _printed_page(page: ReservedPage) -> PrintedPage:
    return PrintedPage(
        job_id=page.job_id,
        sheet_code=page.sheet_code,
        cells=[a.cell for a in page.assignments if a.item_index is not None],
        id_cell=page.id_cell,
        margin_id=page.margin_id,
        margin_band=page.margin_placement.band if page.margin_placement else None,
        id_not_printed=page.id_not_printed,
        feed_mark=page.feed_mark is not None,
    )


async def _queue_pages(
    session_factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    *,
    printer: Printer,
    reserved: Sequence[ReservedPage],
    items: Sequence[ResolvedItem],
    tray: str,
    facts: PrinterFacts,
    snapshot: Any,
    scan: Callable[[str], str],
    queue: PageQueue,
    api_key_id: UUID | None,
    source_ip: str | None,
    actor: str,
    bus: Any,
) -> tuple[UUID, list[PrintedPage]]:
    """Payloads, the batch and the page jobs of reserved pages; the part of a print that follows
    the reservation, shared by ``print_sheets`` and ``create_sheet_with_id_label``.

    Everything that can fail without touching the queue comes first, so that the queue is the
    only failure point left once the first page is submitted. A failure frees the reservations
    of the page that failed and of every later one; pages already submitted stay, and their
    outcome handler settles them (``_undo_partial_print``).
    """
    printed: list[PrintedPage] = []
    batch_id: UUID | None = None
    try:
        types: dict[UUID, _TypeInfo] = {}
        payloads: list[PagePayload] = []
        for page in reserved:
            info = await _type_info(session, page.type_version_id, types)
            payloads.append(
                _page_payload(
                    page,
                    items,
                    info,
                    tray=tray,
                    render_dpi=facts.render_dpi,
                    calibration=snapshot,
                    scan=scan,
                )
            )
        # The batch exists before the first job and names all of them (ruling T7-2).
        batch = await batches_repo.create(
            session,
            PrintBatch(
                printer_id=printer.id,
                job_ids=[str(p.job_id) for p in reserved],
                created_by=actor,
            ),
        )
        batch_id = batch.id
        for page, payload in zip(reserved, payloads, strict=True):
            try:
                await queue.submit_page_job(
                    printer.id,
                    payload,
                    api_key_id=api_key_id,
                    source_ip=source_ip,
                    job_id=page.job_id,
                )
            except KeyError:
                raise PrinterUnavailableError() from None
            printed.append(_printed_page(page))
    except BaseException as exc:
        await asyncio.shield(
            _undo_partial_print(
                session_factory, reserved, [p.job_id for p in printed], batch_id, bus, exc
            )
        )
        raise
    assert batch_id is not None  # the loop ended without a failure
    return batch_id, printed


async def print_sheets(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    printer: Printer,
    request: SheetPrintRequest,
    lookup: AppLookupService,
    queue: PageQueue,
    actor: str,
    api_key_id: UUID | None,
    source_ip: str | None,
    language: str | None,
    bus: Any = None,
) -> SheetPrintResponse:
    """Print the items onto sheets: one page job per planned page, one batch for all of them.

    Order: printer kind, tray and the calibration snapshot (once, before anything is reserved),
    a dry plan for the cheap refusals, the integration lookups, the per-item check against the
    cell each item would get, then ``reserve`` (which compares ``expected_cells``), then per page
    payload and ``submit_page_job``. A failure after the reservation frees the reservations of
    the page that failed and of every later one; pages already submitted stay, and their
    outcome handler settles them. ``language`` is the hub's ``general.language``.
    """
    if printer.backend != "ipp":
        raise MediaKindMismatchError()
    scan = scan_payload_builder(str(get_settings().public_url))
    async with session_factory() as session:
        tray = await calibration_service.resolve_tray(session, printer.id, request.tray)
        snapshot = await calibration_service.snapshot(session, printer.id, tray)
        facts = await load_printer_facts(session, printer.id)
        margin = MarginContext(
            deviation=snapshot_to_deviation(snapshot),
            scan_payload=scan,
            render_dpi=facts.render_dpi,
            language=language,
        )
        # A plan on views read without the lock: it tells which cell each item would get, so a
        # sheet that does not exist or does not fit is refused before any lookup.
        views, infos, _ = await _placements(session, request)
        # The version of each new sheet, resolved once here: the fit check below and the
        # reservation then use the same geometry, whatever an admin adds meanwhile.
        pinned = [infos[id(v.sheet)].version for v in views]
        dry = await asyncio.to_thread(
            plan, views, len(request.items), hw_margins_hmm=facts.margins_hmm, margin=margin
        )
        await session.commit()  # no read transaction stays open while the lookups run
        items = await resolve_items(request.items, lookup)
        await asyncio.to_thread(_check_plan_items, dry.pages, items, facts.render_dpi)

        expected = (
            None
            if request.expected_cells is None
            else [ExpectedPage(e.sheet, list(e.cells), e.id_cell) for e in request.expected_cells]
        )
        reserved = await reserve(
            session,
            placements=[
                _placement_request(p, v) for p, v in zip(request.placements, pinned, strict=True)
            ],
            items=[i.meta for i in items],
            expected=expected,
            hw_margins_hmm=facts.margins_hmm,
            margin=margin,
            required_type_key=None,
            actor=actor,
            bus=bus,
        )

        batch_id, printed = await _queue_pages(
            session_factory,
            session,
            printer=printer,
            reserved=reserved,
            items=items,
            tray=tray,
            facts=facts,
            snapshot=snapshot,
            scan=scan,
            queue=queue,
            api_key_id=api_key_id,
            source_ip=source_ip,
            actor=actor,
            bus=bus,
        )
    return SheetPrintResponse(batch_id=batch_id, pages=printed)


async def create_sheet_with_id_label(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    printer: Printer,
    tray: str | None,
    new: NewSheetIn,
    queue: PageQueue,
    actor: str,
    api_key_id: UUID | None,
    source_ip: str | None,
    language: str | None,
    bus: Any = None,
) -> tuple[str, UUID]:
    """Create a sheet with its hand-marked cells and queue its ID-only job (spec 10.1, ``cell``).

    One reservation creates the sheet (counter step, hand marks and note), reserves the lowest
    free cell for the ID label and nothing else (``items=[]``, pre-flight C2/C31); the job goes
    through the same payload, batch and queue path as a print (``_queue_pages``). The job carries
    the feed-direction mark too (OC-58), in ``language`` as read when it is reserved. Returns the
    sheet's code and the job's id.

    A refusal before the reservation commits (no free cell, an archived type, a bad tray) leaves
    no sheet: the counter step rolls back with it. A failure after the commit keeps the sheet,
    frees the ID cell and says so: the error carries ``sheet_code``, and the ID goes onto the
    next job's first free cell (OC-40).
    """
    if printer.backend != "ipp":
        raise MediaKindMismatchError()
    scan = scan_payload_builder(str(get_settings().public_url))
    async with session_factory() as session:
        tray_key = await calibration_service.resolve_tray(session, printer.id, tray)
        snapshot = await calibration_service.snapshot(session, printer.id, tray_key)
        facts = await load_printer_facts(session, printer.id)
        margin = MarginContext(
            deviation=snapshot_to_deviation(snapshot),
            scan_payload=scan,
            render_dpi=facts.render_dpi,
            language=language,
        )
        await session.commit()  # no read transaction stays open into the reservation
        reserved = await reserve(
            session,
            placements=[PlacementRequest(sheet_code=None, new_sheet=new)],
            items=[],
            expected=None,
            hw_margins_hmm=facts.margins_hmm,
            margin=margin,
            required_type_key=None,
            actor=actor,
            bus=bus,
        )
        (page,) = reserved
        try:
            await _queue_pages(
                session_factory,
                session,
                printer=printer,
                reserved=reserved,
                items=[],
                tray=tray_key,
                facts=facts,
                snapshot=snapshot,
                scan=scan,
                queue=queue,
                api_key_id=api_key_id,
                source_ip=source_ip,
                actor=actor,
                bus=bus,
            )
        except SheetApiError as exc:
            exc.detail = {**(exc.detail or {}), "sheet_code": page.sheet_code}
            raise
        except Exception as exc:
            # The cell is free again (``_undo_partial_print``); the client still gets the sheet.
            logger.exception("ID-only job of sheet %s failed unexpectedly", page.sheet_code)
            raise SheetIdJobFailedError(page.sheet_code) from exc
    return page.sheet_code, page.job_id


# ---------------------------------------------------------------------------- margin check


@dataclass(frozen=True)
class MarginCheck:
    """Whether, where and how a sheet type's margin ID and feed mark fit a printer and tray.

    ``bands_mm`` are the uncapped depths (they can be negative); ``usable_mm`` is the depth that
    is drawn (capped). ``reason`` is set exactly when ``printable`` is false.
    """

    bands_mm: dict[str, float]
    band: MarginBand | None
    corner: MarginCorner | None
    usable_mm: float | None
    qr: bool
    printable: bool
    reason: str | None
    feed_mark: bool


NO_MARGIN_BAND_REASON: Final = "no margin band is 4 mm deep on this printer"


async def margin_check(
    session: AsyncSession,
    *,
    printer: Printer,
    type_key: str,
    tray: str | None,
    language: str | None,
) -> MarginCheck:
    """Where the margin ID of a new sheet of ``type_key`` would go on ``printer``, read-only.

    The same decisions the first job makes (OC-50), from the same inputs: the printer's hardware
    margins, the tray's calibration, the render resolution, the feed-direction mark in the hub's
    current language (it shortens the top band) and, as the QR payload, the code the next sheet
    of the type will probably get (spec 10.1). Nothing is written and no lock is taken.
    """
    if printer.backend != "ipp":
        raise MediaKindMismatchError()
    sheet_type = await repo.get_type_by_key(session, type_key)
    if sheet_type is None:
        raise SheetTypeNotFoundError()
    version = await types_repo.current_version(session, sheet_type.id)
    if version is None:  # every type has a version
        raise SheetTypeVersionNotFoundError()
    geometry = version_geometry(version)
    tray_key = await calibration_service.resolve_tray(session, printer.id, tray)
    deviation = snapshot_to_deviation(
        await calibration_service.snapshot(session, printer.id, tray_key)
    )
    facts = await load_printer_facts(session, printer.id)
    payload = scan_payload_builder(str(get_settings().public_url))(
        await ss.peek_next_code(session, sheet_type.key)
    )
    mark = choose_feed_mark(
        geometry, hw=facts.margins_hmm, dev=deviation, text=feed_mark_text(language)
    )
    placement = choose_margin_placement(
        geometry,
        hw=facts.margins_hmm,
        dev=deviation,
        payload=payload,
        dpi=facts.render_dpi,
        top_taken_hmm=0 if mark is None else feed_mark_top_taken_hmm(geometry, mark),
    )
    bands = margin_bands_hmm(geometry, hw=facts.margins_hmm, dev=deviation)
    return MarginCheck(
        bands_mm={band: hmm_to_mm(depth) for band, depth in bands.items()},
        band=None if placement is None else placement.band,
        corner=None if placement is None else placement.corner,
        usable_mm=None if placement is None else hmm_to_mm(placement.depth_hmm),
        qr=placement is not None and placement.qr,
        printable=placement is not None,
        reason=NO_MARGIN_BAND_REASON if placement is None else None,
        feed_mark=mark is not None,
    )


# ---------------------------------------------------------------------------- retry


def _retry_meta(cell: SheetCellPayload) -> ItemMeta:
    """The record keeping of a cell of the failed job, from its payload. A payload stored before
    the record was kept falls back to what the label says (no ``ref``)."""
    label = cell.label_data
    title, primary_id = label.get("title"), label.get("primary_id")
    return ItemMeta(
        source=cell.source or str(label.get("source_app") or _DEFAULT_SOURCE),
        purpose=cell.purpose
        or default_purpose(
            title if isinstance(title, str) else None,
            primary_id if isinstance(primary_id, str) else None,
        ),
        ref=cell.ref,
    )


async def retry_sheet_page(
    session_factory: async_sessionmaker[AsyncSession],
    queue: PageQueue,
    job: Job,
    *,
    actor: str,
    settings_store: SettingsStore,
    api_key_id: UUID | None = None,
    source_ip: str | None = None,
    bus: Any = None,
) -> UUID:
    """Retry a failed or cancelled ``sheet_page`` job: the same cells on the same sheet, a new job.

    Allowed when no cell is still waiting for confirmation (OC-42, ``cells_unconfirmed``); the
    labels stay as the first attempt stored them (no new lookup). The cells are reserved again
    for a new job id, the ID cell where it was (``cells_taken`` with the numbers if any is no
    longer free). Everything that depends on the printer is decided again: a fresh calibration
    snapshot (spec 11.4; a removed or disabled tray answers ``tray_unknown``), the render dpi, and
    whether the margin ID and the feed mark are still due and where they go. The page is queued
    at once. A failure after the reservation frees it unless the job row exists.
    """
    payload = PagePayload.model_validate(job.payload)  # ValueError: not a usable stored payload
    detail = SheetPageDetail.model_validate(payload.detail)
    if detail.sheet_code is None:
        raise ValueError("the stored page names no sheet")
    scan = scan_payload_builder(str(get_settings().public_url))
    language = settings_store.get("general.language")
    new_id = uuid4()
    async with session_factory() as session:
        unconfirmed = await repo.unconfirmed_cells_of_job(session, job.id)
        if unconfirmed:
            raise CellsUnconfirmedError(unconfirmed)
        snapshot = await calibration_service.snapshot(session, job.printer_id, payload.tray)
        facts = await load_printer_facts(session, job.printer_id)
        margin = MarginContext(
            deviation=snapshot_to_deviation(snapshot),
            scan_payload=scan,
            render_dpi=facts.render_dpi,
            language=None if language is None else str(language),
        )
        page = await reserve_exact(
            session,
            job_id=new_id,
            sheet_code=detail.sheet_code,
            cells=[(c.cell, _retry_meta(c)) for c in detail.cells],
            id_cell=None if detail.id_cell is None else detail.id_cell.cell,
            hw_margins_hmm=facts.margins_hmm,
            margin=margin,
            actor=actor,
            bus=bus,
        )
        try:
            info = await _type_info(session, page.type_version_id, {})
            new_detail = detail.model_copy(
                update={
                    "id_cell": detail.id_cell if page.id_cell is not None else None,
                    "margin_id": reserved_margin_id_payload(page, info.label, scan),
                    "feed_mark": (
                        feed_mark_payload(page.feed_mark) if page.feed_mark is not None else None
                    ),
                }
            )
            new_payload = payload.model_copy(
                update={
                    "render_dpi": facts.render_dpi,
                    "calibration": snapshot,
                    "detail": new_detail.model_dump(mode="json"),
                }
            )
            try:
                await queue.submit_page_job(
                    job.printer_id,
                    new_payload,
                    api_key_id=api_key_id,
                    source_ip=source_ip,
                    job_id=new_id,
                )
            except KeyError:
                raise PrinterUnavailableError() from None
        except BaseException as exc:
            await asyncio.shield(_undo_partial_print(session_factory, [page], [], None, bus, exc))
            raise
    return new_id
