"""D7 end to end on a schema built by the real alembic migrations (not create_all).

Proves a fresh install has no API key, the migrations print no key, and the
one-time bootstrap key signs in afterwards.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import app.db.engine as _engine_module
import app.db.session as _session_module
import app.main as _main_module
import pytest
from alembic import command
from alembic.config import Config
from app.config import get_settings
from app.db.engine import _apply_pragmas
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_ALEMBIC_INI = Path(__file__).parents[3] / "alembic.ini"
FAKE_BOOTSTRAP_KEY = "fake-bootstrap-key-for-tests-0123456789ab"


@pytest.mark.asyncio
async def test_fresh_migrated_db_has_no_key_and_bootstrap_sign_in_works(
    tmp_path, monkeypatch, capfd
):
    db = tmp_path / "migrated.db"
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db}")
    cfg.attributes["configure_logger"] = False
    # env.py runs its own event loop, so migrate from a worker thread.
    await asyncio.to_thread(command.upgrade, cfg, "head")
    out, err = capfd.readouterr()
    assert "lh_" not in out + err, "a migration printed an API key"

    eng = create_async_engine(f"sqlite+aiosqlite:///{db}")
    event.listen(eng.sync_engine, "connect", _apply_pragmas)
    async with eng.connect() as conn:
        count = (await conn.execute(text("SELECT COUNT(*) FROM api_keys"))).scalar()
    assert count == 0

    # Point the app at the migrated DB (the autouse fixture set a create_all one).
    sess = async_sessionmaker(bind=eng, expire_on_commit=False)
    for module in (_engine_module, _main_module):
        monkeypatch.setattr(module, "engine", eng)
    for module in (_engine_module, _main_module, _session_module):
        monkeypatch.setattr(module, "async_session", sess)
    monkeypatch.setenv("PRINTER_HUB_BOOTSTRAP_ADMIN_KEY", FAKE_BOOTSTRAP_KEY)
    get_settings.cache_clear()
    from app.services.rate_limiter import _sign_in_rate_limiter

    _sign_in_rate_limiter.clear()

    app = _main_module.create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post("/api/v1/auth/session", json={"key": FAKE_BOOTSTRAP_KEY})
        assert resp.status_code == 204, resp.text
        body = (await client.get("/api/v1/auth/session")).json()
        assert body["source"] == "bootstrap"
        assert body["scope"] == "admin"
    await eng.dispose()
