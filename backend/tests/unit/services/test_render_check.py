# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Cart pre-check (#285): per-item verdicts, one lookup per distinct item, tape checked first."""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest
from app.printer_backends.exceptions import UnsupportedTapeError
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.render_check import (
    RenderCheckItem,
    RenderCheckLookup,
    RenderCheckRequest,
)
from app.services.errors import AppLookupNotFoundError
from app.services.lookup_gate import MAX_BATCH_LOOKUPS
from app.services.lookup_service import LookupFailedError, UnknownAppError
from app.services.render_check import check_items


class _FakeLookups:
    def __init__(self, *, data=None, raises=None, delay=0.0):
        self.calls: list[tuple[str, str]] = []
        self.running = 0
        self.peak = 0
        self._data = data
        self._raises = raises or {}
        self._delay = delay

    async def lookup(self, app: str, identifier: str) -> LabelData:
        self.calls.append((app, identifier))
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
            if identifier in self._raises:
                raise self._raises[identifier]
            if callable(self._data):
                return self._data(identifier)
            return self._data or LabelData(
                source_app=app,
                primary_id=identifier,
                title="Title",
                qr_payload="https://x.invalid/1",
            )
        finally:
            self.running -= 1


def _item(identifier="A1", content_type=ContentType.QR_TWO_LINES, app="snipeit"):
    return RenderCheckItem(
        content_type=content_type, lookup=RenderCheckLookup(app=app, identifier=identifier)
    )


def _req(*items, tape_mm=62):
    return RenderCheckRequest(tape_mm=tape_mm, items=list(items))


@pytest.mark.asyncio
async def test_fitting_item_is_ok():
    out = await check_items(_req(_item()), _FakeLookups())
    assert [(r.index, r.ok, r.error_code) for r in out.results] == [(0, True, None)]


@pytest.mark.asyncio
async def test_long_qr_payload_on_62mm_is_flagged():
    data = LabelData(source_app="x", primary_id="A", title="T", qr_payload="u" * 800)
    out = await check_items(_req(_item()), _FakeLookups(data=data))
    r = out.results[0]
    assert not r.ok and r.error_code == "qr_payload_too_long"
    assert r.error_detail is not None
    assert r.error_detail["length"] == 800
    assert isinstance(r.error_detail["max_bytes"], int)


@pytest.mark.asyncio
async def test_missing_fields_are_flagged():
    data = LabelData(source_app="x", primary_id="A", qr_payload="https://x.invalid")
    out = await check_items(_req(_item()), _FakeLookups(data=data))
    r = out.results[0]
    assert r.error_code == "content_type_data_mismatch"
    assert r.error_detail == {"missing_fields": ["title"]}


@pytest.mark.asyncio
async def test_lookup_not_found_is_per_item():
    lookups = _FakeLookups(raises={"GONE": AppLookupNotFoundError("secret detail")})
    out = await check_items(_req(_item("GONE"), _item("A1")), lookups)
    assert [r.ok for r in out.results] == [False, True]
    assert out.results[0].error_code == "integration_item_not_found"
    assert "secret detail" not in (out.results[0].error_message or "")


@pytest.mark.asyncio
async def test_lookup_failure_is_per_item_with_fixed_message():
    err = LookupFailedError("grocy lookup failed: http://grocy.internal.invalid:9283/api boom")
    out = await check_items(_req(_item("BAD"), _item("A1")), _FakeLookups(raises={"BAD": err}))
    r = out.results[0]
    assert r.error_code == "integration_lookup_failed"
    assert r.error_message == "The integration failed or could not be reached."
    assert "grocy.internal.invalid" not in r.model_dump_json()
    assert out.results[1].ok


@pytest.mark.asyncio
async def test_lookup_failure_from_httpx_never_leaks_the_base_url():
    err = httpx.ConnectError("connect to http://internal.invalid:9283 failed")
    out = await check_items(
        _req(_item("BAD")), _FakeLookups(raises={"BAD": LookupFailedError(str(err))})
    )
    assert "internal.invalid" not in out.results[0].model_dump_json()


@pytest.mark.asyncio
async def test_unknown_app_is_per_item():
    out = await check_items(
        _req(_item("U", app="nope")), _FakeLookups(raises={"U": UnknownAppError("known: a, b")})
    )
    r = out.results[0]
    assert r.error_code == "integration_unknown_app"
    assert r.error_message == "The requested integration is not available."


@pytest.mark.asyncio
async def test_check_deduplicates_identical_items():
    lookups = _FakeLookups()
    out = await check_items(_req(_item("A1"), _item("A1")), lookups)
    assert len(lookups.calls) == 1
    assert [r.index for r in out.results] == [0, 1]
    assert all(r.ok for r in out.results)


@pytest.mark.asyncio
async def test_same_item_with_different_content_type_is_separate():
    lookups = _FakeLookups()
    out = await check_items(
        _req(_item("A1"), _item("A1", content_type=ContentType.QR_ONE_LINE)), lookups
    )
    assert len(lookups.calls) == 2
    assert len(out.results) == 2


@pytest.mark.asyncio
async def test_at_most_eight_lookups_at_once():
    lookups = _FakeLookups(delay=0.01)
    out = await check_items(_req(*[_item(f"A{i}") for i in range(20)]), lookups)
    assert len(lookups.calls) == 20
    assert 1 < lookups.peak <= MAX_BATCH_LOOKUPS
    assert all(r.ok for r in out.results)


@pytest.mark.asyncio
async def test_unsupported_tape_makes_no_lookup():
    lookups = _FakeLookups()
    with pytest.raises(UnsupportedTapeError):
        await check_items(_req(_item(), tape_mm=13), lookups)
    assert lookups.calls == []


@pytest.mark.asyncio
async def test_concurrent_checks_share_one_lookup_bound():
    lookups = _FakeLookups(delay=0.02)
    first = _req(*[_item(f"A{i}") for i in range(20)])
    second = _req(*[_item(f"B{i}") for i in range(20)])
    await asyncio.gather(check_items(first, lookups), check_items(second, lookups))
    assert len(lookups.calls) == 40
    assert 1 < lookups.peak <= MAX_BATCH_LOOKUPS


@pytest.mark.asyncio
async def test_unexpected_lookup_error_is_that_items_verdict_and_leaves_nothing_running():
    lookups = _FakeLookups(delay=0.02, raises={"BOOM": RuntimeError("not a lookup error")})
    out = await check_items(_req(*[_item(f"A{i}") for i in range(12)], _item("BOOM")), lookups)
    assert lookups.running == 0
    assert out.results[-1].error_code == "render_failed"
    assert out.results[-1].error_message == "The label could not be drawn."
    assert all(r.ok for r in out.results[:-1])


@pytest.mark.asyncio
async def test_unexpected_error_logs_one_error_line_without_traceback_or_message(caplog):
    """Review M-2: the type at ERROR, the traceback only at DEBUG; never the exception's text."""
    caplog.set_level(logging.DEBUG, logger="app.services.render_check")
    lookups = _FakeLookups(raises={"BOOM": RuntimeError("token=hunter2")})
    await check_items(_req(_item("BOOM")), lookups)
    records = [r for r in caplog.records if r.name == "app.services.render_check"]
    errors = [r for r in records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    (error,) = errors
    assert "RuntimeError" in error.getMessage()
    assert error.exc_info is None
    assert "hunter2" not in error.getMessage()
    debug = [r for r in records if r.levelno == logging.DEBUG and r.exc_info is not None]
    assert len(debug) == 1


@pytest.mark.asyncio
async def test_unexpected_render_error_is_that_items_verdict(monkeypatch):
    from app.services.layout_engine import LayoutEngine

    real = LayoutEngine.render

    def _render(self, tape_mm, content_type, data, **kw):
        if data.primary_id == "BOOM":
            raise ValueError("font exploded")
        return real(self, tape_mm, content_type, data, **kw)

    monkeypatch.setattr(LayoutEngine, "render", _render)
    lookups = _FakeLookups(delay=0.01)
    out = await check_items(_req(*[_item(f"A{i}") for i in range(9)], _item("BOOM")), lookups)
    assert lookups.running == 0
    assert [r.error_code for r in out.results[:-1]] == [None] * 9
    assert out.results[-1].error_code == "render_failed"
    assert "exploded" not in out.results[-1].model_dump_json()


def _swatch_lookups() -> _FakeLookups:
    from tests.helpers.spool_swatch import SAMPLE_URL, every_row

    return _FakeLookups(
        data=LabelData(source_app="spoolman", qr_payload=SAMPLE_URL, swatch=every_row())
    )


@pytest.mark.asyncio
async def test_render_check_accepts_a_swatch_on_62mm():
    item = _item(content_type=ContentType.SPOOL_SWATCH, app="spoolman")
    out = await check_items(_req(item, tape_mm=62), _swatch_lookups())
    assert [(r.ok, r.error_code) for r in out.results] == [(True, None)]


@pytest.mark.asyncio
async def test_render_check_names_unsupported_tape_for_a_swatch_on_12mm(caplog):
    import logging

    item = _item(content_type=ContentType.SPOOL_SWATCH, app="spoolman")
    with caplog.at_level(logging.ERROR, logger="app.services.render_check"):
        out = await check_items(_req(item, tape_mm=12), _swatch_lookups())
    r = out.results[0]
    assert (r.ok, r.error_code) == (False, "unsupported_tape")
    assert r.error_message == "This layout is not available for this tape."
    assert r.error_detail == {"tape_mm": 12}
    assert not [rec for rec in caplog.records if rec.levelno >= logging.ERROR]


@pytest.mark.asyncio
@pytest.mark.parametrize("tape_mm", [29, 38, 50, 54])
async def test_render_check_accepts_a_swatch_cart_on_the_other_dk_widths(tape_mm: int):
    items = [_item("7", content_type=ContentType.SPOOL_SWATCH, app="spoolman")]
    out = await check_items(_req(*items, tape_mm=tape_mm), _swatch_lookups())
    assert [(r.ok, r.error_code) for r in out.results] == [(True, None)]


@pytest.mark.asyncio
async def test_render_check_flags_the_other_labels_of_a_mixed_cart_on_38mm():
    """The other layouts have no 38 mm yet (#258): each gets its own verdict naming why."""
    items = [_item("7", content_type=ContentType.SPOOL_SWATCH, app="spoolman"), _item("A1")]
    out = await check_items(_req(*items, tape_mm=38), _swatch_lookups())
    swatch, other = out.results
    assert (swatch.ok, swatch.error_code) == (True, None)
    assert (other.ok, other.error_code) == (False, "unsupported_tape")
    assert other.error_detail == {"tape_mm": 38, "spool_label_only": True}


@pytest.mark.asyncio
async def test_render_check_without_spool_labels_on_38mm_is_refused_as_before():
    with pytest.raises(UnsupportedTapeError):
        await check_items(_req(_item("A1"), tape_mm=38), _swatch_lookups())
