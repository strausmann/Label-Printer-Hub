"""Capabilities of a printer, from the status cache (no live call, no connection details)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.api.dependencies.printer_runtime import get_printer_runtime
from app.auth.dependencies import AuthContext, check_printer_access
from app.auth.scope_deps import require_read
from app.calibration import service as calibration_service
from app.config import get_settings
from app.db.session import get_session
from app.models.printer import Printer
from app.models.printer_status_cache import PrinterStatusCache
from app.models.printer_tray import PrinterTray
from app.printer_backends.ipp.attributes import Margins, ProbeSummary
from app.printer_models.pt import PTP750WDriver
from app.printer_models.ql import QL820NWBDriver
from app.printer_models.registry import ModelNotFoundError, ModelRegistry
from app.schemas.capabilities import (
    Capabilities,
    HardwareMargins,
    PageMedia,
    PageResolution,
    PageSize,
    TapeMedia,
    TapeResolution,
    TrayCapability,
)
from app.schemas.tape_geometry import TAPE_GEOMETRY
from app.services.printer_runtime import PrinterRuntime
from app.services.status_freshness import backoff_of, is_stale
from app.sheets.errors import PrinterNotFoundError
from app.sheets.printer_facts import facts_of, read_status

router = APIRouter(prefix="/api/v1/printers", tags=["printers"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadDep = Annotated[AuthContext, Depends(require_read)]
RuntimeDep = Annotated[PrinterRuntime | None, Depends(get_printer_runtime)]
PrinterPath = Annotated[UUID, Path(description="Printer id.")]

_SIZE = re.compile(
    r"^[a-z0-9]+_(?P<name>[a-z0-9-]+)_(?P<w>\d+(?:\.\d+)?)x(?P<h>\d+(?:\.\d+)?)(?P<unit>mm|in)$"
)


def _page_sizes(names: list[str]) -> list[PageSize]:
    """PWG self-describing names such as ``iso_a4_210x297mm``; anything else is skipped."""
    sizes: list[PageSize] = []
    for raw in names:
        m = _SIZE.match(raw)
        if m is None or raw.startswith("custom_"):
            continue
        factor = 25.4 if m["unit"] == "in" else 1.0
        name = m["name"].upper() if len(m["name"]) <= 3 else m["name"].replace("-", " ").title()
        sizes.append(
            PageSize(
                name=name,
                width_mm=round(float(m["w"]) * factor, 2),
                height_mm=round(float(m["h"]) * factor, 2),
            )
        )
    return sizes


def _page_media(summary: ProbeSummary, margins: Margins | None) -> PageMedia:
    return PageMedia(
        page_sizes=_page_sizes(summary.media_sizes),
        media_type_settable=summary.media_col_supported
        and "media-type" in summary.media_col_members,
        media_types=summary.media_types,
        hardware_margins_mm=None
        if margins is None
        else HardwareMargins(
            top=margins.top / 100,
            left=margins.left / 100,
            bottom=margins.bottom / 100,
            right=margins.right / 100,
        ),
    )


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _driver_dpi(model: str) -> tuple[int, int]:
    """The driver's dpi. The registry is asked first; the shipped drivers are the fallback,
    because the QL driver is not an entry point and registers only when its module is imported."""
    ModelRegistry.ensure_discovered()
    try:
        return ModelRegistry.find_by_model_id(model).dpi
    except ModelNotFoundError:
        for driver in (PTP750WDriver, QL820NWBDriver):
            if driver.model_id == model:
                return driver.dpi
        raise


def _tape(printer: Printer, parsed: dict[str, Any], captured: datetime | None) -> Capabilities:
    try:
        dpi_x, dpi_y = _driver_dpi(printer.model)
    except ModelNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "printer_model_unknown",
                "error_message": "No driver is registered for this printer's model.",
                "error_detail": None,
            },
        ) from None
    media: TapeMedia | None = None
    width = parsed.get("loaded_tape_mm")
    geometry = TAPE_GEOMETRY.get(width) if isinstance(width, int) else None
    if isinstance(width, int) and geometry is not None:
        media = TapeMedia(
            width_mm=width,
            type=None,  # the status cache carries no tape type
            printable_px=geometry.printable_px,
            printable_mm=round(geometry.printable_px / dpi_y * 25.4, 2),
        )
    return Capabilities(
        kind="tape",
        resolution_dpi=TapeResolution(x=dpi_x, y=dpi_y),
        media=media,
        trays=None,
        document_formats=None,
        captured_at=captured,
    )


async def _page(
    session: AsyncSession, printer: Printer, parsed: dict[str, Any], captured: datetime | None
) -> Capabilities:
    status_read = read_status(parsed)
    record = status_read.record
    facts = facts_of(status_read)
    rows = (
        (
            await session.execute(
                select(PrinterTray)
                .where(col(PrinterTray.printer_id) == printer.id)
                .order_by(col(PrinterTray.tray_key))
            )
        )
        .scalars()
        .all()
    )
    calibrations = {c.tray: c for c in await calibration_service.get_all(session, printer.id)}
    if status_read.never_answered:  # the producer's placeholder: nothing is known yet
        captured = None
    loaded = {t.key: t.media for t in record.trays} if record else {}
    trays = []
    for t in rows:
        cal = calibrations.get(t.tray_key)
        trays.append(
            TrayCapability(
                key=t.tray_key,
                label=t.label,
                load_hint=t.load_hint,
                enabled=t.enabled,
                is_default=t.is_default,
                media=loaded.get(t.tray_key),
                calibration=cal if cal is not None and cal.method is not None else None,
            )
        )
    summary = record.summary if record else None
    dpis = facts.resolutions_dpi
    return Capabilities(
        kind="page",
        resolution_dpi=PageResolution(max=max(dpis) if dpis else None, supported=dpis),
        media=_page_media(summary, facts.margins_hmm) if summary else None,
        trays=trays,
        document_formats=None
        if summary is None
        else (["application/pdf"] if summary.pdf_supported else []),
        captured_at=captured,
    )


@router.get(
    "/{printer_id}/capabilities",
    response_model=Capabilities,
    responses={
        status.HTTP_409_CONFLICT: {
            "description": (
                "No driver is registered for the tape printer's model (`printer_model_unknown`)."
            )
        }
    },
    summary="Capabilities of a tape or page printer (cache only)",
    description=(
        "Resolution, media, trays with their calibration and accepted document formats. Served "
        "from the status cache: the printer is never contacted, so a printer that has not been "
        "probed yet answers 200 with ``media`` and ``captured_at`` null. No connection detail "
        "is part of the answer. A page printer that never answered a probe is reported as unknown "
        "(``media``, ``document_formats`` and ``captured_at`` null). A tape width without a "
        "geometry entry also gives ``media`` null. A stale reading or an unpolled printer is "
        "reported as unknown too (``media`` null, ``stale`` true, ``captured_at`` kept). "
        "Only enabled trays carry a calibration."
    ),
)
async def get_capabilities(
    printer_id: PrinterPath, session: SessionDep, auth: ReadDep, runtime: RuntimeDep = None
) -> Capabilities:
    check_printer_access(auth, printer_id)
    printer = await session.get(Printer, printer_id)
    if printer is None:
        raise PrinterNotFoundError().to_http()
    row = await session.get(PrinterStatusCache, printer_id)
    parsed = (row.parsed if row is not None else None) or {}
    captured = _utc(row.captured_at) if row is not None else None
    # A reading nobody refreshes (stale) or nobody takes (unpolled) is unknown, not current.
    unpolled = runtime is None or not runtime.is_polled(printer_id)
    stale = row is not None and is_stale(
        row.updated_at, datetime.now(UTC), get_settings().sse_probe_interval_s, backoff_of(parsed)
    )
    unknown = row is not None and (unpolled or stale)
    if unknown:
        parsed = {}
    caps = (
        await _page(session, printer, parsed, captured)
        if printer.backend == "ipp"
        else _tape(printer, parsed, captured)
    )
    return caps.model_copy(update={"stale": True}) if unknown else caps
