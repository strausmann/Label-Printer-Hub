# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Every printing and render route answers a known printer or render error with its 4xx (#378).

The real app and lifespan (``app_with_fake_auth``, its inner FastAPI app run with its lifespan
context) against a temp database with one mock tape printer. Each case overrides only what keeps
the request from reaching its target, monkeypatches the target to raise, and reads the code from
the body shape the route answers with (R-378-2). The Grocy label webhook authenticates a real
print key itself (``require_print_token`` is not overridden).

A new POST route under a printing prefix fails ``test_every_printing_route_has_a_case`` until it
is listed here (or in ``NOT_PRINTING`` with a reason).
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import app.models  # noqa: F401
import bcrypt
import pytest
import pytest_asyncio
from app.api.dependencies.webhook_auth import enforce_webhook_rate_limit, require_webhook_key
from app.auth.verifier import _cache as verifier_cache
from app.config import get_settings
from app.models.api_key import ApiKey
from app.models.job import Job
from app.models.print_batch import PrintBatch
from app.models.printer import Printer
from app.printer_backends.exceptions import (
    ContentTypeDataMismatchError,
    MediaTypeMismatchError,
    NoTapeLoadedError,
    PrinterCoverOpenError,
    PrinterDisabledError,
    PrinterOfflineError,
    PrinterReportedError,
    QrPayloadTooLongError,
    SnmpQueryError,
    TapeEmptyError,
    TapeMismatchError,
    UnsupportedTapeError,
)
from app.services.lookup_service import LookupFailedError, UnknownAppError
from app.services.print_error_codes import KNOWN_PRINT_ERROR_TYPES, SYNC_ERROR_MAP
from app.services.rate_limiter import _rate_limiter
from httpx import ASGITransport, AsyncClient

from tests.helpers.routes import iter_api_routes

pytestmark = pytest.mark.asyncio

PRINTING = re.compile(
    r"^/api/v1/(print(/|$)|render/|printers/\{printer_id\}/(test-print|calibration/)|webhook/"
    r"|batches/\{batch_id\}/(continue|reprint)|jobs/\{job_id\}/retry"
    # #350: a new sheet's ID-only or back-side job, the code on the back, the loading test page
    r"|sheets$|sheets/\{code\}/back-side$"
    r"|printers/\{printer_id\}/trays/\{tray\}/loading/test-page$)"
)
NOT_PRINTING = {
    ("POST", "/api/v1/printers/{printer_id}/calibration/{tray}/fit"): (
        "computes a fit, never prints or renders a label"
    ),
}

SLUG = "tape-a"


def _key(word: str, fill: str) -> str:
    """A made-up key in the real format, built at runtime (no literal for secret scanners)."""
    return "lh_pat_" + word + fill * (43 - len(word))


PRINT_KEY = _key("guardprint", "G")

_LABEL = {
    "content_type": "qr_two_lines",
    "data": {"title": "T", "primary_id": "ID-1", "qr_payload": "https://e.invalid"},
}


def _sample(cls: type[Exception]) -> Exception:
    samples: dict[type[Exception], Callable[[], Exception]] = {
        UnknownAppError: lambda: UnknownAppError("no such app"),
        LookupFailedError: lambda: LookupFailedError("https://grocy.example.invalid/x secret"),
        PrinterDisabledError: lambda: PrinterDisabledError(uuid4(), SLUG),
        TapeMismatchError: lambda: TapeMismatchError(expected_mm=12, loaded_mm=24),
        TapeEmptyError: TapeEmptyError,
        NoTapeLoadedError: NoTapeLoadedError,
        PrinterCoverOpenError: PrinterCoverOpenError,
        PrinterOfflineError: lambda: PrinterOfflineError("cannot reach 192.0.2.10:9100: refused"),
        UnsupportedTapeError: lambda: UnsupportedTapeError(tape_mm=70),
        ContentTypeDataMismatchError: lambda: ContentTypeDataMismatchError(
            content_type="qr_two_lines", missing_fields=("title",)
        ),
        QrPayloadTooLongError: lambda: QrPayloadTooLongError(length=300, max_bytes=100),
        SnmpQueryError: lambda: SnmpQueryError("preflight SNMP failed: community hunter2"),
        MediaTypeMismatchError: lambda: MediaTypeMismatchError(
            loaded_kind="die_cut", media_raw="29mm x 90mm"
        ),
        PrinterReportedError: lambda: PrinterReportedError(["jammed", "serviceRequested"]),
    }
    return samples[cls]()


# What the samples carry and no answer may repeat (CWE-209): an upstream URL and a secret, the
# printer's address, an SNMP community, the API key.
TAINT = ("grocy.example.invalid", "secret", "192.0.2.10", "hunter2", PRINT_KEY)


def _assert_untainted(text: str) -> None:
    leaked = [t for t in TAINT if t in text]
    assert not leaked, f"the answer repeats {leaked}: {text}"


# ------------------------------------------------------------------------------------- the hub


@dataclass
class Hub:
    client: AsyncClient
    app: Any
    printer_id: UUID
    batch_id: UUID
    job_id: UUID
    sheet_code: str = ""
    """A ``back_side`` 3490 sheet (#350): the ``{code}`` of the sheet routes."""


@pytest_asyncio.fixture
async def hub(app_with_fake_auth: Any) -> AsyncIterator[Hub]:
    import app.db.engine as eng
    from app.integrations import (  # type: ignore[attr-defined]
        IntegrationRegistry,
        _discover_plugins,
    )

    if not IntegrationRegistry.names():
        _discover_plugins()
    get_settings.cache_clear()
    _rate_limiter.clear()
    verifier_cache.clear()
    async with eng.async_session() as s:
        printer = Printer(name="Tape A", slug=SLUG, model="PT-P750W", backend="mock")
        s.add(printer)
        await s.flush()
        batch = PrintBatch(printer_id=printer.id, job_ids=[], created_by="guard")
        job = Job(
            printer_id=printer.id,
            state="failed",
            payload={
                "label_data": {"title": "T", "primary_id": "ID-1", "source_app": "manual"},
                "content_type": "qr_two_lines",
                "rendered_tape_mm": 12,
                "tape_mm": 12,
                "options": {},
            },
        )
        s.add_all(
            [
                batch,
                job,
                ApiKey(
                    name="guard-print",
                    key_hash=bcrypt.hashpw(PRINT_KEY.encode(), bcrypt.gensalt(rounds=4)).decode(),
                    key_prefix=PRINT_KEY[:16],
                    scopes=["print"],
                    enabled=True,
                ),
            ]
        )
        await s.commit()
        ids = (printer.id, batch.id, job.id)
    inner = app_with_fake_auth._app
    inner.dependency_overrides[require_webhook_key] = lambda: None
    inner.dependency_overrides[enforce_webhook_rate_limit] = lambda: None
    async with (
        inner.router.lifespan_context(inner),
        AsyncClient(
            transport=ASGITransport(app=inner, raise_app_exceptions=True), base_url="http://t"
        ) as client,
    ):
        async with eng.async_session() as s:
            await inner.state.settings_store.set_many(s, {"integrations.grocy.label.enabled": True})
        from app.sheets import sheet_service

        async with eng.async_session() as s:  # the types are seeded by the lifespan
            sheet = await sheet_service.create_sheet(
                s,
                type_key="avery-zweckform-3490",
                version=None,
                id_placement="back_side",
                used_cells=[],
                note=None,
                actor="guard",
            )
        yield Hub(client, inner, *ids, sheet_code=sheet.code)
    _rate_limiter.clear()
    verifier_cache.clear()
    get_settings.cache_clear()


# ------------------------------------------------------------------------------------- the cases


@dataclass(frozen=True)
class Case:
    name: str
    route: str
    """The route template, as ``app.routes`` lists it."""
    target: str
    """``module.attr`` or ``module.Class.attr`` that is made to raise."""
    shape: str
    """``a`` (envelope, ``b`` for a disabled printer), ``c`` (wrapped), ``d`` (wrapped
    problem) or ``dt`` (top-level problem)."""
    body: dict[str, Any] | None = None
    sync: bool = False
    headers: dict[str, str] | None = None

    def url(self, hub: Hub) -> str:
        return (
            self.route.replace("{printer_key}", SLUG)
            .replace("{printer_id}", str(hub.printer_id))
            .replace("{batch_id}", str(hub.batch_id))
            .replace("{job_id}", str(hub.job_id))
            .replace("{tray}", "auto")
            .replace("{code}", hub.sheet_code)
        )


_SHEET_BODY = {"items": [_LABEL], "placements": [{"sheet": "S-1"}]}

MATRIX = [
    Case("print", "/api/v1/print", "app.services.print_service.PrintService.submit_print_job",
         "a", _LABEL),
    Case("render-preview", "/api/v1/render/preview",
         "app.services.layout_engine.LayoutEngine.render", "a",
         {"content_type": "qr_two_lines", "data": _LABEL["data"], "tape_mm": 12}, sync=True),
    Case("render-check", "/api/v1/render/check", "app.api.routes.print.check_items", "a",
         {"tape_mm": 12, "items": [{"content_type": "qr_two_lines",
                                    "lookup": {"app": "grocy", "identifier": "1"}}]}),
    Case("webhook-spoolman", "/api/v1/webhook/spoolman",
         "app.services.print_service.PrintService.submit_print_job", "a",
         {"spool_id": "42", "type": "updated"}),
    Case("webhook-grocy", "/api/v1/webhook/grocy",
         "app.services.print_service.PrintService.submit_print_job", "a",
         {"product_id": "17", "type": "consumed"}),
    Case("batch", "/api/v1/print/{printer_key}/batch", "app.api.routes.batch.dispatch_batch",
         "c", {"items": [_LABEL]}),
    Case("test-print", "/api/v1/printers/{printer_id}/test-print",
         "app.services.print_service.PrintService.submit_test_label", "d"),
    # #350: the routes the global handlers answer (top-level problem).
    Case("sheet-create", "/api/v1/sheets",
         "app.sheets.print_service.create_sheet_with_id_label", "dt",
         {"type": "avery-zweckform-3490", "id_placement": "cell", "printer": SLUG}),
    Case("sheet-create-back-side", "/api/v1/sheets",
         "app.sheets.print_service.create_sheet_with_back_label", "dt",
         {"type": "avery-zweckform-3490", "id_placement": "back_side", "printer": SLUG}),
    Case("sheet-back-side", "/api/v1/sheets/{code}/back-side",
         "app.sheets.print_service.print_sheet_back", "dt", {"printer": SLUG}),
    Case("tray-loading-page", "/api/v1/printers/{printer_id}/trays/{tray}/loading/test-page",
         "app.services.tray_loading_service.build_test_page", "dt"),
]  # fmt: skip

NET = [
    Case("grocy-label", "/api/v1/webhook/grocy/label",
         "app.services.print_service.PrintService.accept_deferred_job", "dt",
         {"product": "Oat milk", "grocycode": "grcy:p:12"},
         headers={"X-Label-Hub-Key": PRINT_KEY}),
    Case("batch-continue", "/api/v1/batches/{batch_id}/continue",
         "app.services.print_queue.PrintQueue.confirm_run", "dt"),
    Case("batch-reprint", "/api/v1/batches/{batch_id}/reprint",
         "app.services.print_queue.PrintQueue.reprint_from", "dt", {"from_label": 1}),
    Case("sheet", "/api/v1/print/{printer_key}/sheet", "app.sheets.print_service.print_sheets",
         "dt", _SHEET_BODY),
    Case("sheet-preview", "/api/v1/print/{printer_key}/sheet/preview",
         "app.sheets.print_service.preview", "dt", _SHEET_BODY),
    Case("calibration-page", "/api/v1/printers/{printer_id}/calibration/{tray}/page",
         "app.calibration.page.build_payload", "dt", {"type": "acme-t1"}),
    Case("job-retry", "/api/v1/jobs/{job_id}/retry",
         "app.services.print_queue.PrintQueue.enqueue_persisted", "dt"),
]  # fmt: skip
NET_CLASSES = (UnsupportedTapeError, ContentTypeDataMismatchError)

EXCEPTIONS: dict[tuple[str, type[Exception]], tuple[int, str]] = {
    # R-378-1: the test print answers an unreachable printer with 409 (503 elsewhere).
    ("test-print", PrinterOfflineError): (409, "printer-offline"),
    ("test-print", SnmpQueryError): (409, "printer-offline"),
}


def _raise_on(monkeypatch: pytest.MonkeyPatch, case: Case, exc: Exception) -> None:
    def sync_raiser(*_a: Any, **_k: Any) -> Any:
        raise exc

    async def async_raiser(*_a: Any, **_k: Any) -> Any:
        raise exc

    monkeypatch.setattr(case.target, sync_raiser if case.sync else async_raiser)


async def _post(hub: Hub, case: Case) -> Any:
    return await hub.client.post(case.url(hub), json=case.body, headers=case.headers)


def _code(case: Case, cls: type[Exception], body: dict[str, Any]) -> str:
    if case.shape == "a":
        return str(body["error"] if cls is PrinterDisabledError else body["error_code"])
    if case.shape == "c":
        return str(body["detail"]["error_code"])
    if case.shape == "d":
        return str(body["detail"]["type"])
    return str(body["type"])


def _expected(case: Case, cls: type[Exception]) -> tuple[int, str]:
    if (case.name, cls) in EXCEPTIONS:
        return EXCEPTIONS[(case.name, cls)]
    status, code = SYNC_ERROR_MAP[cls]
    return status, code.replace("_", "-") if case.shape in ("d", "dt") else code


# ------------------------------------------------------------------------------------- the tests


async def test_every_printing_route_has_a_case(app_with_fake_auth: Any) -> None:
    listed = {("POST", c.route) for c in (*MATRIX, *NET)} | set(NOT_PRINTING)
    routes = iter_api_routes(app_with_fake_auth._app.routes)
    printing = {("POST", r.path) for r in routes if "POST" in r.methods and PRINTING.match(r.path)}
    assert printing, "the route walk found nothing: the guard would pass vacuously"
    missing = sorted(printing - listed)
    assert not missing, f"printing routes without a guard case: {missing}"
    stale = sorted(listed - printing)
    assert not stale, f"guard cases for routes that do not exist: {stale}"


async def test_every_known_error_has_a_handler(app_with_fake_auth: Any) -> None:
    handlers = app_with_fake_auth._app.exception_handlers
    for cls in KNOWN_PRINT_ERROR_TYPES:
        assert any(base in handlers for base in cls.__mro__), f"no handler for {cls.__name__}"


@pytest.mark.parametrize("cls", KNOWN_PRINT_ERROR_TYPES, ids=lambda c: c.__name__)
@pytest.mark.parametrize("case", MATRIX, ids=lambda c: c.name)
async def test_known_errors_answer_as_documented(
    hub: Hub, monkeypatch: pytest.MonkeyPatch, case: Case, cls: type[Exception]
) -> None:
    _raise_on(monkeypatch, case, _sample(cls))
    resp = await _post(hub, case)
    assert (resp.status_code, _code(case, cls, resp.json())) == _expected(case, cls), resp.text
    _assert_untainted(resp.text)


@pytest.mark.parametrize("cls", NET_CLASSES, ids=lambda c: c.__name__)
@pytest.mark.parametrize("case", NET, ids=lambda c: c.name)
async def test_net_routes_never_answer_500(
    hub: Hub, monkeypatch: pytest.MonkeyPatch, case: Case, cls: type[Exception]
) -> None:
    _raise_on(monkeypatch, case, _sample(cls))
    resp = await _post(hub, case)
    _assert_untainted(resp.text)
    body = resp.json()
    if cls is UnsupportedTapeError:
        assert (resp.status_code, body["type"]) == (409, "unsupported-tape"), resp.text
        assert body["extensions"]["tape_mm"] == 70
    else:
        assert (resp.status_code, body["type"]) == (422, "content-type-data-mismatch"), resp.text


_TEST_PRINT = next(c for c in MATRIX if c.name == "test-print")


async def test_unsupported_width_detail_reaches_the_body(
    hub: Hub, monkeypatch: pytest.MonkeyPatch
) -> None:
    _raise_on(monkeypatch, _TEST_PRINT, UnsupportedTapeError(tape_mm=70))
    resp = await _post(hub, _TEST_PRINT)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["extensions"] == {"tape_mm": 70}


async def test_known_error_logs_one_line_without_traceback(
    hub: Hub, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _raise_on(monkeypatch, _TEST_PRINT, UnsupportedTapeError(tape_mm=70))
    with caplog.at_level(logging.WARNING, logger="app.api.print_errors"):
        resp = await _post(hub, _TEST_PRINT)
    assert resp.status_code == 409, resp.text
    records = [r for r in caplog.records if r.name == "app.api.print_errors"]
    assert len(records) == 1, records
    [record] = records
    assert record.levelno == logging.WARNING
    assert record.exc_info is None
    assert record.getMessage().endswith(": unsupported_tape")


DOCUMENTED = ("print", "webhook-spoolman", "webhook-grocy", "batch", "test-print")


@pytest.mark.parametrize("case", [c for c in MATRIX if c.name in DOCUMENTED], ids=lambda c: c.name)
async def test_printing_routes_document_every_known_code(
    app_with_fake_auth: Any, case: Case
) -> None:
    """#378 I2: a client learns every status and code these routes answer from the OpenAPI."""
    responses = app_with_fake_auth._app.openapi()["paths"][case.route]["post"]["responses"]
    missing = []
    for cls in KNOWN_PRINT_ERROR_TYPES:
        status, code = _expected(case, cls)
        description = responses.get(str(status), {}).get("description", "")
        if f"`{code}`" not in description:
            missing.append(f"{status} {code}")
    assert not missing, f"{case.route} does not document: {missing}"


@pytest.mark.parametrize("case", [c for c in MATRIX if c.name in DOCUMENTED], ids=lambda c: c.name)
async def test_documented_422_keeps_a_body_schema(app_with_fake_auth: Any, case: Case) -> None:
    """Documenting the known 422 codes must not drop the schema of the 422 body (a generated
    client needs it): FastAPI's validation error, or the envelope on a webhook route."""
    schema = app_with_fake_auth._app.openapi()
    content = schema["paths"][case.route]["post"]["responses"]["422"]["content"]
    ref = content["application/json"]["schema"]["$ref"]
    name = ref.rsplit("/", 1)[-1]
    expected = "SheetApiErrorResponse" if case.name.startswith("webhook") else "HTTPValidationError"
    assert name == expected
    assert name in schema["components"]["schemas"]


@pytest.mark.parametrize("cls", (LookupFailedError, PrinterOfflineError, SnmpQueryError))
async def test_the_net_repeats_no_secret(
    hub: Hub, monkeypatch: pytest.MonkeyPatch, cls: type[Exception]
) -> None:
    """The safety net answers from the same fixed texts: no URL, address or community."""
    case = next(c for c in NET if c.name == "sheet")
    _raise_on(monkeypatch, case, _sample(cls))
    resp = await _post(hub, case)
    assert resp.status_code in (502, 503), resp.text
    _assert_untainted(resp.text)


async def test_the_log_line_has_no_query_string(
    hub: Hub, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The Grocy label key can ride in ``?token=``: the net logs the path only."""
    case = next(c for c in NET if c.name == "grocy-label")
    _raise_on(monkeypatch, case, UnsupportedTapeError(tape_mm=70))
    with caplog.at_level(logging.WARNING, logger="app.api.print_errors"):
        resp = await hub.client.post(f"{case.route}?token={PRINT_KEY}", json=case.body)
    assert resp.status_code == 409, resp.text
    [record] = [r for r in caplog.records if r.name == "app.api.print_errors"]
    assert record.getMessage() == f"refused POST {case.route}: unsupported_tape"
    assert record.exc_info is None
    _assert_untainted(resp.text)


async def test_offline_cause_goes_to_the_log_only(
    hub: Hub, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    case = next(c for c in MATRIX if c.name == "print")
    _raise_on(monkeypatch, case, _sample(PrinterOfflineError))
    with caplog.at_level(logging.WARNING, logger="app.api.print_errors"):
        resp = await _post(hub, case)
    assert resp.json()["error_message"] == "The printer could not be reached."
    [record] = [r for r in caplog.records if r.name == "app.api.print_errors"]
    assert "192.0.2.10" in record.getMessage()
