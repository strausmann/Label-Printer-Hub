from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.schemas.label_data import LabelData
from app.schemas.print_request import (
    PrintLookupRequest,
    PrintOptions,
    PrintRequest,
    RawLabelData,
)
from app.services.print_service import PrintService
from app.services.template_loader import TemplateNotFoundError
from PIL import Image


@pytest.fixture
def template():
    # Build a minimal TemplateSchema-compatible object — the actual schema
    # was created in Phase 4. Use the real schema if available, else a
    # MagicMock with .tape_mm attribute.
    tpl = MagicMock()
    tpl.tape_mm = 24
    tpl.id = "qr-only-24mm"
    return tpl


@pytest.fixture
def image():
    return Image.new("1", (200, 128))


@pytest.fixture
def loader(template):
    m = MagicMock()
    m.get.return_value = template
    return m


@pytest.fixture
def renderer(image):
    m = MagicMock()
    m.render.return_value = image
    return m


@pytest.fixture
def queue():
    m = AsyncMock()
    m.submit.return_value = "job-1"
    return m


@pytest.fixture
def lookup_service():
    m = AsyncMock()
    m.lookup.return_value = LabelData(
        title="X",
        primary_id="1",
        qr_payload="u",
        source_app="snipeit",
        secondary=(),
    )
    return m


def _service(loader, renderer, queue, lookup_service):
    return PrintService(
        template_loader=loader,
        renderer=renderer,
        print_queue=queue,
        lookup_service=lookup_service,
        printer_id="pt@x",
    )


async def test_lookup_path_calls_lookup_and_renders(
    loader,
    renderer,
    queue,
    lookup_service,
) -> None:
    svc = _service(loader, renderer, queue, lookup_service)
    req = PrintRequest(
        template_id="qr-only-24mm",
        lookup=PrintLookupRequest(app="snipeit", identifier="42"),
    )
    job_id = await svc.submit_print_job(req)
    lookup_service.lookup.assert_awaited_once_with("snipeit", "42")
    renderer.render.assert_called_once()
    queue.submit.assert_awaited_once()
    assert job_id == "job-1"


async def test_data_path_bypasses_lookup_and_marks_source_manual(
    loader,
    renderer,
    queue,
    lookup_service,
) -> None:
    svc = _service(loader, renderer, queue, lookup_service)
    req = PrintRequest(
        template_id="qr-only-24mm",
        data=RawLabelData(title="T", primary_id="P", qr_payload="Q", secondary=["a"]),
    )
    job_id = await svc.submit_print_job(req)
    lookup_service.lookup.assert_not_called()
    args, _ = renderer.render.call_args
    label_data = args[1]
    assert isinstance(label_data, LabelData)
    assert label_data.source_app == "manual"
    assert label_data.secondary == ("a",)
    assert job_id == "job-1"


async def test_template_not_found_raises_synchronously(
    loader,
    renderer,
    queue,
    lookup_service,
) -> None:
    loader.get.side_effect = TemplateNotFoundError("qr-only-24mm")
    svc = _service(loader, renderer, queue, lookup_service)
    req = PrintRequest(
        template_id="qr-only-24mm",
        lookup=PrintLookupRequest(app="snipeit", identifier="x"),
    )
    with pytest.raises(TemplateNotFoundError):
        await svc.submit_print_job(req)
    queue.submit.assert_not_called()


async def test_options_passed_to_queue(loader, renderer, queue, lookup_service) -> None:
    svc = _service(loader, renderer, queue, lookup_service)
    req = PrintRequest(
        template_id="qr-only-24mm",
        data=RawLabelData(title="T", primary_id="P", qr_payload="Q"),
        options=PrintOptions(copies=2, auto_cut=False, high_resolution=True),
    )
    await svc.submit_print_job(req)
    _, kwargs = queue.submit.call_args
    assert kwargs["tape_mm"] == 24
    assert kwargs["auto_cut"] is False
    assert kwargs["high_resolution"] is True
    # `copies` is deliberately NOT forwarded — see service comment
    assert "copies" not in kwargs
