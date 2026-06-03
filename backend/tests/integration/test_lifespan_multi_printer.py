"""Phase 1i H (Task 7b): Multi-Printer-Wiring — BackendRouter + per-slug PrintService.

R4-A-C2-Fix: Jeder konfigurierte Drucker-Slug bekommt eine dedizierte
PrintService-Instanz registriert via backend_router.register_service(slug, service).
"""

from __future__ import annotations

import app.db.engine as _engine_module
import app.db.lifespan as _lifespan_module
import app.main as _main_module
import app.models  # noqa: F401 — registers all models with SQLModel.metadata
import pytest
from app.config import get_settings
from app.db.engine import _apply_pragmas
from app.main import create_app
from app.printer_backends import BackendRegistry
from app.printer_models.registry import ModelRegistry
from app.services.backend_router import BackendRouter
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

pytestmark = pytest.mark.asyncio


async def _noop_migrations() -> None:
    pass


async def _noop_verify(*_args, **_kwargs) -> None:
    pass


async def _noop_seed_templates(*_args, **_kwargs) -> int:
    return 0


@pytest.fixture()
async def clean_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Temp-DB + noop-migrations für Multi-Printer-Test."""
    import app.db.session as _session_module

    db_path = tmp_path / "multi_printer_test.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    eng = create_async_engine(url, echo=False, connect_args={"check_same_thread": False})
    event.listen(eng.sync_engine, "connect", _apply_pragmas)
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    sess = async_sessionmaker(bind=eng, expire_on_commit=False)

    monkeypatch.setattr(_engine_module, "engine", eng)
    monkeypatch.setattr(_engine_module, "async_session", sess)
    monkeypatch.setattr(_main_module, "engine", eng)
    monkeypatch.setattr(_main_module, "async_session", sess)
    monkeypatch.setattr(_session_module, "async_session", sess)
    monkeypatch.setattr(_lifespan_module, "run_migrations", _noop_migrations)
    monkeypatch.setattr(_main_module, "run_migrations", _noop_migrations)
    monkeypatch.setattr(_lifespan_module, "verify_alembic_at_head", _noop_verify)
    monkeypatch.setattr(_main_module, "verify_alembic_at_head", _noop_verify)
    monkeypatch.setattr(_lifespan_module, "seed_templates", _noop_seed_templates)
    monkeypatch.setattr(_main_module, "seed_templates", _noop_seed_templates)

    BackendRegistry._factories.clear()
    BackendRegistry._discovered = False
    ModelRegistry._models.clear()
    ModelRegistry._discovered = False
    get_settings.cache_clear()

    yield

    BackendRegistry._factories.clear()
    BackendRegistry._discovered = False
    ModelRegistry._models.clear()
    ModelRegistry._discovered = False
    get_settings.cache_clear()
    await eng.dispose()


async def test_lifespan_registers_per_slug_services(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    clean_db,
) -> None:
    """R4-A-C2-Fix: BackendRouter hat eine PrintService-Instanz pro konfiguriertem Slug.

    Verifikation nach Task 7b:
    - app.state.backend_router ist ein echter BackendRouter (nicht Shim)
    - service_for('brother-p750w') gibt eine PrintService-Instanz zurück
    - app.state.print_service verweist auf den ersten Drucker (Backward-Compat)
    """
    from app.printer_backends.mock_backend import MockPrinterBackend
    from app.services.print_service import PrintService

    cfg = tmp_path / "printers.yaml"
    cfg.write_text(
        "schema_version: 1\n"
        "printers:\n"
        "  - slug: brother-p750w\n"
        "    name: Brother P750W\n"
        "    backend: ptouch\n"
        "    model: PT-P750W\n"
        "    host: ''\n"
        "    port: 9100\n"
        "    snmp:\n"
        "      discover: false\n"
        "      community: public\n"
        "    cut_defaults:\n"
        "      half_cut: false\n"
        "      cut_at_end: true\n"
    )
    monkeypatch.setenv("PRINTER_HUB_PRINTERS_CONFIG", str(cfg))
    # BackendRouter._build_one auf MockPrinterBackend patchen (kein echter Drucker im Test).
    monkeypatch.setattr(BackendRouter, "_build_one", staticmethod(lambda _cfg: MockPrinterBackend()))
    get_settings.cache_clear()

    test_app = create_app()
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://t") as c:
        r = await c.get("/healthz")
        assert r.status_code in (200, 404)

        inner_state = test_app._app.state  # type: ignore[attr-defined]

        # BackendRouter ist ein echter BackendRouter (kein Shim mehr)
        assert isinstance(inner_state.backend_router, BackendRouter), (
            f"app.state.backend_router sollte BackendRouter sein, "
            f"ist aber {type(inner_state.backend_router)!r}"
        )

        # service_for('brother-p750w') gibt eine PrintService-Instanz zurück
        service = inner_state.backend_router.service_for("brother-p750w")
        assert isinstance(service, PrintService), (
            f"service_for('brother-p750w') sollte PrintService sein, "
            f"ist aber {type(service)!r}"
        )

        # Backward-Compat: app.state.print_service verweist auf ersten Drucker
        assert inner_state.print_service is service, (
            "app.state.print_service sollte auf denselben PrintService verweisen "
            "wie backend_router.service_for('brother-p750w')"
        )

        # app.state.printer_id ist gesetzt
        assert inner_state.printer_id is not None, (
            "app.state.printer_id sollte nach Lifespan-Start gesetzt sein"
        )
