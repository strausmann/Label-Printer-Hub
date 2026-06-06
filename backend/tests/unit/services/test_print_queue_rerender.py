"""Test the _rerender_from_db recovery path uses LayoutEngine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.services.layout_engine import LayoutEngine
from app.services.print_queue import PrintQueue


class TestRerenderFromDb:
    def test_rerender_uses_engine_with_stored_content_type(self) -> None:
        printer = MagicMock(id=uuid4())
        queue = PrintQueue(
            printers=[printer],
            engine=LayoutEngine(),
            store=MagicMock(),
            on_state_change=AsyncMock(),
        )
        stored_payload = {
            "label_data": {
                "source_app": "manual",
                "primary_id": "K-02",
                "title": "Werkstatt",
                "qr_payload": "https://example.com/x",
                "secondary": [],
                "items": [],
            },
            "content_type": "qr_two_lines",
            "rendered_tape_mm": 12,
            "tape_mm": 12,
            "options": {
                "copies": 1,
                "auto_cut": True,
                "high_resolution": False,
                "half_cut": False,
                "last_page": True,
            },
        }
        image = queue._rerender_from_db_payload(stored_payload)
        assert image.height == 70
