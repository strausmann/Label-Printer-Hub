# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Test the _rerender_from_db recovery path uses LayoutEngine."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.printer_backends.snmp_helper import PreflightStatus
from app.services.layout_engine import LayoutEngine
from app.services.print_queue import PrintQueue
from app.services.print_service import PrintService
from app.services.test_label import TapeTestText
from app.services.test_label import test_label_band as band_of
from PIL import Image


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


def _queue() -> PrintQueue:
    return PrintQueue(
        printers=[MagicMock(id=uuid4())],
        engine=LayoutEngine(),
        store=MagicMock(),
        on_state_change=AsyncMock(),
    )


class TestRerenderTestLabel:
    """#377: a test job prints the same label after a restart or a retry."""

    async def test_test_label_job_rerenders_identically(self) -> None:
        backend = AsyncMock()
        backend.preflight_check = AsyncMock(
            return_value=PreflightStatus(
                hr_printer_status="idle", loaded_tape_mm=29, error_flags=[]
            )
        )
        queue = MagicMock()
        queue.submit_with_id = AsyncMock()
        store = MagicMock()
        store.save_queued = AsyncMock()
        svc = PrintService(
            printer_id=uuid4(), backend=backend, queue=queue, store=store, engine=LayoutEngine()
        )
        text = TapeTestText(
            printer="Workshop",
            width_mm=29,
            printed_at="2026-11-17 14:03",
            version="1.7.0",
            qr_payload="https://hub.example.invalid/printers/0d5c6b1e-8f6a-4f4e-9d61-3a2b9c1f7e42",
        )
        await svc.submit_test_label(
            lambda _mm: text, lambda mm: band_of("brother_ql", "QL-820NWB", mm)
        )
        first = queue.submit_with_id.await_args.args[2]
        payload = store.save_queued.await_args.args[0].payload
        again = _queue()._rerender_from_db_payload(payload)
        assert _png(again) == _png(first)

    def test_old_test_job_without_test_label_still_rerenders(self) -> None:
        stored = {
            "label_data": {
                "source_app": "manual",
                "primary_id": "Workshop",
                "title": "24 mm · 2026-11-10 09:00",
                "qr_payload": "https://hub.example.invalid/printers/x",
                "secondary": ["Printer Hub 1.6.0"],
                "items": [],
            },
            "content_type": "qr_three_lines",
            "rendered_tape_mm": 24,
            "tape_mm": 24,
            "options": {"copies": 1, "auto_cut": True, "high_resolution": False},
        }
        image = _queue()._rerender_from_db_payload(stored)
        assert image.height == 128


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
