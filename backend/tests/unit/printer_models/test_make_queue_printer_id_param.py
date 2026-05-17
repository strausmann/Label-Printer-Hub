"""Phase 7b Cluster 1b — driver.make_queue_printer(...) accepts an optional
printer_id so lifespan can plumb the deterministic UUIDv5 from
upsert_runtime_printer() into the runtime printer."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from app.printer_backends.mock_backend import MockPrinterBackend
from app.printer_models.pt import PTP750WDriver
from app.services.tape_registry import TapeRegistry


@pytest.fixture
def backend() -> MockPrinterBackend:
    return MockPrinterBackend(host="192.0.2.99")


@pytest.fixture
def tape_registry() -> TapeRegistry:
    return TapeRegistry()


def test_make_queue_printer_accepts_explicit_printer_id(
    backend: MockPrinterBackend,
    tape_registry: TapeRegistry,
) -> None:
    driver = PTP750WDriver(backend=backend)
    custom = uuid4()
    queue_printer = driver.make_queue_printer(tape_registry, printer_id=custom)
    assert queue_printer.id == custom


def test_make_queue_printer_generates_uuid_when_omitted(
    backend: MockPrinterBackend,
    tape_registry: TapeRegistry,
) -> None:
    driver = PTP750WDriver(backend=backend)
    queue_printer = driver.make_queue_printer(tape_registry)
    assert isinstance(queue_printer.id, UUID)


def test_make_queue_printer_two_omitted_calls_get_different_ids(
    backend: MockPrinterBackend,
    tape_registry: TapeRegistry,
) -> None:
    """Sanity: omitting the param defaults to a fresh uuid4 each time, not a shared sentinel."""
    driver = PTP750WDriver(backend=backend)
    a = driver.make_queue_printer(tape_registry)
    b = driver.make_queue_printer(tape_registry)
    assert a.id != b.id
