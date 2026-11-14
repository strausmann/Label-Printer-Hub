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

Live changes (#224)
-------------------
Create, update, disable and enable take effect at once, without a hub restart: after the
commit the route calls ``PrinterRuntime.reconcile`` (shielded, so a client that disconnects
does not leave the printer half wired). Disable stands in for delete: the printer stops being
polled and new jobs for it are refused (409 ``printer-unavailable``). A job printing on the
printer finishes within its queue timeout, so the call can take that long; jobs waiting behind
it stay ``queued`` and print after the printer is enabled again. A rename alone re-wires
nothing. A printer whose stored connection cannot be wired is saved anyway and left detached.
The backend of a printer is fixed here; should a row's kind change from tape to page in the
store, its queued tape jobs fail with ``recovery_invalid_page_payload`` when the page printer
is wired (as after a restart).

Auth
----
Alle Endpoints erfordern ``admin``-Scope (API-Key mit scope=admin).
Pangolin-SSO und claude-automation-Bypass gewähren nur ``read`` — kein Zugriff.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AuthContext, check_printer_access
from app.auth.scope_deps import require_admin
from app.db.session import get_session
from app.models.printer import Printer
from app.models.printer_identity import PrinterIdentity
from app.models.printer_tray import PrinterTray
from app.printer_backends.ipp.attributes import ProbeSummary
from app.schemas._datetime import serialize_datetime_utc
from app.schemas.label_layout import LayoutDefault, parse_layout_defaults
from app.schemas.printer import CONNECTION_READ_DOC
from app.schemas.printer_admin import IppConnection, PrinterCreatePayload, PrinterUpdatePayload
from app.services.event_bus import BusEvent, EventBus
from app.services.printer_admin_service import (
    IPP_BACKEND,
    ConnectionKindMismatchError,
    DuplicateNameError,
    DuplicateSlugError,
    IdentityChangedError,
    IppTransportFactory,
    NoIdentityMismatchError,
    PrinterAdminService,
    PrinterAlreadyDisabledError,
    PrinterAlreadyEnabledError,
    PrinterNotFoundBySlugError,
    PrinterNotFoundError,
    SnmpCommunityRequiredError,
    TraysNotAllowedError,
    probe_ipp,
    snmp_view,
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
    connection: dict[str, Any] = Field(description=CONNECTION_READ_DOC)
    queue: dict[str, Any]
    cut_defaults: dict[str, Any]
    layout_defaults: dict[str, LayoutDefault] = Field(
        default_factory=dict,
        description=(
            "Stored label layout per tape width in mm (#258), keyed by the width as a string; "
            "a missing width uses the tape default (62 mm across/compact, else along)"
        ),
    )
    enabled: bool
    created_at: str
    updated_at: str
    trays: list[TrayRead] | None = None
    hardware_id: str | None = Field(
        default=None,
        description="Serial, IPP printer-uuid or MAC the hub stored for the device; admin only",
    )
    hardware_id_kind: str | None = Field(default=None, description="serial | ipp_uuid | mac")
    hardware_id_seen_at: str | None = Field(
        default=None, description="When a probe last saw the stored device"
    )
    observed_id: str | None = Field(
        default=None, description="The differing device a flagged swap is about; null otherwise"
    )
    observed_kind: str | None = Field(default=None, description="serial | ipp_uuid | mac")


class IdentityResolve(BaseModel):
    """Body of ``POST /admin/printers/{id}/identity/resolve``."""

    model_config = ConfigDict(extra="forbid")

    resolution: Literal["same_device", "replaced"] = Field(
        description=(
            "same_device: the flagged device is accepted and the calibration stays; "
            "replaced: the device was swapped, so its stored calibration is deleted"
        )
    )
    expected_observed_id: str = Field(
        min_length=1, description="The flagged device the admin reviewed (``observed_id``)"
    )
    expected_observed_kind: str = Field(
        min_length=1, description="Its kind (``observed_kind``); the call binds to this device"
    )


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


async def _read(
    svc: PrinterAdminService,
    printer: Printer,
    identities: dict[UUID, PrinterIdentity] | None = None,
) -> PrinterRead:
    """The admin view; a list passes ``identities`` (one query) instead of one read per row."""
    view = _row_to_read(printer)
    if printer.backend == IPP_BACKEND:
        view.trays = [_tray_read(t) for t in await svc.list_trays(printer.id)]
    # Explicit, never from_attributes: the identity is inventory data for admins (#231).
    identity = (
        await svc.get_identity(printer.id) if identities is None else identities.get(printer.id)
    )
    if identity is not None:
        view.hardware_id = identity.hardware_id
        view.hardware_id_kind = identity.hardware_id_kind
        view.observed_id = identity.observed_id
        view.observed_kind = identity.observed_kind
        if identity.hardware_id_seen_at is not None:
            view.hardware_id_seen_at = serialize_datetime_utc(identity.hardware_id_seen_at, None)
    return view


def _row_to_read(printer: Printer) -> PrinterRead:
    """Konvertiert eine Printer-DB-Row in das API-Response-Schema."""
    return PrinterRead(
        id=printer.id,
        name=printer.name,
        slug=printer.slug,
        model=printer.model,
        backend=printer.backend,
        connection=snmp_view(printer.connection or {}),  # never the community (#296)
        queue={"timeout_s": printer.queue_timeout_s},
        cut_defaults={"half_cut": printer.cut_defaults_half_cut},
        layout_defaults={
            str(width): value
            for width, value in parse_layout_defaults(printer.layout_defaults).items()
        },
        enabled=printer.enabled,
        created_at=printer.created_at.isoformat() if printer.created_at else "",
        updated_at=printer.updated_at.isoformat() if printer.updated_at else "",
    )


async def _apply_live(request: Request, printer_id: UUID) -> None:
    """Wire the saved row into the running hub (#224); the response still reports the row.

    Runs before ``hub.printers_changed`` is published: an open event stream re-subscribes on
    that event (``events_v1.py``, ``frontend/src/api/events.ts``) and must find the new wiring.
    Shielded: a client disconnect cancels the request, not the reconcile. ``reconcile`` logs
    and swallows wiring and store failures itself.
    """
    runtime = getattr(request.app.state, "printer_runtime", None)
    if runtime is None:  # an app without the lifespan (unit tests of the routes)
        return
    task = asyncio.ensure_future(runtime.reconcile(printer_id))
    # Strong references on the runtime of this app, so a shielded reconcile outlives a
    # cancelled request.
    runtime.reconciles.add(task)
    task.add_done_callback(runtime.reconciles.discard)
    await asyncio.shield(task)


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
    identities = await svc.get_identities([p.id for p in printers])
    return [await _read(svc, p, identities) for p in printers]


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
        "not report a configured tray (422 ``tray_unknown``). "
        "The printer is wired into the running hub before the answer; no restart is needed."
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
    await _apply_live(request, printer.id)  # before the event: see _apply_live
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
        "``connection.snmp.community`` is write-only: omitted or null keeps the stored one "
        "while host and port stay the same; a new host or port without a community, or "
        "discovery without any community, is 422 ``snmp_community_required``. "
        "An ``ipp`` printer is probed again when its URI changes or a tray key is new. "
        "A change of the connection, the trays or the IPP queue timeout re-wires the printer "
        "before the answer: a job printing on it finishes first (up to its queue timeout), "
        "waiting jobs stay queued. A rename re-wires nothing."
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
    except SnmpCommunityRequiredError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "snmp_community_required",
                "error_message": (
                    "Send the SNMP community: status discovery needs one, and a new host "
                    "or port does not take over the stored one."
                ),
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
    await _apply_live(request, printer.id)  # before the event: see _apply_live
    _publish_changed(request, printer, "updated")
    return await _read(svc, printer)


@router.post(
    "/{slug}/disable",
    response_model=PrinterRead,
    summary="Drucker deaktivieren",
    description=(
        "Deaktiviert einen Drucker (Soft-Delete). "
        "Gibt 404 zurück wenn kein Drucker mit diesem Slug existiert. "
        "Gibt 409 zurück wenn der Drucker bereits deaktiviert ist. "
        "Takes effect before the answer: polling stops and new jobs are refused (409 "
        "``printer-unavailable``); a job printing on it finishes first (up to its queue "
        "timeout), waiting jobs stay queued and print after enable."
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
    await _apply_live(request, printer.id)  # before the event: see _apply_live
    _publish_changed(request, printer, "disabled")
    return await _read(svc, printer)


@router.post(
    "/{slug}/enable",
    response_model=PrinterRead,
    summary="Drucker aktivieren",
    description=(
        "Aktiviert einen deaktivierten Drucker. "
        "Gibt 404 zurück wenn kein Drucker mit diesem Slug existiert. "
        "Gibt 409 zurück wenn der Drucker bereits aktiv ist. "
        "The printer is wired again before the answer; no restart is needed."
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
    await _apply_live(request, printer.id)  # before the event: see _apply_live
    _publish_changed(request, printer, "enabled")
    return await _read(svc, printer)


@router.post(
    "/{printer_id}/identity/resolve",
    response_model=PrinterRead,
    summary="Resolve a flagged device swap",
    description=(
        "Ends the device-swap flag of a printer (#231). ``same_device`` accepts the flagged "
        "device as the printer and keeps its calibration; ``replaced`` does the same and "
        "deletes every stored calibration of the printer, in one transaction. The held "
        "sheet and calibration jobs are released once the change is committed. 404 for an "
        "unknown printer, 409 ``no-identity-mismatch`` when no swap is flagged and 409 "
        "``identity-changed`` when the flagged device is no longer the one reviewed. Admin only."
    ),
)
async def resolve_identity(
    printer_id: UUID,
    body: IdentityResolve,
    request: Request,
    session: SessionDep,
    _auth: AdminAuthDep,
) -> PrinterRead:
    # No-op for every key that can reach this admin route (an admin key is never restricted,
    # #283); kept as defence in depth.
    check_printer_access(_auth, printer_id)
    svc = PrinterAdminService(session, audit_user=_audit_user(_auth))
    try:
        printer = await svc.resolve_identity(
            printer_id,
            body.resolution,
            expected_observed_id=body.expected_observed_id,
            expected_observed_kind=body.expected_observed_kind,
        )
    except IdentityChangedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "identity-changed",
                "error_message": (
                    f"Printer {printer_id}: the flagged device changed since it was reviewed. "
                    "Review it again before resolving."
                ),
            },
        ) from exc
    except PrinterNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "not_found",
                "error_message": f"Printer {printer_id} not found.",
            },
        ) from exc
    except NoIdentityMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "no-identity-mismatch",
                "error_message": "No device swap is flagged for this printer.",
            },
        ) from exc
    # Committed. A failed commit raised above and the hold stays (fail closed). The hold now
    # follows the database through the runtime's fail-closed path, before anything below that
    # can raise: a device seen after the commit keeps it, a failed read never releases it.
    runtime = getattr(request.app.state, "printer_runtime", None)
    if runtime is not None:
        await runtime.resync_identity_hold(printer.id)
    _publish_changed(request, printer, "updated")
    return await _read(svc, printer)
