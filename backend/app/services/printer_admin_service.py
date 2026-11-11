"""PrinterAdminService — CRUD + Audit fuer printers-Tabelle (Issue #124, Tasks 2.4 + 2.5).

Verantwortlichkeiten:
- create_printer: Neue Drucker-Row anlegen, Audit-Eintrag schreiben
- update_printer: PATCH-Semantik, nur geaenderte Felder schreiben, Audit-Eintrag
- disable_printer: Soft-Delete (enabled=False), Audit-Eintrag
- enable_printer: Soft-Delete rueckgaengig machen, Audit-Eintrag
- list_printers: Alle Drucker (optional inkl. deaktivierter) abrufen
- get_printer: Einzelnen Drucker per Slug abrufen

Flattening-Helpers (top-level Funktionen fuer einfaches Unit-Testing):
- _payload_to_row: Pydantic-Payload → flache DB-row
- _apply_update_patch: Bestehende Row + PATCH-Payload → dict mit geaenderten Spalten
- _row_to_audit_view: Flache DB-row → verschachtelte Audit-JSON-Darstellung
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.printer import Printer, PrinterAudit
from app.models.printer_calibration import PrinterCalibration
from app.models.printer_identity import PrinterIdentity
from app.models.printer_tray import PrinterTray
from app.printer_backends.ipp.attributes import PRINTER_ATTRS, ProbeSummary, summarise
from app.printer_backends.ipp.client import IppClient, to_http_url
from app.printer_backends.ipp.errors import (
    IppError,
    IppStatusError,
    IppTransportError,
    IppUnreachableError,
)
from app.repositories import printer_identity as identity_repo
from app.repositories import printers as printers_repo
from app.schemas.label_layout import LayoutDefault
from app.schemas.printer_admin import (
    IppConnection,
    PrinterConnection,
    PrinterCreatePayload,
    PrinterUpdatePayload,
    TrayIn,
)
from app.services.audit_redaction import redact_secrets
from app.services.printer_identity import derive_printer_id
from app.sheets.errors import (
    IppBadResponseApiError,
    IppPdfUnsupportedError,
    IppRejectedError,
    IppUnreachableApiError,
    StoredConnectionInvalidError,
    TrayUnknownError,
)
from app.sheets.text import log_value
from app.sheets.type_service import write_transaction

_log = logging.getLogger(__name__)

IPP_BACKEND = "ipp"
AUTO_TRAY = "auto"
IPP_MODEL_FALLBACK = "IPP printer"
MAX_MODEL_LENGTH = 120
MAX_PROBE_TIMEOUT_S = 5.0
"""Probe = an attribute query: ``min(5, queue_timeout_s)`` seconds (spec 11.2, OC-41)."""

IppTransportFactory = Callable[[str], httpx.AsyncBaseTransport]
"""Builds the httpx transport for an IPP URI. Test injection point only (see ``probe_ipp``)."""

IppProber = Callable[[IppConnection, int], Awaitable[ProbeSummary]]
"""``(connection, queue_timeout_s) -> summary``; raises the ``app.sheets.errors`` IPP errors."""

# ---------------------------------------------------------------------------
# Domain-Exceptions
# ---------------------------------------------------------------------------


class DuplicateSlugError(Exception):
    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"slug={slug!r} bereits vergeben")


class DuplicateNameError(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"name={name!r} bereits vergeben")


class PrinterAlreadyDisabledError(Exception):
    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"Drucker {slug!r} ist bereits deaktiviert")


class PrinterAlreadyEnabledError(Exception):
    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"Drucker {slug!r} ist bereits aktiv")


class PrinterNotFoundBySlugError(Exception):
    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"Drucker {slug!r} nicht gefunden")


class PrinterNotFoundError(Exception):
    """No printer with this id."""


class NoIdentityMismatchError(Exception):
    """The printer has no pending device-swap flag, so there is nothing to resolve."""


class IdentityChangedError(Exception):
    """The flagged device is no longer the one the caller reviewed."""


class ConnectionKindMismatchError(Exception):
    """An update's ``connection`` does not fit the stored printer's backend."""


class TraysNotAllowedError(Exception):
    """``trays`` were sent for a tape printer."""


# ---------------------------------------------------------------------------
# IPP probe
# ---------------------------------------------------------------------------


async def probe_ipp(
    connection: IppConnection,
    *,
    queue_timeout_s: int,
    transport_factory: IppTransportFactory | None = None,
    unreachable_status: int = 502,
    log_name: str = "probe",
) -> ProbeSummary:
    """Run Get-Printer-Attributes live and return the bounded summary (spec 11.1).

    ``transport_factory`` is a test injection point (``app.state.ipp_transport_factory``);
    production passes ``None`` and the client uses the network. The client bounds the
    exchange (1 MB body cap, timeouts, no redirects, no proxy from the environment).
    Errors carry fixed text and at most the IPP status name; logs name the printer by
    ``log_name`` (slug) and the error class, never the URI.
    """
    timeout_s = min(MAX_PROBE_TIMEOUT_S, float(queue_timeout_s))
    transport = transport_factory(connection.uri) if transport_factory is not None else None
    try:
        async with IppClient(
            connection.uri,
            tls_verify=connection.tls_verify,
            query_timeout_s=timeout_s,
            upload_timeout_s=timeout_s,
            transport=transport,
        ) as client:
            attrs = await client.get_printer_attributes(PRINTER_ATTRS)
    except (IppUnreachableError, IppTransportError, httpx.InvalidURL) as exc:
        # No usable answer in time: for the admin the printer is not reachable.
        _log.warning(
            "IPP probe for %s: printer not reachable (%s)", log_value(log_name), type(exc).__name__
        )
        raise IppUnreachableApiError(unreachable_status) from None
    except IppStatusError as exc:
        _log.warning("IPP probe for %s: printer answered %s", log_value(log_name), exc.name)
        raise IppRejectedError(exc.name) from None
    except IppError as exc:
        _log.warning(
            "IPP probe for %s: unusable answer (%s)", log_value(log_name), type(exc).__name__
        )
        raise IppBadResponseApiError() from None
    return summarise(attrs)


def _ipp_model(summary: ProbeSummary, given: str | None) -> str:
    """``printer-make-and-model`` (informational), else what the admin typed, else a fallback."""
    for candidate in (summary.make_and_model, given):
        if candidate and candidate.strip():
            return candidate.strip()[:MAX_MODEL_LENGTH]
    return IPP_MODEL_FALLBACK


def _ipp_host_port(uri: str) -> tuple[str, int]:
    """Host and effective port of an IPP URI, the identity salt for ``derive_printer_id``."""
    parts = urlsplit(to_http_url(uri))
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return parts.hostname or "", port


def _check_ipp_save(summary: ProbeSummary, tray_keys: Sequence[str]) -> None:
    """OC-18 (PDF required) and every tray other than ``auto`` reported by the printer."""
    if not summary.pdf_supported:
        raise IppPdfUnsupportedError()
    reported = set(summary.media_sources)
    unknown = [k for k in tray_keys if k != AUTO_TRAY and k not in reported]
    if unknown:
        raise TrayUnknownError(unknown)


def _tray_rows(printer_id: UUID, trays: Sequence[TrayIn]) -> list[PrinterTray]:
    return [
        PrinterTray(
            printer_id=printer_id,
            tray_key=t.key,
            label=t.label,
            load_hint=t.load_hint,
            enabled=t.enabled,
            is_default=t.is_default,
        )
        for t in trays
    ]


def _trays_audit(trays: Sequence[TrayIn] | Sequence[PrinterTray]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in trays:
        key = t.key if isinstance(t, TrayIn) else t.tray_key
        out.append(
            {
                "key": key,
                "label": t.label,
                "load_hint": t.load_hint,
                "enabled": t.enabled,
                "is_default": t.is_default,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Flattening-Helpers
# ---------------------------------------------------------------------------


def _payload_to_row(
    payload: PrinterCreatePayload,
    printer_id: UUID,
    created_at_utc: datetime,
) -> dict[str, Any]:
    """Mappt Pydantic-Payload auf flache DB-row.

    connection bleibt verschachtelt als JSON; queue.timeout_s und
    cut_defaults.half_cut werden auf flache Spalten gemappt.
    """
    return {
        "id": printer_id,
        "name": payload.name,
        "slug": payload.slug,
        "model": payload.model,
        "backend": payload.backend,
        "connection": payload.connection.model_dump(mode="json"),
        "queue_timeout_s": payload.queue.timeout_s,
        # Cut defaults do not apply to page printers (spec 11.1).
        "cut_defaults_half_cut": (
            False if payload.backend == IPP_BACKEND else payload.cut_defaults.half_cut
        ),
        "layout_defaults": (
            {} if payload.backend == IPP_BACKEND else _layout_json(payload.layout_defaults)
        ),
        "enabled": payload.enabled,
        "created_at": created_at_utc,
        "updated_at": created_at_utc,
    }


def _apply_update_patch(
    row: dict[str, Any],  # noqa: ARG001 — row wird nicht genutzt, aber fuer API-Konsistenz behalten
    patch: PrinterUpdatePayload,
) -> dict[str, Any]:
    """Returns dict mit nur geaenderten Spalten fuer SQL-UPDATE.

    slug/model/backend/id werden silent ignoriert (PrinterUpdatePayload
    kennt sie ohnehin nicht).
    connection wird ATOMAR ersetzt (kein Sub-Field-Merge).
    """
    changes: dict[str, Any] = {}
    if patch.name is not None:
        changes["name"] = patch.name
    if patch.connection is not None:
        changes["connection"] = patch.connection.model_dump(mode="json")
    if patch.queue is not None:
        changes["queue_timeout_s"] = patch.queue.timeout_s
    if patch.cut_defaults is not None:
        changes["cut_defaults_half_cut"] = patch.cut_defaults.half_cut
    if patch.layout_defaults is not None:
        changes["layout_defaults"] = _layout_json(patch.layout_defaults)
    if patch.enabled is not None:
        changes["enabled"] = patch.enabled
    return changes


def _layout_json(defaults: Mapping[int, LayoutDefault]) -> dict[str, Any]:
    """``{62: LayoutDefault}`` as the JSON column stores it: ``{"62": {...}}``."""
    return {str(width): d.model_dump(mode="json") for width, d in sorted(defaults.items())}


def _row_to_audit_view(
    row: dict[str, Any], trays: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Rekonstruiert verschachtelte Form fuer Audit-JSON.

    Resultat ist JSON-serialisierbar. Wird von redact_secrets weiterverarbeitet.
    ``trays`` is added for page printers only, so tape audits keep their shape.
    """
    raw_id = row.get("id") if "id" in row else None
    view = {
        "id": str(raw_id) if raw_id is not None else None,
        "name": row.get("name"),
        "slug": row.get("slug"),
        "model": row.get("model"),
        "backend": row.get("backend"),
        "connection": row.get("connection"),
        "queue": {"timeout_s": row.get("queue_timeout_s")},
        "cut_defaults": {"half_cut": row.get("cut_defaults_half_cut")},
        "layout_defaults": row.get("layout_defaults") or {},
        "enabled": row.get("enabled"),
    }
    if trays is not None:
        view["trays"] = trays
    return view


# ---------------------------------------------------------------------------
# Helper: Printer → Audit-row-Dict
# ---------------------------------------------------------------------------


def _printer_to_row_dict(printer: Printer) -> dict[str, Any]:
    """Extrahiert relevante Felder aus einer Printer-Instanz als flaches Dict."""
    return {
        "id": printer.id,
        "name": printer.name,
        "slug": printer.slug,
        "model": printer.model,
        "backend": printer.backend,
        "connection": printer.connection,
        "queue_timeout_s": printer.queue_timeout_s,
        "cut_defaults_half_cut": printer.cut_defaults_half_cut,
        "layout_defaults": dict(printer.layout_defaults or {}),
        "enabled": printer.enabled,
    }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class PrinterAdminService:
    """CRUD + Audit fuer printers-Tabelle (Issue #124)."""

    def __init__(
        self,
        session: AsyncSession,
        audit_user: str,
        *,
        ipp_transport_factory: IppTransportFactory | None = None,
    ) -> None:
        self._session = session
        self._audit_user = audit_user
        self._ipp_transport_factory = ipp_transport_factory

    async def _probe_for_save(
        self, connection: IppConnection, timeout_s: int, slug: str
    ) -> ProbeSummary:
        """Probe before anything is written; unreachable is 409 here (nothing saved)."""
        return await probe_ipp(
            connection,
            queue_timeout_s=timeout_s,
            transport_factory=self._ipp_transport_factory,
            unreachable_status=409,
            log_name=slug,
        )

    async def list_trays(self, printer_id: UUID) -> list[PrinterTray]:
        """Trays of a page printer in key order (empty for tape printers)."""
        result = await self._session.execute(
            select(PrinterTray)
            .where(col(PrinterTray.printer_id) == printer_id)
            .order_by(col(PrinterTray.tray_key))
        )
        return list(result.scalars())

    async def _replace_trays(self, printer_id: UUID, trays: Sequence[TrayIn]) -> None:
        await self._session.execute(
            delete(PrinterTray).where(col(PrinterTray.printer_id) == printer_id)
        )
        # A calibration belongs to a physical tray set-up: when a tray leaves the list it goes
        # too, so that re-adding the key months later does not revive an old deviation. A
        # *disabled* tray stays in the list and keeps its measurement. Same transaction as the
        # tray delete; a calibration PUT re-checks the tray inside the sheet write lock, so
        # whichever of the two commits second sees the other's result and no orphan survives.
        await self._session.execute(
            delete(PrinterCalibration).where(
                col(PrinterCalibration.printer_id) == printer_id,
                col(PrinterCalibration.tray_key).not_in([t.key for t in trays]),
            )
        )
        self._session.add_all(_tray_rows(printer_id, trays))

    async def get_printer(self, slug: str) -> Printer | None:
        """Gibt einen Drucker per Slug zurueck, oder None wenn nicht vorhanden."""
        result = await self._session.execute(select(Printer).where(col(Printer.slug) == slug))
        return result.scalar_one_or_none()

    async def list_printers(self, *, include_disabled: bool = False) -> list[Printer]:
        """Gibt alle Drucker zurueck. Ohne include_disabled werden deaktivierte ausgeblendet."""
        stmt = select(Printer).order_by(col(Printer.created_at))
        if not include_disabled:
            stmt = stmt.where(col(Printer.enabled).is_(True))
        result = await self._session.execute(stmt)
        return list(result.scalars())

    async def _exists(self, column: Any, value: str) -> bool:
        result = await self._session.execute(select(col(column)).where(col(column) == value))
        return result.first() is not None

    async def create_printer(self, payload: PrinterCreatePayload) -> Printer:
        """Legt einen neuen Drucker an und schreibt einen create-Audit-Eintrag.

        Raises:
            DuplicateSlugError: wenn der Slug bereits vergeben ist.
            DuplicateNameError: wenn der Name bereits vergeben ist.
        """
        # Before the probe: a duplicate must not cost a request to the printer (the unique
        # constraint below stays as the guard against a race).
        if await self._exists(Printer.slug, payload.slug):
            raise DuplicateSlugError(payload.slug)
        if await self._exists(Printer.name, payload.name):
            raise DuplicateNameError(payload.name)
        trays: list[TrayIn] | None = None
        if isinstance(payload.connection, IppConnection):
            trays = list(payload.trays or [])
            summary = await self._probe_for_save(
                payload.connection, payload.queue.timeout_s, payload.slug
            )
            _check_ipp_save(summary, [t.key for t in trays])
            model = _ipp_model(summary, payload.model)
            host, port = _ipp_host_port(payload.connection.uri)
        else:
            model = payload.model or ""
            host, port = payload.connection.host, payload.connection.port
        created_at = datetime.now(UTC)
        printer_id = derive_printer_id(
            model=model,
            host=host,
            port=port,
            created_at_utc=created_at,
        )
        row = _payload_to_row(payload, printer_id, created_at)
        row["model"] = model
        printer = Printer(**row)
        self._session.add(printer)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            # SQLite error format: "UNIQUE constraint failed: printers.<column>"
            # We match against the table.column token which appears BEFORE the [SQL:] section.
            exc_str = str(exc).lower()
            # Extract the constraint portion before [SQL: ...] to avoid false matches in
            # column lists within the INSERT statement.
            constraint_part = exc_str.split("[sql:")[0]
            if "printers.slug" in constraint_part:
                raise DuplicateSlugError(payload.slug) from exc
            if "printers.name" in constraint_part:
                raise DuplicateNameError(payload.name) from exc
            raise
        if trays is not None:  # after the printer row: the trays reference it
            self._session.add_all(_tray_rows(printer_id, trays))
            await self._session.flush()

        after_view = _row_to_audit_view(row, _trays_audit(trays) if trays is not None else None)
        await self._record_audit(
            printer_id=printer_id,
            slug=payload.slug,
            action="create",
            before=None,
            after=after_view,
        )
        await self._session.commit()
        await self._session.refresh(printer)
        return printer

    async def update_printer(self, slug: str, patch: PrinterUpdatePayload) -> Printer:
        """Aktualisiert einen Drucker per PATCH-Semantik und schreibt Audit.

        Raises:
            PrinterNotFoundBySlugError: wenn kein Drucker mit dem Slug existiert.
        """
        printer = await self.get_printer(slug)
        if printer is None:
            raise PrinterNotFoundBySlugError(slug)

        is_ipp = printer.backend == IPP_BACKEND
        expected = IppConnection if is_ipp else PrinterConnection
        if patch.connection is not None and not isinstance(patch.connection, expected):
            raise ConnectionKindMismatchError()
        if patch.trays is not None and not is_ipp:
            raise TraysNotAllowedError()

        stored_trays = await self.list_trays(printer.id) if is_ipp else []
        before_view = _row_to_audit_view(
            _printer_to_row_dict(printer), _trays_audit(stored_trays) if is_ipp else None
        )
        changes = _apply_update_patch(_printer_to_row_dict(printer), patch)
        if is_ipp:
            changes.pop("cut_defaults_half_cut", None)  # does not apply to page printers
            changes.pop("layout_defaults", None)  # nor do tape layouts (#258)
            changes.update(await self._ipp_update_checks(printer, patch, stored_trays))

        for key, value in changes.items():
            setattr(printer, key, value)
        printer.updated_at = datetime.now(UTC)

        self._session.add(printer)
        if patch.trays is not None:
            await self._replace_trays(printer.id, patch.trays)
        await self._session.flush()

        after_trays = _trays_audit(await self.list_trays(printer.id)) if is_ipp else None
        after_view = _row_to_audit_view(_printer_to_row_dict(printer), after_trays)
        await self._record_audit(
            printer_id=printer.id,
            slug=printer.slug,
            action="update",
            before=before_view,
            after=after_view,
        )
        await self._session.commit()
        await self._session.refresh(printer)
        return printer

    async def _ipp_update_checks(
        self,
        printer: Printer,
        patch: PrinterUpdatePayload,
        stored_trays: Sequence[PrinterTray],
    ) -> dict[str, Any]:
        """Probe when the URI changes or a tray key is new; return extra column changes.

        Relabelling, re-ordering defaults or toggling known trays, and switching TLS
        verification on the same URI, need no live call.
        """
        try:
            stored: IppConnection | None = IppConnection.model_validate(printer.connection or {})
        except ValidationError:
            # An old or hand-edited row. A new connection in this very request replaces it;
            # without one the printer id is all the answer names (never the stored value).
            if not isinstance(patch.connection, IppConnection):
                raise StoredConnectionInvalidError(printer.id) from None
            stored = None
        new_conn = patch.connection if isinstance(patch.connection, IppConnection) else stored
        assert new_conn is not None  # stored is None only when the patch carries a connection
        uri_changed = stored is None or new_conn.uri != stored.uri
        tray_keys = (
            [t.key for t in patch.trays]
            if patch.trays is not None
            else [t.tray_key for t in stored_trays]
        )
        known = {t.tray_key for t in stored_trays}
        new_key = any(k != AUTO_TRAY and k not in known for k in tray_keys)
        if not uri_changed and not new_key:
            return {}
        timeout_s = patch.queue.timeout_s if patch.queue is not None else printer.queue_timeout_s
        summary = await self._probe_for_save(new_conn, timeout_s, printer.slug)
        _check_ipp_save(summary, tray_keys)
        if uri_changed:  # another device answers now: its make and model
            return {"model": _ipp_model(summary, None)}
        return {}

    async def disable_printer(self, slug: str) -> Printer:
        """Deaktiviert einen Drucker (Soft-Delete) und schreibt Audit.

        Raises:
            PrinterNotFoundBySlugError: wenn kein Drucker mit dem Slug existiert.
            PrinterAlreadyDisabledError: wenn der Drucker bereits deaktiviert ist.
        """
        printer = await self.get_printer(slug)
        if printer is None:
            raise PrinterNotFoundBySlugError(slug)
        if not printer.enabled:
            raise PrinterAlreadyDisabledError(slug)

        before_view = _row_to_audit_view(_printer_to_row_dict(printer))
        printer.enabled = False
        printer.updated_at = datetime.now(UTC)
        self._session.add(printer)
        await self._session.flush()

        after_view = _row_to_audit_view(_printer_to_row_dict(printer))
        await self._record_audit(
            printer_id=printer.id,
            slug=printer.slug,
            action="disable",
            before=before_view,
            after=after_view,
        )
        await self._session.commit()
        await self._session.refresh(printer)
        return printer

    async def enable_printer(self, slug: str) -> Printer:
        """Aktiviert einen deaktivierten Drucker und schreibt Audit.

        Raises:
            PrinterNotFoundBySlugError: wenn kein Drucker mit dem Slug existiert.
            PrinterAlreadyEnabledError: wenn der Drucker bereits aktiv ist.
        """
        printer = await self.get_printer(slug)
        if printer is None:
            raise PrinterNotFoundBySlugError(slug)
        if printer.enabled:
            raise PrinterAlreadyEnabledError(slug)

        before_view = _row_to_audit_view(_printer_to_row_dict(printer))
        printer.enabled = True
        printer.updated_at = datetime.now(UTC)
        self._session.add(printer)
        await self._session.flush()

        after_view = _row_to_audit_view(_printer_to_row_dict(printer))
        await self._record_audit(
            printer_id=printer.id,
            slug=printer.slug,
            action="enable",
            before=before_view,
            after=after_view,
        )
        await self._session.commit()
        await self._session.refresh(printer)
        return printer

    async def get_identity(self, printer_id: UUID) -> PrinterIdentity | None:
        """The stored hardware identity row of a printer (admin views only)."""
        return await identity_repo.get(self._session, printer_id)

    async def get_identities(self, printer_ids: Sequence[UUID]) -> dict[UUID, PrinterIdentity]:
        """The stored identities of several printers in one query."""
        return await identity_repo.get_many(self._session, printer_ids)

    async def resolve_identity(
        self,
        printer_id: UUID,
        resolution: Literal["same_device", "replaced"],
        *,
        expected_observed_id: str,
        expected_observed_kind: str,
    ) -> Printer:
        """End a flagged device swap (#231): keep the calibration or reset it.

        Bound to the device the admin reviewed: it only applies while the observed device still
        is ``(expected_observed_kind, expected_observed_id)``. One transaction: the observed
        device becomes the stored one and the mismatch ends (this is also the check, so a 409
        deletes nothing), then ``replaced`` deletes every calibration row of the printer (the rows
        found, not every configured tray), then one audit row (no identity value), then one
        commit. Any failure rolls everything back. Releasing the queue hold and the events belong
        to the caller and happen only after this returns.
        """
        printer = await printers_repo.get(self._session, printer_id)
        if printer is None:
            raise PrinterNotFoundError
        removed = 0
        async with write_transaction(self._session):
            if not await identity_repo.adopt_observed(
                self._session,
                printer_id,
                expected_id=expected_observed_id,
                expected_kind=expected_observed_kind,
                now=datetime.now(UTC),
            ):
                current = await identity_repo.get(self._session, printer_id)
                if current is None or current.mismatch_since is None:
                    raise NoIdentityMismatchError
                raise IdentityChangedError
            if resolution == "replaced":
                rows = (
                    await self._session.execute(
                        select(PrinterCalibration).where(
                            col(PrinterCalibration.printer_id) == printer_id
                        )
                    )
                ).scalars()
                for row in list(rows):
                    await self._session.delete(row)
                    removed += 1
                await self._session.flush()
            await self._record_audit(
                printer_id=printer_id,
                slug=printer.slug,
                action="identity_resolved",
                before=None,
                after=(
                    {"resolution": resolution, "calibrations_removed": removed}
                    if resolution == "replaced"
                    else {"resolution": resolution}
                ),
            )
            await self._session.commit()
        return printer  # nothing on the row changed; no refresh that could fail after the commit

    async def _record_audit(
        self,
        *,
        printer_id: UUID,
        slug: str,
        action: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        """Schreibt einen Eintrag in printers_audit mit redacted Secrets."""
        audit = PrinterAudit(
            printer_id=printer_id,
            slug=slug,
            action=action,
            before_json=redact_secrets(before) if before is not None else None,
            after_json=redact_secrets(after) if after is not None else None,
            updated_by=self._audit_user,
        )
        self._session.add(audit)
        await self._session.flush()
