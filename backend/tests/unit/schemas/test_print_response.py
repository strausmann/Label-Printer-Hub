from __future__ import annotations

import pytest
from app.schemas.print_response import PrintJobResponse
from pydantic import ValidationError


def test_print_job_response_status_is_literal_queued() -> None:
    r = PrintJobResponse(job_id="abc", status="queued")
    assert r.status == "queued"
    with pytest.raises(ValidationError):
        PrintJobResponse(job_id="abc", status="printing")
