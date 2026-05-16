"""Model package — re-exports all SQLModel table classes.

Every class listed here is registered with SQLModel.metadata, which is
required for Alembic autogenerate to detect schema changes.
"""
from app.models.job import Job, JobState
from app.models.preset import Preset
from app.models.printer import Printer
from app.models.printer_state import PrinterState
from app.models.printer_status_cache import PrinterStatusCache
from app.models.template import Template

__all__ = ["Job", "JobState", "Preset", "Printer", "PrinterState", "PrinterStatusCache", "Template"]
