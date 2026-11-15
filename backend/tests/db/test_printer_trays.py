# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tables ``printer_trays`` and ``printer_calibrations`` (spec 7.1) and their migration."""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.models.printer import Printer
from app.models.printer_calibration import PrinterCalibration
from app.models.printer_tray import PrinterTray
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

BACKEND_DIR = Path(__file__).resolve().parents[2]
_ALEMBIC = Path(sys.executable).parent / "alembic"


async def _printer(session: Any) -> Printer:
    p = Printer(
        name=f"p-{uuid4().hex[:6]}",
        slug=f"p-{uuid4().hex[:6]}",
        model="IPP printer",
        backend="ipp",
        connection={"uri": "ipp://printer.example.invalid/ipp/print", "tls_verify": True},
    )
    session.add(p)
    await session.commit()
    return p


def _tray(printer_id: Any, key: str = "auto", **over: Any) -> PrinterTray:
    base: dict[str, Any] = {
        "printer_id": printer_id,
        "tray_key": key,
        "label": "Tray",
        "load_hint": None,
        "enabled": True,
        "is_default": key == "auto",
    }
    base.update(over)
    return PrinterTray(**base)


def _calibration(printer_id: Any, key: str = "auto", **over: Any) -> PrinterCalibration:
    base: dict[str, Any] = {
        "printer_id": printer_id,
        "tray_key": key,
        "method": "manual",
        "offset_x_hmm": 0,
        "offset_y_hmm": 0,
        "scale_x_ppm": 1_000_000,
        "scale_y_ppm": 1_000_000,
        "rotation_udeg": 0,
    }
    base.update(over)
    return PrinterCalibration(**base)


@pytest.mark.asyncio
async def test_trays_round_trip(session: Any) -> None:
    p = await _printer(session)
    session.add(_tray(p.id, "auto", load_hint="written side down"))
    session.add(_tray(p.id, "tray-2", is_default=False, enabled=False))
    await session.commit()
    rows = (await session.execute(select(PrinterTray).order_by(PrinterTray.tray_key))).scalars()
    got = [(t.tray_key, t.enabled, t.is_default, t.load_hint) for t in rows]
    assert got == [("auto", True, True, "written side down"), ("tray-2", False, False, None)]


@pytest.mark.asyncio
async def test_composite_pk_prevents_duplicate_tray_keys(session: Any) -> None:
    p = await _printer(session)
    session.add(_tray(p.id, "auto"))
    await session.commit()
    session.add(_tray(p.id, "auto", label="again"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


@pytest.mark.asyncio
async def test_same_tray_key_on_two_printers(session: Any) -> None:
    a = await _printer(session)
    b = await _printer(session)
    session.add_all([_tray(a.id), _tray(b.id)])
    await session.commit()


@pytest.mark.asyncio
async def test_tray_needs_existing_printer(session: Any) -> None:
    session.add(_tray(uuid4()))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


@pytest.mark.asyncio
async def test_trays_do_not_cascade_delete_with_printer(session: Any) -> None:
    """Printers are soft-disabled; a hard delete of a printer with trays is refused."""
    p = await _printer(session)
    session.add(_tray(p.id))
    await session.commit()
    with pytest.raises(IntegrityError):
        await session.execute(delete(Printer).where(Printer.id == p.id))
        await session.commit()
    await session.rollback()


@pytest.mark.asyncio
async def test_calibration_round_trip_and_pk(session: Any) -> None:
    p = await _printer(session)
    session.add(
        _calibration(p.id, offset_x_hmm=-125, scale_y_ppm=1_002_500, rotation_udeg=-350_000)
    )
    await session.commit()
    row = (await session.execute(select(PrinterCalibration))).scalar_one()
    assert (row.offset_x_hmm, row.scale_y_ppm, row.rotation_udeg) == (-125, 1_002_500, -350_000)
    assert row.corrections is None
    assert row.measured_on_type_version_id is None
    assert row.updated_at is not None
    session.add(_calibration(p.id))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


@pytest.mark.asyncio
async def test_calibration_method_check(session: Any) -> None:
    printer_id = (await _printer(session)).id
    session.add(_calibration(printer_id, method="guess"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()
    session.add(_calibration(printer_id, method="photo"))
    await session.commit()


@pytest.mark.asyncio
async def test_calibration_needs_existing_printer(session: Any) -> None:
    session.add(_calibration(uuid4()))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


def _alembic(sandbox: Path, *args: str) -> None:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{BACKEND_DIR}{os.pathsep}{existing}" if existing else str(BACKEND_DIR)
    proc = subprocess.run(
        [str(_ALEMBIC), *args],
        cwd=sandbox,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def _tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def test_migration_up_and_down() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        sandbox = Path(tmp)
        shutil.copy2(BACKEND_DIR / "alembic.ini", sandbox / "alembic.ini")
        shutil.copytree(BACKEND_DIR / "alembic", sandbox / "alembic")
        (sandbox / "data").mkdir()
        db = sandbox / "data" / "hub.db"

        _alembic(sandbox, "upgrade", "20261105b1")
        assert {"printer_trays", "printer_calibrations"} <= _tables(db)

        _alembic(sandbox, "downgrade", "20261105a1")
        tables = _tables(db)
        assert "printer_trays" not in tables
        assert "printer_calibrations" not in tables
        assert "sheets" in tables  # the previous revision is untouched

        _alembic(sandbox, "upgrade", "20261105b1")
        assert {"printer_trays", "printer_calibrations"} <= _tables(db)
