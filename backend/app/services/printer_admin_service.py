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

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.printer import Printer, PrinterAudit
from app.schemas.printer_admin import PrinterCreatePayload, PrinterUpdatePayload
from app.services.audit_redaction import redact_secrets
from app.services.printer_identity import derive_printer_id

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
        "cut_defaults_half_cut": payload.cut_defaults.half_cut,
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
    if patch.enabled is not None:
        changes["enabled"] = patch.enabled
    return changes


def _row_to_audit_view(row: dict[str, Any]) -> dict[str, Any]:
    """Rekonstruiert verschachtelte Form fuer Audit-JSON.

    Resultat ist JSON-serialisierbar. Wird von redact_secrets weiterverarbeitet.
    """
    raw_id = row.get("id") if "id" in row else None
    return {
        "id": str(raw_id) if raw_id is not None else None,
        "name": row.get("name"),
        "slug": row.get("slug"),
        "model": row.get("model"),
        "backend": row.get("backend"),
        "connection": row.get("connection"),
        "queue": {"timeout_s": row.get("queue_timeout_s")},
        "cut_defaults": {"half_cut": row.get("cut_defaults_half_cut")},
        "enabled": row.get("enabled"),
    }


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
        "enabled": printer.enabled,
    }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class PrinterAdminService:
    """CRUD + Audit fuer printers-Tabelle (Issue #124)."""

    def __init__(self, session: AsyncSession, audit_user: str) -> None:
        self._session = session
        self._audit_user = audit_user

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

    async def create_printer(self, payload: PrinterCreatePayload) -> Printer:
        """Legt einen neuen Drucker an und schreibt einen create-Audit-Eintrag.

        Raises:
            DuplicateSlugError: wenn der Slug bereits vergeben ist.
            DuplicateNameError: wenn der Name bereits vergeben ist.
        """
        created_at = datetime.now(UTC)
        printer_id = derive_printer_id(
            model=payload.model,
            host=payload.connection.host,
            port=payload.connection.port,
            created_at_utc=created_at,
        )
        row = _payload_to_row(payload, printer_id, created_at)
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

        after_view = _row_to_audit_view(row)
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

        before_view = _row_to_audit_view(_printer_to_row_dict(printer))
        changes = _apply_update_patch(_printer_to_row_dict(printer), patch)

        for key, value in changes.items():
            setattr(printer, key, value)
        printer.updated_at = datetime.now(UTC)

        self._session.add(printer)
        await self._session.flush()

        after_view = _row_to_audit_view(_printer_to_row_dict(printer))
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
