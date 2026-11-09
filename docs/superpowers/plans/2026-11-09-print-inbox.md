# Print Inbox — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-browser cart with a server-side print inbox that every device shares and other apps can fill. Parked items are printed by selection onto tape or onto a scanned label sheet, with data freshness, refresh/diff, user-defined event rules, a Grocy-format label webhook and a webhook call log (#27). The work starts by fixing #188.

**Architecture:** A new `app/inbox/` package (models, service, freshness resolver, print adapters, refresh, event rules, webhook log) in the style of `app/sheets/`. Routes live under `/api/v1/inbox`, `/api/v1/integrations/{name}/event-rules`, `/api/v1/webhook/grocy/label` and `/api/v1/admin/webhook-calls`. Tape prints go through a new `PrintService.submit_labels`, which takes resolved `LabelData` and keeps `source_app`. Sheet prints build a raw-data `SheetPrintRequest` and reuse `app.sheets.print_service.preview/print_sheets`. Auth moves from one effective scope to a capability set with the additive `inbox` capability. The frontend keeps `useCart()`'s shape on top of a TanStack Query inbox that `inbox.changed` SSE events keep current. Selection stays in `localStorage`.

**Tech Stack:** FastAPI / Starlette, SQLModel + SQLite, Alembic, asyncio, pytest; React + Vite, TanStack Query/Router, react-aria-components, lingui, Vitest + jsdom, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-09-print-inbox-design.md` (approved; decisions 1–17 in section 4, builder's calls B1–B41 and controller's calls C1–C10 are binding). Read it alongside this plan. Sections are cited as "§n".

**Base:** this plan starts on `main` **after** 1.5.0 (`feat/api-v1-status-manifest`, #224–#231) is merged. Every route is already under `/api/v1`, `PrinterRuntime` wires printers, and the Alembic head is `20261109b1` (`printer_identity`, per the 1.5.0 plan Task 14). Before Task 1, check that the head is really `20261109b1` (`alembic heads`). If it differs, set Task 3's `down_revision` to the real head and keep the chain linear.

## Global Constraints

- **Repo rules.** Public repo: English identifiers, comments, docs and commits; Conventional Commits; author `bjoern@strausmann.net`; **no AI attribution** (no `Co-Authored-By: Claude`, no session trailer, no "Generated with" footer). Never `git add -A`; stage explicit paths; run `git status --short` before each commit. Each commit body ends with `Refs #27` (Task 1: `Fixes #188`).
- **Release.** The release stays 1.x (1.6.x). Use `feat`/`fix`/`refactor`/`test`/`docs` and **no `BREAKING CHANGE:` footer and no `!`**, also for the removal of the old `/api/v1/webhook/grocy` (§8.1.5, B36).
- **Every regression test must go red against the unfixed code.** Run each counter-test named in a task once: revert or disable the guard, see the test fail **for the stated reason**, restore. Record the result in the task report.
- **Backend checks.** `ruff check .`, `ruff format --check .`, `mypy app/`, `pytest <touched dirs>`. Before each PR: `pytest -m "not slow" --cov=app --cov-fail-under=80`, `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`.
- **Frontend checks.** `pnpm typecheck`, `pnpm lint`, `pnpm test:coverage`, `pnpm build`; `pnpm e2e` before each PR. `schema.gen.ts` is changed only through `pnpm gen:api`, after every backend task that changes the OpenAPI.
- **Frontend JS needs Vitest + jsdom tests.** Every new module with logic (selection store, migration, inbox client, diff mapping) gets a `*.test.ts(x)`, with roundtrip tests for localStorage keys. A changed file without a changed test is a review fail.
- **i18n strings in de and en.** Every new UI string goes into `frontend/src/i18n/locales/en/messages.po` and `de/messages.po`, with real umlauts in German and counts through `plural`. Removed strings leave both catalogs.
- **UI task protocol (Tasks 2, 8–12, 18, 19).** Before writing UI code, load `taste-skill:design-taste-frontend`, `emil-design-eng`, `mobile-native` and `break-ui`. At the end of the task, run `impeccable:impeccable` on the changed screens. Take Playwright screenshots (light and dark, 1280 px and 390 px, `SHOTS` pattern in `frontend/e2e/shell.spec.ts`) as artifacts, not as a gate.
- **Untrusted text (§12.4).** Upstream titles, rows and QR payloads render as text nodes only: no `dangerouslySetInnerHTML`, never an `href`, and never in SSE events or metric labels. Logs name line ids and app names through `log_value`, never titles, keys or tokens.
- **Error bodies (§12.3).** Use the existing envelope `{error_code, error_message, error_detail?}`. Bodies never echo the request body, an idempotency key, a header value, a token or an upstream URL. Validation errors name field paths only.
- **Single process (§5.1).** In-memory state (duplicate windows, preview cache, refresh lock, inbox write lock) is per process. Add no shared store.
- **Route auth guardrail.** Every new route uses one of the deps that `tests/unit/api/test_route_auth_coverage_guardrail.py` accepts. A route that authenticates inside its handler (Grocy label) is added to that test's allow-list with a one-line reason.

## Review Focus

1. **The same line changed on two devices at once** (copies edited on the phone while the desktop prints it): the print gets `409 inbox_item_changed`, nothing is queued and nothing is lost. Test `test_print_after_concurrent_copies_edit_is_409` in Task 5.
2. **A webhook parks a line between preview and print:** the new line is not printed (the server prints only the ids sent) and arrives unselected. Backend `test_sheet_print_ignores_line_added_after_preview` in Task 6; frontend `sse arrival is unselected` in Task 8.
3. **A real-world Grocy payload with awkward values:** no `details`, best-before `2999-12-31`, a 600-character product name, emoji, form encoding with repeated keys. It is parked, bounded and never `422`. Test `test_grocy_label_awkward_payloads_park` in Task 15.
4. **The limit with merges and copies:** a merge that lifts a line from 9 to 10+ copies is clamped to 10, and the limit counts the labels after the clamp. Test `test_merge_clamps_and_limit_counts_after_clamp` in Task 4.
5. **A key edited after a session was minted** (`print` removed, or `["inbox"]` only): the session's capabilities follow the key on its next use. Test `test_session_follows_key_capability_change` in Task 2.

---

## Phases and PR boundaries

| PR | Tasks | Ships |
|---|---|---|
| **PR 1 — backend inbox** | 1–6 | #188 fix, capability set + `inbox` key, inbox store/API/events, freshness, tape and sheet print from the inbox. The old cart keeps working, because the UI is unchanged except the key form |
| **PR 2 — inbox UI** | 7–12 | Server cart and migration, selection, sheet preview and scan, expiry notices, refresh and diff |
| **PR 3 — integrations** | 13–20 | Event rules, webhook call log, Grocy label route and enrichment, Spoolman routing, settings UI, docs and release notes |

Each PR is reviewed and merged before the next one starts. The security audit runs at each PR (per the repo's ship gate), with focus on Task 2 in PR 1 and Tasks 14–16 in PR 3. The **Kept receiver (§8.3) is not in this plan**: it waits for #173.

## Migrations (linear chain)

| Revision | File | Task |
|---|---|---|
| `20261110a1` ← `20261109b1` | `backend/alembic/versions/2026_11_10_0001-20261110a1_print_inbox.py` | 3 |
| `20261110a2` ← `a1` | `…_0002-20261110a2_jobs_data_source.py` (add nullable column `jobs.data_source`) | 5 |
| `20261110a3` ← `a2` | `…_0003-20261110a3_inbox_refreshes.py` | 11 |
| `20261110a4` ← `a3` | `…_0004-20261110a4_integration_event_rules.py` | 13 |
| `20261110a5` ← `a4` | `…_0005-20261110a5_webhook_calls.py` | 14 |

All of them are additive. Downgrades drop what the upgrade added. Each migration has a test in `backend/tests/integration/db/test_alembic_<name>.py`, following `test_alembic_sheet_migration.py`: upgrade from the previous head on an empty DB and on a populated one, then `downgrade -1`.

---

## PR 1 — backend inbox

### Task 1: Webhook jobs reach the print queue (#188)

#188 is open and not fixed on the 1.5.0 branch: `webhooks.py:118/:158` still call `jobs_repo.create_queued` and stop there.

**Files:**
- Modify: `backend/app/services/print_service.py`: add `submit_label` and make `submit_print_job` resolve and then delegate to it.
- Modify: `backend/app/api/routes/webhooks.py`: both handlers submit through `submit_label`; fix the module docstring and the route descriptions.
- Test: `backend/tests/unit/api/test_webhooks_routes.py` (extend), `backend/tests/integration/api/test_webhook_prints.py` (new)

**Interfaces:**
- Produces: `PrintService.submit_label(content_type: ContentType, label: LabelData, options: PrintOptions = PrintOptions(), *, extra_payload: Mapping[str, Any] | None = None) -> UUID`. It does what `submit_print_job` does after resolving (preflight, render, `save_queued`, `submit_with_id`). The job payload keeps `label.source_app` and merges `extra_payload` under the key `"origin"`.
- Produces: `async def submit_webhook_label(request: Request, session: AsyncSession, *, app: str, entity_id: str, event_type: str) -> UUID` in `webhooks.py`. It looks the item up, picks the first enabled tape printer, gets the service through `request.app.state.backend_router.service_for(printer.slug)`, and calls `submit_label(ContentType.QR_TWO_LINES, label, extra_payload={"source": "webhook", "event_type": event_type, "entity_id": entity_id})`. The content type is the plan's call: webhook payloads carry none, and Task 17 replaces it with the event rule's format.

- [ ] **Step 1: Write the failing tests.** `test_spoolman_webhook_job_is_printed_without_restart`: a mock backend printer and a stubbed lookup. `POST /api/v1/webhook/spoolman` gives `202`, and within 2 s the mock backend recorded one print and the job row is `completed`. `test_webhook_job_payload_is_rerenderable`: the payload has `content_type`, `label_data.source_app == "spoolman"` and `rendered_tape_mm`; a `POST /api/v1/jobs/{id}/retry` gives a new queued job, not `422`. Write the same pair for `/grocy`. `test_webhook_no_tape_printer_503` is unchanged.
- [ ] **Step 2: Run them.** `pytest tests/integration/api/test_webhook_prints.py -v`. Expected: FAIL (the job stays `queued`, retry answers `422`).
- [ ] **Step 3: Implement** `submit_label` and `submit_webhook_label`. Errors of the print path map like `print.py` (`_ERROR_MAP`) into the envelope; the response stays `WebhookAcceptedResponse`.
- [ ] **Step 4: Verify.** The tests pass. Counter-test: put `jobs_repo.create_queued` back in one handler, and its test turns red on "no print recorded".
- [ ] **Step 5: Commit** `fix(webhooks): hand webhook jobs to the print queue with a re-renderable payload` (body `Fixes #188`).

### Task 2: Capability set and the `inbox` key scope (security)

**Files:**
- Create: `backend/app/auth/capabilities.py`
- Modify: `backend/app/auth/dependencies.py` (`AuthContext`, `_validate_api_key` :244-262, `_session_context`, the SSO and bypass paths, `require_scope`), `backend/app/auth/sessions.py` (`ValidSession`, `load_valid`), `backend/app/auth/scope_deps.py`, `backend/app/api/routes/admin_api_keys.py` (accept `inbox`), `frontend/src/features/settings/AccessKeys.tsx` (`SCOPES`, a checkbox labelled "Can add items to the print inbox")
- Test: `backend/tests/unit/auth/test_capabilities.py`, `backend/tests/integration/auth/test_scope_set.py`, `frontend/src/features/settings/AccessKeys.test.tsx`

**Interfaces:**
- Produces: `Capability = Literal["read", "print", "admin", "inbox"]`; `grants(scopes: Iterable[str]) -> frozenset[Capability]` computes the union: `read` → {read, inbox}; `print` → {read, print, inbox}; `admin` → all four; `inbox` → {inbox}; unknown values are ignored. `effective_label(caps) -> Scope` returns the highest chain scope, else `"inbox"`.
- Produces: `AuthContext.capabilities: frozenset[Capability]`. `AuthContext.scope` widens to `Literal["read","print","admin","inbox"]` and keeps the meaning "highest", for logs.
- Produces: `require_scope("inbox")` checks `required in ctx.capabilities`. `scope_deps.require_inbox = require_scope("inbox")`.
- Produces: `ValidSession.capabilities: frozenset[Capability]`. For a key session it is re-read from the key's current `scopes` on every use (B37); for SSO and bootstrap sessions it comes from `grants([row.scope])`.
- Produces: `caller_id(ctx: AuthContext) -> str`: `key:<api_key_id>` for keys and key sessions, `sso:<user>` for SSO, `bypass` for the Basic bypass (C5). Tasks 4, 7 and 15 use it.

- [ ] **Step 1: Write the failing tests.**
  - `test_inbox_only_key_authenticates_for_inbox`: a `["inbox"]` key passes `require_inbox`, and gets `403 insufficient_scope` on `require_read`.
  - `test_read_key_has_inbox`.
  - `test_unknown_only_scopes_still_key_no_scopes`: `["foo"]` gives `401 key_no_scopes`.
  - `test_bypass_downgrade_read_grants_inbox_not_print` (§12.1, B28).
  - `test_session_follows_key_capability_change` (Review Focus 5): mint a session from `["inbox","print"]`; it passes `require_print`. Edit the key to `["inbox"]`; the same cookie now gets `403` on print and still passes inbox.
  - Frontend: the key form sends `["inbox"]` when only the inbox box is checked.
- [ ] **Step 2: Run them.** Expected: `["inbox"]` gets `401 key_no_scopes`, and the session test fails.
- [ ] **Step 3: Implement.** Keep `_SCOPE_HIERARCHY` only as a compatibility shim, or delete it once nothing reads it. Re-run the route-auth guardrail test.
- [ ] **Step 4: Verify.** Counter-test: restore the "highest of three" reduction, and `test_inbox_only_key_authenticates_for_inbox` turns red with `401 key_no_scopes`.
- [ ] **Step 5: Commit** `feat(auth): grant capabilities as a set and add the enqueue-only inbox scope`.

### Task 3: Inbox data model, revision counter and events

**Files:**
- Create: `backend/app/models/inbox.py`, the migration `20261110a1`, `backend/app/inbox/__init__.py`, `backend/app/inbox/snapshot.py`, `backend/app/inbox/events.py`, `backend/app/repositories/inbox.py`
- Modify: `backend/app/settings_store/registry.py` (the `inbox.*` settings), `backend/app/api/routes/events_v1.py` and `backend/app/services/sse_snapshot.py` (`inbox` channel, snapshot counts)
- Test: `backend/tests/unit/inbox/test_snapshot.py`, `backend/tests/integration/db/test_alembic_print_inbox.py`, `backend/tests/integration/api/test_events_inbox.py`

**Interfaces:**
- Produces, table `inbox_items`: every field of §5.1, plus **`item_meta: JSON | None`** (holds `stock_id`; see spec gap G1). `source_app` is `Literal["snipeit","grocy","spoolman","kept","manual"]`. `format` is the tagged dict. The index is on `(source_app, item_ref)`.
- Produces, table `inbox_idempotency` per §5.3: primary key `scope_key`, plus a nullable `released_at` (when the line was printed or removed; retention counts from it).
- Produces, table `inbox_state`: one row, `revision: int`, and `last_expired_count`, `last_expired_labels`, `last_expired_at` for the expiry notice (see G4).
- Produces: `normalise_snapshot(data: SheetRawLabelData) -> dict[str, Any]` (sorted keys, NFC, trailing whitespace stripped, `None` and empty fields dropped) and `line_hash(source_app, item_ref, fmt, snapshot, item_meta) -> str` (SHA-256 over canonical JSON; `item_meta` takes part only through `stock_id`).
- Produces: `INBOX_CHANNEL = "inbox"`, `publish_inbox_changed(bus, *, revision: int, reason: InboxReason, item_ids: Sequence[UUID], counts: InboxCounts) -> None`, `publish_inbox_expiring(bus, *, count, labels, earliest_expires_at)`, and `InboxCounts(count: int, labels: int, waiting_for_sheet: int)`. The data never carries titles (B21).
- Produces in the repo: `bump_revision(session) -> int` (same transaction as the write) and `counts(session, now) -> InboxCounts` (`waiting_for_sheet` = the copies of lines whose `intended_printer_id` is a page printer).
- Produces settings: `inbox.freshness` enum (`snapshot`, `fresh`, `fresh_with_fallback`, default `fresh_with_fallback`); `inbox.max_items` 500; `inbox.expiry_days` 30; `inbox.expiry_warning_days` 3; `inbox.idempotency_days` 7. All have `env_field=None`.

- [ ] **Step 1: Write the failing tests.**
  - `test_line_hash_differs_on_best_before`: two snapshots that differ only in one secondary line hash differently.
  - `test_line_hash_differs_on_stock_id`.
  - `test_line_hash_stable_across_key_order`.
  - The migration test.
  - `test_stream_subscribes_inbox_for_read`: an `inbox.changed` published on the bus reaches a `read` stream.
  - `test_inbox_only_key_cannot_open_stream`: `403`.
  - `test_snapshot_frame_has_inbox_counts`.
- [ ] **Step 2: Run them.** Expected: import and collection errors.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify,** including the migration up, down and up.
- [ ] **Step 5: Commit** `feat(inbox): add the print inbox tables, revision counter and inbox event channel`.

### Task 4: Read, add, change and remove lines

**Files:**
- Create: `backend/app/schemas/inbox.py`, `backend/app/inbox/service.py`, `backend/app/inbox/dedupe.py`, `backend/app/api/routes/inbox.py` (router prefix `/api/v1/inbox`, registered in the app factory)
- Test: `backend/tests/unit/inbox/test_service.py`, `backend/tests/integration/api/test_inbox_api.py`

**Interfaces:**
- Consumes: Task 2 `require_inbox`, `require_read`, `require_print`, `caller_id`; Task 3 models, `line_hash`, the events, `counts`.
- Produces schemas:
  - `InboxItemIn`: `content_type`, `format?`, `copies` 1–10 default 1, `lookup?: PrintLookupRequest`, `data?: SheetRawLabelData`, `idempotency_key?` (1–128 printable ASCII). At least one of `lookup` or `data` is required. `format.kind == "designer_layout"` gives `422 format_not_supported`.
  - `InboxAddRequest`: `items` 1–50.
  - `InboxAddResponse`: `{revision, results: [{index, outcome: "parked"|"merged", item_id, duplicate}]}`, with **no snapshot field**.
  - `InboxItemRead`: §6.1 fields plus `expires_in_days`.
  - `InboxRead`: `{revision, items, limits, freshness, expiring_soon: {count, labels}, expired_recently: {count, labels, at} | null}`.
- Produces: `class InboxService` with `async add(session, items: Sequence[InboxItemIn], *, caller: str, origin: Origin, origin_detail: str | None, origin_event: str | None = None, intended_printer_id: UUID | None = None, now: datetime) -> InboxAddResponse`, `list(session, now) -> InboxRead`, `set_copies(session, item_id, version, copies)`, `remove(session, refs: Sequence[tuple[UUID,int]])`, `clear(session, revision)`. Every write holds `inbox_write_lock: asyncio.Lock` (module-level, one per process), bumps the revision in the same transaction, and publishes after the commit.
- Produces: `@dataclass ParsedEntry(source_app, item_ref: str | None, fmt: dict, snapshot: dict, snapshot_complete: bool, copies: int, item_meta: dict | None, idempotency_key: str | None, request_hash: str)` and `InboxService.add_entries(session, entries: Sequence[ParsedEntry], *, caller, origin, origin_detail, origin_event, intended_printer_id, now) -> InboxAddResponse`. `add` performs the lookups, builds the entries and calls `add_entries`; receivers that already hold the data (Task 15) call `add_entries` directly.
- Produces: `RecentRequests(window_s: float)` in `dedupe.py`, with `seen(caller, request_hash) -> InboxAddResponse | None` and `remember(...)`. Window 60 s here; Task 15 uses 10 s.
- Behaviour pinned by the spec:
  - The merge rule of §5.1 (same `line_hash` → copies added, clamped to 10, `version` + 1, `expires_at` unchanged).
  - All or nothing per request.
  - The limit counts the labels after a clamp (`409 inbox_full`).
  - `idempotency_conflict` names only the `index`.
  - Source down, with `data` present → park with `snapshot_complete=False` and call `InboxService.on_incomplete(item_id)` (a `Callable[[UUID], None]`, default no-op). Task 16 wires the real filler.
  - Reference only → `503 integration_unavailable` with `Retry-After: 30`.
  - Not found → `404 app-lookup-not-found` with `item_index`.
  - Expired lines are hidden from `list` before the sweep.
- Routes: `GET /api/v1/inbox` (`read`), `POST /api/v1/inbox/items` (`inbox`), `PATCH /api/v1/inbox/items/{id}`, `DELETE /api/v1/inbox/items/{id}?version=`, `POST /api/v1/inbox/remove`, `DELETE /api/v1/inbox` (all `print`). A stale version gives `409 inbox_item_changed` with the current lines in `error_detail`; a missing line gives `404 inbox_item_not_found`. Body ≤ 256 KiB → `413`.

- [ ] **Step 1: Write the failing tests** (the §14 "Enqueue", "Line identity", "Limits" and "Scope" bullets as named tests):
  - `test_lookup_add_stores_snapshot`.
  - `test_source_down_with_data_parks_incomplete`.
  - `test_source_down_reference_only_503_nothing_stored`. Counter-test: park reference-only items, and the test sees a line.
  - `test_data_only_is_manual`.
  - `test_same_key_twice_one_line_duplicate`.
  - `test_same_key_other_body_409_conflict_index_only`.
  - `test_key_reused_after_print_no_new_line`. Counter-test: delete the record on removal.
  - `test_no_key_60s_window`.
  - `test_same_product_equal_data_merges_copies_2`.
  - `test_other_best_before_two_lines`. Counter-test: merge on `(app, ref, format)`.
  - `test_label_per_unit_two_lines`.
  - `test_limit_counts_labels_not_lines`: 499 labels + 2 copies gives `409`, and nothing is stored. Counter-test: count lines.
  - `test_merge_clamps_and_limit_counts_after_clamp` (Review Focus 4).
  - `test_inbox_key_403_on_get_patch_delete`.
  - `test_read_key_adds_but_403_on_patch_remove`.
  - `test_enqueue_response_has_no_snapshot_raw_json`: assert on `response.text`.
  - `test_error_bodies_never_echo_title_or_key`.
  - `test_every_write_publishes_increasing_revision_without_title`.
  - `test_stale_version_409_with_current_lines`.
- [ ] **Step 2: Run them.** Expected: 404 (no route).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify,** with each counter-test.
- [ ] **Step 5: Commit** `feat(inbox): read, add, change and remove inbox lines with idempotency and limits`.

### Task 5: Freshness resolution, tape print from the inbox, `jobs.data_source`

**Files:**
- Create: `backend/app/inbox/resolve.py`, `backend/app/inbox/print_tape.py`, `backend/app/api/routes/inbox_print.py`, the migration `20261110a2`
- Modify: `backend/app/services/print_service.py` (`submit_labels`; `submit_batch_job` delegates to it), `backend/app/models/job.py` (`data_source: str | None`), `backend/app/schemas/job.py` (`JobRead.data_source`, `JobRead.printed_from_snapshot: bool`), `frontend/src/features/jobs/*` ("Printed from snapshot" badge, en + de)
- Test: `backend/tests/unit/inbox/test_resolve.py`, `backend/tests/integration/api/test_inbox_print_tape.py`, `backend/tests/integration/db/test_alembic_jobs_data_source.py`, a jobs list Vitest

**Interfaces:**
- Produces: `DataSource = Literal["fresh","snapshot","snapshot_fallback"]` and `@dataclass ResolvedLine(item: InboxItem, label: LabelData, data_source: DataSource | None, unavailable: bool)`.
- Produces: `async resolve_lines(items, *, freshness, lookup: AppLookupService, cache: LookupCache | None) -> list[ResolvedLine]`.
  - `snapshot`: no lookup.
  - `fresh`: on a failure or not-found, `unavailable=True`.
  - `fresh_with_fallback`: on `LookupFailedError`, `integration_not_configured` or not-found, the snapshot with `snapshot_fallback`.
  - `manual` lines always give `snapshot`.
  - The `LabelData` built from a snapshot keeps `source_app = item.source_app`.
  - At most 4 lookups in flight per app (B11).
- Produces: `LookupCache(ttl_s=60)`, which caches successes **and** failures per `(app, ref)` (C7). It is used by previews only; prints pass `cache=None` (B20).
- Produces: `@dataclass ResolvedLabel(content_type: ContentType, label: LabelData, copies: int, data_source: DataSource | None)` and `PrintService.submit_labels(labels: Sequence[ResolvedLabel], *, half_cut: bool) -> list[UUID]`. This is today's batch body; it writes `jobs.data_source` and the payload key `data_source`.
- Route: `POST /api/v1/inbox/print/{printer_key}` (`print`, printer ACL), body `{items: [{id, version}], half_cut_override}`. Response: `BatchResponse` + `data_sources: [{id, data_source}]`.
- Order:
  1. Take `inbox_write_lock`.
  2. Check the versions (a mismatch gives `409 inbox_item_changed`, nothing queued).
  3. More than 500 expanded labels gives `422 selection_too_large` with `{labels, max}`.
  4. An IPP printer gives `409 media_kind_mismatch`.
  5. Resolve (`fresh` + unavailable gives `502` with the integration's error, nothing printed).
  6. `submit_labels`.
  7. Delete the printed lines, set `released_at` on their idempotency rows, bump the revision, and publish `reason="printed"`. This step runs under the lock right after the queue accepted (see G2).

- [ ] **Step 1: Write the failing tests.**
  - `test_snapshot_mode_makes_no_lookup_call`: the mock's call count is 0.
  - `test_fallback_prints_snapshot_and_flags_job`: the client mock **was** called and the job row has `data_source == "snapshot_fallback"`.
  - `test_fallback_on_deleted_item`.
  - `test_fresh_source_down_502_nothing_printed_lines_unchanged`.
  - `test_print_removes_exactly_sent_lines`.
  - `test_print_after_concurrent_copies_edit_is_409` (Review Focus 1).
  - `test_selection_501_labels_422_nothing_queued`.
  - `test_job_payload_keeps_source_app_not_manual`.
  - `test_ipp_printer_409_media_kind_mismatch`.
  - `test_job_read_printed_from_snapshot`.
  - The migration test.
  - Vitest: the badge shows for `printed_from_snapshot`.
- [ ] **Step 2: Run them.** Expected: they fail.
- [ ] **Step 3: Implement.** `pnpm gen:api`.
- [ ] **Step 4: Verify.** Counter-test: skip the version check, and the concurrent-edit test prints.
- [ ] **Step 5: Commit** `feat(inbox): print inbox lines onto tape with the freshness setting and record the data source`.

### Task 6: Sheet preview and print from the inbox

**Files:**
- Create: `backend/app/inbox/print_sheet.py`
- Modify: `backend/app/api/routes/inbox_print.py` (two routes), `backend/app/schemas/inbox.py`
- Test: `backend/tests/integration/api/test_inbox_print_sheet.py`

**Interfaces:**
- Consumes: Task 5 `resolve_lines`, `LookupCache`; `app.sheets.print_service.preview(...)` and `print_sheets(...)`; `InsufficientCellsError.detail["free_cells"]`; `ItemContentMismatchError(index)`.
- Produces schemas:
  - `InboxSheetRequest`: `items [{id, version}]`, `placements` (as `PlacementInModel`), `tray`, `overflow: "next_sheet" | "refuse"` default `next_sheet`, `expected_cells`.
  - `InboxSheetPreview(SheetPreview)` adds `item_map: list[{inbox_item_id, copy, source_app, title}]` (per expanded item index), `next_sheet` (same shape), `not_printable: [{inbox_item_id, reason: "content_type_not_supported" | "unavailable"}]` and `data_sources`.
  - The print response is `SheetPrintResponse` plus the same three lists.
- Produces: `build_sheet_items(lines: Sequence[ResolvedLine]) -> list[SheetItem]`: one item per copy, in the order sent; raw `data`, `source = source_app`, `ref = item_ref`, `purpose = title`.
- Produces: `async plan_inbox_sheet(...) -> InboxSheetPlan`. The algorithm is not fixed by the signature, so here it is:
  1. Drop `unavailable` lines into `not_printable` (`unavailable`).
  2. Call `preview` on the expanded items. On `ItemContentMismatchError(index)`, move that item's **line** (all its copies) to `not_printable` (`content_type_not_supported`) and repeat. There are at most as many rounds as lines.
  3. On `InsufficientCellsError` with `overflow="next_sheet"`, keep the first `len(free_cells)` expanded items, move the rest to `next_sheet`, and repeat once. With `refuse`, re-raise.
  4. Never add a placement (C1).
- Routes: `POST /api/v1/inbox/sheet/preview/{printer_key}` (`read`) and `POST /api/v1/inbox/sheet/print/{printer_key}` (`print`). The print re-plans with `cache=None`, passes `expected_cells` (so `409 plan_changed` still applies), and removes only the lines whose copies were all queued. A line with some copies queued keeps the rest as copies, and its version is bumped. `502 print_interrupted` removes only the queued copies.

- [ ] **Step 1: Write the failing tests.**
  - `test_preview_maps_items_to_lines_and_copies`.
  - `test_overflow_lists_next_sheet_not_409`.
  - `test_overflow_refuse_keeps_409`.
  - `test_next_sheet_never_adds_a_placement`: spy on `print_sheets`, which gets exactly the sent placements.
  - `test_unrenderable_line_not_printable_others_print`.
  - `test_fresh_source_down_line_unavailable_others_render`.
  - `test_second_preview_within_60s_no_new_lookup_for_failed`.
  - `test_print_removes_placed_keeps_next_sheet_and_not_printable`.
  - `test_partial_print_removes_only_queued_copies`.
  - `test_sheet_print_ignores_line_added_after_preview` (Review Focus 2).
  - `test_sheet_print_501_labels_422`.
- [ ] **Step 2: Run them.** Expected: they fail.
- [ ] **Step 3: Implement.** `pnpm gen:api`.
- [ ] **Step 4: Verify.** Counter-test: let the mismatch re-raise, and the unrenderable test gets `422`.
- [ ] **Step 5: Commit** `feat(inbox): preview and print selected inbox lines onto a sheet with next-sheet leftovers`.

**PR 1 gate:** full backend gate, migrations up/down, `pnpm gen:api` + frontend gate, security audit on the changed surface (Task 2 first), then open the PR.

---

## PR 2 — inbox UI

### Task 7: The server cart and the localStorage migration

**Files:**
- Create: `frontend/src/features/inbox/api.ts`, `frontend/src/features/inbox/migrate.ts`, `backend/app/api/routes/inbox.py` (`POST /api/v1/inbox/import`)
- Modify: `frontend/src/features/lookup/cart.ts` (backed by the inbox; the `storage` sync is removed), `frontend/src/api/events.ts` (`inbox.changed`: invalidate `["inbox"]` when `revision` > cached), `CartPage.tsx`, `ItemView.tsx`, `IntegrationPage.tsx` (only if `useCart`'s shape forces it)
- Test: `frontend/src/features/inbox/api.test.ts`, `migrate.test.ts`, `cart.test.tsx` (rewritten), `backend/tests/integration/api/test_inbox_import.py`

**Interfaces:**
- Produces backend: `POST /api/v1/inbox/import` (`read`, B10), body `{device_id: str (8–64, [A-Za-z0-9-]), lines: [{app, id, name, content_type, copies}] ≤ 500}`. On a lookup failure it stores the snapshot `{title: name}` with `snapshot_complete=False`. The idempotency `scope_key` is `device:<device_id>:<app>:<id>` (C5) and `origin = ui`. The response is like `InboxAddResponse`.
- Produces frontend:
  - `useInbox(): UseQueryResult<InboxRead>` (key `["inbox"]`).
  - `useInboxMutations()` with `add`, `setCopies(id, version, copies)`, `remove(refs)` and `clear(revision)`. On a `409`, refetch.
  - `useCart()` keeps `{items, add, remove, setCopies, clear}`, and `items` become `InboxLine` (`CartItem` + `lineId`, `version`, `origin`, `snapshotComplete`, `expiresInDays`).
  - `print` moves to Task 8, where it takes ids.
  - `migrateLocalCart(fetcher): Promise<"none"|"done"|"failed">` uses the keys `lph.cart`, `lph.cart.migrated` and `lph.device`. It removes `lph.cart` only after a `2xx`.
- Copies edit: debounced 400 ms with the line's `version`; a `409` keeps the typed value with a note (B23).

- [ ] **Step 1: Write the failing tests.**
  - Vitest, migration: the lines are sent once with `<device>:<app>:<id>` keys; `lph.cart` is removed only after a `2xx` and kept on `500`; a second call is a no-op; a read-only session migrates.
  - Vitest, cart: `add` POSTs `/api/v1/inbox/items`; an `inbox.changed` with a newer revision refetches and an older one does not.
  - pytest: `test_import_lookup_failure_name_only_snapshot`, `test_import_twice_one_line`, `test_inbox_only_key_403_on_import`.
- [ ] **Step 2: Run them.** Expected: they fail.
- [ ] **Step 3: Implement.** `pnpm gen:api`. i18n: the note "N items from this browser could not be moved yet" (plural).
- [ ] **Step 4: Verify.** Counter-test: remove `lph.cart` before the response, and the error-path test turns red.
- [ ] **Step 5: Commit** `feat(ui): keep the cart in the server inbox and move local carts there once`.

### Task 8: Line selection and tape print by selection (UI)

**Files:**
- Create: `frontend/src/features/inbox/selection.ts`, `frontend/src/features/inbox/InboxList.tsx`
- Modify: `CartPage.tsx`, `lookup/cart.ts` (`print(printerKey, ids)` → `POST /api/v1/inbox/print/{key}`)
- Test: `selection.test.ts`, `InboxList.test.tsx`, `CartPage.test.tsx`

**Interfaces:**
- Produces:
  - `useSelection(lines: readonly InboxLine[]): { selected: ReadonlySet<string>; state: "none"|"some"|"all"; toggle(id); toggleAll(); clear(); }`.
  - Storage key `lph.inbox.selection` (a JSON array of ids), pruned to the existing ids on every inbox change.
  - With no stored key, everything is selected; ids that arrive later are not selected (B25).
  - `toggleAll()`: from `all` it clears, otherwise it selects all.
- `InboxList`: one tab stop with roving focus (arrow keys) and Space toggles (B24). A row click toggles, except on the name link, the copies field and Remove. Targets are at least 44 px. Read-only sessions get no copies, Remove or print, plus the note that printing needs a print key.
- Print button copy: "Print {n} of {total} labels"; when everything is selected, "Print {total} labels". It is disabled with nothing selected, and disabled with "At most 500 labels per print" above 500 (C3). Origin badge "from {app}" for `webhook`/`api`.

- [ ] **Step 1: Write the failing tests** (§14 frontend "Selection", "Selection storage", "Read-only"):
  - `select all, untick two → print body has exactly the remaining ids`.
  - `header states none/some/all`.
  - `header click when all clears`.
  - `clear selection button only with a selection`.
  - `space toggles focused row`.
  - `row click toggles, remove click does not`.
  - `selection survives reload`.
  - `pruned ids`.
  - `sse arrival is unselected` (Review Focus 2).
  - `selection never sent except print ids`: spy on `apiFetch` bodies.
  - `read-only: add and select work, no print/remove/copies`.
  - `501 labels disables with reason`.
  - `title <img onerror> renders as text`.
- [ ] **Step 2: Run them.** Expected: they fail.
- [ ] **Step 3: Implement** under the UI task protocol. Phone: a sticky bottom bar with the count, "Clear selection" and print, safe-area insets, 16 px input font.
- [ ] **Step 4: Verify,** including screenshots.
- [ ] **Step 5: Commit** `feat(ui): select inbox lines per device and print only the selection`.

### Task 9: Sheet preview from the selection, and scan to sheet (UI)

**Files:**
- Modify: `frontend/src/features/sheets/print/SheetSection.tsx` (props `lines`, `selected` instead of `items`; calls the inbox preview and print; the client-side leftover logic `:262-282` is removed because the server does it), `SheetPreview.tsx` (cell numbers on new cells, the list "Cell N → App · Name (k/n)", two-way highlight, the "Next sheet" and "Not printable on this sheet type" / "Source unreachable" groups, the "snapshot" marker), `frontend/src/features/sheets/resolver.ts`, `CartPage.tsx` (`?sheet=`: printer preselect; an empty inbox replaces the route with `/sheet/{code}`), and the colour token for cell numbers (`--color-cell-number` in the theme CSS, reused if #249 landed first; legend "1 = cell number (not printed)")
- Test: `SheetSection.test.tsx`, `SheetPreview.test.tsx`, `resolver.test.ts`

**Interfaces:**
- Consumes: Task 6 `InboxSheetPreview`.
- Produces: `sheetResolver.resolve(hit)` returns `/cart?sheet=<code>`, and the cart redirects to `/sheet/<code>` when `useInbox()` resolves to zero lines. That gives the same outcome as §11.4 B26 with a synchronous resolver. Printer preselect order: the page printer that last printed onto this sheet (from the sheet's API), else the first selected line's `intended_printer_id`, else the only usable page printer, else none.
- The preview rebuilds through the existing `useDebounced(PREVIEW_DEBOUNCE_MS)` on any change of the selection, copies or snapshot. The print button reads "Print {placed} of {selected} labels onto {code}". `next_sheet` lines stay selected after the print (B38).

- [ ] **Step 1: Write the failing tests.**
  - `selection change → one debounced preview with exactly the selected ids` (three quick changes, one request).
  - `next_sheet listed by name and count`.
  - `list entry and cell agree for each item`.
  - `hover entry highlights cell and the reverse; tap toggles on touch`.
  - `not_printable listed and excluded from print count`.
  - `resolver goes to cart; empty inbox redirects to sheet page`.
  - `preselect order`.
- [ ] **Step 2: Run them.** Expected: they fail.
- [ ] **Step 3: Implement** under the UI protocol, including `break-ui` with long names and 60 lines.
- [ ] **Step 4: Verify.** Add a Playwright e2e `inbox-sheet.spec.ts`: a line parked through the API with an IPP intended printer, scan the sheet code, `/cart?sheet=…` with the preview, print, the line is gone and the cells are used; a partial print leaves the unselected lines after a reload.
- [ ] **Step 5: Commit** `feat(ui): preview the selected inbox lines on the scanned sheet`.

### Task 10: Expiry sweep, waiting-for-sheet count and notices

**Files:**
- Create: `backend/app/inbox/sweep.py`
- Modify: `backend/app/services/cleanup_task.py` (generic `extra_sweeps: Sequence[Callable[[], Awaitable[int]]]` run after the session purge), `backend/app/main.py` (pass the inbox sweep), `frontend/src/shell/TopBar.tsx` (count on the cart link), `CartPage.tsx` (banners and the "Expires in N days" badge)
- Test: `backend/tests/unit/inbox/test_sweep.py`, `TopBar.test.tsx`, `CartPage.test.tsx`

**Interfaces:**
- Produces: `async sweep_inbox(session_factory, bus, *, now: datetime) -> int`.
  1. Mark lines with `expires_at - now ≤ inbox.expiry_warning_days` and `expiry_warned_at IS NULL`, and publish **one** `inbox.expiring` when any were marked.
  2. Delete the expired lines, write `inbox_state.last_expired_*`, and publish `inbox.changed reason="expired"` with the ids.
  3. Delete idempotency rows whose `released_at < now - inbox.idempotency_days`.
- Interim, because #255 is not built: the top bar shows `waiting_for_sheet` on the cart link (hidden at 0). The cart shows a warning banner "N labels expire in 3 days or less" from `expiring_soon`, and "N labels expired and were removed" from `expired_recently`, dismissed per device through `lph.inbox.expiredSeen` = `at` (see G4).

- [ ] **Step 1: Write the failing tests.**
  - `test_warning_raised_once_not_daily_again` (two sweeps a day apart, one event).
  - `test_expired_removed_with_notice`.
  - `test_no_line_disappears_without_warning_or_notice`: a time-travel run over 31 days asserts both events for the line.
  - `test_idempotency_rows_kept_7_days_after_release`.
  - Vitest: the count badge follows `inbox.changed`; the banner shows and is dismissed per device; the expiry badge.
- [ ] **Step 2: Run them.** Expected: they fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify.** Counter-test: drop the `expiry_warned_at` check, and the "once" test sees two events.
- [ ] **Step 5: Commit** `feat(inbox): warn before inbox lines expire, remove them with a notice, show the waiting count`.

### Task 11: Refresh and accept (backend)

**Files:**
- Create: the migration `20261110a3` (`inbox_refreshes(id, created_at, expires_at)` and `inbox_refresh_items(refresh_id, item_id, item_version, status, candidate JSON)`), `backend/app/inbox/refresh.py`, `backend/app/api/routes/inbox_refresh.py`
- Test: `backend/tests/unit/inbox/test_refresh_diff.py`, `backend/tests/integration/api/test_inbox_refresh.py`

**Interfaces:**
- Produces: `diff_snapshots(before: dict, after: dict) -> list[FieldChange(field, before, after)]`. Paths are `title`, `primary_id`, `qr_payload`, `secondary[i]`, `items[i].item`, `items[i].qr_payload`, and only changed paths are listed.
- Produces routes (§6.4):
  - `POST /api/v1/inbox/refresh` (`print`): an in-process `refresh_lock`, held → `409 refresh_running`; 4 lookups per app; `expires_at` = +15 min.
  - `GET /api/v1/inbox/refresh/{rid}/items/{iid}/render?side=&printer=&sheet_type=` (`read`): a PNG through the render path of `POST /api/v1/render/preview`; for an IPP `printer`, one cell of `sheet_type` (required then, `422` without it) through `DEFAULT_CELL_RENDERER` (B12; see G6).
  - `POST /api/v1/inbox/refresh/{rid}/accept` (`print`).
  - The errors `409 inbox_item_changed` (nothing written), `409 refresh_expired`, `404 refresh_not_found` and `422 not_changed`. Accept publishes `reason="accepted"`.
- Refresh rows expire through `sweep_inbox` (Task 10 gets one more delete).

- [ ] **Step 1: Write the failing tests.**
  - `test_refresh_writes_no_snapshot` (rows before and after are equal).
  - `test_diff_one_changed_field_one_entry`.
  - `test_accept_all_writes_only_changed`.
  - `test_accept_after_copies_edit_409_nothing_written`. Counter-test: skip the version check.
  - `test_expired_refresh_409`.
  - `test_manual_lines_unchanged`.
  - `test_deleted_vs_unavailable`.
  - `test_second_refresh_409_running`.
  - `test_render_before_after_png`.
- [ ] **Step 2: Run them.** Expected: they fail.
- [ ] **Step 3: Implement.** `pnpm gen:api`.
- [ ] **Step 4: Verify,** including the migration test.
- [ ] **Step 5: Commit** `feat(inbox): refresh inbox data for review and accept changes under a version guard`.

### Task 12: Refresh and diff (UI)

**Files:**
- Create: `frontend/src/features/inbox/RefreshPanel.tsx`, `DiffView.tsx`, `fieldNames.ts`
- Modify: `CartPage.tsx`, `InboxList.tsx` (the badges "Changed", "Source unreachable" and "Deleted at source")
- Test: `RefreshPanel.test.tsx`, `DiffView.test.tsx`, `fieldNames.test.ts`

**Interfaces:**
- Produces: `fieldLabel(app: string, path: string, t): string`, a fixed mapping per app (B27): `title` → "Name", `primary_id` → "Code", `secondary[*]` → per app (Grocy: best before, amount, location, note), and an unknown path shows itself.
- Summary copy: "{changed} of {total} changed · {n} unreachable · {n} deleted at the source". Each line has "Accept" / "Keep"; at the top, "Accept all changes" (`{all: true}`, no confirmation) and "Keep all" (client-only). Before and after sit side by side, stacked below 640 px, and the diff view is a full-height sheet on phones. A `409` shows "This item changed since the refresh. Refresh again." with the button. There is one sentence per freshness mode (§11.5). Values wrap with `overflow-wrap:anywhere`.

- [ ] **Step 1: Write the failing tests:** the summary counts; the diff shows only the changed fields; accept-all sends `all: true`; a 409 shows the refresh-again note; the preview query is invalidated after accept; a taint title renders as text in the diff.
- [ ] **Step 2: Run them.** Expected: they fail.
- [ ] **Step 3: Implement** under the UI protocol.
- [ ] **Step 4: Verify.** Add a Playwright e2e: two browser contexts, an add on one appears on the other without a reload; screenshots of the cart, the preview and the diff.
- [ ] **Step 5: Commit** `feat(ui): review refreshed inbox data side by side and accept or keep each change`.

**PR 2 gate:** the full gate on both sides, e2e, and the security audit on the import route and the UI taint surface.

---

## PR 3 — integrations

### Task 13: Event rules (backend)

**Files:**
- Create: the migration `20261110a4` (`integration_event_defaults`, `integration_event_rules` per §7.1), `backend/app/models/event_rules.py`, `backend/app/inbox/rules.py`, `backend/app/api/routes/event_rules.py`
- Test: `backend/tests/unit/inbox/test_rules.py`, `backend/tests/integration/api/test_event_rules_api.py`

**Interfaces:**
- Produces: `KNOWN_EVENTS: dict[str, tuple[EventPreset, ...]]` holding Grocy (`grocy.product`, `grocy.stock_entry`, both `park`) and Spoolman (`spoolman.created`, `spoolman.updated`, both `park`; any other payload `type` is unknown and therefore `none`, §7.1). The Kept preset (§7.1) is defined in code but **not seeded** until #173. `ensure_presets(session)` runs on startup and creates the missing rows; the default format is `{"kind":"content_type","content_type":"qr_two_lines"}`.
- Produces: `@dataclass CallOverride(printer: str | None, mode: Literal["print","collect"] | None)`, `@dataclass Decision(action: Literal["ignored","park","print"], printer: Printer | None, fmt: dict, reason: str | None)`, and `async evaluate(session, *, integration: str, event_type: str, override: CallOverride | None, auth: AuthContext) -> Decision`. These are rules 1–6 of §7.2 plus the B33 bounds:
  - An override never enables a `none` rule.
  - `mode=print` needs `print` on that printer, else `park` with `reason="key_cannot_print"`.
  - A page printer always parks.
  - An offline or disabled printer parks with `reason="printer_unavailable"` and logs a warning.
  - An unknown event type is `ignored` and logged once per process.
- Routes: `GET/PUT /api/v1/integrations/{name}/event-rules` (`admin`). `PUT` refuses `print` with an IPP target (`422 page_printer_always_parks`) and `designer_layout` (`422 format_not_supported`).

- [ ] **Step 1: Write the failing tests:** `test_fresh_integration_has_presets_none_print`, `test_none_ignored`, `test_event_printer_and_format_override_default`, `test_print_onto_ipp_parks`, `test_offline_tape_printer_parks_with_reason`, `test_unknown_event_ignored`, `test_designer_layout_422`, `test_mode_print_never_enables_none` (counter-test: let `mode` win and it turns red), `test_mode_print_inbox_key_parks_key_cannot_print`, `test_put_print_with_ipp_422`.
- [ ] **Step 2: Run them.** Expected: they fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify,** with the migration test.
- [ ] **Step 5: Commit** `feat(integrations): add user-defined event rules per integration and event type`.

### Task 14: Webhook call log (backend, security)

**Files:**
- Create: the migration `20261110a5` (`webhook_calls`, fields per §8.4 plus `replay_of: UUID | None`), `backend/app/models/webhook_call.py`, `backend/app/inbox/webhook_log.py`, `backend/app/api/routes/admin_webhook_calls.py`
- Modify: `backend/app/main.py` (install the middleware and the access-log filter), `cleanup_task` wiring (prune sweep)
- Test: `backend/tests/unit/inbox/test_webhook_redaction.py`, `backend/tests/integration/api/test_webhook_call_log.py`

**Interfaces:**
- Produces:
  - `redact(value: Any) -> Any`: recursive; keys equal to or ending in `token`, `key`, `secret`, `signature` or `password` (case-insensitive) become `"[redacted]"`.
  - `redact_query(qs: str) -> str`: drops `token`.
  - `bounded_payload(raw: bytes, content_type, *, limit: int) -> tuple[Any, bool]`: parses form or JSON, falls back to text, and the bool is "truncated".
- Produces: `class WebhookLogMiddleware` (pure ASGI). It covers paths under `/api/v1/webhook/` and `POST /api/v1/inbox/items` when `X-Label-Hub-Key` is present. It captures the body (up to 64 KiB), the status and the duration, and writes one record in a short session after the response. The handler adds details through `current_call: ContextVar[CallNote | None]` with `CallNote(integration, event_type, key_id, key_name, outcome, reason, inbox_item_id, job_id)`. A call without `key_id` that ends `401`/`403` keeps at most 2 KiB of payload.
- Produces: `class StripQueryForWebhooks(logging.Filter)` on the `uvicorn.access` logger, which removes the query string for `/api/v1/webhook/` paths.
- Produces: `async prune_webhook_calls(session_factory, *, now) -> int` (14 days **or** 2,000 newest, whichever is fewer).
- Routes (`admin`): `GET /api/v1/admin/webhook-calls?integration=&outcome=&since=&until=&cursor=` (newest first, 50 per page; the final status is joined live from the inbox line or job: `parked`, `printed`, `failed: <reason>`, `expired` or `removed`), `GET …/{id}`, and `POST …/{id}/replay`. Replay is allowed only for `outcome="rejected"` with `reason ∈ {"integration_not_configured","no_tape_printer"}`, else `422 not_replayable`. It re-runs the handler with the stored payload under the original key id and links `replay_of`.

- [ ] **Step 1: Write the failing tests** (§8.4 tests):
  - `test_token_in_query_or_body_never_stored`. Counter-test: no-op `redact`, and the test turns red.
  - `test_rejected_401_logged_without_key_id`.
  - `test_final_status_follows_line_to_printed`.
  - `test_prune_respects_both_limits`.
  - `test_unauthenticated_payload_capped_2kib`.
  - `test_access_log_has_no_query_for_webhooks` (`caplog` on `uvicorn.access`).
  - `test_read_and_inbox_keys_403_on_log`.
  - `test_ui_session_inbox_add_not_logged`.
  - `test_replay_only_config_rejections`.
- [ ] **Step 2: Run them.** Expected: they fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify,** including the counter-test and the migration test.
- [ ] **Step 5: Commit** `feat(webhooks): log every webhook call with built-in redaction and admin-only access`.

### Task 15: Grocy label route in Grocy's own format (security)

**Files:**
- Create: `backend/app/schemas/grocy_label.py`, `backend/app/inbox/grocy_label.py`, `backend/app/api/routes/webhook_grocy_label.py`; fixtures `backend/tests/fixtures/grocy_label/{product_form.txt, stock_entry_form.txt, stock_entry.json, no_details.json}`, built from Grocy 4.5's `WebhookRunner.php` / `GetProductDetails` field shapes as cited in §8.1
- Modify: `webhooks.py` (delete the `/grocy` handler and `GrocyWebhookPayload`), `settings_store/registry.py` (`integrations.grocy.webhook_cors_origin`, str, default `""`), `test_route_auth_coverage_guardrail.py` (allow-list entry: "authenticates the token inside the handler, Grocy cannot send headers")
- Test: `backend/tests/unit/inbox/test_grocy_mapping.py`, `backend/tests/integration/api/test_webhook_grocy_label.py`

**Interfaces:**
- Produces: `GrocyLabelPayload` (`extra="ignore"`): `product: str | None`, `grocycode: str | None`, `due_date: str | None` (never parsed), `details: dict | None`, `stock_entry: GrocyStockEntry | None` (`amount`, `best_before_date`, `location_id`, `note`, `stock_id`, rest ignored), `token: str | None`, `printer: str | None`, `mode: Literal["print","collect"] | None`. The parser takes form-encoded **and** JSON. With repeated form keys, the last one wins.
- Produces: `map_grocy_label(p: GrocyLabelPayload, *, language: Literal["en","de"]) -> GrocyMapped(snapshot: SheetRawLabelData, item_ref: str, event_type: str, item_meta: dict)`.
  - Field mapping per §8.1.2.
  - Best-before copy: en `"Best before {YYYY-MM-DD}"`, de `"MHD {DD.MM.YYYY}"`. `2999-12-31` is omitted.
  - Amount: `"{amount} {unit}"`, where the unit is singular or plural from `details.quantity_unit_stock.name` / `name_plural`.
  - Location: `details.location.name`. Note: `stock_entry.note`.
  - Every value is bounded and truncated to the `SheetRawLabelData` limits, never refused.
- Route `POST /api/v1/webhook/grocy/label`, in this order:
  1. Body ≤ 64 KiB, else `413`.
  2. Parse.
  3. Token from the query `token`, else the body field: unknown → `401` with a fixed message; `admin` capability → `403 token_scope_too_broad`.
  4. `evaluate(...)` (Task 13).
  5. Park through `InboxService.add_entries` (`origin=webhook`, `origin_detail="grocy"`, `origin_event`, `intended_printer_id`), or print through `submit_label` (Task 1) with the payload data and the rule's format.
  6. Answer `200 {outcome, item_id?, job_id?, reason?}`.
  - **The route never calls the Grocy plugin** (enrichment is Task 16).
  - Dedupe with `RecentRequests(10)` over `(key id, request hash)` (B35).
  - CORS: `OPTIONS /api/v1/webhook/grocy/label` answers only when `Origin` equals the setting (`POST`, no credentials, `Access-Control-Allow-Headers: content-type`); the `POST` adds `Access-Control-Allow-Origin` under the same condition.
  - Fill `current_call` (Task 14). The token never goes into logs, error bodies or idempotency rows.

- [ ] **Step 1: Write the failing tests** (§14 "Grocy label route"):
  - `test_mapping_product_and_stock_entry_fixtures`.
  - `test_token_in_query_and_in_body`.
  - `test_no_header_needed`.
  - `test_route_never_calls_grocy_plugin`: zero calls on the plugin mock.
  - `test_answers_within_budget_with_plugin_hanging` (< 0.5 s with the mock hanging). Counter-test: a synchronous lookup.
  - `test_identical_within_10s_duplicate`.
  - `test_admin_token_403`.
  - `test_mode_print_inbox_key_parks_reason`.
  - `test_mode_print_page_printer_parks`.
  - `test_token_never_in_caplog_or_body`.
  - `test_cors_only_configured_origin`.
  - `test_old_grocy_route_404`.
  - `test_grocy_label_awkward_payloads_park` (Review Focus 3).
- [ ] **Step 2: Run them.** Expected: they fail.
- [ ] **Step 3: Implement.** `pnpm gen:api`.
- [ ] **Step 4: Verify,** with the counter-tests.
- [ ] **Step 5: Commit** `feat(webhooks): accept Grocy's label webhook as it is and park or print by event rule`, then a separate `refactor(webhooks): remove the unused JSON Grocy webhook` (release notes point to `/grocy/label`).

### Task 16: Background fill for incomplete lines (Grocy enrichment and generic retry)

**Files:**
- Create: `backend/app/inbox/fill.py`
- Modify: `backend/app/integrations/grocy/plugin.py` (`enrichment(...)`), `InboxService.on_incomplete` wiring in `main.py` (task set on `app.state`, cancelled on shutdown)
- Test: `backend/tests/unit/inbox/test_fill.py`, `backend/tests/unit/integrations/test_grocy_enrichment.py`

**Interfaces:**
- Produces: `GrocyPlugin.enrichment(location_id: int | None, product_group_id: int | None, shopping_location_id: int | None, product_id: int | None) -> GrocyEnrichment(location_name, product_group_name, shopping_location_name, userfields: dict, picture_file_name)`, read from Grocy's `/objects/{entity}/{id}` and `/userfields/products/{id}`, with the plugin's timeout.
- Produces: `class IncompleteFiller` with `schedule(item_id)`. It runs at most 2 at a time and retries at 1, 5 and 30 minutes, then stops. Each run reads the line, fills (Grocy: the location line from `location_name`, the rest into `item_meta` per B40; other apps: a plain `lookup` that replaces the snapshot), and writes only if `version` is unchanged; then `snapshot_complete=True`, `version` + 1, and publish `updated`. If the plugin is not configured, it does nothing.

- [ ] **Step 1: Write the failing tests:** `test_fill_replaces_location_line_and_marks_complete`, `test_fill_skips_when_version_changed` (counter-test: drop the version check), `test_fill_unconfigured_plugin_leaves_line_printable`, `test_generic_incomplete_filled_when_source_back`.
- [ ] **Step 2: Run them.** Expected: they fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify.**
- [ ] **Step 5: Commit** `feat(inbox): fill incomplete inbox lines in the background under a version guard`.

### Task 17: Spoolman webhook through event rules

**Files:**
- Modify: `backend/app/api/routes/webhooks.py` (Spoolman: also accept `X-Label-Hub-Key` with `inbox`+; `evaluate` per `spoolman.<type>`; park or print or ignore; dedupe through `Idempotency-Key` or a 60 s window over `(app, spool_id, type)`; `quantity` is not copies; the shared secret `access.webhook_api_key` gets a fixed limit of 60 requests per minute through `rate_limiter`, B29), `backend/app/schemas/webhook.py` (`WebhookOutcomeResponse {outcome, item_id?, job_id?, reason?}`, `202`), docstrings and OpenAPI text per #188's acceptance
- Test: `test_webhooks_routes.py`, `backend/tests/integration/api/test_webhook_spoolman_rules.py`

**Interfaces:**
- Consumes: Task 13 `evaluate`, Task 4 `InboxService.add`, Task 1 `submit_label`.

- [ ] **Step 1: Write the failing tests:** `test_default_parks`, `test_rule_print_reaches_queue_and_prints`, `test_ipp_target_parks`, `test_hub_key_inbox_scope_accepted`, `test_quantity_not_copies`, `test_shared_secret_61st_request_429`, `test_idempotency_header_dedupes`, `test_response_keeps_job_id_name`.
- [ ] **Step 2: Run them.** Expected: they fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify.** Counter-test: skip `evaluate` (print always), and `test_default_parks` turns red.
- [ ] **Step 5: Commit** `feat(webhooks): route Spoolman events through the event rules and park by default`.

### Task 18: Event rules UI and the Grocy setup panel

**Files:**
- Create: `frontend/src/features/settings/EventRules.tsx`, `GrocyWebhookPanel.tsx`, `backend/app/api/routes/grocy_setup.py`
- Modify: `frontend/src/features/settings/Integrations.tsx`
- Test: `EventRules.test.tsx`, `GrocyWebhookPanel.test.tsx`, `backend/tests/integration/api/test_grocy_setup.py`

**Interfaces:**
- Produces backend (`admin`):
  - `GET /api/v1/integrations/grocy/label-webhook` → `{url: "<general.public_url>/api/v1/webhook/grocy/label", cors_origin, last_call: {received_at, outcome, event_type} | null}`. `last_call` is the newest Task 14 record.
  - `POST /api/v1/integrations/grocy/label-test` runs the Task 15 code path with a fixed sample payload (product "Sample product", grocycode `grcy:p:0:test`) under an internal caller `test`, and returns the outcome.
- Produces frontend:
  - "Incoming events": the integration default (target "Collect in the print inbox" or a printer; format) and one row per event type (action, printer or default, format or default), with the note "A page printer always collects". The page refuses to save `print` + IPP.
  - The Grocy panel: the URL with Copy; "Create a Grocy key" (`POST /api/v1/admin/api-keys {name:"grocy", scopes:["inbox"]}`, the value shown once, then the URL with `?token=`); the configuration block (`LABEL_PRINTER_WEBHOOK`, `LABEL_PRINTER_RUN_SERVER=true`, `LABEL_PRINTER_HOOK_JSON=true`, `FEATURE_FLAG_LABEL_PRINTER=true`) with the server-mode note; "Send test label"; "Last call received".

- [ ] **Step 1: Write the failing tests:** `test_panel_url_uses_public_url_not_host` (a request with another `Host`); `test_test_label_parks_with_default_rule`; Vitest: the key value appears only after create and not after a reload; the rule row saves; `print` + IPP is blocked with the reason.
- [ ] **Step 2: Run them.** Expected: they fail.
- [ ] **Step 3: Implement** under the UI protocol (i18n en + de).
- [ ] **Step 4: Verify.**
- [ ] **Step 5: Commit** `feat(ui): configure incoming event rules and the Grocy label webhook in the settings`.

### Task 19: Webhook log UI

**Files:**
- Create: `frontend/src/features/settings/WebhookLog.tsx`, `WebhookCallDetail.tsx`
- Modify: the settings sections and the integration page (filtered view)
- Test: `WebhookLog.test.tsx`

- [ ] **Step 1: Write the failing tests:** the table columns (time, integration, event, source, outcome, final status, duration); rejected rows are highlighted; the filters change the query string; the detail shows the payload in a `<pre>` as text (a taint payload `<img onerror>` is not markup); Replay is shown only for replayable records; non-admin sessions do not see the page.
- [ ] **Step 2: Run them.** Expected: they fail.
- [ ] **Step 3: Implement** under the UI protocol.
- [ ] **Step 4: Verify.**
- [ ] **Step 5: Commit** `feat(ui): show the webhook call log with payload detail and replay`.

### Task 20: Docs, decision register and release notes

**Files:**
- Modify: `README.md`, `docs/` (API keys: `inbox` scope; integrations: Grocy label webhook setup and the token warning; webhooks; the print inbox), `docs/decisions/register.md` (four rows from §15, with D-numbers assigned at merge), and the release notes source used by the release workflow (§16 text)
- Test: none (docs). The docs link check, if the repo has one, must pass.

- [ ] **Step 1:** Write the docs and the four register rows ("The cart is a server-side print inbox; selection stays per device", "Parked items always store a snapshot; `inbox.freshness` decides which source prints", "Scope `inbox` may only enqueue", "Page printers always park").
- [ ] **Step 2:** The release notes per §16: the cart moves on first visit; read-only can add and select; webhook `outcome`; old `/api/v1/webhook/grocy` gone; `LABEL_PRINTER_WEBHOOK=…/api/v1/webhook/grocy/label?token=…`; server mode recommended; the single setting for "print now".
- [ ] **Step 3: Commit** `docs: document the print inbox, the inbox scope and the Grocy label webhook`.

**PR 3 gate:** the full gate, e2e, and the security audit with focus on Tasks 14–16 (token taint, redaction, CORS, unauthenticated flood). Then release 1.6.x through `workflow_dispatch`.

---

## Spec gaps found while planning (not fixed in the spec)

- **G1** §5.1 has no column for the `stock_id` "metadata" of §8.1.2. The plan adds `inbox_items.item_meta` (JSON), and `line_hash` includes `stock_id`.
- **G2** §6.5 says printed lines are removed "in the same transaction that accepts the print". `JobStore` writes jobs in its own sessions, so one DB transaction is not possible. The plan removes the lines under the inbox write lock immediately after the queue accepted. A crash in between leaves a printed line in the inbox, and can never lose an unprinted one.
- **G3** `jobs.data_source` (§9) is one value per job, but a sheet page job holds several lines. The plan stores the worst value of the page (`snapshot_fallback` > `snapshot` > `fresh`) on the row and the per-cell value in the page payload.
- **G4** "N labels expired and were removed … stays until read" (§10) has no store without #255. The plan keeps the last expiry summary in `inbox_state` and the read mark per device in `lph.inbox.expiredSeen`.
- **G5** §11.4 has the sheet resolver decide on the inbox count, but `ScanResolver.resolve` is synchronous. The plan always resolves to `/cart?sheet=`, and the cart redirects to the sheet page when the inbox is empty. The outcome is the same.
- **G6** The render route of §6.4 renders "one cell of the sheet type the cart has selected", but it takes only `side` and `printer`, and the server does not know the cart's selected sheet type. The plan adds the query parameter `sheet_type`, which is required for page printers.
