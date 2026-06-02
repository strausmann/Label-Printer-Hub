"""Unit-Tests für BatchRead und BatchSummary (Phase 2 Schemas).

Stellt sicher, dass datetime-Felder in BatchRead mit UTC-Offset (`Z`)
serialisiert werden, damit der Go-Client (RFC3339-strict) die Antworten
korrekt dekodieren kann.
"""

from __future__ import annotations

import datetime
import json
from uuid import uuid4

from app.schemas.batch_read import BatchRead, BatchSummary
from app.schemas.job import JobRead


def _make_summary(queued: int = 0, printing: int = 0) -> BatchSummary:
    return BatchSummary(
        total=queued + printing,
        queued=queued,
        printing=printing,
        done=0,
        failed=0,
        cancelled=0,
    )


def _make_job_read(
    created_at: datetime.datetime,
    updated_at: datetime.datetime,
) -> JobRead:
    return JobRead(
        id=uuid4(),
        printer_id=uuid4(),
        template_key="hangar-furniture-12mm",
        state="done",
        payload={},
        result=None,
        error=None,
        created_at=created_at,
        updated_at=updated_at,
        started_at=None,
        finished_at=None,
    )


def _make_batch_read(created_at: datetime.datetime) -> BatchRead:
    job_dt = datetime.datetime(2026, 6, 2, 9, 46, 18, 701971)
    return BatchRead(
        id=uuid4(),
        printer_id=uuid4(),
        created_by="test@example.com",
        created_at=created_at,
        jobs=[_make_job_read(job_dt, job_dt)],
        summary=_make_summary(),
    )


# ---------------------------------------------------------------------------
# Hauptanforderung: RFC3339 mit Z-Suffix für naive datetimes
# ---------------------------------------------------------------------------


def test_created_at_naive_serialised_with_z_suffix() -> None:
    """Naive datetime (aus SQLite) muss in `model_dump_json` mit `Z` enden.

    Regression: Vor dem Fix lieferte BatchRead naive ISO-Strings ohne TZ
    (`2026-06-02T09:46:18.701971`), die der Go-RFC3339-Parser ablehnte.
    """
    naive_dt = datetime.datetime(2026, 6, 2, 9, 46, 18, 701971)
    batch = _make_batch_read(naive_dt)

    dumped = json.loads(batch.model_dump_json())

    assert dumped["created_at"].endswith("Z"), (
        f"created_at muss mit 'Z' enden, ist aber: {dumped['created_at']!r}"
    )


def test_created_at_utc_aware_serialised_with_z_suffix() -> None:
    """UTC-aware datetime wird ebenfalls mit `Z` serialisiert."""
    utc_dt = datetime.datetime(2026, 6, 2, 9, 46, 18, 701971, tzinfo=datetime.UTC)
    batch = _make_batch_read(utc_dt)

    dumped = json.loads(batch.model_dump_json())

    assert dumped["created_at"].endswith("Z"), (
        f"created_at muss mit 'Z' enden, ist aber: {dumped['created_at']!r}"
    )


def test_created_at_no_naive_iso_without_tz() -> None:
    """Sicherstellen, dass kein naiver ISO-String ohne TZ ausgegeben wird.

    Das ist die direkte Regression aus dem Hangar-Decode-Fehler:
    `cannot parse "" as "Z07:00"`.
    """
    naive_dt = datetime.datetime(2026, 6, 2, 9, 46, 18)
    batch = _make_batch_read(naive_dt)

    dumped = json.loads(batch.model_dump_json())

    created_at_str: str = dumped["created_at"]
    # Muss entweder mit Z oder +HH:MM enden — nie mit einer reinen Zeitangabe
    has_tz = created_at_str.endswith("Z") or (
        len(created_at_str) >= 6 and created_at_str[-6] in ("+", "-")
    )
    assert has_tz, f"Kein TZ-Suffix in created_at: {created_at_str!r}"


# ---------------------------------------------------------------------------
# Vollständiger JSON-Roundtrip (Schema → JSON → Go-Kompatibilitäts-Check)
# ---------------------------------------------------------------------------


def test_batch_read_full_json_contains_z_timestamps() -> None:
    """Kompletter model_dump_json-Output darf keine naiven Timestamps enthalten."""
    naive_dt = datetime.datetime(2026, 6, 2, 9, 46, 18, 701971)
    batch = _make_batch_read(naive_dt)

    raw_json = batch.model_dump_json()
    data = json.loads(raw_json)

    # Alle datetime-Felder auf oberster Ebene prüfen
    for field in ("created_at",):
        val: str = data[field]
        assert "Z" in val or "+" in val or (len(val) >= 6 and val[-6] == "-"), (
            f"Feld {field!r} hat keinen TZ-Suffix: {val!r}"
        )


# ---------------------------------------------------------------------------
# BatchSummary.all_terminal Logik
# ---------------------------------------------------------------------------


def test_batch_summary_all_terminal_false_when_queued() -> None:
    summary = _make_summary(queued=2, printing=0)
    assert summary.all_terminal is False


def test_batch_summary_all_terminal_false_when_printing() -> None:
    summary = _make_summary(queued=0, printing=1)
    assert summary.all_terminal is False


def test_batch_summary_all_terminal_true_when_neither() -> None:
    summary = BatchSummary(total=3, queued=0, printing=0, done=3, failed=0, cancelled=0)
    assert summary.all_terminal is True
