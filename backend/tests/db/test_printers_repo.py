"""Tests for the printers repository."""
import pytest

from app.models.printer import Printer
from app.repositories import printers


@pytest.mark.asyncio
async def test_create_and_get_by_name(session):
    # Use registered entry-points; pt-series + ptouch are the only ones
    # available pre-Phase-2-followup (#11 adds ql-series + QL backend).
    p = Printer(
        name="pt-office",
        model="pt-series",
        backend="ptouch",
        connection={"interface": "usb", "serial": "0000G0Z123456"},
    )
    created = await printers.create(session, p)
    assert created.id is not None
    found = await printers.get_by_name(session, "pt-office")
    assert found is not None and found.id == created.id


@pytest.mark.asyncio
async def test_unique_name(session):
    from sqlalchemy.exc import IntegrityError

    a = Printer(name="dup", model="pt-series", backend="ptouch", connection={})
    b = Printer(name="dup", model="pt-series", backend="ptouch", connection={})
    await printers.create(session, a)
    with pytest.raises(IntegrityError):
        await printers.create(session, b)
