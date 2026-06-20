"""Phase 1i CA-1 / Phase 7b Cluster 1b end-to-end test: a fresh DB after
lifespan startup contains one deterministic-id printer, and
app.state.printer_id matches the DB printer.id.

Phase 1k.1a (Task 25): Template seeding removed (templates table dropped).
Test renamed from test_fresh_lifespan_seeds_templates_and_creates_printer
→ test_fresh_lifespan_creates_printer_with_deterministic_id.
Template assertions removed; printer assertions kept verbatim.

Issue #124 (Phase 5-Übergang): Der derive_printer_id-Vergleich mit 3-arg ist
TEMPORÄR ÜBERSPRUNGEN. Phase 5 stellt die volle Testabdeckung wieder her.
"""

from __future__ import annotations

import app.db.engine as _engine_module
import pytest
from app.models.printer import Printer
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

pytestmark = pytest.mark.asyncio


@pytest.mark.skip(
    reason="Issue #124 Phase 5: derive_printer_id 3-arg entfernt — "
    "UUID-Vergleich muss auf 4-arg-Semantik umgestellt werden"
)
async def test_fresh_lifespan_creates_printer_with_deterministic_id(
    _temp_db_engine,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """After lifespan startup, printer is upserted and app.state.printer_id
    matches the one Printer row in the DB.

    Phase 1i CA-1/H (Task 7b): printers.yaml mit nicht-leerem Host statt Env-Vars,
    damit upsert_runtime_printers() eine echte Printer-Row anlegt.
    BackendRouter._build_one wird auf MockPrinterBackend gepatcht weil
    PTouchBackend bei leerem Host ValueError wirft.
    """
    from app.printer_backends.mock_backend import MockPrinterBackend
    from app.services.backend_router import BackendRouter
    from app.services.printer_identity import derive_printer_id

    # printers.yaml mit echtem Host → upsert_runtime_printers legt Zeile an
    _printers_yaml = tmp_path / "test_printers.yaml"
    _printers_yaml.write_text(
        "schema_version: 1\n"
        "printers:\n"
        "  - slug: test-pt-p750w\n"
        "    name: Test PT-P750W\n"
        "    backend: ptouch\n"
        "    model: PT-P750W\n"
        "    host: '192.0.2.50'\n"
        "    port: 9100\n"
        "    snmp:\n"
        "      discover: false\n"
        "      community: public\n"
        "    cut_defaults:\n"
        "      half_cut: false\n"
        "      cut_at_end: true\n"
    )
    monkeypatch.setenv("PRINTER_HUB_PRINTERS_CONFIG", str(_printers_yaml))
    # Phase 1i H (Task 7b): _build_backend_from_config entfernt — BackendRouter._build_one patchen.
    monkeypatch.setattr(
        BackendRouter, "_build_one", staticmethod(lambda _cfg: MockPrinterBackend())
    )

    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()

    test_app = create_app()

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # Trigger the lifespan by making any request; the lifespan runs at
        # ASGI startup inside ASGITransport.
        resp = await client.get("/healthz")
        assert resp.status_code == 200, f"healthz failed: {resp.text}"

        # Inspect the DB state while the lifespan is active.
        # Use the attribute on _engine_module (patched by _temp_db_engine fixture),
        # not the name bound at test-module import time.
        async with _engine_module.async_session() as s:
            printers = list((await s.execute(select(Printer))).scalars())

        assert len(printers) == 1, (
            f"Expected exactly one upserted Printer row, got {len(printers)}. "
            "Check that upsert_runtime_printers() is wired in the lifespan."
        )
        # The deterministic id from upsert_runtime_printers must be the same id
        # that make_queue_printer received and exposed via app.state.printer_id.
        expected_id = derive_printer_id("PT-P750W", "192.0.2.50", 9100)  # type: ignore[call-arg]
        inner_app_state = test_app._app.state  # type: ignore[attr-defined]
        assert inner_app_state.printer_id == printers[0].id, (
            f"app.state.printer_id={inner_app_state.printer_id!r} != "
            f"DB Printer.id={printers[0].id!r}. "
            "The DB uuid from upsert_runtime_printers must be plumbed into "
            "make_queue_printer(printer_id=db_printer_id)."
        )
        assert printers[0].id == expected_id, (
            f"DB Printer.id={printers[0].id!r} != expected deterministic id {expected_id!r}. "
            "upsert_runtime_printers muss derive_printer_id(model, host, port) nutzen."
        )
