"""Phase 7b Cluster 1c — every datetime column must be timezone-aware."""

import pytest
from app.models.job import Job
from app.models.preset import Preset
from app.models.printer import Printer
from app.models.printer_state import PrinterState
from app.models.printer_status_cache import PrinterStatusCache
from app.models.template import Template
from sqlalchemy import DateTime


@pytest.mark.parametrize(
    "model,columns",
    [
        (Template, ["created_at", "updated_at"]),
        (Printer, ["created_at", "updated_at"]),
        (Job, ["created_at", "updated_at", "started_at", "finished_at"]),
        (Preset, ["created_at", "updated_at"]),
        (PrinterState, ["updated_at"]),
        (PrinterStatusCache, ["captured_at", "updated_at"]),
    ],
)
def test_datetime_columns_are_timezone_aware(model, columns):
    for col_name in columns:
        col = model.__table__.columns[col_name]
        assert isinstance(col.type, DateTime), f"{model.__name__}.{col_name} is not DateTime"
        assert col.type.timezone is True, (
            f"{model.__name__}.{col_name} must be DateTime(timezone=True)"
        )
