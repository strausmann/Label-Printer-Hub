<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Sheet archive, Plan 2 of 4: IPP page printers, PDF pages and manual calibration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A page printer can be added by IPP URI, shows state, reasons, toner and trays, prints PDF page jobs through the existing per-printer queue with tracking, cancel and restart recovery, and can be calibrated by hand with a printed calibration page; `GET /api/printers/{id}/capabilities` reports all of it.

**Architecture:** An own IPP/1.1–2.0 client over `httpx` (`app/printer_backends/ipp/`) with a binary codec and five operations; a pure attribute-mapping layer turns printer answers into the hub's status model. The queue gains a third item type, the **page job**, run by a `PageJobRunner` that renders the PDF from the persisted payload at send time, uploads it, and tracks the IPP job to a final state. Rendering and outcome handling are looked up by payload `kind` from two small registries, so Plan 3 adds `sheet_page` without touching the runner. reportlab writes DeviceGray PDFs; calibration is applied as the page's transformation matrix.

**Tech Stack:** Python 3.12, FastAPI, httpx, SQLModel/Alembic on SQLite, reportlab (new, BSD), Pillow, pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-sheet-archive-design.md` (sections 4, 7.1 trays/calibrations, 11, 12.4, 13, 14, 18, 19, 20). Read it with this plan.

**Plan series:** 1 archive & sheets → **2 (this)** → 3 sheet printing → 4 UI. This plan does not need Plan 1 at runtime except for the sheet type versions the calibration page is drawn for (Plan 1 Tasks 2–3), so Plan 1 must be merged first.

**Requires [#184](https://github.com/strausmann/Label-Printer-Hub/issues/184) merged.** Today `POST /api/jobs/{id}/cancel` and `POST /api/printers/{id}/queue/clear` only write the database and never reach the in-memory queue (`app/api/routes/jobs.py`, `app/api/routes/printers.py` call `jobs_repo.mark_cancelled`), so a "cancelled" job still prints; and `POST /api/jobs/{id}/retry` clones the payload into a new `queued` row without the queue. #184 fixes both for tape jobs in its own bugfix PR: the routes go through `PrintQueue.cancel` and the retry route enqueues at once. This plan builds page jobs on that path; it does not fix #184 itself.

**Runtime note:** queues and printer wiring are built at startup (`app/main.py` lifespan); the admin service only writes the database. A newly added IPP printer prints after a restart, exactly as tape printers do today. Plan 4 Task 7 tells the user so.

## Global Constraints

- Everything in Plan 1's Global Constraints applies (Python 3.12, mypy strict, ruff, httpx, logging, TDD, coverage gates, error shape, scopes, route-auth guardrail, endpoint-count bound, `pnpm gen:api` on API change, English, privacy, Conventional Commits with commitlint scopes — here `printer-backends`, `queue`, `status`, `api`, `decisions`, `deps`, `docs` — and no AI attribution).
- **One new dependency: `reportlab`** (BSD; pulls `charset-normalizer`, MIT), pinned with a lower bound in `backend/pyproject.toml`, a row in `THIRD_PARTY_NOTICES.md`, and named with its licence in the PR description (CLAUDE.md). Also add `reportlab.*` to the mypy `ignore_missing_imports` override if it ships no stubs. **No IPP library.**
- Migration: revision `20261105b1`, `down_revision = "20261105a1"`, file `backend/alembic/versions/2026_11_05_0002-20261105b1_printer_trays_calibrations.py`.
- IPP URIs: schemes `ipp`, `ipps`, `http`, `https`; no user info, no fragment; `ipp://h/p` → `http://h:631/p`, `ipps://h/p` → `https://h:631/p` when no port is given. TLS verification on by default (OC-17). No IPP authentication (OC-2). Logs show the printer slug, never the URI.
- IPP request limits: response body cap **1 MB** (`1_048_576` bytes, streamed and aborted beyond); query timeout `min(5, queue_timeout_s)` s; Print-Job upload timeout `queue_timeout_s` s (default 30) (spec 11.2, OC-41).
- Print-Job attributes exactly per OC-19: `document-format=application/pdf`, `job-name` "Sheet <code> · <n> labels" / "Calibration page · <type key> v<n>", `requesting-user-name=label-printer-hub`; `media-col` (`media-size` 21000 × 29700 A4 / 21590 × 27940 Letter, `media-type=labels`, `media-source` unless tray `auto`) when the printer accepts the `media-col` job attribute — `job-creation-attributes-supported` contains `media-col`, or, if that attribute is absent, `media-col-supported` (which lists the collection's **members**, PWG 5100.7) contains `media-size`; `media-type` and `media-source` go into the collection only when they are listed members — else `media` keyword `iso_a4_210x297mm` / `na_letter_8.5x11in`; `print-scaling=none` when supported; `print-color-mode=monochrome` when supported; `copies=1`, `sides=one-sided` when supported.
- PDF: one page, media box exactly A4 595.2756 × 841.8898 pt or Letter 612 × 792 pt, **DeviceGray only**, 1-bit images stay 1-bit, text drawn as plain strings with the embedded bundled font (DejaVu Sans, as the tape renderer uses), never reportlab's paragraph/markup API.
- Calibration sign conventions (OC-30): `dx > 0` printed too far right, `dy > 0` too low, `sx, sy > 1` too large, `θ > 0` clockwise on the printed side. Ranges: offsets ±10 mm, scale 0.950–1.050, rotation ±2°. Stored as integers: offsets in hundredths of mm (D16), scale in parts per million (`1.000000` → `1000000`), rotation in micro-degrees; the API speaks mm (≤ 2 decimals), scale (≤ 6 decimals) and degrees (≤ 6 decimals). *(Plan decision: integers keep stored values exact on SQLite, which has no decimal type; the API values are the spec's decimals.)*
- Printer-controlled content is bounded: every list in `ProbeSummary` ≤ 64 entries, every string ≤ 120 characters (longer entries dropped or cut). A `job-uri` returned by the printer is stored, never requested.
- IPP fixtures are synthetic; no captures from a real device are committed (spec 18). Example hosts use `printer.example.invalid`; the fake printer listens on `127.0.0.1`.
- Hardware acceptance is **operator-verified**, never a task gate: spec acceptance 5 and 22 (real CP1525N print, calibration page readability, ±0.5 mm after calibration) and `V1` (media type settable via `media-col`). Tasks test against `FakeIppPrinter`.

## Review Focus

1. **The printer answers with unexpected attributes.** Missing `printer-state`, an unknown state value (e.g. 7), `marker-levels` sent as text, `marker-names` with 3 entries but `marker-levels` with 2, levels −1/−2/−3/150, 5000 `printer-state-reasons`, a reason with spaces or 300 characters, `media-source-supported` absent. Mapping never raises, the hub shows what it can, and the oddity is logged once at WARNING. Owner: Task 4 (`test_map_status_hostile_inputs` table).
2. **The hub restarts while a page job is at the printer.** On start the job resumes tracking and completes; a job that was mid-upload without an IPP job id ends `failed_restart` and its outcome handler is told the result is unknown. Owner: Task 8 (`test_restart_resumes_tracking_to_completion`, `test_restart_without_ipp_job_id_unknown_outcome`).
3. **The upload dies after bytes were sent** (read timeout, connection reset mid-response). The job must not be retried silently or deferred as if nothing reached the printer: it ends `failed` with `error_code=interrupted` and `started=True` (persisted). An unreachable or not-ready printer at the **pre-flight** read defers (job never leaves `queued`); a connect error or `server-error-busy` on the Print-Job itself fails cleanly (`started=False`). Owner: Task 7 (`test_upload_read_timeout_is_interrupted`, `test_preflight_unreachable_defers`, `test_connect_error_at_upload_fails_clean`).
4. **The printer reboots and forgets the job, or stays unreachable for minutes during tracking.** Unreachable keeps polling with backoff and never fails on time (OC-23); `client-error-not-found` ends the job `interrupted`, with `started` as observed. Owner: Task 8 (`test_unreachable_during_tracking_keeps_waiting`, `test_printer_forgot_job`).
5. **Malformed or oversized IPP responses.** Truncated message, attribute length beyond the buffer, collection nesting deeper than 8, more than 10 000 values, body over 1 MB, non-`application/ipp` content type. Each is a typed error, no exception escapes as 500, memory stays bounded. Owner: Task 1 (`test_decode_rejects_*`) and Task 2 (`test_response_over_1mb_aborted`).

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/printer_backends/ipp/__init__.py` | package |
| `backend/app/printer_backends/ipp/codec.py` | RFC 8010 encode/decode (pure) |
| `backend/app/printer_backends/ipp/client.py` | `IppClient`: five operations over httpx, limits, errors |
| `backend/app/printer_backends/ipp/errors.py` | typed IPP errors |
| `backend/app/printer_backends/ipp/attributes.py` | requested attribute lists, probe summary, status mapping (pure) |
| `backend/app/printer_backends/ipp/job_attrs.py` | build Print-Job attributes from summary + tray + media (pure) |
| `backend/app/models/printer_tray.py`, `backend/app/models/printer_calibration.py` | tables |
| `backend/alembic/versions/2026_11_05_0002-20261105b1_printer_trays_calibrations.py` | migration |
| `backend/app/schemas/printer_admin.py` | `ipp` backend, `IppConnection`, `TrayIn` (modify) |
| `backend/app/services/printer_admin_service.py`, `backend/app/api/routes/admin_printers_api.py` | probe and trays (modify) |
| `backend/app/services/producers/ipp_status_producer.py` | status polling, cache, auto-resume |
| `backend/app/services/page_jobs.py` | `PageJob`, `PagePayload`, renderer and outcome registries |
| `backend/app/services/page_job_runner.py` | send, track, cancel, defer |
| `backend/app/services/print_queue.py` | page-job dispatch, held slot, recovery (modify) |
| `backend/app/page_render/pdf.py` | reportlab page writer |
| `backend/app/page_render/transform.py` | deviation/correction maths (pure) |
| `backend/app/calibration/model.py`, `service.py`, `fit.py`, `page.py` | calibration values, storage, fit, calibration page |
| `backend/app/api/routes/calibration.py`, `backend/app/api/routes/capabilities.py` | routes |
| `backend/tests/helpers/fake_ipp_printer.py` | scriptable ASGI fake printer (tests and browser tests) |
| `docs/decisions/0020-backend-kinds-ipp-page-printers.md` | ADR |

---

### Task 1: IPP codec

**Files:**
- Create: `backend/app/printer_backends/ipp/__init__.py`, `codec.py`, `errors.py`
- Test: `backend/tests/unit/printer_backends/ipp/__init__.py`, `test_codec.py`, fixtures `backend/tests/unit/printer_backends/ipp/fixtures/*.bin` (hand-assembled, synthetic)

**Interfaces:**
- Produces (`codec.py`):
  - `class Tag(IntEnum)` — delimiter tags `OPERATION=0x01, JOB=0x02, END=0x03, PRINTER=0x04, UNSUPPORTED=0x05`; value tags `UNSUPPORTED_VALUE=0x10, UNKNOWN=0x12, NO_VALUE=0x13, INTEGER=0x21, BOOLEAN=0x22, ENUM=0x23, OCTET_STRING=0x30, DATETIME=0x31, RESOLUTION=0x32, RANGE=0x33, BEG_COLLECTION=0x34, TEXT_LANG=0x35, NAME_LANG=0x36, END_COLLECTION=0x37, TEXT=0x41, NAME=0x42, KEYWORD=0x44, URI=0x45, URI_SCHEME=0x46, CHARSET=0x47, LANGUAGE=0x48, MIME=0x49, MEMBER_NAME=0x4A`.
  - Value types: `int`, `bool`, `str`, `bytes`, `@dataclass(frozen) Resolution(x: int, y: int, units: int)`, `Range(lower: int, upper: int)`, `Collection(members: dict[str, list[Value]])`, `OutOfBand(tag: int)`, `Unknown(tag: int, raw: bytes)`; `Value = int | bool | str | bytes | Resolution | Range | Collection | OutOfBand | Unknown`.
  - `@dataclass Attr(name: str, tag: Tag, values: list[Value])`, `@dataclass Group(tag: Tag, attrs: list[Attr])`, `@dataclass Message(version: tuple[int, int], code: int, request_id: int, groups: list[Group])` with `def attrs(self, group: Tag) -> dict[str, list[Value]]` (first group of that tag; later duplicates of a name ignored).
  - `def encode(msg: Message, document: bytes = b"") -> bytes`, `def decode(data: bytes) -> tuple[Message, bytes]` (message, trailing document bytes).
  - `MAX_DEPTH = 8`, `MAX_VALUES = 10_000`; violations raise `IppDecodeError(reason)` (`errors.py`).
  - `OPERATIONS = {"Print-Job": 0x0002, "Validate-Job": 0x0004, "Cancel-Job": 0x0008, "Get-Job-Attributes": 0x0009, "Get-Jobs": 0x000A, "Get-Printer-Attributes": 0x000B}`; `STATUS_NAMES: dict[int, str]` for 0x0000–0x0002, the `client-error-*` 0x0400–0x0420 and `server-error-*` 0x0500–0x050C names of RFC 8011 / PWG 5100.x used by the client.
- Unknown value tags decode to `Unknown(tag, raw)` and re-encode byte-identically; an unknown delimiter tag in 0x06–0x0F starts a group that is kept but never read.

- [ ] **Step 1: Write the failing tests**
  - `test_roundtrip_get_printer_attributes_request` — the request built for `requested-attributes=["printer-state","marker-levels"]` encodes to the bytes in `fixtures/gpa_request.bin` (assembled by hand from RFC 8010 §3.1) and decodes back to an equal `Message`.
  - `test_decode_response_types` — `fixtures/gpa_response.bin` contains one attribute of every value type including `printer-resolution-supported` (resolution), `copies-supported` (range), `media-col-default` (collection with nested `media-size` collection), a `1setOf keyword`, an out-of-band `no-value`; decoded values equal the expected Python objects.
  - `test_print_job_request_with_media_col` — the Print-Job request with `media-col{media-size{x-dimension=21000, y-dimension=29700}, media-type=labels, media-source=main-tray}` encodes to `fixtures/print_job_request.bin`, assembled by hand from RFC 8010 §3.1.6 (begCollection with empty member name, `memberAttrName` values, nested collection, endCollection) — not produced by our encoder.
  - `test_unknown_tag_preserved` — value tag `0x7F` decodes to `Unknown` and re-encodes identical bytes.
  - `test_print_job_document_is_trailing_bytes` — `decode(encode(msg, b"%PDF-1.4..."))[1] == b"%PDF-1.4..."`.
  - `test_decode_rejects_*` (parametrised, each `IppDecodeError`): empty input; 7-byte header; value length pointing past the end; name length past the end; missing end-of-attributes tag; collection depth 9; 10 001 values in one attribute; `endCollection` without `begCollection`; integer value of length 3.
- [ ] **Step 2: Run, expect FAIL** — `pytest tests/unit/printer_backends/ipp/test_codec.py -v`.
- [ ] **Step 3: Implement** encode/decode (big-endian, RFC 8010 §3; additional values carry an empty name; collections per RFC 8010 §3.1.6 with `memberAttrName`).
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add backend/app/printer_backends/ipp backend/tests/unit/printer_backends/ipp && git commit -m "feat(printer-backends): IPP message codec"`

---

### Task 2: IPP client and the fake printer

**Files:**
- Create: `backend/app/printer_backends/ipp/client.py`, `backend/tests/helpers/fake_ipp_printer.py`
- Modify: `backend/app/printer_backends/ipp/errors.py`
- Test: `backend/tests/unit/printer_backends/ipp/test_client.py`, `backend/tests/unit/helpers/__init__.py`, `backend/tests/unit/helpers/test_fake_ipp_printer.py`

**Interfaces:**
- Consumes: Task 1.
- Produces (`errors.py`): `IppError(Exception)`; `IppUnreachableError` (connect error or connect timeout — nothing was sent); `IppTransportError` (any failure after the request started: read/write timeout, reset, protocol error); `IppStatusError(status: int, name: str)`; subclasses `IppNotFoundError` (0x0406), `IppBusyError` (0x0507); `IppDecodeError`; `IppResponseTooLargeError`; `IppBadResponseError` (HTTP status ≠ 200 or content type not `application/ipp`).
- Produces (`client.py`):
  - `def to_http_url(uri: str) -> str` and `def validate_ipp_uri(uri: str) -> None` (raises `ValueError` with a fixed message per rule).
  - `@dataclass(frozen) PrintAccepted(job_id: int, job_uri: str | None)`, `@dataclass(frozen) JobInfo(job_id: int, state: int, reasons: list[str], impressions_completed: int | None)`.
  - `class IppClient(uri: str, *, tls_verify: bool = True, query_timeout_s: float = 5.0, upload_timeout_s: float = 30.0, transport: httpx.AsyncBaseTransport | None = None)` with `async def get_printer_attributes(self, requested: Sequence[str]) -> dict[str, list[Value]]`, `async def print_job(self, pdf: bytes, job_attrs: list[Attr], op_attrs: list[Attr]) -> PrintAccepted`, `async def get_job(self, job_id: int) -> JobInfo`, `async def get_jobs(self, which: Literal["not-completed","completed"] = "not-completed") -> list[JobInfo]`, `async def cancel_job(self, job_id: int) -> None`, `async def validate_job(self, job_attrs: list[Attr]) -> None`, `async def aclose(self) -> None`. Request ids increment per client; every request carries `attributes-charset=utf-8`, `attributes-natural-language=en`, `printer-uri` (or `job-id` + `printer-uri`). One `httpx.AsyncClient` per `IppClient`, `verify=tls_verify`, `follow_redirects=False`.
- Produces (`fake_ipp_printer.py`, tests only): `class FakeIppPrinter` — an ASGI app (`async def __call__(scope, receive, send)`) using the codec. Scriptable fields: `printer_state: int = 3`, `reasons: list[str] = ["none"]`, `markers: list[dict]`, `media_sources: list[str]`, `formats: list[str] = ["application/pdf"]`, `job_creation_attributes: list[str] = ["media-col", "print-scaling", "print-color-mode", "copies", "sides"]`, `media_col_members: list[str] = ["media-size", "media-type", "media-source"]`, `accepting_jobs: bool = True`, `scaling_supported: bool = True`, `margins_hmm: int = 423`, `resolutions: list[int] = [600]`, `job_script: list[int] = [3, 5, 9]` (job states returned on successive Get-Job-Attributes), `print_status: int = 0`, `busy: bool = False`,  `fail_get_job_with: int | None`. Records `received: list[ReceivedOp]` (operation name, attributes, document bytes). `def forget_jobs(self) -> None` (reboot), `def advance(self) -> None`. A connection that dies after the body cannot be expressed by an ASGI app through `httpx.ASGITransport`, so the helper also provides `class FailingTransport(httpx.AsyncBaseTransport)` wrapping the ASGI transport: `FailingTransport(inner, fail_on: str, exc: type[Exception])` reads the request (including the document) and then raises `exc` (`httpx.RemoteProtocolError` or `httpx.ReadTimeout`) for the named operation. Plus `async def serve_on_loopback(fake) -> tuple[str, Callable[[], Awaitable[None]]]` that runs it with uvicorn on `127.0.0.1:<free port>` and returns the `ipp://` URI and a stop function (for browser tests in Plan 4).

- [ ] **Step 1: Write the failing tests** (`FakeIppPrinter` through `httpx.ASGITransport`):
  - `test_uri_rules` — `to_http_url("ipp://printer.example.invalid/ipp/print") == "http://printer.example.invalid:631/ipp/print"`; `ipps` → `https://…:631`; explicit port kept; `validate_ipp_uri` refuses `ftp://…`, `ipp://user:pw@…`, `ipp://h/p#x`, empty host.
  - `test_get_printer_attributes` — returns the fake's state and `document-format-supported`.
  - `test_print_job_sends_document_and_attrs` — fake records operation `Print-Job`, the PDF bytes, and `requesting-user-name=label-printer-hub`; returns `PrintAccepted(job_id=1, ...)`.
  - `test_get_job_script_progression` — three `get_job` calls → states 3, 5, 9.
  - `test_status_errors` — `print_status=0x040A` → `IppStatusError(name="client-error-document-format-not-supported")`; `busy=True` → `IppBusyError`; after `forget_jobs()` `get_job` → `IppNotFoundError`.
  - `test_connect_error_is_unreachable` — transport raising `httpx.ConnectError` → `IppUnreachableError`; `httpx.ReadTimeout` → `IppTransportError`; `FailingTransport(..., "Print-Job", httpx.RemoteProtocolError)` → `IppTransportError` (after the document was read).
  - `test_response_over_1mb_aborted` — a transport streaming 2 MB → `IppResponseTooLargeError`, read stops at 1 MB + one chunk.
  - `test_bad_content_type` — `text/html` 200 → `IppBadResponseError`.
  - `test_timeouts_passed` — client built with `query_timeout_s=2, upload_timeout_s=30` uses those values on the respective calls (assert via a recording transport).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add backend/app/printer_backends/ipp backend/tests/helpers/fake_ipp_printer.py backend/tests/unit/printer_backends/ipp backend/tests/unit/helpers && git commit -m "feat(printer-backends): IPP client over httpx with limits"`

---

### Task 3: Spike S2 — interoperability of the codec and client (time box: 60 minutes)

**Question:** Do our Print-Job (with `media-col`, `print-scaling`, `print-color-mode`), Get-Job-Attributes, Get-Jobs and Cancel-Job requests decode correctly in an independent IPP implementation, and do its responses decode in ours? The fake printer uses our own codec, so encoder and decoder bugs can cancel out; this spike is the only check against a second implementation before real hardware.

- [ ] **Step 1:** On a developer machine (not CI, not a dependency), run CUPS's `ippeveprinter` (Apache-2.0) with `-f application/pdf` on loopback, and drive it with a throw-away script using `IppClient`. Also run `ipptool -tv` with the bundled `get-printer-attributes.test` against `FakeIppPrinter` served on loopback.
- [ ] **Step 2:** Record in `docs/research/2026-11-05-ipp-client-interop.md` (English, no hostnames, no device data): tool versions, each operation's outcome, any attribute the other side refused, and the decision taken. If `ippeveprinter` is unavailable, record that and what was checked instead.
- [ ] **Step 3:** Any defect found becomes a regression test in `test_codec.py` / `test_client.py` and a fix in Task 1/2 code, committed separately (`fix(printer-backends): …`).
- [ ] **Step 4: Commit** — `git add docs/research/2026-11-05-ipp-client-interop.md && git commit -m "docs(printer-backends): IPP client interoperability check"`

---

### Task 4: Attribute summary, status mapping, Print-Job attributes

**Files:**
- Create: `backend/app/printer_backends/ipp/attributes.py`, `backend/app/printer_backends/ipp/job_attrs.py`
- Test: `backend/tests/unit/printer_backends/ipp/test_attributes.py`, `test_job_attrs.py`

**Interfaces:**
- Consumes: Task 1 value types.
- Produces (`attributes.py`):
  - `PRINTER_ATTRS: tuple[str, ...]` — `printer-make-and-model, ipp-versions-supported, document-format-supported, printer-resolution-supported, media-supported, media-size-supported, media-type-supported, media-source-supported, media-col-supported, job-creation-attributes-supported, printer-is-accepting-jobs, media-col-ready, media-ready, print-color-mode-supported, print-scaling-supported, sides-supported, media-top-margin-supported, media-bottom-margin-supported, media-left-margin-supported, media-right-margin-supported, printer-state, printer-state-reasons, marker-names, marker-colors, marker-levels, marker-low-levels, marker-types, queued-job-count`.
  - `class ProbeSummary(BaseModel)`: `make_and_model: str | None, ipp_versions: list[str], pdf_supported: bool, pdf_versions: list[str], resolutions_dpi: list[int]` (x resolution, dpi, deduplicated, descending; dots-per-cm converted), `media_sizes: list[str], media_types: list[str], media_sources: list[str], color_modes: list[str], margins_hmm: Margins | None` (`class Margins(BaseModel): top, left, bottom, right: int` in hundredths of mm; each side = minimum of its supported list), `media_col_supported: bool` (rule of the Global Constraints), `media_col_members: list[str]`, `accepting_jobs: bool | None`, `scaling_none_supported: bool, monochrome_supported: bool, one_sided_supported: bool, state: str`.
  - `class Reason(BaseModel)`: `keyword: str` (base without suffix), `severity: Literal["report","warning","error"]`, `blocking: bool`.
  - `class Marker(BaseModel)`: `name: str, color: str | None, type: str | None, level_percent: int | None, some_remaining: bool, low: bool, empty: bool`.
  - `class IppStatusRecord(BaseModel)`: `kind: Literal["page"] = "page", online: bool, printer_state: Literal["idle","printing","stopped"], reasons: list[Reason], blocking_reason: str | None, warnings: list[str], markers: list[Marker], trays: list[TrayLoad], jobs_ahead: int | None, summary: ProbeSummary`; `class TrayLoad(BaseModel): key: str, media: str | None, ready: bool` (from `media-col-ready` / `media-ready` where reported).
  - `def summarise(attrs: Mapping[str, list[Value]]) -> ProbeSummary`; `def map_status(attrs: Mapping[str, list[Value]]) -> IppStatusRecord`.
  - Rules: state 3 idle, 4 printing, 5 stopped, anything else → `stopped` + reason `unknown-state` (error). Severity from suffix `-report`/`-warning`/`-error`; no suffix → `error` (OC-20) **except** the base keywords `toner-low`, `marker-supply-low`, `media-low`, `developer-low`, which are warnings (spec 11.3: low supplies never block); `none` ignored. Blocking = any `error` severity or base in `{media-empty, media-jam, door-open, cover-open, toner-empty, marker-supply-empty, paused, offline}`. `blocking_reason` = first blocking base keyword. Reasons are keyword-filtered (`[a-z0-9-]`, ≤ 64 chars, others dropped) and capped at 32. Markers zip by index over the shortest of the `marker-*` lists present; level `-1`/`-2` or > 100 → `None`; `-3` → `None` + `some_remaining=True`; `low` = level ≤ low level, or reason `toner-low`/`marker-supply-low`; `empty` = level 0 or reason `toner-empty`/`marker-supply-empty`. Values of the wrong type are skipped; each attribute anomaly logs one WARNING per process (`functools.cache` on `(attribute, anomaly)`).
- Produces (`job_attrs.py`): `def print_job_attributes(summary: ProbeSummary, *, media: Literal["A4","Letter"], tray: str, job_name: str) -> tuple[list[Attr], list[Attr]]` (operation attrs, job attrs) per the Global Constraints list.

- [ ] **Step 1: Write the failing tests**
  - `test_map_status_real_shape` — synthetic answer: state 5, reasons `["toner-low-warning"]`, marker `black` level 0 → `printer_state="stopped"`, `warnings == ["toner-low"]`, marker `level_percent=0, low=True, empty=True`, `blocking_reason is None` (the spec's real-device example, shown "as is").
  - `test_toner_empty_blocks` — `["toner-empty-error"]` → `blocking_reason == "toner-empty"`.
  - `test_reason_without_suffix_is_error` — `["media-jam"]` → error, blocking; `["toner-low"]` → warning, not blocking.
  - `test_map_status_hostile_inputs` (parametrised; each asserts no exception and the listed outcome): no `printer-state` → `stopped`/`unknown-state`; state 7 → same; `marker-levels` as text → markers without levels; 3 names / 2 levels → 2 markers; levels `-1, -2, -3, 150` → `None, None, None+some_remaining, None`; 5000 reasons → 32 kept; reason `"bad reason!"` and a 300-char reason dropped; no `media-source-supported` → `trays == []`.
  - `test_summarise_resolution_and_margins` — resolutions `600x600 dpi, 1200x600 dpi, 236 dots/cm` → `[1200, 600, 599]` (236 dpcm × 2.54 = 599.44, rounded to 599, a distinct value); margins `[423, 500]` → 423.
  - `test_pdf_supported_flag` — without `application/pdf` → `pdf_supported is False`.
  - `test_media_col_detection` — `job-creation-attributes-supported` with `media-col` → supported; attribute absent but `media-col-supported = [media-size, media-type, media-source]` → supported with those members; `media-col-supported = [media-size]` only → collection without `media-type`/`media-source`; neither → not supported.
  - `test_print_job_attributes_media_col` — summary with `media_col_supported`, members `media-size, media-type, media-source`, and tray `main-tray` → job attrs contain collection `media-col{media-size{x-dimension=21000,y-dimension=29700},media-type=labels,media-source=main-tray}`, `print-scaling=none`, `print-color-mode=monochrome`, `copies=1`, `sides=one-sided`; op attrs contain `document-format=application/pdf`, `job-name`, `requesting-user-name=label-printer-hub`.
  - `test_print_job_attributes_fallback` — without `media-col`, scaling or monochrome support, tray `auto`, Letter → only `media=na_letter_8.5x11in`, `copies=1`; no `media-source`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add backend/app/printer_backends/ipp/attributes.py backend/app/printer_backends/ipp/job_attrs.py backend/tests/unit/printer_backends/ipp && git commit -m "feat(status): map IPP printer attributes to hub status"`

---

### Task 5: Configure IPP printers (backend kind, trays, probe, ADR 0020)

**Files:**
- Create: `backend/app/models/printer_tray.py`, `backend/app/models/printer_calibration.py`, migration `20261105b1`, `docs/decisions/0020-backend-kinds-ipp-page-printers.md`
- Modify: `backend/app/main.py` (skip `ipp` rows in `_build_configs_from_db`, model resolution and SNMP producers — moved here so no `ipp` row reaches the tape wiring once it can be saved), `backend/app/api/routes/printers.py` (`connection` of `ipp` rows), `backend/app/schemas/printer_admin.py`, `backend/app/services/printer_admin_service.py`, `backend/app/api/routes/admin_printers_api.py`, `backend/app/api/routes/batch.py`, `backend/app/api/routes/print.py` (tape routes refuse page printers), `backend/app/sheets/errors.py` (codes), `docs/decisions/register.md`, `docs/decisions/README.md`, `backend/tests/api/test_openapi_completeness.py`, `frontend/src/api/schema.gen.ts`
- Test: `backend/tests/unit/schemas/test_printer_admin_ipp.py`, `backend/tests/integration/api/test_admin_printers_ipp.py`, `backend/tests/db/test_printer_trays.py`

**Interfaces:**
- Consumes: Tasks 2, 4.
- Produces:
  - Tables: `printer_trays(printer_id FK printers.id, tray_key, label, load_hint, enabled, is_default; PK (printer_id, tray_key))`; `printer_calibrations(printer_id FK, tray_key; PK both; method CHECK IN ('manual','photo'), offset_x_hmm, offset_y_hmm, scale_x_ppm, scale_y_ppm, rotation_udeg INTEGER NOT NULL, corrections JSON NULL, measured_on_type_version_id UUID NULL, updated_at, updated_by)`.
  - Schemas: `PrinterCreatePayload.backend: Literal["ptouch","brother_ql","ipp"]`; for `ipp` the `connection` must parse as `IppConnection(uri: str, tls_verify: bool = True)` (`extra="forbid"`, validated with `validate_ipp_uri`) and `trays: list[TrayIn]` is required (1…16); for tape backends `trays` must be absent. `model` becomes optional for `ipp` (filled from the probe) and stays required for tape backends. `PrinterUpdatePayload.connection` is today typed as the tape `PrinterConnection`; it becomes `PrinterConnection | IppConnection` and the **service** validates it against the `backend` of the stored row (the payload carries no backend). `TrayIn(key: str` — `"auto"` or `^[a-z0-9][a-z0-9-]{0,63}$`, `label: str ≤ 60, load_hint: str | None ≤ 200, enabled: bool = True, is_default: bool = False)`; at least one enabled, exactly one default and it is enabled. `PrinterUpdatePayload` gains optional `connection` (ipp only) and `trays` (replace-all).
  - `POST /api/v1/admin/printers/ipp/probe` (admin; body `IppConnection`) → `ProbeSummary` live; errors `ipp_unreachable` (502), `ipp_rejected` (502, IPP status name in detail), `ipp_bad_response` (502). Placed on the existing admin printers router (it lives under `/api/v1/admin/printers`; the spec's `/api/admin/printers/ipp/probe` follows that prefix). *(Plan decision, recorded in the ADR.)*
  - Save rules: on create, and on update when `connection.uri` changes, the service probes; `pdf_supported is False` → `409 ipp_pdf_unsupported` (OC-18); unreachable → `409 ipp_unreachable` (nothing saved); every tray key other than `auto` must be in `media_sources`, else `422 tray_unknown`. `model` = `make_and_model` (truncated to 120), or `"IPP printer"` when absent. SNMP and cut defaults are ignored for `ipp`.
  - Tape print routes (`POST /api/print/{printer}/batch`, `POST /print`) on an `ipp` printer → `409 media_kind_mismatch`. (`POST /api/render/preview` takes no printer and is unaffected.)
  - `GET /api/printers` and `GET /api/printers/{id}`: for `ipp` rows the `connection` shown to non-admin callers is `{"tls_verify": …}` without `uri` (spec 14/18: the URI is connection detail); admin callers see the URI. Tape rows are unchanged — that they expose the host to `read` keys today is existing behaviour and reported separately, not changed here.
  - Test injection point: `app.state.ipp_transport_factory: Callable[[str], httpx.AsyncBaseTransport] | None` (default `None` = real network). Production code only reads it when building an `IppClient`; it is documented as an injection point in the code and set only by tests and `backend/tests/e2e_app.py`.
  - Errors added to `app/sheets/errors.py`: `MediaKindMismatchError` 409, `TrayUnknownError` 422, `IppUnreachableApiError` 409/502 per route, `IppPdfUnsupportedError` 409, `IppRejectedError` 502.
  - ADR 0020 (proposed, amends 0004): backend kinds beyond Brother raster; IPP with an own client over httpx; PDF only; Cancel-Job allowed for IPP (ADR 0005's ban is about TCP/9100 streams); configuration in the UI. Register rows `D18` "IPP backend kind with an own client" (ADR 0020) and `V1` "Media type `labels` is settable on the test printer via `media-col`" (To verify).

- [ ] **Step 1: Write the failing tests**
  - Schema: valid ipp payload; refused: `ftp://`, user info, no trays, two defaults, default disabled, tray key `"Main Tray"`, `trays` on a `ptouch` printer.
  - API (fake printer injected through an app-state transport hook `app.state.ipp_transport_factory` used only in tests): probe returns summary; probe needs admin (print key → 403); create stores trays and model; create refused with `ipp_pdf_unsupported` when `formats=["image/urf"]`; refused `tray_unknown`; update without URI change does not probe (fake records no request); update with a new URI probes.
  - `test_tape_routes_refuse_page_printer` — batch print to an ipp printer → 409 `media_kind_mismatch`.
  - `test_ipp_model_optional_and_filled` — create without `model` → model from `make_and_model`; tape create without `model` → 422.
  - `test_update_connection_validated_by_row_backend` — `{"uri": …}` on a tape row → 422; `{"host": …}` on an ipp row → 422.
  - `test_ipp_uri_hidden_from_read_keys` — read key sees no `uri`, admin key does.
  - `test_lifespan_ignores_ipp_rows_for_tape_wiring` — app start with an ipp row: no SNMP producer, no model resolution, no `PrinterYAMLConfig` for it.
  - DB: trays cascade-delete with printer row is **not** used (printers are soft-disabled); composite PK prevents duplicate tray keys; migration up/down.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**; ADR + register + README index; raise endpoint bound; `pnpm gen:api`.
- [ ] **Step 4: Run, expect PASS** — the three test files, `tests/api`, guardrail, `tests/unit/test_decision_register.py`, `tests/db/test_alembic_consistency.py`.
- [ ] **Step 5: Commit** — `git add <files above> && git commit -m "feat(printer-backends): configure IPP page printers with trays and probe"`

---

### Task 6: IPP status producer and the extended printer status

**Files:**
- Create: `backend/app/services/producers/ipp_status_producer.py`
- Modify: `backend/app/schemas/printer.py` (`PrinterStatus`), `backend/app/api/routes/printers.py` (status from cache), `backend/app/main.py` (start one producer per enabled ipp printer), `frontend/src/api/schema.gen.ts`
- Test: `backend/tests/unit/services/test_ipp_status_producer.py`, `backend/tests/integration/api/test_printer_status_ipp.py`

**Interfaces:**
- Consumes: Tasks 2, 4, 5; `PrintQueue.pause_info`, `PrintQueue.resume_printer`, `printer_status_cache` repository, `EventBus`.
- Produces:
  - `class PauseControl(Protocol)`: `def pause_info(self, printer_id: UUID) -> PauseInfo | None`, `async def resume_printer(self, printer_id: UUID) -> None` (`PrintQueue` satisfies it).
  - `class IppPrinterState` — in-memory holder `{summary: ProbeSummary | None, status: IppStatusRecord | None}` per IPP printer, written by the producer after every probe and read synchronously by `PagePrinter.summary()` / `status()` (Task 7).
  - `class IppStatusProducer(*, bus: EventBus, printer_id: UUID, client: IppClient, session_factory, state: IppPrinterState, pause_control: PauseControl | None, interval_s: float)` with `start()`, `stop()`, `async def probe_once() -> IppStatusRecord | None`. Each probe: Get-Printer-Attributes with `PRINTER_ATTRS`, Get-Jobs `not-completed` for `jobs_ahead` (count minus the hub's own tracked job), write `printer_status_cache.parsed = record.model_dump(mode="json")` and `captured_at`; failure → `online=false` record and `last_error` as today; publish `printer.status` on the same debounce rule as `StatusProbeProducer`. **Auto-resume (OC-22):** if the queue's `pause_info(printer_id).source == "printer_error"` and the new record has `blocking_reason is None` and `online`, call `pause_control.resume_printer(printer_id)`; a `user` pause is never touched. In this task the lifespan wires `pause_control=None` (the queue does not know page printers yet; `pause_printer`/`resume_printer` raise `KeyError` for unknown ids); Task 7 passes the queue.
  - `PrinterStatus` gains optional `kind: Literal["tape","page"] | None`, `printer_state: Literal["idle","printing","stopped"] | None`, `state_reasons: list[ReasonRead] | None`, `markers: list[MarkerRead] | None`, `trays: list[TrayStatusRead] | None` (key, label, load hint, enabled, default, loaded media where reported), `jobs_ahead: int | None`. `ReasonRead`, `MarkerRead` mirror `Reason`, `Marker` field for field; `TrayStatusRead` = `printer_trays` row fields + `TrayLoad.media`. For page printers `tape_loaded` stays `None`, `error_state` = `blocking_reason`.
- [ ] **Step 1: Write the failing tests**
  - `test_probe_writes_cache_and_publishes` — fake state idle → cache `parsed.kind == "page"`, one `printer.status` event; unchanged second probe → no event.
  - `test_offline_on_unreachable` — transport connect error → `online=false`, `last_error` set, no exception.
  - `test_auto_resume_only_printer_error_pause` — a fake `PauseControl` paused `source="printer_error", reason="toner-empty"`; fake clears the reason → resumed; same with `source="user"` → still paused.
  - `test_jobs_ahead_excludes_own_job`.
  - API: `GET /api/printers/{id}/status` for an ipp printer returns `kind="page"`, markers, reasons, trays with labels from `printer_trays`; for a tape printer the new fields are `null` and existing fields unchanged (regression).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**; label `# D18` where the producer is chosen by backend kind.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add backend/app/services/producers/ipp_status_producer.py backend/app/schemas/printer.py backend/app/api/routes/printers.py backend/app/main.py backend/tests/unit/services/test_ipp_status_producer.py backend/tests/integration/api/test_printer_status_ipp.py frontend/src/api/schema.gen.ts && git commit -m "feat(status): IPP status producer with toner, trays and auto-resume"`

---

### Task 7: Page jobs in the queue (submit, defer, upload, track, cancel)

**Files:**
- Create: `backend/app/services/page_jobs.py`, `backend/app/services/page_job_runner.py`
- Modify: `backend/app/services/print_queue.py`, `backend/app/services/job_lifecycle.py` (allow `PRINTING → CANCELLED`), `backend/app/services/job_store.py`, `backend/app/services/job_store_sqlite.py`, `backend/app/repositories/jobs.py`, `backend/app/main.py` (build page printers for `ipp` rows; skip them in `_build_configs_from_db`, model resolution and SNMP producers), `backend/app/api/routes/jobs.py`, `backend/app/api/routes/printers.py` (page jobs on the cancel, clear and retry paths that #184 routes through the queue); `backend/app/services/producers/ipp_status_producer.py` wiring (`pause_control=queue`)
- Test: `backend/tests/unit/services/test_page_job_runner.py`, `backend/tests/unit/services/test_print_queue_page_jobs.py`, `backend/tests/integration/api/test_page_job_cancel_api.py`

**Interfaces:**
- Consumes: Tasks 2, 4, 6; the queue's `Job` lifecycle, `JobStore`, `pause_printer(printer_id, reason, source)`.
- Produces (`page_jobs.py`):
  - `PageKind = Literal["sheet_page", "calibration_page"]`; `class CalibrationSnapshot(BaseModel)` (method, offsets hmm, scale ppm, rotation µdeg — Task 11 fills it); `class PagePayload(BaseModel)`: `kind: PageKind, media: Literal["A4","Letter"], tray: str, render_dpi: int, job_name: str, calibration: CalibrationSnapshot | None, detail: dict[str, Any]` (kind-specific, owned by the renderer). Stored as `jobs.payload` (`model_dump(mode="json")`); a payload without `kind` is a tape job (no data migration).
  - `PageRenderer = Callable[[PagePayload], bytes]`; `def register_page_renderer(kind: PageKind, fn: PageRenderer) -> None`; `def render_page(payload: PagePayload) -> bytes`.
  - `class PageOutcomeHandler(Protocol)`: `async def on_started(self, job_id: UUID) -> None`, `async def on_completed(self, job_id: UUID) -> None`, `async def on_ended(self, job_id: UUID, *, state: Literal["cancelled","failed"], started: bool, error_code: str) -> None`, `async def on_unknown(self, job_id: UUID) -> None` (restart without IPP job id). `def register_outcome_handler(kind, handler)`; default handler is a no-op.
  - `@dataclass PageJob(job: Job, payload: PagePayload)` (in-memory `Job` from `job_lifecycle` for state + events).
  - `class PagePrinter(Protocol)`: `id: UUID`, `client: IppClient`, `summary() -> ProbeSummary | None`, `status() -> IppStatusRecord | None` — both synchronous reads of the `IppPrinterState` the producer keeps (Task 6), never the database.
- Produces (`page_job_runner.py`):
  - `class Deferred(Exception)` with `reason_code: str`.
  - `class PageJobRunner(*, store: JobStore, notify: Callable[..., None], poll_interval_s: float = 2.0, max_backoff_s: float = 10.0)` with `async def run(self, printer: PagePrinter, page_job: PageJob) -> None` and `async def request_cancel(self, job_id: UUID) -> bool`, `def is_tracking(self, job_id: UUID) -> bool`.
  - Run sequence: (1) **pre-flight** (OC-21, maintainer ruling 2026-11-05): a live Get-Printer-Attributes **before** `mark_printing`; any `IppError`, `printer_state == "stopped"` with a `blocking_reason`, or `accepting_jobs is False` → raise `Deferred(reason)` (`ipp_unreachable`, the blocking keyword, `not_accepting`); the job never left `queued`, so there is no way back to build (no `PRINTING → QUEUED`). (2) `mark_printing`, `result={"phase": "uploading", "started": false}`. (3) render via `asyncio.to_thread(render_page, payload)`; render error → `failed` `render_failed`, `on_ended(started=False)`. (4) Print-Job: `IppUnreachableError` (connect failed, nothing sent) → `failed` `ipp_unreachable`, `on_ended(started=False)`; `IppBusyError` → `failed` `ipp_busy`, `on_ended(started=False)`; other `IppStatusError` `client-error-*` → `failed` `ipp_rejected` (detail `{"ipp_status": name}`), `on_ended(started=False)`; `IppTransportError` → persist `result.started = true`, `failed` `interrupted`, `on_ended(started=True)` (bytes may have reached the printer). The clean failures are retryable. (5) accepted → `result={"phase":"tracking","ipp_job_id":n,"job_uri":…,"started":false}`. (6) poll `get_job` every `poll_interval_s`: states 3/4 → `at_printer="waiting"`, 5 → `printing`, 6 → `stopped` (reasons in event); first observation of state ≥ 5 or `impressions_completed > 0` → persist `started=true`, `on_started`. 9 → `done`, `on_completed`. 7 → `cancelled` if not started else `failed` `interrupted`; 8 → `failed` `ipp_aborted` if not started else `failed` `interrupted` (a final 7/8 that reports `impressions_completed > 0` counts as started even if no earlier poll saw it; `result.started` is persisted before `on_ended`); `on_ended(...)` accordingly. `IppUnreachableError`/`IppTransportError` while polling → keep polling with backoff doubling to `max_backoff_s`, never time out (OC-23). `IppNotFoundError` → `failed` `interrupted` with `started` as persisted.
  - *(Plan decision: spec 8 and 11.5 together mean "started ⇒ failed/interrupted, cells unconfirmed"; a never-started IPP cancel is `cancelled`, a never-started abort `failed/ipp_aborted`.)*
- Produces (`print_queue.py`): `PrintQueue(..., page_printers: list[PagePrinter] = (), page_runner: PageJobRunner | None = None)`; queues exist for tape and page printers; `async def submit_page_job(self, printer_id: UUID, payload: PagePayload, *, api_key_id: UUID | None, source_ip: str | None, job_id: UUID | None = None) -> UUID` (refuses tape printers with `MediaKindMismatchError`; tape `submit` refuses page printers likewise); worker dispatch `isinstance(item, PageJob)`; a per-printer **held slot** `_held: dict[UUID, PageJob | None]` the worker drains before `queue.get()`; on `Deferred` the job goes back into the held slot and the printer is paused with `source="printer_error"`, `reason_code=<reason>`; `cancel(job_id)` (the method #184 makes the cancel and clear routes use) → queued/held page job cancelled at once (`on_ended(state="cancelled", started=False)`), tracked page job → `runner.request_cancel` (sends Cancel-Job; tracking decides the outcome; the route answers `202` with the job still `printing`). `queue/clear` cancels queued and held page jobs, never tracked ones.
  - Retry (route enqueues through the queue after #184): a `calibration_page` job is re-submitted with `submit_page_job` from its payload; a `sheet_page` payload is refused with `409 job_not_retryable` until Plan 3 Task 9 adds the cell-aware path. The worker awaits `runner.run` to completion before the next item (one hub job at the printer).
  - Job events: page-job transitions go through the existing `on_state_change` callback with extra fields `kind`, `at_printer` (`waiting`/`printing`/`stopped`, while tracked) and `summary` (`payload.detail["job_summary"]` when present — Plan 3 puts sheet code and cell count there) (spec 16).
  - `job_lifecycle`: `PRINTING → CANCELLED` allowed; tape cancel paths still only cancel queued jobs (ADR 0005) — asserted by a regression test.
  - `JobStore` gains `async def set_result(self, job_id: UUID, result: dict[str, Any]) -> None` and `async def mark_failed_code(self, job_id: UUID, code: str, message: str, detail: dict[str, Any] | None) -> None` (stores `error` as `"<code>: <message>"` like today) and `async def mark_cancelled(self, job_id: UUID) -> None` (both stores).

- [ ] **Step 1: Write the failing tests** (runner with `FakeIppPrinter`, `poll_interval_s=0`, a recording outcome handler, `MemoryJobStore`):
  - `test_completed_flow` — script `[3, 5, 9]` → states queued → printing → done; handler `on_started` then `on_completed`; result has `ipp_job_id`.
  - `test_cancel_before_start_at_printer` — script stays `[3]`, `request_cancel` → fake receives Cancel-Job, next poll 7 → `cancelled`, `on_ended(started=False, state="cancelled")`.
  - `test_cancel_after_start` — `[5]` then cancel → 7 → `failed`, `error_code="interrupted"`, `started=True`.
  - `test_aborted_before_start` → `failed`/`ipp_aborted`, `started=False`.
  - `test_rejected_document` — `print_status=0x040A` → `failed`/`ipp_rejected`, `on_ended(started=False)`, message is fixed text (no printer text).
  - `test_preflight_unreachable_defers` — queue-level: pre-flight connect error → job stays `queued` (never `printing` in the store), printer paused `printer_error` `ipp_unreachable`; after resume the job prints.
  - `test_connect_error_at_upload_fails_clean` — pre-flight passes, Print-Job connect error → `failed`/`ipp_unreachable`, `on_ended(started=False)`.
  - `test_not_accepting_defers` — `printer-is-accepting-jobs=false` → deferred.
  - `test_blocking_reason_defers` — pre-flight answer `printer-state=5`, `toner-empty-error` → no Print-Job sent, job `queued`, pause reason `toner-empty`.
  - `test_busy_at_upload_fails_clean` — Print-Job answers `server-error-busy` → `failed`/`ipp_busy`, `started=False`.
  - `test_final_state_with_impressions_counts_as_started` — script `[3, 8]` with `impressions_completed=1` on the final answer → `failed`/`interrupted`, `started=True`.
  - HTTP (`tests/integration/api/test_page_job_cancel_api.py`): `test_cancel_route_queued_page_job_not_sent` (`POST /api/jobs/{id}/cancel` → fake never receives Print-Job, `on_ended(cancelled, started=False)`); `test_cancel_route_held_page_job`; `test_cancel_route_tracked_page_job_sends_cancel_job`; `test_queue_clear_cancels_queued_page_jobs`; `test_retry_route_calibration_page_resubmits`; `test_retry_route_refuses_sheet_page`.
  - `test_upload_read_timeout_is_interrupted` — `FailingTransport(..., "Print-Job", httpx.ReadTimeout)` → `failed`/`interrupted`, `result.started == True`, `on_ended(started=True)`.
  - `test_unreachable_while_tracking_backs_off` — after acceptance the transport fails 5 polls then recovers with state 9 → `done`; no failure in between.
  - `test_queue_refuses_kind_mismatch` — `submit_page_job` to a tape printer and tape `submit` to a page printer → `MediaKindMismatchError`.
  - `test_one_job_at_printer` — two page jobs; the second's Print-Job is recorded only after the first reaches 9.
  - `test_tape_printing_job_still_not_cancellable` (regression, ADR 0005).
  - `test_render_error_fails_cleanly`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**; label `# D18` where tape vs. page dispatch happens.
- [ ] **Step 4: Run, expect PASS** — plus the existing `tests/unit/services/test_print_queue*.py` unchanged and green.
- [ ] **Step 5: Commit** — `git add <files above> && git commit -m "feat(queue): page jobs with IPP upload, tracking, cancel and deferral"`

---

### Task 8: Restart recovery and forgotten jobs

**Files:**
- Modify: `backend/app/services/print_queue.py` (`start()`), `backend/app/services/job_store.py`, `backend/app/services/job_store_sqlite.py`, `backend/app/repositories/jobs.py`
- Test: `backend/tests/unit/services/test_print_queue_page_recovery.py`, `backend/tests/integration/test_page_job_restart.py`

**Interfaces:**
- Consumes: Task 7.
- Produces: `JobStore.list_page_jobs_in_flight(printer_id: UUID) -> list[DbJob]` (state `printing`, `payload.kind` set); `mark_interrupted(printer_id)` no longer touches page-kind jobs. `PrintQueue.start()`: for each in-flight page job with `result.ipp_job_id` → put a "resume tracking" `PageJob` into the held slot (the worker resumes polling before anything else, `started` restored from `result`); without `ipp_job_id` → `failed_restart` and `on_unknown(job_id)` (OC-24). Before resuming, one Get-Jobs `not-completed` call cross-checks (spec 11.5): a tracked id that is neither listed nor answers Get-Job-Attributes ends `interrupted` as in Task 7; a listed id resumes. Queued page jobs are re-enqueued from the payload without rendering (rendering happens at send).
- [ ] **Step 1: Write the failing tests**
  - `test_restart_resumes_tracking_to_completion` — run a job to state 5 (`started`), stop the queue, build a new queue with the same SQLite store and fake (script continues `[5, 9]`), start → `done`, `on_completed` called once, no second Print-Job recorded.
  - `test_restart_without_ipp_job_id_unknown_outcome` — DB row `printing`, `result={"phase":"uploading"}` → `failed_restart`, `on_unknown` called.
  - `test_restart_requeues_queued_page_jobs` — queued page job prints after restart; tape recovery behaviour unchanged (existing tests stay green).
  - `test_printer_forgot_job` — after acceptance `forget_jobs()` → `failed`/`interrupted`, `started` as persisted.
  - `test_unreachable_during_tracking_keeps_waiting` — 20 failed polls with `max_backoff_s=0` → still `printing`, cancellable.
  - Integration (`test_page_job_restart.py`, real app lifespan twice on one temp DB with the fake injected): restart mid-job → job ends `done`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add <files above> && git commit -m "feat(queue): resume IPP job tracking after a hub restart"`

---

### Task 9: Spike S1 — reportlab output (time box: 45 minutes)

**Questions (only answerable by running reportlab):** (a) Does `drawImage`/`drawInlineImage` of a PIL mode `"1"` image produce an image XObject with `/BitsPerComponent 1` and `/ColorSpace /DeviceGray` (or an `/ImageMask`), without resampling and without RGB conversion? Which call and which image preparation guarantee it? (b) With `pageCompression=0`, are the content-stream operators (`cm`, `g`/`G`, `re`, `m`/`l`/`S`, `Tf`) readable by a regex, so tests can assert DeviceGray-only and the transformation matrix? (c) Does `setFillGray`/`setStrokeGray` avoid any `rg`/`k` operator, including for text? (d) How is DejaVu Sans located and embedded (`TTFont` path resolution in the image and on CI)? (e) Does `Canvas(..., invariant=True)` make two renders of the same input byte-identical (no CreationDate/ModDate drift, fixed `/ID`)? (f) Which reportlab version is current, and which transitive dependency does it pull (`charset-normalizer` from 4.4.4 on; earlier 4.x pull `chardet`)?

- [ ] **Step 1:** Throw-away script in a scratch directory (not committed) answering (a)–(d) with printed evidence.
- [ ] **Step 2:** Record answers and the chosen calls in `docs/research/2026-11-05-reportlab-pdf-output.md`; note any fallback (e.g. writing the image XObject as an `/ImageMask`).
- [ ] **Step 3: Commit** — `git add docs/research/2026-11-05-reportlab-pdf-output.md && git commit -m "docs(printer-backends): reportlab PDF output check"`

---

### Task 10: PDF page writer and the correction transform

**Files:**
- Create: `backend/app/page_render/__init__.py`, `pdf.py`, `transform.py`, `backend/tests/helpers/pdf_inspect.py`
- Modify: `backend/pyproject.toml` (reportlab), `THIRD_PARTY_NOTICES.md`
- Test: `backend/tests/unit/page_render/__init__.py`, `test_pdf.py`, `test_transform.py`

**Interfaces:**
- Consumes: Task 9 findings.
- Produces (`transform.py`, pure, mm-space with y down):
  - `@dataclass(frozen) Deviation(offset_x_hmm: int = 0, offset_y_hmm: int = 0, scale_x_ppm: int = 1_000_000, scale_y_ppm: int = 1_000_000, rotation_udeg: int = 0)`; `IDENTITY = Deviation()`.
  - `def apply_deviation(dev: Deviation, page: Literal["A4","Letter"], p_mm: tuple[float, float]) -> tuple[float, float]` — `C + R(θ)·diag(sx, sy)·(p − C) + d`, `R(θ) = [[cos θ, −sin θ], [sin θ, cos θ]]` (y down ⇒ θ > 0 is clockwise as seen), C = page centre.
  - `def correction_mm(dev, page) -> Affine` and `def correction_pdf_matrix(dev, page) -> tuple[float, float, float, float, float, float]` — `F ∘ inverse(deviation) ∘ F⁻¹` where `F(x, y) = (k·x, H_pt − k·y)`, `k = 72 / 25.4`.
- Produces (`pdf.py`):
  - `@dataclass PageImage(x_hmm: int, y_hmm: int, w_hmm: int, h_hmm: int, image: Image.Image)` (mode `"1"` required, else `ValueError`); `@dataclass PageText(x_hmm: int, baseline_y_hmm: int, size_pt: float, text: str)`.
  - `write_pdf` always builds the canvas with `invariant=True` (deterministic bytes, spec 11.4) and takes `title` from the caller; no wall-clock value enters the PDF.
  - `def write_pdf(page: Literal["A4","Letter"], *, images: Sequence[PageImage] = (), texts: Sequence[PageText] = (), vector: Callable[[VectorPen], None] | None = None, correction: Deviation = IDENTITY, compress: bool = True, title: str = "") -> bytes` — one page; `canvas.transform(*correction_pdf_matrix(...))` applied once before any content when not identity.
  - `class VectorPen` (thin wrapper so callers draw in mm, y down, gray only): `line(x1, y1, x2, y2, *, width_mm: float, dash: tuple[float, ...] | None = None)`, `text(x, y, s, *, size_pt, anchor: Literal["start","middle","end"] = "start")`, `rect(x, y, w, h, *, width_mm)`. No colour parameters exist.
- Produces (`tests/helpers/pdf_inspect.py`): `media_box(pdf) -> tuple[float, ...]`, `operators(pdf) -> list[str]`, `cm_matrices(pdf) -> list[tuple[float, ...]]`, `images(pdf) -> list[dict]` (keys `BitsPerComponent`, `ColorSpace`, `ImageMask`, `Width`, `Height`), `text_positions(pdf) -> list[tuple[float, float]]` (from `Td`/`Tm`, in page coordinates after the CTM) — regex over `compress=False` output, per Task 9.

- [ ] **Step 1: Write the failing tests**
  - `test_identity_roundtrip` — for 20 points and `Deviation(150, -80, 1_002_000, 998_500, 500_000)`: `apply_deviation(dev, correction(q)) ≈ q` within 1e-6 mm.
  - `test_offset_correction_matrix` — `Deviation(offset_x_hmm=150, offset_y_hmm=-80)` on A4 → `correction_pdf_matrix ≈ (1, 0, 0, 1, -4.2520, -2.2677)` (±1e-3) — acceptance 14.
  - `test_scale_and_rotation_matrix` — `Deviation(scale_x_ppm=1_010_000, scale_y_ppm=990_000, rotation_udeg=500_000)` on A4: the first `cm` matrix in the PDF equals `correction_pdf_matrix(dev, "A4")` (±1e-4), and mapping the four page corners through that matrix and then through the deviation (in pt) returns the corners within 1e-3 pt (acceptance 14, scale and rotation).
  - `test_pdf_is_deterministic` — two `write_pdf` calls with the same input → identical bytes.
  - `test_rotation_sign` — `rotation_udeg=1_000_000` (1°): a point right of the centre moves **down** (y grows) under `apply_deviation`.
  - `test_media_box_exact` — A4 `(0, 0, 595.2756, 841.8898)`, Letter `(0, 0, 612, 792)` (±1e-3).
  - `test_gray_only` — page with an image, a text and vector lines → `operators` contains none of `rg RG k K sc SC scn SCN cs CS`; every image `BitsPerComponent == 1` and (`ColorSpace == "/DeviceGray"` or `ImageMask`) — acceptance 15.
  - `test_image_placed_at_mm_rect` — image at (985, 6370, 4570, 2120) hmm → its placement `cm` equals `(4570·k/100, 0, 0, 2120·k/100, 985·k/100, H − (6370+2120)·k/100)`.
  - `test_transform_applied_once_first` — non-identity correction → first `cm` in the stream is the correction.
  - `test_rejects_non_1bit_image`, `test_text_is_literal` (text `"(a)\\ <b>"` round-trips escaped, no markup interpretation).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**; add `reportlab>=4.4.4` (raise to the version confirmed in Task 9; 4.4.4 is the first that pulls `charset-normalizer` instead of `chardet`) and the notices rows (`reportlab` | BSD-3-Clause | PDF pages for page printers; `charset-normalizer` | MIT | pulled by reportlab — the transitive dependency Task 9 recorded).
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add backend/app/page_render backend/tests/helpers/pdf_inspect.py backend/tests/unit/page_render backend/pyproject.toml THIRD_PARTY_NOTICES.md && git commit -m "feat(printer-backends): DeviceGray PDF page writer with correction transform"`

---

### Task 11: Calibration values, storage, fit and API

**Files:**
- Create: `backend/app/calibration/__init__.py`, `model.py`, `service.py`, `fit.py`, `backend/app/api/routes/calibration.py`
- Modify: `backend/app/main.py`, `backend/app/sheets/errors.py`, `docs/decisions/register.md` (`D17`), `backend/tests/api/test_openapi_completeness.py`, `frontend/src/api/schema.gen.ts`
- Test: `backend/tests/unit/calibration/__init__.py`, `test_fit.py`, `test_service.py`, `backend/tests/integration/api/test_calibration_api.py`

**Interfaces:**
- Consumes: Task 5 tables, Task 10 `Deviation`, `apply_deviation`; Plan 1 type service (crossing geometry).
- Produces (`model.py`): `CalibrationIn(BaseModel)` — `offset_x_mm, offset_y_mm` (≤ 2 decimals, ±10), `scale_x, scale_y` (≤ 6 decimals, 0.95–1.05), `rotation_deg` (≤ 6 decimals, ±2); `CalibrationRead(tray, method, offset_x_mm, offset_y_mm, scale_x, scale_y, rotation_deg, measured_on: {type_key, version} | None, updated_at, updated_by)`; `def to_deviation(row | None) -> Deviation` (None → identity); out of range → `CalibrationOutOfRangeError` (422, `calibration_out_of_range`, detail field + bounds).
- Produces (`fit.py`):
  - `@dataclass Reading(col_gap: int, row_gap: int, across_mm: float, down_mm: float)` — gap indices 1-based (S1…S(cols−1), Z1…Z(rows−1)).
  - `def crossing_point(g: Geometry, col_gap: int, row_gap: int) -> tuple[float, float]` — `x = margin_left + (i−1)·pitch_x + label_w + (pitch_x − label_w)/2`, `y = margin_top + (j−1)·pitch_y + label_h + (pitch_y − label_h)/2` (mm; for pitch = label size this is the nominal cut).
  - `@dataclass FitResult(dev: Deviation, residuals_mm: list[float], flagged: list[int], out_of_range: list[str])`; `def fit(g: Geometry, page, readings: Sequence[Reading]) -> FitResult`. Algorithm (not determined by the signature):
    ```
    u, v = q - C                     # nominal crossing relative to page centre
    P = q + (across, down) - C       # printed position relative to centre
    solve least squares  Px = a·u + b·v + dx   and   Py = c·u + e·v + dy   (two 3×3 normal systems)
    sx = hypot(a, c); sy = hypot(b, e); θ = atan2(c, a)
    residual_k = |P_k − (R(θ)·diag(sx, sy)·(u_k, v_k) + d)|
    ```
    Fewer than 3 readings, or all collinear (normal-matrix determinant < 1e-9) → `ReadingsInsufficientError` (422, `readings_insufficient`). Residual > 0.3 mm → index in `flagged`. Values outside the ranges are returned with their names in `out_of_range` (nothing is saved by fit).
- Produces (`service.py`): `get_all(session, printer_id) -> list[CalibrationRead]` (one per enabled tray, `None` values for identity), `put(session, printer_id, tray, values: CalibrationIn, *, measured_on: tuple[str, int] | None, actor) -> CalibrationRead`, `delete(session, printer_id, tray, *, actor) -> None`, `snapshot(session, printer_id, tray) -> CalibrationSnapshot`. Unknown or disabled tray → `TrayUnknownError`; non-page printer → `MediaKindMismatchError`.
- Routes (spec 15): `GET /api/printers/{id}/calibration` (read + printer access), `PUT /api/printers/{id}/calibration/{tray}` (admin + printer access), `DELETE …/{tray}` (admin + printer access; spec 18: printer-restricted keys get `403 printer_not_allowed` for calibration of other printers), `POST …/{tray}/fit` (read + printer access; body `FitRequest(type: str, version: int | None, readings: list[ReadingIn] = Field(min_length=3, max_length=200))` → `FitResponse(values: CalibrationIn-shaped, residuals_mm, flagged, out_of_range)`). Register row `D17` "Calibration stores the printer's deviation around the page centre; the hub applies the inverse"; `# D17` in `transform.py` and `service.py`.

- [ ] **Step 1: Write the failing tests**
  - `test_fit_recovers_known_deviation` — synthesize readings at the four outermost crossings of L4736REV from `Deviation(120, -40, 1_001_000, 999_000, 300_000)` via `apply_deviation`; `fit` returns values within 0.01 mm / 1e-5 / 0.001°; residuals < 0.01.
  - `test_fit_flags_bad_reading` — perturb one of 5 readings by 1 mm → that index in `flagged`.
  - `test_fit_insufficient_and_collinear` — 2 readings; 3 readings on one row line → `ReadingsInsufficientError`.
  - `test_fit_out_of_range_reported_not_raised`.
  - `test_crossing_point_no_gap` — L4736REV Z1 (pitch 21.2 = label) → `y = 21.3 + 21.2 = 42.5`.
  - Service: put/get/delete roundtrip; ranges enforced (`offset_x_mm=10.01` → `calibration_out_of_range`); tray unknown; tape printer → `media_kind_mismatch`.
  - API: scope matrix (PUT/DELETE need admin; GET/fit read; printer-restricted key on another printer → 403 `printer_not_allowed`).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**; raise endpoint bound; `pnpm gen:api`.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add <files above> && git commit -m "feat(api): manual calibration per printer and tray with a readings fit"`

---

### Task 12: Calibration page (drawing, page job, download)

**Files:**
- Create: `backend/app/calibration/page.py`
- Modify: `backend/app/api/routes/calibration.py`, `backend/app/main.py` (register renderer `calibration_page`), `backend/app/sheets/errors.py`, `frontend/src/api/schema.gen.ts`, `backend/tests/api/test_openapi_completeness.py`
- Test: `backend/tests/unit/calibration/test_page.py`, `backend/tests/integration/api/test_calibration_page_api.py`

**Interfaces:**
- Consumes: Tasks 7, 10, 11; Plan 1 `get_version`, `Geometry`.
- Produces:
  - `def draw_calibration_page(pen: VectorPen, g: Geometry, *, footer: str) -> None` — all black, line width 0.1 mm. Column-gap lines **solid** through the full grid height at `crossing_point` x of S1…S(cols−1); row lines **dashed** (1.0 on / 0.5 off) at Z1…Z(rows−1); where a direction has no gap (pitch = label size) the line is drawn **dotted** (0.2 / 0.4) on the nominal cut and the page prints "Peel every other label (checkerboard) if the cut is hard to see." Labels `S<i>` above the grid and below, `Z<j>` left and right of the grid, 2.5 pt. Mini scales at every crossing: along x and along y, ±2 mm, tick every 0.2 mm 0.6 mm long, every 1 mm 1.2 mm long, centre tick 1.8 mm. Rulers on all four grid edges at every gap line: ±3 mm, 0.5 mm ticks. L-shaped corner marks, 1.5 mm legs, at every nominal label corner. Page corners: four 15 × 15 mm squares are reserved for Part B markers; nothing is drawn in them — any mark, ruler tick, scale, number or text that would fall inside one is omitted (on L4731REV the top-left label corner at 8.6 / 13.5 mm lies inside the square, so its corner mark is left out; on a 0 mm margin type more marks go). Footer centred horizontally (`anchor="middle"`), baseline 7 mm above the bottom edge, 6 pt, so it never reaches a corner square: `"<type key> v<n> · <printer name> · tray <tray> · <YYYY-MM-DD> · Calibration page — printed without correction"` (or `"— check print with correction"`).
  - Requires `cols ≥ 2` and `rows ≥ 2`, else `CalibrationTypeUnsuitableError` (422, `calibration_type_unsuitable`) — a crossing needs both directions. *(Plan decision; the spec's readings model needs crossings.)*
  - Renderer for kind `calibration_page`: `detail = {"type_key", "version", "printer_name", "date", "corrected": bool}`; `write_pdf(..., correction = snapshot if corrected else IDENTITY)`. No sheet record is created or touched (spec 13.2).
  - `POST /api/printers/{id}/calibration/{tray}/page` (print + printer access; body `{type: str, version: int | None, corrected: bool = False}`) → `202 {job_id}` via `queue.submit_page_job` (`job_name = "Calibration page · <key> v<n>"`, `render_dpi` unused, `calibration` snapshot when corrected).
  - `GET /api/printers/{id}/calibration/{tray}/page/pdf?type=&version=&corrected=` (read + printer access; path segment `pdf`, because `test_path_segments_are_lowercase` allows no dot — maintainer ruling 2026-11-05) → `application/pdf` attachment, same bytes as the job would send (OC-35).
- [ ] **Step 1: Write the failing tests**
  - `test_page_line_counts_l4736` — on L4736REV: 3 solid column lines, 11 dotted row lines (no vertical gap), 33 crossings with mini scales; checkerboard sentence present.
  - `test_page_line_counts_gapped_type` — Avery 7160-like (pitch_y = label_h, pitch_x > label_w): solid S lines, dotted Z lines; a fully gapped synthetic type → dashed Z lines and no checkerboard sentence.
  - `test_page_is_gray_only_and_corners_empty` — on L4736REV **and** L4731REV: `pdf_inspect.operators` gray only; no path point (`m`/`l`/`re`) and no text position (`Td`/`Tm`, `pdf_inspect.text_positions`) inside the four 15 mm corner squares; the footer text is centred.
  - `test_uncorrected_page_has_no_cm_correction`; `test_corrected_page_has_correction_matrix`.
  - `test_unsuitable_type` — single-column type → 422 `calibration_type_unsuitable`.
  - API: `POST …/page` queues a `calibration_page` job that the fake printer receives as PDF with `media-type=labels`; `page/pdf` returns `%PDF` and equals the rendered job bytes for the same inputs (dates pinned); scopes and printer restriction enforced.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**; raise endpoint bound; `pnpm gen:api`.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add <files above> && git commit -m "feat(api): printable calibration page as a page job and PDF download"`

---

### Task 13: Capabilities endpoint

**Files:**
- Create: `backend/app/api/routes/capabilities.py`, `backend/app/schemas/capabilities.py`
- Modify: `backend/app/main.py`, `backend/tests/api/test_openapi_completeness.py`, `frontend/src/api/schema.gen.ts`
- Test: `backend/tests/integration/api/test_capabilities_api.py`

**Interfaces:**
- Consumes: status cache (tape and page), model plugins (`dpi`), `TAPE_GEOMETRY`, Task 5 trays, Task 11 calibrations.
- Produces `GET /api/printers/{id}/capabilities` (read + printer access; cache only, no live call) → `Capabilities(kind: Literal["tape","page"], resolution_dpi: ResolutionRead, media: TapeMedia | PageMedia | None, trays: list[TrayCapability] | None, document_formats: list[str] | None, captured_at: datetime | None)`:
  - Tape: `resolution_dpi = {x, y}` from the driver's `dpi`; `media = {width_mm, type, printable_px, printable_mm}` from the cached `tape_loaded` and `TAPE_GEOMETRY` (`printable_mm = printable_px / dpi_y × 25.4`, 2 decimals), `None` without tape.
  - Page: `resolution_dpi = {max, supported: [...]}`; `media = {page_sizes: [{name, width_mm, height_mm}], media_type_settable: summary.media_col_supported and "media-type" in summary.media_col_members, media_types, hardware_margins_mm: {top, left, bottom, right} | None}`; trays with key, label, load hint, enabled, default, loaded media where reported, and `calibration: CalibrationRead | None`; `document_formats` from the summary.
  - Never contains the IPP URI or any `connection` detail.
- [ ] **Step 1: Write the failing tests** — PT printer (mock backend, 12 mm tape cached) → `kind="tape"`, `resolution_dpi={x:180,y:180}`, printable mm from `TAPE_GEOMETRY[12]`; QL printer → `{x:300,y:300}`; IPP printer with one calibrated tray → `kind="page"`, A4 listed with 210/297, margins 4.23, `calibration.offset_x_mm` as stored; JSON of the IPP response contains neither the URI nor `"connection"`; printer-restricted key on another printer → 403 (acceptance 18).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**; raise endpoint bound; `pnpm gen:api`.
- [ ] **Step 4: Run, expect PASS** — then the full suite: `pytest -m "not slow" --cov=app --cov-fail-under=80`, `mypy app/`, `ruff check . && ruff format --check .`, `cd frontend && pnpm typecheck`.
- [ ] **Step 5: Commit** — `git add backend/app/api/routes/capabilities.py backend/app/schemas/capabilities.py backend/app/main.py backend/tests/api/test_openapi_completeness.py backend/tests/integration/api/test_capabilities_api.py frontend/src/api/schema.gen.ts && git commit -m "feat(api): printer capabilities for tape and page printers"`

---

## Operator-verified (not task gates)

- CP1525N-class printer added by URI; probe summary plausible; status shows the real reasons and toner. Records `V1`.
- Calibration page on L4736REV and L4731REV readable (acceptance 22); fit + save; check print within ±0.5 mm (OC-33, acceptance 5 together with Plan 3).

## Plan review 2026-11-05

Findings of the independent plan review worked in, each checked against the code: P2-B1 (requires #184; page jobs on the same cancel/clear path, HTTP tests here), P2-B2 (`page/pdf`), P2-M1 (pre-flight before `mark_printing`, no way back to queued — maintainer ruling), P2-M2, P2-M3 (retry after #184; `sheet_page` refused until Plan 3), P2-M4, P2-M5, P2-M6, P2-m1 … P2-m13. None rejected. P2-m11 is changed for IPP rows only; that tape rows expose their host to `read` keys is existing behaviour and is to be reported separately.
