from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.printer_backends.snmp_helper import LiveStatus
from app.schemas.print_response import (
    PrintJobResponse,
    PrintJobStatusResponse,
)
from app.services.job_lifecycle import JobState
from pydantic import ValidationError


def test_print_job_response_status_is_literal_queued() -> None:
    r = PrintJobResponse(job_id="abc", status="queued")
    assert r.status == "queued"
    with pytest.raises(ValidationError):
        PrintJobResponse(job_id="abc", status="printing")


def test_status_response_accepts_each_job_state() -> None:
    for state in JobState:
        r = PrintJobStatusResponse(
            job_id="j",
            status=state,
            created_at=datetime.now(UTC),
        )
        assert r.status == state


def test_status_response_optional_fields_none() -> None:
    r = PrintJobStatusResponse(
        job_id="j",
        status=JobState.QUEUED,
        created_at=datetime.now(UTC),
    )
    assert r.error_code is None
    assert r.error_message is None
    assert r.error_detail is None
    assert r.started_at is None
    assert r.finished_at is None
    assert r.live is None


def test_status_response_live_block_optional() -> None:
    r = PrintJobStatusResponse(
        job_id="j",
        status=JobState.QUEUED,
        created_at=datetime.now(UTC),
    )
    assert r.live is None


def test_status_response_carries_live_block() -> None:
    live = LiveStatus(hr_printer_status="printing", error_flags=["doorOpen"])
    r = PrintJobStatusResponse(
        job_id="j",
        status=JobState.PRINTING,
        created_at=datetime.now(UTC),
        live=live,
    )
    assert r.live is live
    assert r.live.hr_printer_status == "printing"
