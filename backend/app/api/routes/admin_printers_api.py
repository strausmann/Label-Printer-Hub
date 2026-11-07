"""JSON-Admin-API für Drucker-Verwaltung (Issue #124, Task 3.1).

Nur JSON — keine HTML-/Web-Routes, kein CSRF. Frontend (Go) folgt in Phase 7.

Routes
------
GET    /api/v1/admin/printers                   — Liste aller Drucker
POST   /api/v1/admin/printers                   — Neuen Drucker anlegen (201)
GET    /api/v1/admin/printers/{slug}            — Einzelner Drucker (200, 404)
PUT    /api/v1/admin/printers/{slug}            — Drucker aktualisieren (200, 404)
POST   /api/v1/admin/printers/{slug}/disable    — Drucker deaktivieren (200, 404, 409)
POST   /api/v1/admin/printers/{slug}/enable     — Drucker aktivieren (200, 404, 409)
POST   /api/v1/admin/printers/ipp/probe         — read an IPP printer live (200, 422, 502)

The probe makes the hub connect to an admin-supplied URI (SSRF surface, spec 18): admin
only; ``ipp``/``ipps``/``http``/``https`` without user info; the client's timeouts, 1 MB
cap and no redirects; the answer is the bounded summary, never raw attributes; errors
never repeat the URI or the printer's answer beyond the IPP status name.

Auth
----
Alle Endpoints erfordern ``admin``-Scope (API-Key mit scope=admin).
Pangolin-SSO und claude-automation-Bypass gewähren nur ``read`` — kein Zugriff.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin
from app.db.session import get_session
from app.models.printer import Printer
from app.models.printer_tray import PrinterTray
from app.printer_backends.ipp.attributes import ProbeSummary
from app.schemas.printer_admin import IppConnection, PrinterCreatePayload, PrinterUpdatePayload
from app.services.event_bus import BusEvent, EventBus
from app.services.printer_admin_service import (
    IPP_BACKEND,
    ConnectionKindMismatchError,
    DuplicateNameError,
    DuplicateSlugError,
    IppTransportFactory,
    PrinterAdminService,
    PrinterAlreadyDisabledError,
    PrinterAlreadyEnabledError,
    PrinterNotFoundBySlugError,
    TraysNotAllowedError,
    probe_ipp,
)
from app.sheets.errors import SheetApiError

router = APIRouter(prefix="/api/v1/admin/printers", tags=["admin"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
AdminAuthDep = Annotated[AuthContext, Depends(require_admin)]


# ---------------------------------------------------------------------------
# Response-Schema
# ---------------------------------------------------------------------------


class TrayRead(BaseModel):
    """A configured tray of a page printer."""

    key: str
    label: str
    load_hint: str | None
    enabled: bool
    is_default: bool


class PrinterRead(BaseModel):
    """Lesbare Darstellung eines Druckers.

    Enthält alle DB-Felder — keine internen Implementierungsdetails.
    ``trays`` is the tray list of a page printer and ``null`` for tape printers.
    """

    id: UUID
    name: str
    slug: str
    model: str
    backend: str
    connection: dict[str, Any]
    queue: dict[str, Any]
    cut_defaults: dict[str, Any]
    enabled: bool
    created_at: str
    updated_at: str
    trays: list[TrayRead] | None = None


def _ipp_transport_factory(request: Request) -> IppTransportFactory | None:
    """Test injection point: ``app.state.ipp_transport_factory`` (``None`` = real network).

    Only tests (and the browser-test app) set it, to hand the IPP client a transport into
    a fake printer. Production never sets it.
    """
    factory: IppTransportFactory | None = getattr(request.app.state, "ipp_transport_factory", None)
    return factory


def _service(session: AsyncSession, auth: AuthContext, request: Request) -> PrinterAdminService:
    return PrinterAdminService(
        session,
        audit_user=_audit_user(auth),
        ipp_transport_factory=_ipp_transport_factory(request),
    )


def _tray_read(tray: PrinterTray) -> TrayRead:
    return TrayRead(
        key=tray.tray_key,
        label=tray.label,
        load_hint=tray.load_hint,
        enabled=tray.enabled,
        is_default=tray.is_default,
    )


async def _read(svc: PrinterAdminService, printer: Printer) -> PrinterRead:
    view = _row_to_read(printer)
    if printer.backend == IPP_BACKEND:
        view.trays = [_tray_read(t) for t in await svc.list_trays(printer.id)]
    return view


def _row_to_read(printer: Printer) -> PrinterRead:
    """Konvertiert eine Printer-DB-Row in das API-Response-Schema."""
    return PrinterRead(
        id=printer.id,
        name=printer.name,
        slug=printer.slug,
        model=printer.model,
        backend=printer.backend,
        connection=printer.connection or {},
        queue={"timeout_s": printer.queue_timeout_s},
        cut_defaults={"half_cut": printer.cut_defaults_half_cut},
        enabled=printer.enabled,
        created_at=printer.created_at.isoformat() if printer.created_at else "",
        updated_at=printer.updated_at.isoformat() if printer.updated_at else "",
    )


def _publish_changed(
    request: Request,
    printer: Printer,
    change: Literal["created", "updated", "disabled", "enabled"],
) -> None:
    """Tell open event streams that the printer list changed (the service stays DB-only)."""
    bus: EventBus | None = getattr(request.app.state, "event_bus", None)
    if bus is None:
        return
    bus.publish(
        "hub",
        BusEvent(
            channel="hub",
            event_id=bus.next_event_id("hub"),
            event_type="hub.printers_changed",
            timestamp=datetime.now(UTC),
            data={"printer_id": str(printer.id), "change": change},
        ),
    )


def _audit_user(auth: AuthContext) -> str:
    """Leitet den Audit-User-String aus dem AuthContext ab."""
    if auth.api_key_id is not None:
        return f"api-key:{auth.api_key_id}"
    return f"{auth.source}:{auth.ip}"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[PrinterRead],
    summary="Alle Drucker auflisten",
    description=(
        "Gibt alle Drucker zurück. Deaktivierte Drucker werden standardmäßig "
        "ausgeblendet. Mit ``?include_disabled=true`` werden auch deaktivierte "
        "Drucker zurückgegeben."
    ),
)
async def list_printers(
    session: SessionDep,
    _auth: AdminAuthDep,
    include_disabled: bool = False,
) -> list[PrinterRead]:
    svc = PrinterAdminService(session, audit_user=_audit_user(_auth))
    printers = await svc.list_printers(include_disabled=include_disabled)
    return [await _read(svc, p) for p in printers]


@router.post(
    "",
    response_model=PrinterRead,
    status_code=status.HTTP_201_CREATED,
    summary="Neuen Drucker anlegen",
    description=(
        "Legt einen neuen Drucker an. Slug und Name müssen eindeutig sein. "
        "Gibt 409 zurück wenn Slug oder Name bereits vergeben ist. "
        "An ``ipp`` printer is probed first; nothing is saved when it is unreachable "
        "(409 ``ipp_unreachable``), accepts no PDF (409 ``ipp_pdf_unsupported``) or does "
        "not report a configured tray (422 ``tray_unknown``)."
    ),
)
async def create_printer(
    body: PrinterCreatePayload,
    request: Request,
    session: SessionDep,
    _auth: AdminAuthDep,
) -> PrinterRead:
    svc = _service(session, _auth, request)
    try:
        printer = await svc.create_printer(body)
    except SheetApiError as exc:
        raise exc.to_http() from None
    except DuplicateSlugError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "duplicate_slug",
                "error_message": f"Slug {exc.slug!r} ist bereits vergeben.",
            },
        ) from exc
    except DuplicateNameError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "duplicate_name",
                "error_message": f"Name {exc.name!r} ist bereits vergeben.",
            },
        ) from exc
    _publish_changed(request, printer, "created")
    return await _read(svc, printer)


@router.post(
    "/ipp/probe",
    response_model=ProbeSummary,
    summary="Read an IPP printer",
    description=(
        "Runs Get-Printer-Attributes against the given URI now and returns a bounded "
        "summary (make and model, IPP and PDF versions, resolutions, media, trays, "
        "colour modes, margins, state); never the raw attributes. Errors: 502 "
        "``ipp_unreachable``, ``ipp_rejected`` (IPP status name in ``error_detail``) or "
        "``ipp_bad_response``. Admin only."
    ),
)
async def probe_ipp_printer(
    body: IppConnection,
    request: Request,
    _auth: AdminAuthDep,
) -> ProbeSummary:
    try:
        return await probe_ipp(
            body,
            queue_timeout_s=30,
            transport_factory=_ipp_transport_factory(request),
            unreachable_status=status.HTTP_502_BAD_GATEWAY,
        )
    except SheetApiError as exc:
        raise exc.to_http() from None


@router.get(
    "/{slug}",
    response_model=PrinterRead,
    summary="Einzelnen Drucker abrufen",
    description=(
        "Gibt einen Drucker per Slug zurück. 404 wenn kein Drucker mit diesem Slug existiert."
    ),
)
async def get_printer(
    slug: str,
    session: SessionDep,
    _auth: AdminAuthDep,
) -> PrinterRead:
    svc = PrinterAdminService(session, audit_user=_audit_user(_auth))
    printer = await svc.get_printer(slug)
    if printer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "not_found",
                "error_message": f"Drucker mit Slug {slug!r} nicht gefunden.",
            },
        )
    return await _read(svc, printer)


@router.put(
    "/{slug}",
    response_model=PrinterRead,
    summary="Drucker aktualisieren",
    description=(
        "Aktualisiert einen Drucker per PATCH-Semantik (nur geänderte Felder). "
        "Slug und ID können nicht geändert werden. "
        "Gibt 404 zurück wenn kein Drucker mit diesem Slug existiert. "
        "``connection`` must fit the stored backend (422 ``invalid_connection``); "
        "``trays`` (replace-all) are for ``ipp`` printers only (422 ``trays_not_allowed``). "
        "An ``ipp`` printer is probed again when its URI changes or a tray key is new."
    ),
)
async def update_printer(
    slug: str,
    body: PrinterUpdatePayload,
    request: Request,
    session: SessionDep,
    _auth: AdminAuthDep,
) -> PrinterRead:
    svc = _service(session, _auth, request)
    try:
        printer = await svc.update_printer(slug, body)
    except SheetApiError as exc:
        raise exc.to_http() from None
    except ConnectionKindMismatchError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "invalid_connection",
                "error_message": "The connection does not fit this printer's backend.",
            },
        ) from exc
    except TraysNotAllowedError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "trays_not_allowed",
                "error_message": "Trays can only be set for page printers (IPP).",
            },
        ) from exc
    except PrinterNotFoundBySlugError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "not_found",
                "error_message": f"Drucker mit Slug {slug!r} nicht gefunden.",
            },
        ) from exc
    _publish_changed(request, printer, "updated")
    return await _read(svc, printer)


@router.post(
    "/{slug}/disable",
    response_model=PrinterRead,
    summary="Drucker deaktivieren",
    description=(
        "Deaktiviert einen Drucker (Soft-Delete). "
        "Gibt 404 zurück wenn kein Drucker mit diesem Slug existiert. "
        "Gibt 409 zurück wenn der Drucker bereits deaktiviert ist."
    ),
)
async def disable_printer(
    slug: str,
    request: Request,
    session: SessionDep,
    _auth: AdminAuthDep,
) -> PrinterRead:
    svc = PrinterAdminService(session, audit_user=_audit_user(_auth))
    try:
        printer = await svc.disable_printer(slug)
    except PrinterNotFoundBySlugError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "not_found",
                "error_message": f"Drucker mit Slug {slug!r} nicht gefunden.",
            },
        ) from exc
    except PrinterAlreadyDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "already_disabled",
                "error_message": f"Drucker {slug!r} ist bereits deaktiviert.",
            },
        ) from exc
    _publish_changed(request, printer, "disabled")
    return await _read(svc, printer)


@router.post(
    "/{slug}/enable",
    response_model=PrinterRead,
    summary="Drucker aktivieren",
    description=(
        "Aktiviert einen deaktivierten Drucker. "
        "Gibt 404 zurück wenn kein Drucker mit diesem Slug existiert. "
        "Gibt 409 zurück wenn der Drucker bereits aktiv ist."
    ),
)
async def enable_printer(
    slug: str,
    request: Request,
    session: SessionDep,
    _auth: AdminAuthDep,
) -> PrinterRead:
    svc = PrinterAdminService(session, audit_user=_audit_user(_auth))
    try:
        printer = await svc.enable_printer(slug)
    except PrinterNotFoundBySlugError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "not_found",
                "error_message": f"Drucker mit Slug {slug!r} nicht gefunden.",
            },
        ) from exc
    except PrinterAlreadyEnabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "already_enabled",
                "error_message": f"Drucker {slug!r} ist bereits aktiv.",
            },
        ) from exc
    _publish_changed(request, printer, "enabled")
    return await _read(svc, printer)
