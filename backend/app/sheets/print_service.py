"""Printing onto sheets: item resolution and the read-only preview (spec 12.6, 15).

``resolve_items`` turns each requested item into label data, by an integration lookup or from
the raw data of the request. It runs before anything is written and outside any lock.

``preview`` plans with the planner on views built the way a reservation builds them, but never
takes the write lock and never writes: a sheet that does not exist yet is a view with a
``code_hint``, and the counter is only read. The result is a plan plus a 150 dpi PNG of the new
content per page. Calibration is not applied to the picture; the tray's deviation only decides
the margin band, as it does for the job (OC-50).
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Final

import qrcode
import qrcode.constants
import qrcode.exceptions
from PIL import Image, ImageDraw
from sqlalchemy.ext.asyncio import AsyncSession

from app.calibration import service as calibration_service
from app.config import get_settings
from app.models.printer import Printer
from app.models.printer_tray import PrinterTray
from app.models.sheet import SheetType, SheetTypeVersion
from app.printer_backends.exceptions import ContentTypeDataMismatchError
from app.repositories import sheet_types as types_repo
from app.repositories import sheets as repo
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.print_request import PrintLookupRequest
from app.schemas.sheet_print import (
    ExpectedPageModel,
    PlacementInModel,
    PreviewCell,
    PreviewPage,
    ReprintHint,
    SheetItem,
    SheetPreview,
    SheetPrintRequest,
)
from app.services.errors import AppLookupNotFoundError, IntegrationNotConfiguredError
from app.services.lookup_service import AppLookupService, LookupFailedError, UnknownAppError
from app.services.page_jobs import snapshot_to_deviation
from app.sheets import sheet_service as ss
from app.sheets.cell_render import (
    BoxHmm,
    CellImage,
    CellRenderer,
    content_box,
    load_cell_font,
    map_content_type,
    qr_edge_px,
)
from app.sheets.errors import (
    ItemContentMismatchError,
    ItemLookupFailedError,
    MediaKindMismatchError,
    PreviewTooLargeError,
    SheetTypeArchivedError,
    SheetTypeNotFoundError,
    SheetTypeVersionNotFoundError,
)
from app.sheets.exchange import geometry_to_doc
from app.sheets.geometry import Geometry, cell_count
from app.sheets.planner import (
    MARGIN_TEXT_GAP_HMM,
    MarginContext,
    PagePlan,
    PlacementIn,
    SheetView,
    plan,
)
from app.sheets.printer_facts import PrinterFacts, load_printer_facts
from app.sheets.reservation import ID_CELL_PURPOSE, ItemMeta, expected_of, load_sheet_view
from app.sheets.sheet_page import (
    PREVIEW_DPI,
    FeedMarkPayload,
    MarginIdPayload,
    feed_mark_payload,
    margin_id_payload,
    render_preview_png,
)
from app.sheets.text import sanitise_text
from app.sheets.type_service import version_geometry

__all__ = [
    "LOOKUP_CONCURRENCY",
    "MAX_PREVIEW_PAGES",
    "ResolvedItem",
    "id_cell_label",
    "margin_id_text",
    "page_margin_id_payload",
    "preview",
    "resolve_items",
    "scan_payload_builder",
    "sheet_type_label",
]

LOOKUP_CONCURRENCY: Final = 8
MAX_CONCURRENT_RENDERS: Final = 2  # preview renders at once, process-wide (spec 18, CPU)
MAX_PREVIEW_PAGES: Final = 10  # a plan decision, not the spec's (spec 18, CPU)
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


def _purpose(item: SheetItem, label: LabelData) -> str:
    """The request's purpose, cleaned; else the title, else the primary id, cut to 120."""
    if item.purpose is not None:
        cleaned = sanitise_text(item.purpose, max_len=PURPOSE_MAX)
        if cleaned:
            return cleaned
    for candidate in (label.title, label.primary_id):
        if candidate:
            cleaned = sanitise_text(
                candidate[:_DEFAULT_PURPOSE_SCAN], max_len=_DEFAULT_PURPOSE_SCAN
            )
            if cleaned:
                return cleaned[:PURPOSE_MAX]
    return _FALLBACK_PURPOSE


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
    symbol too fine for 150 dpi)."""
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, edge_px - 1, edge_px - 1), fill=1, outline=0)
    step = max(4, edge_px // 10)
    for offset in range(-edge_px, edge_px, step):
        draw.line((offset, edge_px, offset + edge_px, 0), fill=0)
    font = load_cell_font(max(8, edge_px // 4))
    label = "QR"
    w = round(font.getlength(label))
    x, y = (edge_px - w) // 2, edge_px // 2
    draw.rectangle((x - 2, y - edge_px // 6, x + w + 2, y + edge_px // 6), fill=1)
    draw.text((x, y), label, font=font, fill=0, anchor="lm")


MAX_QR_CHARS: Final = 4296  # the most any QR symbol holds; a longer payload can never fit


def _qr_modules(payload: str) -> int | None:
    """Modules per side of the symbol ``build_qr`` makes for ``payload``; ``None`` if no QR
    holds it. A payload longer than ``MAX_QR_CHARS`` is answered here and never reaches the
    cache, so every cache key is at most that long (512 keys cannot pin much memory)."""
    if len(payload) > MAX_QR_CHARS:
        return None
    return _qr_modules_cached(payload)


@lru_cache(maxsize=512)
def _qr_modules_cached(payload: str) -> int | None:
    """Cached: making a dense symbol is the slow part of a preview."""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    try:
        qr.add_data(payload)
        qr.make(fit=True)
    except (qrcode.exceptions.DataOverflowError, ValueError):
        return None
    return len(qr.get_matrix())


def _qr_fits_at(payload: str, w_mm: float, h_mm: float, dpi: int) -> bool:
    """The rule of ``build_qr`` by arithmetic: a whole-pixel module of at least one pixel
    inside four quiet modules per side."""
    modules = _qr_modules(payload)
    return modules is not None and qr_edge_px(w_mm, h_mm, dpi) >= modules + 8


def _render_cell(renderer: CellRenderer, box: BoxHmm, job: _CellJob, render_dpi: int) -> CellImage:
    """One cell at preview resolution (150 dpi, never more).

    A dense QR can need modules finer than one pixel at 150 dpi and still print at the job's
    resolution. The preview does not render at the job's resolution (CPU); it draws the cell with
    a hatched "QR" box where the symbol goes. Whether the job could draw it is decided by
    arithmetic: if not even the job's resolution can, the item is drawn normally, which refuses
    it as a content mismatch (spec 12.5).
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
        payload
        and job.content_type.value.startswith("qr_")
        and render_dpi > PREVIEW_DPI
        and not _qr_fits_at(payload, w_mm, h_mm, PREVIEW_DPI)
        and _qr_fits_at(payload, w_mm, h_mm, render_dpi)
    ):
        cell = draw(job.data.model_copy(update={"qr_payload": "QR"}))
        _qr_placeholder(cell.image, qr_edge_px(w_mm, h_mm, PREVIEW_DPI))
        return cell
    return draw(job.data)


def _draw_page(
    renderer: CellRenderer,
    geometry: Geometry,
    jobs: Sequence[_CellJob],
    margin: MarginIdPayload | None,
    feed_mark: FeedMarkPayload | None,
    render_dpi: int,
) -> _Drawn:
    """Everything CPU-bound for one page (run in a thread)."""
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
    png = render_preview_png(geometry, images, margin, render_dpi=render_dpi, feed_mark=feed_mark)
    return _Drawn(images, truncated, png)


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


def page_margin_id_payload(
    page: PagePlan, type_label: str, scan: Callable[[str], str]
) -> MarginIdPayload | None:
    """The margin ID of a planned page, as the preview draws it and as a job must store it.

    One rule for both (OC-50): the text is ``margin_id_text``, the QR encodes ``scan(code)`` of
    the sheet's code or, for a sheet not created yet, its hint, and when the feed-direction mark
    shares the top band the text ends ``MARGIN_TEXT_GAP_HMM`` before it. ``None`` when the page
    carries no margin ID.
    """
    placement = page.margin_placement
    if not page.margin_id or placement is None:
        return None
    code = page.sheet.code or page.sheet.code_hint
    assert code is not None  # a view without a code carries its hint
    text_end = (
        page.feed_mark.x_hmm - MARGIN_TEXT_GAP_HMM
        if page.feed_mark is not None and placement.band == "top"
        else None
    )
    return margin_id_payload(
        margin_id_text(code, type_label), scan(code), placement, text_end_hmm=text_end
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
    session: AsyncSession,
    *,
    printer: Printer,
    request: SheetPrintRequest,
    lookup: AppLookupService,
    renderer: CellRenderer,
    language: str | None,
) -> SheetPreview:
    """The plan and the pictures of a sheet print, written nowhere.

    Order: printer kind and tray, sheets and the plan (only the item count is needed), the page
    bound, then the integration lookups, then the pictures. A refused request makes no lookup.
    ``language`` is the hub's ``general.language``; it picks the feed-direction mark's text.
    """
    if printer.backend != "ipp":
        raise MediaKindMismatchError()
    tray = await calibration_service.resolve_tray(session, printer.id, request.tray)
    snapshot = await calibration_service.snapshot(session, printer.id, tray)
    facts: PrinterFacts = await load_printer_facts(session, printer.id)

    # Everything that needs only the item count comes before any integration call: a refused
    # request must not fire up to 500 lookups first.
    placements, infos, new_views = await _placements(session, request)
    scan = scan_payload_builder(str(get_settings().public_url))
    margin = MarginContext(
        deviation=snapshot_to_deviation(snapshot),
        scan_payload=scan,
        render_dpi=facts.render_dpi,
        language=language,
    )
    result = plan(placements, len(request.items), hw_margins_hmm=facts.margins_hmm, margin=margin)
    if len(result.pages) > MAX_PREVIEW_PAGES:
        raise PreviewTooLargeError(len(result.pages), MAX_PREVIEW_PAGES)
    items = await resolve_items(request.items, lookup)

    tray_row = await session.get(PrinterTray, (printer.id, tray))
    load_hint = tray_row.load_hint if tray_row is not None else None

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
            for row in await repo.cells_of(session, view.sheet_id):
                existing[row.cell_no] = (row.state, row.purpose)
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

    return SheetPreview(
        pages=pages,
        free_after=list(result.free_after),
        expected_cells=[
            ExpectedPageModel(sheet=e.sheet, cells=e.cells, id_cell=e.id_cell)
            for e in expected_of(result, new_views)
        ],
        reprint_hints=await _reprint_hints(session, items),
    )
