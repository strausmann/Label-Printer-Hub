"""Phase 1i CA-1 — upsert_runtime_printers materialises Printer rows
from PrinterYAMLConfig list; idempotent across restarts.

R4-M-4/M-5-Fix: Ersetzt test_lifespan_printer_upsert.py das noch die
entfernte upsert_runtime_printer(Settings) Funktion testete.
M-H2-Fix: Multi-Printer-Loop.
PR#98-Gemini: session.flush() statt commit() im Loop — atomare Transaktion.
PR#98-Copilot: Slug-Collision-Detection bei UUID-Wechsel.
"""

from __future__ import annotations

import pytest
from app.db.lifespan import upsert_runtime_printers
from app.models.printer import Printer
from app.schemas.printer_config import CutDefaults, PrinterYAMLConfig, QueueConfig, SNMPConfig
from app.services.printer_identity import derive_printer_id
from sqlmodel import select

pytestmark = pytest.mark.asyncio

_PT750W_HOST = "192.0.2.50"
_PT750W_PORT = 9100
_PT750W_MODEL = "PT-P750W"


def _pt750w_cfg(
    *,
    slug: str = "pt-p750w-office",
    name: str = "PT-P750W Office",
    host: str = _PT750W_HOST,
    port: int = _PT750W_PORT,
    model: str = _PT750W_MODEL,
) -> PrinterYAMLConfig:
    """Test-PrinterYAMLConfig für PT-P750W."""
    return PrinterYAMLConfig(
        slug=slug,
        name=name,
        backend="ptouch",
        model=model,
        host=host,
        port=port,
        snmp=SNMPConfig(discover=False, community="public"),
        queue=QueueConfig(timeout_s=30),
        cut_defaults=CutDefaults(half_cut=False, cut_at_end=True),
    )


async def test_upsert_creates_row_when_db_empty(async_session_empty):
    cfg = _pt750w_cfg()
    expected_id = derive_printer_id(_PT750W_MODEL, _PT750W_HOST, _PT750W_PORT)

    returned_ids = await upsert_runtime_printers(async_session_empty, [cfg])

    assert len(returned_ids) == 1
    assert returned_ids[0] == expected_id
    result = await async_session_empty.execute(select(Printer))
    rows = list(result.scalars())
    assert len(rows) == 1
    assert rows[0].id == expected_id
    assert rows[0].slug == cfg.slug
    assert rows[0].name == cfg.name


async def test_upsert_is_idempotent(async_session_empty):
    cfg = _pt750w_cfg()
    first = await upsert_runtime_printers(async_session_empty, [cfg])
    second = await upsert_runtime_printers(async_session_empty, [cfg])
    assert first == second
    result = await async_session_empty.execute(select(Printer))
    assert len(list(result.scalars())) == 1


async def test_upsert_refreshes_slug_and_name_when_row_exists(async_session_empty):
    """Re-running upsert mit geändertem slug/name aktualisiert die Zeile."""
    cfg_v1 = _pt750w_cfg(slug="pt-v1", name="PT v1")
    ids_v1 = await upsert_runtime_printers(async_session_empty, [cfg_v1])
    assert len(ids_v1) == 1
    pid = ids_v1[0]

    cfg_v2 = _pt750w_cfg(slug="pt-v2", name="PT v2")
    await upsert_runtime_printers(async_session_empty, [cfg_v2])

    refreshed = await async_session_empty.get(Printer, pid)
    assert refreshed is not None
    assert refreshed.slug == "pt-v2"
    assert refreshed.name == "PT v2"


async def test_upsert_returns_empty_list_for_empty_configs(async_session_empty):
    result_ids = await upsert_runtime_printers(async_session_empty, [])
    assert result_ids == []
    result = await async_session_empty.execute(select(Printer))
    assert len(list(result.scalars())) == 0


async def test_upsert_multiple_printers(async_session_empty):
    """M-H2-Fix: Multi-Printer-Loop erzeugt mehrere Zeilen."""
    cfg1 = _pt750w_cfg(slug="printer-a", name="Printer A", host="192.0.2.50")
    cfg2 = _pt750w_cfg(slug="printer-b", name="Printer B", host="192.0.2.51")
    expected_id1 = derive_printer_id(_PT750W_MODEL, "192.0.2.50", _PT750W_PORT)
    expected_id2 = derive_printer_id(_PT750W_MODEL, "192.0.2.51", _PT750W_PORT)

    returned_ids = await upsert_runtime_printers(async_session_empty, [cfg1, cfg2])

    assert len(returned_ids) == 2
    assert expected_id1 in returned_ids
    assert expected_id2 in returned_ids

    result = await async_session_empty.execute(select(Printer))
    rows = list(result.scalars())
    assert len(rows) == 2


async def test_upsert_multi_printer_is_idempotent(async_session_empty):
    """Multi-Printer-Upsert bleibt idempotent."""
    cfg1 = _pt750w_cfg(slug="printer-a", name="Printer A", host="192.0.2.50")
    cfg2 = _pt750w_cfg(slug="printer-b", name="Printer B", host="192.0.2.51")

    first = await upsert_runtime_printers(async_session_empty, [cfg1, cfg2])
    second = await upsert_runtime_printers(async_session_empty, [cfg1, cfg2])

    assert sorted(str(i) for i in first) == sorted(str(i) for i in second)
    result = await async_session_empty.execute(select(Printer))
    rows = list(result.scalars())
    assert len(rows) == 2


# --- PR#98 Gemini + Copilot: flush() + slug-collision-detection ---

async def test_same_uuid_update_idempotent(async_session_empty):
    """PR#98-Gemini: Gleiche UUID beim zweiten Upsert → normaler UPDATE-Pfad."""
    cfg_v1 = _pt750w_cfg(slug="pt-office", name="PT Office v1")
    ids_v1 = await upsert_runtime_printers(async_session_empty, [cfg_v1])
    pid = ids_v1[0]

    cfg_v2 = _pt750w_cfg(slug="pt-office-renamed", name="PT Office v2")
    ids_v2 = await upsert_runtime_printers(async_session_empty, [cfg_v2])

    # UUID bleibt gleich (model/host/port unverändert)
    assert ids_v2[0] == pid
    result = await async_session_empty.execute(select(Printer))
    rows = list(result.scalars())
    assert len(rows) == 1
    assert rows[0].slug == "pt-office-renamed"
    assert rows[0].name == "PT Office v2"


async def test_slug_collision_different_uuid_migrates(async_session_empty):
    """PR#98-Copilot: Slug-Collision — alter Row mit gleicher slug aber anderer UUID
    wird gelöscht und durch neuen Row mit neuer UUID ersetzt (Migration-Pfad).
    """
    # Erster Eintrag: PT-P750W auf host .50
    cfg_old = _pt750w_cfg(slug="office-printer", name="Office Printer", host="192.0.2.50")
    ids_old = await upsert_runtime_printers(async_session_empty, [cfg_old])
    old_uuid = ids_old[0]

    # Zweiter Eintrag: gleiche slug, aber anderer host → andere UUID
    cfg_new = _pt750w_cfg(slug="office-printer", name="Office Printer", host="192.0.2.99")
    new_uuid = derive_printer_id(_PT750W_MODEL, "192.0.2.99", _PT750W_PORT)
    assert new_uuid != old_uuid  # Sicherheitscheck: UUIDs müssen verschieden sein

    ids_new = await upsert_runtime_printers(async_session_empty, [cfg_new])
    assert ids_new[0] == new_uuid

    # Es gibt nur noch einen Row mit der neuen UUID
    result = await async_session_empty.execute(select(Printer))
    rows = list(result.scalars())
    assert len(rows) == 1
    assert rows[0].id == new_uuid
    assert rows[0].slug == "office-printer"


async def test_multi_printer_transaction_atomicity(async_session_empty):
    """PR#98-Gemini: flush()-in-loop + commit()-am-Ende bleibt atomar.
    Alle Rows landen in derselben Transaktion; kein Partial-Write bei Fehler.
    """
    cfg1 = _pt750w_cfg(slug="atomic-a", name="Atomic A", host="192.0.2.50")
    cfg2 = _pt750w_cfg(slug="atomic-b", name="Atomic B", host="192.0.2.51")

    returned_ids = await upsert_runtime_printers(async_session_empty, [cfg1, cfg2])
    assert len(returned_ids) == 2

    result = await async_session_empty.execute(select(Printer))
    rows = list(result.scalars())
    assert len(rows) == 2
    slugs = {r.slug for r in rows}
    assert slugs == {"atomic-a", "atomic-b"}
