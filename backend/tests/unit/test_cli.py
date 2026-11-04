"""Recovery command: printer-hub admin create-key (spec 8.2, D7)."""

from __future__ import annotations

import pytest


@pytest.fixture
def _cli_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Temp SQLite DB; NullPool so the CLI's own event loop can use it safely."""
    import asyncio

    import app.db.engine as engine_module
    import app.models  # noqa: F401
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from sqlmodel import SQLModel

    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'cli.db'}", poolclass=NullPool)

    async def _create() -> None:
        async with eng.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    asyncio.run(_create())
    factory = async_sessionmaker(eng, expire_on_commit=False)
    monkeypatch.setattr(engine_module, "async_session", factory)
    return factory


def test_cli_create_key_prints_once_and_key_works(_cli_db, capsys) -> None:
    import asyncio

    from app import cli
    from app.auth.verifier import verify_api_key_async
    from app.repositories import api_keys as api_keys_repo

    code = cli.main(["admin", "create-key", "--scope", "admin", "--name", "recovery"])
    out, err = capsys.readouterr()
    assert code == 0, err
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1
    plaintext = lines[0].strip()
    assert plaintext.startswith("lh_pat_")
    assert out.count(plaintext) == 1
    assert plaintext not in err

    async def _check() -> None:
        async with _cli_db() as s:
            row = await api_keys_repo.get_by_prefix(s, plaintext[:16])
            assert row is not None
            assert row.scopes == ["admin"]
            assert row.name == "recovery"
            assert row.enabled
            assert await verify_api_key_async(plaintext, row.key_hash)

    asyncio.run(_check())


def test_cli_rejects_unknown_scope(capsys) -> None:
    from app import cli

    code = cli.main(["admin", "create-key", "--scope", "root", "--name", "x"])
    assert code == 2
    assert "lh_pat_" not in capsys.readouterr().out


def test_cli_reports_database_error(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    import app.db.engine as engine_module
    from app import cli

    def _broken():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(engine_module, "async_session", _broken)
    code = cli.main(["admin", "create-key", "--scope", "print", "--name", "x"])
    out, err = capsys.readouterr()
    assert code == 1
    assert "lh_pat_" not in out
    assert "database unavailable" in err
