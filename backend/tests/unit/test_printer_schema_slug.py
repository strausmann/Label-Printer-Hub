"""PrinterRead exposiert slug-Feld."""

from datetime import UTC, datetime
from uuid import uuid4

from app.schemas.printer import PrinterRead


def test_printer_read_has_slug_field():
    now = datetime.now(UTC)
    payload = {
        "id": str(uuid4()),
        "slug": "brother-p750w",
        "name": "Brother PT-P750W",
        "model": "PT-P750W",
        "backend": "ptouch",
        "connection": {},
        "enabled": True,
        "paused": False,
        "created_at": now,
        "updated_at": now,
    }
    pr = PrinterRead(**payload)
    assert pr.slug == "brother-p750w"
