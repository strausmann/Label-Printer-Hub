"""Pytest configuration shared across all tests.

Hardware tests are skipped by default — pass `--hardware` to opt in.
"""

from __future__ import annotations

import base64
import os
import pathlib

import pytest
import pytest_asyncio
from app.sheets.locking import install_statement_counter
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

# app.main and app.db.engine call get_settings() at import time, so the required
# settings must exist before any test module is imported (a fixture is too late).
# Obviously fake values, derived at runtime from readable text (no high-entropy literal).
os.environ.setdefault(
    "LABELYARD_SECRET_KEY",
    base64.urlsafe_b64encode(b"test-secret-key-0123456789abcdef").decode(),
)
os.environ.setdefault("LABELYARD_PUBLIC_URL", "http://localhost:8000")


SETTINGS_ENV_PREFIXES = ("LABELYARD_", "PRINTER_HUB_")


def clear_settings_env(monkeypatch: pytest.MonkeyPatch, *prefixes: str) -> None:
    """Delete every variable with one of the prefixes (both settings prefixes by default).

    Tests that depend on a variable being absent must not depend on what the runner or a
    developer shell exports, and the old prefix is a valid source since the Labelyard rename.
    """
    for name in list(os.environ):
        if name.upper().startswith(prefixes or SETTINGS_ENV_PREFIXES):
            monkeypatch.delenv(name)


@pytest.fixture
def clean_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No LABELYARD_* and no PRINTER_HUB_* variable in the environment for this test."""
    clear_settings_env(monkeypatch)


@pytest.fixture
def clean_legacy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No PRINTER_HUB_* variable in the environment (the cached settings stay untouched)."""
    clear_settings_env(monkeypatch, "PRINTER_HUB_")

# The test engine factory: every engine a test creates counts its statements, as the app's
# engine does, so the sheet write lock's order check (264-01) runs in every test. Installed on
# the ``Engine`` class because the tests create their engines in many places; a test of an
# engine without the counter removes it for its own duration.
install_statement_counter(Engine)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--hardware",
        action="store_true",
        default=False,
        help="run hardware-in-the-loop tests against real Brother printers",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--hardware"):
        return
    skip_hardware = pytest.mark.skip(reason="hardware tests need --hardware flag")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip_hardware)


@pytest_asyncio.fixture
async def async_session_factory(tmp_path: pathlib.Path):
    """Per-test SQLite + async_sessionmaker für isolierte JobStore-Tests.

    FOREIGN KEYS sind absichtlich DEAKTIVIERT (SQLite-Default).
    Phase-2-Tests nutzen uuid4() als printer_id ohne echte Printer-Rows in
    der DB — FK ON würde Tests verlangen die Printer-Stamm-Daten anlegen,
    was den Test-Scope (JobStore-Isolation) unnötig erweitert.

    Produktions-Code läuft mit FK ON (PRAGMA in app/db/engine.py).
    """
    import app.models  # noqa: F401 — registriert alle Models bei SQLModel.metadata

    db_path = tmp_path / "job_store_test.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(url, echo=False, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


# printer_config_loader_fixture entfernt — PrinterConfigLoader wurde in
# Phase 5 (#124) zusammen mit printer_config.py gelöscht.
# Drucker-Konfiguration erfolgt ausschließlich über die Admin-API (DB).
