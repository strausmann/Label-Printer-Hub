# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#393: a wired tape backend sends the way the printer's stored record says, and stores a new
one through the runtime."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from app.models.printer import Printer
from app.printer_backends.brother_ql_backend import BrotherQLBackend
from app.printer_backends.mock_backend import MockPrinterBackend
from app.printer_backends.tape_confirmation import ConfirmationRecord
from app.services.printer_runtime import PrinterRuntime

pytestmark = pytest.mark.anyio

_AT = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)


class _Runtime:
    """Just enough of a runtime for ``_wire_confirmation``: a recording store."""

    def __init__(self) -> None:
        self.stored: list[tuple[Any, ConfirmationRecord]] = []

    async def _store_confirmation(self, printer_id: Any, record: ConfirmationRecord) -> None:
        self.stored.append((printer_id, record))


def _row(stored: dict[str, Any] | None) -> Printer:
    return Printer(
        id=uuid4(),
        name="Shelf",
        model="QL-820NWB",
        backend="brother_ql",
        connection={"host": "192.0.2.12"},
        print_confirmation=stored,
    )


async def test_the_stored_record_reaches_the_backend_and_new_ones_go_to_the_row() -> None:
    runtime = _Runtime()
    row = _row(ConfirmationRecord("raw", True, _AT).to_json())
    backend = BrotherQLBackend(host="192.0.2.12")

    PrinterRuntime._wire_confirmation(runtime, backend, row)  # type: ignore[arg-type]

    assert backend.send_state.record == ConfirmationRecord("raw", True, _AT)
    assert await backend.send_state.use_ipp() is False  # stored raw: no probe
    new = ConfirmationRecord("ipp", True, _AT)
    await backend.send_state.store(new)
    assert runtime.stored == [(row.id, new)]


async def test_without_a_record_the_backend_probes() -> None:
    backend = BrotherQLBackend(host="192.0.2.12")
    PrinterRuntime._wire_confirmation(_Runtime(), backend, _row(None))  # type: ignore[arg-type]
    assert backend.send_state.record is None


def test_a_backend_without_send_state_is_left_alone() -> None:
    PrinterRuntime._wire_confirmation(_Runtime(), MockPrinterBackend(), _row(None))  # type: ignore[arg-type]
