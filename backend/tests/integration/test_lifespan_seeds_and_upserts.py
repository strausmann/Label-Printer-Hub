"""Phase 7b Cluster 1a + 1b end-to-end test: a fresh DB after lifespan
startup contains the seed templates AND one deterministic-id printer,
and app.state.printer_id matches the DB printer.id."""

from __future__ import annotations

import app.db.engine as _engine_module
import pytest
from app.models.printer import Printer
from app.models.template import Template
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

pytestmark = pytest.mark.asyncio


async def test_fresh_lifespan_seeds_templates_and_creates_printer(
    _temp_db_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After lifespan startup, templates are seeded AND printer is upserted,
    and app.state.printer_id matches the one Printer row in the DB."""
    # _mock_backend_env (autouse) sets PRINTER_HUB_PRINTER_MODEL=PT-P750W and
    # PRINTER_HUB_PRINTER_BACKEND=mock.  We additionally set a host+port so
    # upsert_runtime_printer() finds all three required fields (model, host, port).
    monkeypatch.setenv("PRINTER_HUB_PT750W_HOST", "192.0.2.50")
    monkeypatch.setenv("PRINTER_HUB_PT750W_PORT", "9100")

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
            templates = list((await s.execute(select(Template))).scalars())
            printers = list((await s.execute(select(Printer))).scalars())

        assert len(templates) >= 1, (
            f"Expected at least one seeded template, got {len(templates)}. "
            "Check that TemplateLoader.load_dir() runs BEFORE seed_templates() "
            "in the lifespan."
        )
        assert len(printers) == 1, (
            f"Expected exactly one upserted Printer row, got {len(printers)}. "
            "Check that upsert_runtime_printer() is wired in the lifespan."
        )
        # The deterministic id produced by upsert_runtime_printer must be the
        # same id that make_queue_printer received and exposed via app.state.printer_id.
        # create_app() returns a _LifespanManager; the FastAPI state is on ._app.
        inner_app_state = test_app._app.state  # type: ignore[attr-defined]
        assert inner_app_state.printer_id == printers[0].id, (
            f"app.state.printer_id={inner_app_state.printer_id!r} != "
            f"DB Printer.id={printers[0].id!r}. "
            "The DB uuid from upsert_runtime_printer must be plumbed into "
            "make_queue_printer(printer_id=db_printer_id)."
        )
