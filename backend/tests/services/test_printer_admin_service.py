"""Tests für PrinterAdminService (Issue #124, Tasks 2.4 + 2.5).

TDD: Tests wurden vor der Implementation geschrieben.
Alle IPs aus RFC-5737 Bereich (192.0.2.x) — Repo-Konvention.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import app.models  # noqa: F401 — registriert alle Models mit SQLModel.metadata
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from app.schemas.printer_admin import (
    PrinterConnection,
    PrinterCreatePayload,
    PrinterCutDefaults,
    PrinterQueueSettings,
    PrinterUpdatePayload,
    SNMPConfig,
)
from app.services.printer_admin_service import (
    DuplicateNameError,
    DuplicateSlugError,
    PrinterAdminService,
    PrinterAlreadyDisabledError,
    PrinterAlreadyEnabledError,
    PrinterNotFoundBySlugError,
    _apply_update_patch,
    _payload_to_row,
    _row_to_audit_view,
)


# ---------------------------------------------------------------------------
# Test-Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def _engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(_engine):
    factory = async_sessionmaker(_engine, expire_on_commit=False)
    async with factory() as s:
        yield s


def _make_payload(
    *,
    name: str = "Test Drucker",
    slug: str = "test-drucker",
    model: str = "PT-P750W",
    backend: str = "ptouch",
    host: str = "192.0.2.10",
    port: int = 9100,
    timeout_s: int = 30,
    half_cut: bool = False,
    enabled: bool = True,
) -> PrinterCreatePayload:
    return PrinterCreatePayload(
        name=name,
        slug=slug,
        model=model,
        backend=backend,  # type: ignore[arg-type]
        connection=PrinterConnection(
            host=host,
            port=port,
            snmp=SNMPConfig(discover=False, community="public"),
        ),
        queue=PrinterQueueSettings(timeout_s=timeout_s),
        cut_defaults=PrinterCutDefaults(half_cut=half_cut),
        enabled=enabled,
    )


def _make_row(
    *,
    name: str = "Test Drucker",
    slug: str = "test-drucker",
    model: str = "PT-P750W",
    backend: str = "ptouch",
    queue_timeout_s: int = 30,
    cut_defaults_half_cut: bool = False,
    enabled: bool = True,
    connection: dict[str, Any] | None = None,
    printer_id: UUID | None = None,
) -> dict[str, Any]:
    return {
        "id": printer_id or uuid4(),
        "name": name,
        "slug": slug,
        "model": model,
        "backend": backend,
        "connection": connection or {"host": "192.0.2.10", "port": 9100, "snmp": {"discover": False, "community": "public"}},
        "queue_timeout_s": queue_timeout_s,
        "cut_defaults_half_cut": cut_defaults_half_cut,
        "enabled": enabled,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }


# ===========================================================================
# Teil 1 — Flattening-Helper (reine Funktionen, kein DB nötig)
# ===========================================================================


class TestPayloadToRow:
    """_payload_to_row flattens queue und cut_defaults korrekt."""

    def test_flattens_queue_timeout(self) -> None:
        payload = _make_payload(timeout_s=45)
        printer_id = uuid4()
        created_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        row = _payload_to_row(payload, printer_id, created_at)
        assert row["queue_timeout_s"] == 45

    def test_flattens_cut_defaults_half_cut(self) -> None:
        payload = _make_payload(half_cut=True)
        printer_id = uuid4()
        created_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        row = _payload_to_row(payload, printer_id, created_at)
        assert row["cut_defaults_half_cut"] is True

    def test_connection_stays_nested(self) -> None:
        payload = _make_payload(host="192.0.2.20", port=9200)
        printer_id = uuid4()
        created_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        row = _payload_to_row(payload, printer_id, created_at)
        assert isinstance(row["connection"], dict)
        assert row["connection"]["host"] == "192.0.2.20"
        assert row["connection"]["port"] == 9200

    def test_timestamps_set_to_created_at(self) -> None:
        payload = _make_payload()
        printer_id = uuid4()
        created_at = datetime(2025, 6, 15, 8, 0, 0, tzinfo=UTC)
        row = _payload_to_row(payload, printer_id, created_at)
        assert row["created_at"] == created_at
        assert row["updated_at"] == created_at

    def test_id_matches_printer_id(self) -> None:
        payload = _make_payload()
        printer_id = uuid4()
        created_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        row = _payload_to_row(payload, printer_id, created_at)
        assert row["id"] == printer_id

    def test_core_fields_preserved(self) -> None:
        payload = _make_payload(name="Mein Drucker", slug="mein-drucker", model="QL-800", backend="brother_ql")
        printer_id = uuid4()
        created_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        row = _payload_to_row(payload, printer_id, created_at)
        assert row["name"] == "Mein Drucker"
        assert row["slug"] == "mein-drucker"
        assert row["model"] == "QL-800"
        assert row["backend"] == "brother_ql"


class TestApplyUpdatePatch:
    """_apply_update_patch gibt nur die geänderten Spalten zurück."""

    def test_partial_patch_name_only(self) -> None:
        row = _make_row()
        patch = PrinterUpdatePayload(name="Neuer Name")
        changes = _apply_update_patch(row, patch)
        assert changes == {"name": "Neuer Name"}

    def test_empty_payload_returns_empty_dict(self) -> None:
        row = _make_row()
        patch = PrinterUpdatePayload()
        changes = _apply_update_patch(row, patch)
        assert changes == {}

    def test_connection_replaced_atomically(self) -> None:
        row = _make_row(connection={"host": "192.0.2.1", "port": 9100, "snmp": {"discover": False, "community": "old"}})
        new_connection = PrinterConnection(
            host="192.0.2.2",
            port=9200,
            snmp=SNMPConfig(discover=False, community="new"),
        )
        patch = PrinterUpdatePayload(connection=new_connection)
        changes = _apply_update_patch(row, patch)
        assert "connection" in changes
        assert changes["connection"]["host"] == "192.0.2.2"
        assert changes["connection"]["snmp"]["community"] == "new"

    def test_queue_flattened_in_changes(self) -> None:
        row = _make_row(queue_timeout_s=30)
        patch = PrinterUpdatePayload(queue=PrinterQueueSettings(timeout_s=60))
        changes = _apply_update_patch(row, patch)
        assert changes == {"queue_timeout_s": 60}

    def test_cut_defaults_flattened_in_changes(self) -> None:
        row = _make_row(cut_defaults_half_cut=False)
        patch = PrinterUpdatePayload(cut_defaults=PrinterCutDefaults(half_cut=True))
        changes = _apply_update_patch(row, patch)
        assert changes == {"cut_defaults_half_cut": True}

    def test_enabled_false_included(self) -> None:
        row = _make_row(enabled=True)
        patch = PrinterUpdatePayload(enabled=False)
        changes = _apply_update_patch(row, patch)
        assert changes == {"enabled": False}

    def test_multiple_fields_all_returned(self) -> None:
        row = _make_row()
        patch = PrinterUpdatePayload(
            name="Geändert",
            enabled=False,
        )
        changes = _apply_update_patch(row, patch)
        assert set(changes.keys()) == {"name", "enabled"}


class TestRowToAuditView:
    """_row_to_audit_view unflattens queue und cut_defaults."""

    def test_unflattens_queue(self) -> None:
        row = _make_row(queue_timeout_s=45)
        view = _row_to_audit_view(row)
        assert view["queue"] == {"timeout_s": 45}

    def test_unflattens_cut_defaults(self) -> None:
        row = _make_row(cut_defaults_half_cut=True)
        view = _row_to_audit_view(row)
        assert view["cut_defaults"] == {"half_cut": True}

    def test_id_converted_to_str(self) -> None:
        printer_id = uuid4()
        row = _make_row(printer_id=printer_id)
        view = _row_to_audit_view(row)
        assert view["id"] == str(printer_id)

    def test_missing_id_yields_none(self) -> None:
        row = _make_row()
        del row["id"]
        view = _row_to_audit_view(row)
        assert view["id"] is None

    def test_connection_preserved(self) -> None:
        conn = {"host": "192.0.2.30", "port": 9300, "snmp": {"discover": False, "community": "pub"}}
        row = _make_row(connection=conn)
        view = _row_to_audit_view(row)
        assert view["connection"] == conn

    def test_missing_columns_yield_none(self) -> None:
        """Minimale Row (nur Pflichtfelder) — fehlende Spalten werden zu None."""
        row: dict[str, Any] = {}
        view = _row_to_audit_view(row)
        assert view["name"] is None
        assert view["slug"] is None
        assert view["queue"] == {"timeout_s": None}
        assert view["cut_defaults"] == {"half_cut": None}


# ===========================================================================
# Teil 2 — CRUD (Async Session Tests)
# ===========================================================================


class TestCreatePrinter:
    async def test_happy_path_returns_printer_with_id(self, db_session) -> None:
        svc = PrinterAdminService(db_session, audit_user="testuser")
        payload = _make_payload()
        printer = await svc.create_printer(payload)
        assert printer.id is not None
        assert printer.slug == "test-drucker"
        assert printer.name == "Test Drucker"

    async def test_happy_path_creates_audit_row(self, db_session) -> None:
        from sqlmodel import select
        from app.models.printer import PrinterAudit

        svc = PrinterAdminService(db_session, audit_user="testuser")
        payload = _make_payload()
        printer = await svc.create_printer(payload)
        result = await db_session.execute(
            select(PrinterAudit).where(PrinterAudit.printer_id == printer.id)
        )
        audit_rows = list(result.scalars())
        assert len(audit_rows) == 1
        assert audit_rows[0].action == "create"
        assert audit_rows[0].before_json is None
        assert audit_rows[0].after_json is not None
        assert audit_rows[0].updated_by == "testuser"

    async def test_queue_timeout_persisted(self, db_session) -> None:
        svc = PrinterAdminService(db_session, audit_user="testuser")
        payload = _make_payload(timeout_s=90)
        printer = await svc.create_printer(payload)
        assert printer.queue_timeout_s == 90

    async def test_cut_defaults_persisted(self, db_session) -> None:
        svc = PrinterAdminService(db_session, audit_user="testuser")
        payload = _make_payload(half_cut=True)
        printer = await svc.create_printer(payload)
        assert printer.cut_defaults_half_cut is True

    async def test_duplicate_slug_raises(self, db_session) -> None:
        svc = PrinterAdminService(db_session, audit_user="testuser")
        payload1 = _make_payload(name="Drucker Eins", slug="dup-slug")
        payload2 = _make_payload(name="Drucker Zwei", slug="dup-slug")
        await svc.create_printer(payload1)
        with pytest.raises(DuplicateSlugError) as exc_info:
            await svc.create_printer(payload2)
        assert exc_info.value.slug == "dup-slug"

    async def test_duplicate_name_raises(self, db_session) -> None:
        svc = PrinterAdminService(db_session, audit_user="testuser")
        payload1 = _make_payload(name="Gleicher Name", slug="slug-eins")
        payload2 = _make_payload(name="Gleicher Name", slug="slug-zwei")
        await svc.create_printer(payload1)
        with pytest.raises(DuplicateNameError) as exc_info:
            await svc.create_printer(payload2)
        assert exc_info.value.name == "Gleicher Name"


class TestUpdatePrinter:
    async def test_update_name_persisted(self, db_session) -> None:
        svc = PrinterAdminService(db_session, audit_user="testuser")
        await svc.create_printer(_make_payload(slug="update-me"))
        patch = PrinterUpdatePayload(name="Neuer Name")
        updated = await svc.update_printer("update-me", patch)
        assert updated.name == "Neuer Name"

    async def test_update_creates_audit_row(self, db_session) -> None:
        from sqlmodel import select
        from app.models.printer import PrinterAudit

        svc = PrinterAdminService(db_session, audit_user="testuser")
        printer = await svc.create_printer(_make_payload(slug="audited-update"))
        patch = PrinterUpdatePayload(name="Aktualisiert")
        await svc.update_printer("audited-update", patch)
        result = await db_session.execute(
            select(PrinterAudit)
            .where(PrinterAudit.printer_id == printer.id)
            .order_by(PrinterAudit.created_at)
        )
        audit_rows = list(result.scalars())
        assert len(audit_rows) == 2
        update_audit = audit_rows[1]
        assert update_audit.action == "update"
        assert update_audit.before_json is not None
        assert update_audit.after_json is not None

    async def test_empty_patch_no_change(self, db_session) -> None:
        svc = PrinterAdminService(db_session, audit_user="testuser")
        original = await svc.create_printer(_make_payload(name="Unveraendert", slug="no-change"))
        patch = PrinterUpdatePayload()
        updated = await svc.update_printer("no-change", patch)
        assert updated.name == original.name
        assert updated.slug == original.slug

    async def test_not_found_raises(self, db_session) -> None:
        svc = PrinterAdminService(db_session, audit_user="testuser")
        patch = PrinterUpdatePayload(name="X")
        with pytest.raises(PrinterNotFoundBySlugError) as exc_info:
            await svc.update_printer("nonexistent-slug", patch)
        assert exc_info.value.slug == "nonexistent-slug"

    async def test_updated_at_changes(self, db_session) -> None:
        svc = PrinterAdminService(db_session, audit_user="testuser")
        original = await svc.create_printer(_make_payload(slug="ts-check"))
        original_updated_at = original.updated_at
        patch = PrinterUpdatePayload(name="Neuer Name")
        updated = await svc.update_printer("ts-check", patch)
        # updated_at darf nicht früher sein als original (ggf. gleich bei schnellen Tests)
        assert updated.updated_at >= original_updated_at


class TestDisablePrinter:
    async def test_happy_path_sets_enabled_false(self, db_session) -> None:
        svc = PrinterAdminService(db_session, audit_user="testuser")
        await svc.create_printer(_make_payload(slug="to-disable"))
        disabled = await svc.disable_printer("to-disable")
        assert disabled.enabled is False

    async def test_happy_path_creates_audit(self, db_session) -> None:
        from sqlmodel import select
        from app.models.printer import PrinterAudit

        svc = PrinterAdminService(db_session, audit_user="testuser")
        printer = await svc.create_printer(_make_payload(slug="disable-audit"))
        await svc.disable_printer("disable-audit")
        result = await db_session.execute(
            select(PrinterAudit)
            .where(PrinterAudit.printer_id == printer.id)
            .order_by(PrinterAudit.created_at)
        )
        audit_rows = list(result.scalars())
        disable_audits = [r for r in audit_rows if r.action == "disable"]
        assert len(disable_audits) == 1

    async def test_already_disabled_raises(self, db_session) -> None:
        svc = PrinterAdminService(db_session, audit_user="testuser")
        await svc.create_printer(_make_payload(slug="already-off", enabled=True))
        await svc.disable_printer("already-off")
        with pytest.raises(PrinterAlreadyDisabledError) as exc_info:
            await svc.disable_printer("already-off")
        assert exc_info.value.slug == "already-off"

    async def test_not_found_raises(self, db_session) -> None:
        svc = PrinterAdminService(db_session, audit_user="testuser")
        with pytest.raises(PrinterNotFoundBySlugError):
            await svc.disable_printer("ghost")


class TestEnablePrinter:
    async def test_enable_after_disable(self, db_session) -> None:
        svc = PrinterAdminService(db_session, audit_user="testuser")
        await svc.create_printer(_make_payload(slug="re-enable"))
        await svc.disable_printer("re-enable")
        enabled = await svc.enable_printer("re-enable")
        assert enabled.enabled is True

    async def test_enable_creates_audit(self, db_session) -> None:
        from sqlmodel import select
        from app.models.printer import PrinterAudit

        svc = PrinterAdminService(db_session, audit_user="testuser")
        printer = await svc.create_printer(_make_payload(slug="enable-audit"))
        await svc.disable_printer("enable-audit")
        await svc.enable_printer("enable-audit")
        result = await db_session.execute(
            select(PrinterAudit)
            .where(PrinterAudit.printer_id == printer.id)
            .order_by(PrinterAudit.created_at)
        )
        audit_rows = list(result.scalars())
        enable_audits = [r for r in audit_rows if r.action == "enable"]
        assert len(enable_audits) == 1

    async def test_already_enabled_raises(self, db_session) -> None:
        svc = PrinterAdminService(db_session, audit_user="testuser")
        await svc.create_printer(_make_payload(slug="already-on"))
        with pytest.raises(PrinterAlreadyEnabledError) as exc_info:
            await svc.enable_printer("already-on")
        assert exc_info.value.slug == "already-on"

    async def test_not_found_raises(self, db_session) -> None:
        svc = PrinterAdminService(db_session, audit_user="testuser")
        with pytest.raises(PrinterNotFoundBySlugError):
            await svc.enable_printer("phantom")


class TestListPrinters:
    async def test_default_excludes_disabled(self, db_session) -> None:
        svc = PrinterAdminService(db_session, audit_user="testuser")
        await svc.create_printer(_make_payload(name="Aktiv", slug="aktiv-drucker", enabled=True))
        disabled_p = await svc.create_printer(
            _make_payload(name="Deaktiviert", slug="deaktiviert-drucker", enabled=True)
        )
        await svc.disable_printer(disabled_p.slug)
        printers = await svc.list_printers()
        slugs = [p.slug for p in printers]
        assert "aktiv-drucker" in slugs
        assert "deaktiviert-drucker" not in slugs

    async def test_include_disabled_returns_all(self, db_session) -> None:
        svc = PrinterAdminService(db_session, audit_user="testuser")
        await svc.create_printer(_make_payload(name="Aktiv2", slug="aktiv-2"))
        disabled_p = await svc.create_printer(
            _make_payload(name="Deaktiviert2", slug="deaktiviert-2")
        )
        await svc.disable_printer(disabled_p.slug)
        printers = await svc.list_printers(include_disabled=True)
        slugs = [p.slug for p in printers]
        assert "aktiv-2" in slugs
        assert "deaktiviert-2" in slugs


class TestGetPrinter:
    async def test_returns_printer_by_slug(self, db_session) -> None:
        svc = PrinterAdminService(db_session, audit_user="testuser")
        await svc.create_printer(_make_payload(slug="findme"))
        printer = await svc.get_printer("findme")
        assert printer is not None
        assert printer.slug == "findme"

    async def test_returns_none_for_unknown_slug(self, db_session) -> None:
        svc = PrinterAdminService(db_session, audit_user="testuser")
        printer = await svc.get_printer("unknown-slug")
        assert printer is None
