from __future__ import annotations

from app.models.tape import TapeSpec
from app.printer_backends.base import PrinterBackend
from app.services.status_block import StatusBlock
from PIL import Image


class _Compliant:
    backend_id = "compliant"
    host = "1.2.3.4"

    async def print_image(
        self,
        image: Image.Image,
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
    ) -> None:
        return None

    async def query_status(self) -> StatusBlock:  # pragma: no cover - shape only
        # Use the test helper to construct a valid StatusBlock with all 18 fields
        from tests._helpers.status import make_status_block

        return make_status_block()


class _Incomplete:
    backend_id = "incomplete"
    host = "x"
    # No print_image / query_status


def test_protocol_accepts_compliant_class() -> None:
    assert isinstance(_Compliant(), PrinterBackend)


def test_protocol_rejects_incomplete_class() -> None:
    assert not isinstance(_Incomplete(), PrinterBackend)
