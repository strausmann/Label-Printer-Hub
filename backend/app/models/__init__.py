"""Model package — re-exports all SQLModel table classes.

Every class listed here is registered with SQLModel.metadata, which is
required for Alembic autogenerate to detect schema changes.
"""

from app.models.api_key import ApiKey
from app.models.app_setting import AppSetting
from app.models.job import Job, JobState
from app.models.preset import Preset
from app.models.print_batch import PrintBatch
from app.models.printer import Printer, PrinterAudit
from app.models.printer_calibration import PrinterCalibration
from app.models.printer_state import PrinterState
from app.models.printer_status_cache import PrinterStatusCache
from app.models.printer_tray import PrinterTray
from app.models.sheet import (
    Sheet,
    SheetCell,
    SheetIdCounter,
    SheetType,
    SheetTypeVersion,
    SheetWriteLock,
)
from app.models.ui_session import UiSession

__all__ = [
    "ApiKey",
    "AppSetting",
    "Job",
    "JobState",
    "Preset",
    "PrintBatch",
    "Printer",
    "PrinterAudit",
    "PrinterCalibration",
    "PrinterState",
    "PrinterStatusCache",
    "PrinterTray",
    "Sheet",
    "SheetCell",
    "SheetIdCounter",
    "SheetType",
    "SheetTypeVersion",
    "SheetWriteLock",
    "UiSession",
]
