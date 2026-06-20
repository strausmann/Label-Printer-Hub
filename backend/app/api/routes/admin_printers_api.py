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

Auth
----
Alle Endpoints erfordern ``admin``-Scope (API-Key mit scope=admin).
Pangolin-SSO und claude-automation-Bypass gewähren nur ``read`` — kein Zugriff.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin
from app.db.session import get_session
from app.models.printer import Printer
from app.schemas.printer_admin import PrinterCreatePayload, PrinterUpdatePayload
from app.services.printer_admin_service import (
    DuplicateNameError,
    DuplicateSlugError,
    PrinterAdminService,
    PrinterAlreadyDisabledError,
    PrinterAlreadyEnabledError,
    PrinterNotFoundBySlugError,
)

router = APIRouter(prefix="/api/v1/admin/printers", tags=["admin"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
AdminAuthDep = Annotated[AuthContext, Depends(require_admin)]


# ---------------------------------------------------------------------------
# Response-Schema
# ---------------------------------------------------------------------------


class PrinterRead(BaseModel):
    """Lesbare Darstellung eines Druckers.

    Enthält alle DB-Felder — keine internen Implementierungsdetails.
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
    return [_row_to_read(p) for p in printers]


@router.post(
    "",
    response_model=PrinterRead,
    status_code=status.HTTP_201_CREATED,
    summary="Neuen Drucker anlegen",
    description=(
        "Legt einen neuen Drucker an. Slug und Name müssen eindeutig sein. "
        "Gibt 409 zurück wenn Slug oder Name bereits vergeben ist."
    ),
)
async def create_printer(
    body: PrinterCreatePayload,
    session: SessionDep,
    _auth: AdminAuthDep,
) -> PrinterRead:
    svc = PrinterAdminService(session, audit_user=_audit_user(_auth))
    try:
        printer = await svc.create_printer(body)
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
    return _row_to_read(printer)


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
    return _row_to_read(printer)


@router.put(
    "/{slug}",
    response_model=PrinterRead,
    summary="Drucker aktualisieren",
    description=(
        "Aktualisiert einen Drucker per PATCH-Semantik (nur geänderte Felder). "
        "Slug und ID können nicht geändert werden. "
        "Gibt 404 zurück wenn kein Drucker mit diesem Slug existiert."
    ),
)
async def update_printer(
    slug: str,
    body: PrinterUpdatePayload,
    session: SessionDep,
    _auth: AdminAuthDep,
) -> PrinterRead:
    svc = PrinterAdminService(session, audit_user=_audit_user(_auth))
    try:
        printer = await svc.update_printer(slug, body)
    except PrinterNotFoundBySlugError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "not_found",
                "error_message": f"Drucker mit Slug {slug!r} nicht gefunden.",
            },
        ) from exc
    return _row_to_read(printer)


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
    return _row_to_read(printer)


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
    return _row_to_read(printer)
