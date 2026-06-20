"""Unit-Tests für printers_repo.list_all mit enabled-Filter (Issue #124, Task 2.6).

TDD: Tests wurden vor der Implementation geschrieben.
Alle IPs aus RFC-5737 Bereich (192.0.2.x) — Repo-Konvention.
"""

from __future__ import annotations

import app.models  # noqa: F401 — registriert alle Models mit SQLModel.metadata
import pytest
from app.models.printer import Printer
from app.repositories import printers as printers_repo

# ---------------------------------------------------------------------------
# Hilfsfunktion
# ---------------------------------------------------------------------------


async def _create_printer(
    db_session,
    *,
    name: str,
    enabled: bool = True,
) -> Printer:
    """Legt einen Testdrucker mit minimaler Konfiguration an."""
    # Slug muss eindeutig sein — verwende den Namen als Slug-Basis
    p = Printer(
        name=name,
        slug=name,
        model="pt-series",
        backend="ptouch",
        connection={"host": "192.0.2.1", "port": 9100},
        enabled=enabled,
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


# ---------------------------------------------------------------------------
# Task 2.6 — list_all mit include_disabled-Flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_default_excludes_disabled(db_session) -> None:
    """list_all() ohne Argument schließt deaktivierte Drucker aus (Soft-Delete-Filter)."""
    enabled_p = await _create_printer(db_session, name="drucker-aktiv", enabled=True)
    await _create_printer(db_session, name="drucker-deaktiviert", enabled=False)

    result = await printers_repo.list_all(db_session)

    names = [p.name for p in result]
    assert enabled_p.name in names
    assert "drucker-deaktiviert" not in names
    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_all_include_disabled_returns_all(db_session) -> None:
    """list_all(include_disabled=True) liefert alle Drucker inklusive deaktivierter."""
    await _create_printer(db_session, name="drucker-aktiv", enabled=True)
    await _create_printer(db_session, name="drucker-deaktiviert", enabled=False)

    result = await printers_repo.list_all(db_session, include_disabled=True)

    names = [p.name for p in result]
    assert "drucker-aktiv" in names
    assert "drucker-deaktiviert" in names
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_all_empty_db_returns_empty_list(db_session) -> None:
    """list_all() auf leerer DB gibt eine leere Liste zurück."""
    result = await printers_repo.list_all(db_session)

    assert result == []


@pytest.mark.asyncio
async def test_list_all_only_disabled_default_returns_empty(db_session) -> None:
    """list_all() ohne Flag gibt leere Liste wenn nur deaktivierte Drucker existieren."""
    await _create_printer(db_session, name="nur-deaktiviert", enabled=False)

    result = await printers_repo.list_all(db_session)

    assert result == []
