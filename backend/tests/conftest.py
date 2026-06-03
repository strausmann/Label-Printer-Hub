"""Pytest configuration shared across all tests.

Hardware tests are skipped by default — pass `--hardware` to opt in.
"""

from __future__ import annotations

import pathlib

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel


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


@pytest.fixture
def printer_config_loader_fixture(tmp_path: pathlib.Path):
    """Liefert (loader_cls, write_yaml(text) -> Path). Räumt Cache nach Test auf."""
    from app.services.printer_config_loader import PrinterConfigLoader

    def _write(text: str) -> pathlib.Path:
        f = tmp_path / "printers.yaml"
        f.write_text(text)
        PrinterConfigLoader.load_file(f)
        return f

    yield PrinterConfigLoader, _write
    PrinterConfigLoader.clear()
