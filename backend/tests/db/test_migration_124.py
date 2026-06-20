"""Tests für Migration #124: printers_audit-Tabelle + Schema-Erweiterung + Backfill.

TDD-Failing-Tests — werden erst grün nach:
  1. Alembic-Migration erzeugen (printers_audit_and_backfill)
  2. ORM-Model printer.py erweitern (queue_timeout_s, cut_defaults_half_cut)

Testfälle:
  T1 — printers-Tabelle hat die neuen Spalten (queue_timeout_s, cut_defaults_half_cut)
  T2 — printers_audit-Tabelle existiert mit allen Pflichtfeldern + Indizes
  T3 — _backfill_snmp befüllt SNMP für Bestandsrows mit host,
       lässt rows mit bestehendem snmp unverändert,
       überspringt rows mit NULL-connection.
"""

from __future__ import annotations

import importlib
import json
import pathlib
import tempfile
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

# ---------------------------------------------------------------------------
# Hilfsfunktion: temporäre SQLite-DB über alembic upgrade head hochfahren
# ---------------------------------------------------------------------------

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]


def _alembic_upgrade_to_head(db_path: pathlib.Path) -> None:
    """Alembic upgrade head synchron in einem temporären Verzeichnis."""
    import shutil
    import subprocess
    import sys

    alembic_bin = pathlib.Path(sys.executable).parent / "alembic"
    with tempfile.TemporaryDirectory() as tmp:
        sandbox = pathlib.Path(tmp)
        shutil.copy2(BACKEND_DIR / "alembic.ini", sandbox / "alembic.ini")
        shutil.copytree(BACKEND_DIR / "alembic", sandbox / "alembic")
        # Schreibe alembic.ini mit dem konkreten DB-Pfad (absolut)
        ini_text = (sandbox / "alembic.ini").read_text()
        ini_text = ini_text.replace(
            "sqlite+aiosqlite:///./data/hub.db",
            f"sqlite+aiosqlite:///{db_path}",
        )
        (sandbox / "alembic.ini").write_text(ini_text)

        import os

        env = os.environ.copy()
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{BACKEND_DIR}{os.pathsep}{existing}" if existing else str(BACKEND_DIR)

        result = subprocess.run(
            [str(alembic_bin), "upgrade", "head"],
            cwd=sandbox,
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, (
            f"alembic upgrade head fehlgeschlagen\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# T1 — printers-Tabelle hat die neuen Spalten
# ---------------------------------------------------------------------------


def test_printers_new_columns_exist(tmp_path: pathlib.Path) -> None:
    """printers-Tabelle muss queue_timeout_s und cut_defaults_half_cut enthalten.

    Beide Spalten müssen nach alembic upgrade head via PRAGMA table_info
    sichtbar sein.
    """
    db_path = tmp_path / "t1_test.db"
    _alembic_upgrade_to_head(db_path)

    import sqlite3

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(printers)")
    columns = {row[1] for row in cur.fetchall()}
    conn.close()

    assert "queue_timeout_s" in columns, (
        "printers.queue_timeout_s fehlt — Migration hat die Spalte nicht angelegt."
    )
    assert "cut_defaults_half_cut" in columns, (
        "printers.cut_defaults_half_cut fehlt — Migration hat die Spalte nicht angelegt."
    )


# ---------------------------------------------------------------------------
# T2 — printers_audit-Tabelle existiert mit allen Pflichtfeldern + Indizes
# ---------------------------------------------------------------------------


def test_printers_audit_table_exists(tmp_path: pathlib.Path) -> None:
    """printers_audit-Tabelle muss nach Migration mit allen Pflichtfeldern existieren.

    Geprüft: alle Spalten (id, printer_id, slug, action, before_json, after_json,
    updated_by, created_at) sowie die beiden Indizes
    idx_printers_audit_printer_id und idx_printers_audit_created_at_desc.
    """
    db_path = tmp_path / "t2_test.db"
    _alembic_upgrade_to_head(db_path)

    import sqlite3

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Tabelle existiert
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='printers_audit'")
    assert cur.fetchone() is not None, "printers_audit-Tabelle existiert nicht."

    # Spalten prüfen
    cur.execute("PRAGMA table_info(printers_audit)")
    columns = {row[1] for row in cur.fetchall()}
    expected_columns = {
        "id",
        "printer_id",
        "slug",
        "action",
        "before_json",
        "after_json",
        "updated_by",
        "created_at",
    }
    missing = expected_columns - columns
    assert not missing, f"printers_audit: fehlende Spalten {missing}"

    # Indizes prüfen
    cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='printers_audit'")
    indexes = {row[0] for row in cur.fetchall()}
    assert "idx_printers_audit_printer_id" in indexes, "Index idx_printers_audit_printer_id fehlt."
    assert "idx_printers_audit_created_at_desc" in indexes, (
        "Index idx_printers_audit_created_at_desc fehlt."
    )

    conn.close()


# ---------------------------------------------------------------------------
# T3 — _backfill_snmp-Funktion korrekt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backfill_snmp(tmp_path: pathlib.Path) -> None:
    """_backfill_snmp muss:
    - snmp-Block für Rows mit host-Feld einfügen ({"discover": false, "community": "public"})
    - Rows mit bereits vorhandenem snmp-Block unverändert lassen (idempotent)
    - Rows mit NULL-connection überspringen (keine Exception)
    - Rows ohne host-Feld überspringen
    """
    db_path = tmp_path / "t3_test.db"
    _alembic_upgrade_to_head(db_path)

    # Migration-Modul laden um _backfill_snmp direkt zu testen
    mig_dir = BACKEND_DIR / "alembic" / "versions"
    # Finde die Migration-Datei (Dateiname enthält "printers_audit_and_backfill")
    mig_files = list(mig_dir.glob("*printers_audit_and_backfill*.py"))
    assert mig_files, "Keine Migration mit 'printers_audit_and_backfill' im Dateinamen gefunden."
    mig_file = mig_files[0]
    spec = importlib.util.spec_from_file_location("mig_124", mig_file)
    mig = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mig)  # type: ignore[union-attr]

    assert hasattr(mig, "_backfill_snmp"), (
        "_backfill_snmp muss eine top-level Funktion in der Migration sein."
    )

    # Test-Daten direkt in SQLite einfügen (sync)
    import sqlite3

    sync_conn = sqlite3.connect(db_path)
    now = datetime.now(UTC).isoformat()

    def _insert(sync_conn: sqlite3.Connection, pid: str, conn_val: Any) -> None:
        conn_json = json.dumps(conn_val) if conn_val is not None else None
        sync_conn.execute(
            "INSERT INTO printers "
            "(id, name, slug, model, backend, connection, enabled, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pid,
                f"name-{pid[:8]}",
                f"slug-{pid[:8]}",
                "pt-series",
                "ptouch",
                conn_json,
                1,
                now,
                now,
            ),
        )

    # Row A: hat host → snmp wird eingefügt
    pid_a = str(uuid.uuid4())
    _insert(sync_conn, pid_a, {"host": "192.168.1.10", "port": 9100})

    # Row B: hat bereits snmp → bleibt unverändert
    pid_b = str(uuid.uuid4())
    existing_snmp = {"discover": True, "community": "private"}
    _insert(sync_conn, pid_b, {"host": "192.168.1.11", "snmp": existing_snmp})

    # Row C: NULL connection → wird übersprungen
    pid_c = str(uuid.uuid4())
    _insert(sync_conn, pid_c, None)

    # Row D: keine host → wird übersprungen
    pid_d = str(uuid.uuid4())
    _insert(sync_conn, pid_d, {"interface": "usb"})

    sync_conn.commit()
    sync_conn.close()

    # _backfill_snmp via AsyncEngine + run_sync aufrufen
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(mig._backfill_snmp)
    await engine.dispose()

    # Ergebnisse prüfen
    sync_conn = sqlite3.connect(db_path)

    def _get_conn(pid: str) -> Any:
        row = sync_conn.execute("SELECT connection FROM printers WHERE id = ?", (pid,)).fetchone()
        assert row is not None
        val = row[0]
        return json.loads(val) if val is not None else None

    conn_a = _get_conn(pid_a)
    assert "snmp" in conn_a, f"Row A: snmp wurde nicht eingefügt, got {conn_a}"
    assert conn_a["snmp"] == {"discover": False, "community": "public"}, (
        f"Row A: snmp-Wert inkorrekt, got {conn_a['snmp']}"
    )
    # host bleibt erhalten
    assert conn_a.get("host") == "192.168.1.10"

    conn_b = _get_conn(pid_b)
    assert conn_b["snmp"] == existing_snmp, (
        f"Row B: bestehender snmp-Block wurde verändert, got {conn_b['snmp']}"
    )

    conn_c = _get_conn(pid_c)
    assert conn_c is None, f"Row C: NULL-connection wurde verändert, got {conn_c}"

    conn_d = _get_conn(pid_d)
    assert "snmp" not in conn_d, f"Row D: snmp wurde fälschlicherweise eingefügt, got {conn_d}"

    sync_conn.close()
