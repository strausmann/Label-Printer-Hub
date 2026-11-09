"""An API key written by the old phase-7c seed (hyphenated UUID text) still works after upgrade.

SQLModel binds UUIDs as 32-char hex, the old seed stored ``str(uuid4())``. SQLite compares
text, so a browser session referencing such a key must still resolve it.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID, uuid4

import app.db.engine as _engine_module
import app.db.session as _session_module
import app.main as _main_module
import bcrypt
import pytest
from alembic import command
from alembic.config import Config
from app.config import get_settings
from app.db.engine import _apply_pragmas
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_ALEMBIC_INI = Path(__file__).parents[3] / "alembic.ini"
# Last revision before the web UI work.
_REV_BEFORE_UI = "20260605b2c3d4e5"


@pytest.mark.asyncio
async def test_legacy_hyphenated_key_id_signs_in_after_upgrade(tmp_path, monkeypatch):
    db = tmp_path / "legacy.db"
    url = f"sqlite+aiosqlite:///{db}"
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    await asyncio.to_thread(command.upgrade, cfg, _REV_BEFORE_UI)

    # Insert the way the removed phase-7c seed did: id=str(uuid4()), raw SQL.
    legacy_id = str(uuid4())
    plaintext = f"lh_pat_{uuid4().hex}"
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    seed_eng = create_async_engine(url)
    async with seed_eng.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO api_keys (id, name, key_hash, key_prefix, scopes, "
                "allowed_printer_ids, rate_limit_per_minute, enabled, created_at) "
                "VALUES (:id, 'legacy-admin', :h, :p, :s, '[]', 60, 1, '2026-05-17T00:00:00+00:00')"
            ),
            {"id": legacy_id, "h": hashed, "p": plaintext[:16], "s": json.dumps(["admin"])},
        )
    await seed_eng.dispose()

    await asyncio.to_thread(command.upgrade, cfg, "head")

    eng = create_async_engine(url)
    event.listen(eng.sync_engine, "connect", _apply_pragmas)  # foreign_keys=ON
    sess = async_sessionmaker(bind=eng, expire_on_commit=False)
    for module in (_engine_module, _main_module):
        monkeypatch.setattr(module, "engine", eng)
    for module in (_engine_module, _main_module, _session_module):
        monkeypatch.setattr(module, "async_session", sess)
    get_settings.cache_clear()
    from app.services.rate_limiter import _sign_in_rate_limiter

    _sign_in_rate_limiter.clear()

    app = _main_module.create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post("/api/v1/auth/session", json={"key": plaintext})
        assert resp.status_code == 204, resp.text
        body = (await client.get("/api/v1/auth/session")).json()
        assert body["source"] == "api-key"
        assert body["scope"] == "admin"
        # The session keeps working: it resolves the key row on every request.
        assert (await client.get("/api/v1/admin/api-keys")).status_code == 200
        async with eng.connect() as conn:
            stored = (await conn.execute(text("SELECT api_key_id FROM ui_sessions"))).scalar()
    assert stored is not None
    assert UUID(str(stored)) == UUID(legacy_id)
    await eng.dispose()
