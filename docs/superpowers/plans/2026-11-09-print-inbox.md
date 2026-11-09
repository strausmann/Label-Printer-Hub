# Print Inbox — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-browser cart with a server-side print inbox that every device shares and other apps can fill. Parked items are printed by selection onto tape or onto a scanned label sheet, with data freshness, refresh/diff, user-defined event rules, a Grocy-format label webhook and a webhook call log (#27). The work starts with the fix for #188.

**Architecture:** A new `app/inbox/` package in the style of `app/sheets/` holds the service, the freshness resolver, the print adapters, refresh, the event rules and the webhook log. Routes live under `/api/v1/inbox`, `/api/v1/integrations/{name}/…`, `/api/v1/webhook/grocy/label` and `/api/v1/admin/webhook-calls`. Tape prints go through one helper that is shared with the batch route, built on `PrintService.submit_labels`, which takes resolved `LabelData`. Sheet prints build a raw-data `SheetPrintRequest` and reuse `app.sheets.print_service`. Auth moves from one effective scope to a capability set, which adds the `inbox` capability. No network call or render runs under the inbox lock. The frontend keeps the shape of `useCart()` on top of a TanStack Query inbox that `inbox.changed` events keep current. The selection stays in `localStorage`.

**Tech Stack:** FastAPI / Starlette, SQLModel + SQLite, Alembic, asyncio, pytest; React + Vite, TanStack Query/Router, react-aria-components, lingui, Vitest + jsdom, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-09-print-inbox-design.md`. It is approved. These are binding: decisions 1–17 (§4), builder's calls B1–B41, and controller's calls C1–C16. C11–C16 were added after the plan review on 2026-11-09. Read the spec alongside this plan; "§n" refers to its sections.

**Base:** this plan starts on `main` after 1.5.0 is merged (#224–#231: `/api/v1` paths, `PrinterRuntime`). It expects Alembic head `20261109b1` (`printer_identity`, from the 1.5.0 plan, Task 14). At the time of the review the 1.5.0 branch was still at `20261108a1`. So before Task 1, run `alembic heads`, set the `down_revision` of Task 3 to the real head, and keep the chain linear. **Branching:** each PR targets the inbox's integration branch, `milestone/<version>`. The milestone is not set yet. No release is cut from the milestone branch before PR 3 is merged. Task 1 alone would make Spoolman webhooks print again, and Task 18 brings back the default "park".

## Revision 2: response to the plan review (2026-11-09)

The review of `f39acdd` (report `inbox-plan-review.md`) found 3 critical, 10 important and 20 minor issues. Each row below says where an issue was handled.

| Finding | Disposition |
|---|---|
| C-1: the next-sheet algorithm read `free_cells` wrongly | Task 6. It keeps `sum(free_cells)` items, truncates `count`/`cells` per placement, drops placements with no capacity, and tests ≥2 free cells and an explicit `count` |
| C-2: Grocy webhook lines could not be looked up again | C11 (spec §5.1, §8.1.2, §9). `item_ref` holds the product id; the grocycode and `stock_id` go into `item_meta`. A Grocy line resolver (new Task 16) reads the product and the stock entry and keeps the grocycode. The freshness test asserts `data_source == "fresh"` |
| C-3: the global lock was held across lookups and renders | C12 (spec §6.5). Lines are copied under the lock; lookups and renders run outside it; printed lines are removed under a brief second lock by version. Tests in Tasks 5, 6 and 15 cover an add or a Grocy call during a slow print |
| I-1: new routes echoed input in 422 bodies | Global Constraints, plus Tasks 4, 13, 14 and 19. `answers_with_envelope` gets the new prefixes, and each prefix has a marker test |
| I-2: the access-log test could not turn red | C13, Task 14. A unit test feeds a real uvicorn-shaped `LogRecord`; a subprocess test runs real uvicorn with the Dockerfile `CMD` arguments. Task 21 docs and Task 19 panel recommend the body field |
| I-3: a flood could grow the call log without bound | C14, Task 14. The 2,000-row cap and the 2 KiB cap hold at write time; a test sends 2,100 calls without a sweep |
| I-4: Grocy's form bodies use PHP bracket notation | C16, Task 15. A `parse_php_form()` decoder; the form fixtures use `http_build_query` encoding; a form stock entry maps to `grocy.stock_entry` |
| I-5: tape print needs more than `submit_labels` | Task 5. `dispatch_resolved_batch()` is shared by the batch route and the inbox route; it writes the `PrintBatch` row and keeps one error map |
| I-6: G3 could not be built from Task 6's files | Task 6. `print_sheets(..., item_data_sources=…)` in `app/sheets/print_service.py` writes the worst value per page row and the value per cell into the payload; test added |
| I-7: `AuthContext` call sites and the fake-auth fixture would break | Task 2. `capabilities` defaults from `scope` through a validator; the fixture also overrides `require_inbox`; the `scope_deps` docstring is updated |
| I-8: no read-only browser session can exist | C15 (spec §12.1). Read-key sign-in stays refused. The UI keys on "the session has no `print`", tested with a simulated session. Read-key sign-in is listed as a follow-up. `auth_session.py` is in Task 2 |
| I-9: no settings UI for the `inbox.*` settings | Task 10 adds the "Print inbox" settings section; Task 19 adds the Grocy CORS origin field |
| I-10: a Task 4 test needed Task 5 | Task 4 tests reuse after removal; Task 5 tests reuse after print |
| Minor 1 (names) | fixed: `_SYNC_ERROR_MAP`, `detail["item_index"]` |
| Minor 2 (Task 1 expected failure, recovery test) | fixed: retry answers `409 invalid-job-state`; restart-recovery test added |
| Minor 3 (`webhook` caller, `evaluate` without auth) | fixed: Task 2 `caller_id`; Task 13 `evaluate(..., auth: AuthContext \| None)`, where `None` = shared secret with `{inbox, print}` and no printer restriction |
| Minor 4 (§6.2 details) | fixed in Task 4: `Idempotency-Key` header, order, three named error tests |
| Minor 5 (`OPTIONS` route in the allow-list) | fixed in Task 15 |
| Minor 6 (`__init__.py`) | fixed: Global Constraints |
| Minor 7 (scope validation, test via DB edit) | fixed in Task 2 |
| Minor 8 (`cli.py`) | fixed in Task 2 |
| Minor 9 (lock lifetime) | fixed: the locks live on `app.state`, created in the lifespan |
| Minor 10 (Task 7 intermediate state) | fixed: a `legacyPrint` shim stays until Task 9 |
| Minor 11 (`snapshot_hash` vs `line_hash`) | fixed: the column `snapshot_hash` holds the hash of the snapshot only; `merge_key()` is separate (spec §5.1 amended) |
| Minor 12 (Task 15 omissions) | fixed: `snapshot_complete=False` + `on_incomplete`, the `next_due_date` fallback |
| Minor 13 (UI protocol for Tasks 5, 7) | fixed |
| Minor 14 ("the response sent") | fixed: `response_body` field (≤ 2 KiB, the hub's own answer) |
| Minor 15 (replay on redacted data) | fixed: `redacted_paths` is stored; replay is refused when a redaction touched a non-auth field |
| Minor 16 (paste an existing Grocy key) | fixed in Task 19 |
| Minor 17 (releases between PRs) | fixed: the Base paragraph |
| Minor 18 (body caps while reading) | fixed: `read_capped_body()` in Task 4 |
| Minor 19 (counter-tests per redaction path) | fixed in Task 14 |
| Minor 20 (`current_call` handoff) | fixed in Task 14: a mutable note set by the middleware; a failed log write never fails the request |

**Follow-up, not built (C15):** allow `read` keys to sign in to the browser, which would make the read-only UI of decision 15 reachable outside tests. This is a separate, security-relevant change with its own issue.

## Global Constraints

- **Repo rules.** The repo is public: identifiers, comments, docs and commits are in English, using Conventional Commits. Author is `bjoern@strausmann.net`, with **no AI attribution** (no `Co-Authored-By: Claude`, no session trailer, no "Generated with" footer). Never `git add -A`: stage explicit paths and run `git status --short` before each commit. Commit bodies end with `Refs #27`; Task 1 uses `Fixes #188`.
- **Release stays 1.x.** Commits use `feat`/`fix`/`refactor`/`test`/`docs`, and there is **no `BREAKING CHANGE:` footer and no `!`**, also for the removal of the old `/api/v1/webhook/grocy` (§8.1.5, B36).
- **Every regression test must go red against the unfixed code.** For each counter-test a task names, revert or disable the guard once and confirm the test fails **for the stated reason**. Then restore the guard and record the result in the task report.
- **Backend checks.** Per task: `ruff check .`, `ruff format --check .`, `mypy app/` and `pytest <touched dirs>`. Before each PR: `pytest -m "not slow" --cov=app --cov-fail-under=80`, then `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`. Every new test directory gets an `__init__.py`: `tests/unit/inbox/`, `tests/integration/auth/`, `tests/fixtures/grocy_label/`.
- **Frontend checks.** `pnpm typecheck`, `pnpm lint`, `pnpm test:coverage`, `pnpm build`, plus `pnpm e2e` before each PR. `schema.gen.ts` changes only through `pnpm gen:api`; run it after every backend task that changes the OpenAPI.
- **Frontend JS needs Vitest + jsdom tests.** Every new module with logic gets a `*.test.ts(x)`, including roundtrip tests for every localStorage key. A changed file without a changed test fails review.
- **i18n strings in de and en.** Every new UI string goes into both `frontend/src/i18n/locales/en/messages.po` and `de/messages.po`. German uses real umlauts, and counts go through `plural`. A removed string leaves both catalogs.
- **UI task protocol (Tasks 2, 5, 7–12, 19, 20).** Before writing UI code, load the design skills `taste-skill:design-taste-frontend`, `emil-design-eng`, `mobile-native` and `break-ui`. At the end of the task, run `impeccable:impeccable` on the changed screens. Take Playwright screenshots (light and dark, 1280 px and 390 px, the `SHOTS` pattern in `frontend/e2e/shell.spec.ts`) as artifacts, not as a gate.
- **Inbox locking (C12).** `app.state.inbox_lock`, an `asyncio.Lock` created in the lifespan, guards inbox writes only. No network lookup, render or queue submit runs while it is held. Adds never wait on a print.
- **Untrusted text (§12.4).** Upstream text renders as text nodes only. It is never an `href`, and it never goes into SSE events or metric labels. Logs name line ids and app names through `log_value`.
- **Error bodies (§12.3, review I-1).** Every new route prefix joins `answers_with_envelope()` in `backend/app/api/error_handlers.py`, so that its 422 names field paths and never the input. Add `/api/v1/inbox` in Task 4, `/api/v1/integrations/` in Task 13, and `/api/v1/admin/webhook-calls` in Task 14. Bodies never echo the request body, an idempotency key, a header value, a token or an upstream URL.
- **Body caps while reading.** Body caps are enforced while the body streams in, by `read_capped_body()` (Task 4), never after Starlette has read the whole body. The caps are 256 KiB for inbox routes and 64 KiB for the Grocy route.
- **Single process (§5.1).** In-memory state stays per process: duplicate windows, the preview cache, the locks.
- **Route auth guardrail.** Every new route uses a dependency that `tests/unit/api/test_route_auth_coverage_guardrail.py` accepts. A route that authenticates inside its handler goes into that test's `_PUBLIC_BY_DESIGN` with a one-line reason.

## Review Focus

1. **The same line changes on two devices at once.** The copies are edited on the phone before or while the desktop prints. If the edit comes before the print, the print gets `409`. If the edit comes during the print, the line stays and is listed in `kept_changed`. Nothing is lost. Tests: `test_print_after_concurrent_copies_edit_is_409` and `test_edit_during_print_keeps_line_reported` (Task 5).
2. **A Grocy call arrives during a long print.** It answers in under 0.5 s and parks. Test: `test_grocy_label_during_slow_print_answers_fast` (Task 15).
3. **A real Grocy payload in default form encoding with awkward values.** Bracket notation, no `details`, best-before `2999-12-31`, a product name of 600 characters, emoji. The call parks, the values are bounded, and it never answers `422`. Test: `test_grocy_label_awkward_payloads_park` (Task 15).
4. **The limit with merges and copies.** A merge clamps the copies to 10, and the limit counts labels after that clamp. Test: `test_merge_clamps_and_limit_counts_after_clamp` (Task 4).
5. **A key changes after a session was minted.** The session's capabilities follow the key on its next use. Test: `test_session_follows_key_capability_change` (Task 2).

---

## Phases and PR boundaries

All three PRs target the milestone branch.

| PR | Tasks | Ships |
|---|---|---|
| **PR 1 — backend inbox** | 1–6 | The #188 fix, the capability set and the `inbox` key, the inbox store, API and events, freshness, and tape and sheet printing from the inbox. The old cart keeps working: the new routes are additive, and only the key form changes in the UI |
| **PR 2 — inbox UI** | 7–12 | The server cart and its migration, selection, sheet preview and scan, the expiry notices and the inbox settings section, refresh and diff |
| **PR 3 — integrations** | 13–21 | Event rules, the webhook call log, the Grocy label route, Grocy line resolution, the background fill, Spoolman routing, the settings UI, and the docs |

The security audit runs on each PR at the ship gate. Its focus is Task 2 in PR 1, Task 7's import route in PR 2, and Tasks 14–16 in PR 3. The **Kept receiver (§8.3) is not in this plan**; it waits for #173.

## Migrations (linear chain)

| Revision | File | Task |
|---|---|---|
| `20261110a1` ← head | `backend/alembic/versions/2026_11_10_0001-20261110a1_print_inbox.py` | 3 |
| `20261110a2` ← `a1` | `…_0002-20261110a2_jobs_data_source.py` (nullable `jobs.data_source`) | 5 |
| `20261110a3` ← `a2` | `…_0003-20261110a3_inbox_refreshes.py` | 11 |
| `20261110a4` ← `a3` | `…_0004-20261110a4_integration_event_rules.py` | 13 |
| `20261110a5` ← `a4` | `…_0005-20261110a5_webhook_calls.py` | 14 |

All migrations are additive, and each downgrade drops what its upgrade added. Each one gets `backend/tests/integration/db/test_alembic_<name>.py`, following the pattern of `test_alembic_sheet_migration.py`: upgrade from the previous head on an empty DB and on a populated one, then `downgrade -1`.

---

## PR 1 — backend inbox

### Task 1: Webhook jobs reach the print queue (#188)

#188 is open on the 1.5.0 branch as well. There, `webhooks.py:118/:158` call `jobs_repo.create_queued`, and nothing hands the job to the queue.

**Files:**
- Modify: `backend/app/services/print_service.py`: add `submit_label`; `submit_print_job` resolves the data and delegates to it.
- Modify: `backend/app/api/routes/webhooks.py`: both handlers go through `submit_label`. Fix the module docstring and the route descriptions.
- Test: `backend/tests/unit/api/test_webhooks_routes.py` (extend), `backend/tests/integration/api/test_webhook_prints.py`

**Interfaces:**
- Produces: `PrintService.submit_label(content_type: ContentType, label: LabelData, options: PrintOptions = PrintOptions(), *, extra_payload: Mapping[str, Any] | None = None, data_source: DataSource | None = None) -> UUID`. It runs preflight, render, `save_queued` and `submit_with_id`. The payload keeps `label.source_app`; `extra_payload` goes under `"origin"`.
- Produces: `submit_webhook_label(request, session, *, app, entity_id, event_type) -> UUID` in `webhooks.py`. It runs the lookup, takes the first enabled tape printer, gets the service via `request.app.state.backend_router.service_for(slug)` and prints with `ContentType.QR_TWO_LINES`. That content type is the plan's call; Task 18 replaces it with the format from the event rule. Errors map through `print.py`'s `_SYNC_ERROR_MAP`.

- [ ] **Step 1: Write the failing tests.**
  - `test_spoolman_webhook_job_is_printed_without_restart`: a mock backend and a stubbed lookup. The webhook answers `202`. Within 2 s the mock has recorded exactly one print, and the job is `completed`.
  - `test_webhook_job_payload_is_rerenderable`: the payload has `content_type`, `label_data.source_app == "spoolman"` and `rendered_tape_mm`. Cancel works, and retry after a failure gives a new queued job.
  - `test_webhook_payload_recovered_on_restart`: a persisted webhook job is re-rendered by `PrintQueue.start()`, not marked `recovery_skip_legacy_payload`.
  - The same tests for `/grocy`.
- [ ] **Step 2: Run them.** Expected: FAIL. The job stays `queued`, retry answers `409 invalid-job-state`, and recovery skips the job.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify.** Counter-test: put `create_queued` back into one handler. Its test turns red with "no print recorded".
- [ ] **Step 5: Commit** `fix(webhooks): hand webhook jobs to the print queue with a re-renderable payload` (`Fixes #188`).

### Task 2: Capability set and the `inbox` key scope (security)

**Files:**
- Create: `backend/app/auth/capabilities.py`
- Modify:
  - `backend/app/auth/dependencies.py`: `AuthContext`; `_validate_api_key` (:244-262); `_session_context`; the SSO and bypass paths.
  - `backend/app/auth/sessions.py`: `ValidSession`, `load_valid`.
  - `backend/app/auth/scope_deps.py`: add `require_inbox`; update the docstring example.
  - `backend/app/api/routes/auth_session.py`: `SessionInfo.scope` gets `inbox`; sign-in refuses keys without `print` (C15).
  - `backend/app/api/routes/admin_api_keys.py`: validate `scopes`.
  - `backend/app/cli.py`: `--scope` accepts `inbox`.
  - `backend/tests/integration/conftest.py`: the override loop includes `require_inbox`.
  - `frontend/src/features/settings/AccessKeys.tsx`: a checkbox labelled "Can add items to the print inbox".
- Test: `backend/tests/unit/auth/test_capabilities.py`, `backend/tests/integration/auth/test_scope_set.py`, `frontend/src/features/settings/AccessKeys.test.tsx`

**Interfaces:**
- Produces: `Capability = Literal["read","print","admin","inbox"]` and `grants(scopes: Iterable[str]) -> frozenset[Capability]`. The result is the union of what each scope grants: `read` → {read, inbox}; `print` → {read, print, inbox}; `admin` → all four; `inbox` → {inbox}. Unknown values are ignored.
- Produces: `effective_label(caps) -> Scope`: the highest chain scope, else `"inbox"`.
- Produces: `AuthContext.capabilities: frozenset[Capability]`. A model validator defaults it to `grants([scope])`, so the 37 existing constructions keep working. `scope` widens to include `"inbox"` and is kept for logs.
- Produces: `require_scope(x)` checks `x in ctx.capabilities`; `require_inbox = require_scope("inbox")`.
- Produces: `ValidSession.capabilities`. Key sessions re-read it from the key on every use (B37). SSO and bootstrap sessions take `grants([row.scope])`. The session row keeps its single label (spec §12.1 amended).
- Produces: `caller_id(ctx: AuthContext | None) -> str`:
  - `key:<api_key_id>` for keys and for sessions minted from a key;
  - `sso:<user>` for SSO;
  - `bypass` for the bypass;
  - `None` → `webhook`, for the shared secret (C5).
- `ApiKeyCreate.scopes` must be a non-empty subset of the four capability names; anything else gives `422`.

- [ ] **Step 1: Write the failing tests.**
  - `test_inbox_only_key_authenticates_for_inbox`: `403 insufficient_scope` on `require_read`.
  - `test_read_key_has_inbox`.
  - `test_unknown_only_scopes_still_key_no_scopes`.
  - `test_bypass_downgrade_read_grants_inbox_not_print`.
  - `test_session_follows_key_capability_change` (Review Focus 5): mint a session from `["inbox","print"]`, then edit the key row **in the DB** (the API cannot change scopes) to `["inbox"]`. The same cookie gets `403` on print and still passes inbox.
  - `test_sign_in_refuses_read_and_inbox_only_keys`.
  - `test_create_key_rejects_unknown_scope`.
  - `test_authcontext_without_capabilities_defaults_from_scope`.
  - Vitest: the inbox-only box sends `["inbox"]`.
- [ ] **Step 2: Run them.** Expected: `["inbox"]` gets `401 key_no_scopes`, and the session test fails.
- [ ] **Step 3: Implement.** Re-run the route-auth guardrail test.
- [ ] **Step 4: Verify.** Counter-test: restore the "highest of three" reduction. `test_inbox_only_key_authenticates_for_inbox` turns red with `401 key_no_scopes`.
- [ ] **Step 5: Commit** `feat(auth): grant capabilities as a set and add the enqueue-only inbox scope`.

### Task 3: Inbox data model, revision counter and events

**Files:**
- Create:
  - `backend/app/models/inbox.py` and migration `20261110a1`;
  - `backend/app/inbox/__init__.py`, `snapshot.py`, `events.py`;
  - `backend/app/repositories/inbox.py`.
- Modify:
  - `backend/app/settings_store/registry.py`: the `inbox.*` settings;
  - `backend/app/api/routes/events_v1.py` and `backend/app/services/sse_snapshot.py`: the `inbox` channel and the counts in the snapshot;
  - `backend/app/main.py`: create `app.state.inbox_lock` in the lifespan.
- Test: `backend/tests/unit/inbox/test_snapshot.py`, `backend/tests/integration/db/test_alembic_print_inbox.py`, `backend/tests/integration/api/test_events_inbox.py`

**Interfaces:**
- Produces the table `inbox_items`, with every field of §5.1 including `item_meta` (C11, spec amended). `source_app` takes `snipeit`, `grocy`, `spoolman`, `kept` or `manual`; `format` is a tagged dict. Index on `(source_app, item_ref)`.
- Produces the table `inbox_idempotency` (§5.3), keyed by `scope_key`, plus a nullable `released_at`. Retention counts from `released_at`.
- Produces the table `inbox_state`, one row: `revision`, `last_expired_count`, `last_expired_labels`, `last_expired_at` (see G4).
- Produces `normalise_snapshot(data: SheetRawLabelData) -> dict`: sorted keys, NFC, trailing whitespace stripped, empty fields dropped.
- Produces `snapshot_hash(snapshot: dict) -> str`: the SHA-256 of the canonical JSON, stored in the column `snapshot_hash`.
- Produces `merge_key(source_app, item_ref, fmt, item_meta, snapshot_hash) -> tuple`: the five-part key of spec §5.1, with `item_meta.grocycode` and `item_meta.stock_id` (each `None` when absent).
- Produces `INBOX_CHANNEL = "inbox"`, `InboxCounts(count, labels, waiting_for_sheet)` and `publish_inbox_changed(bus, *, revision, reason, item_ids, counts)`, plus `publish_inbox_expiring(bus, *, count, labels, earliest_expires_at)`. Neither carries any text (B21).
- Produces in the repo:
  - `bump_revision(session) -> int`, in the same transaction as the write;
  - `counts(session, now) -> InboxCounts`, where `waiting_for_sheet` is the sum of copies of the lines whose intended printer is a page printer.
- Produces settings, all with `env_field=None`:
  - `inbox.freshness`: enum `snapshot`, `fresh`, `fresh_with_fallback`; default `fresh_with_fallback`;
  - `inbox.max_items` 500;
  - `inbox.expiry_days` 30;
  - `inbox.expiry_warning_days` 3;
  - `inbox.idempotency_days` 7.

- [ ] **Step 1: Write the failing tests.**
  - `test_hash_differs_on_best_before`.
  - `test_merge_key_differs_on_stock_id_and_grocycode`.
  - `test_hash_stable_across_key_order`.
  - The migration test.
  - `test_stream_subscribes_inbox_for_read`.
  - `test_inbox_only_key_cannot_open_stream`: `403`.
  - `test_snapshot_frame_has_inbox_counts`.
- [ ] **Step 2: Run them.** Expected: collection errors.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify,** including migration up, down and up.
- [ ] **Step 5: Commit** `feat(inbox): add the print inbox tables, revision counter and inbox event channel`.

### Task 4: Read, add, change and remove lines

**Files:**
- Create: `backend/app/schemas/inbox.py`, `backend/app/inbox/service.py`, `backend/app/inbox/dedupe.py`, `backend/app/api/body.py`, `backend/app/api/routes/inbox.py` (prefix `/api/v1/inbox`)
- Modify: `backend/app/api/error_handlers.py` (`answers_with_envelope` gets `/api/v1/inbox`)
- Test: `backend/tests/unit/inbox/test_service.py`, `backend/tests/integration/api/test_inbox_api.py`

**Interfaces:**
- Consumes: from Task 2, `require_inbox`, `require_read`, `require_print` and `caller_id`; from Task 3, the models, `merge_key`, the events, `counts` and `app.state.inbox_lock`.
- Produces: `read_capped_body(request: Request, limit: int) -> bytes`. It reads the stream and raises `413 payload_too_large` as soon as `limit` is passed.
- Produces schemas:
  - `InboxItemIn` (§6.2): `content_type`, `format?`, `copies` 1–10 (default 1), `lookup?`, `data?: SheetRawLabelData`, `idempotency_key?` (1–128 printable ASCII). At least one of `lookup` or `data` is required. `designer_layout` gives `422 format_not_supported`.
  - `InboxAddRequest`: `items`, 1 to 50. An `Idempotency-Key` header applies to a single-item request.
  - `InboxAddResponse`: `{revision, results: [{index, outcome: "parked"|"merged", item_id, duplicate}]}`, with **no snapshot field**.
  - `InboxItemRead`: the fields of §6.1 plus `expires_in_days`.
  - `InboxRead`: `{revision, items (created_at ascending), limits, freshness, expiring_soon: {count, labels}, expired_recently: {count, labels, at} | null}`.
- Produces: `@dataclass ParsedEntry(source_app, item_ref, fmt, snapshot, snapshot_complete, copies, item_meta, idempotency_key, request_hash)`.
- Produces: `class InboxService(lock: asyncio.Lock, bus, lookup)` with these methods:
  - `add(session, items, *, caller, origin, origin_detail, now)` runs **every lookup before it takes the lock**, then calls `add_entries`.
  - `add_entries(session, entries, *, caller, origin, origin_detail, origin_event=None, intended_printer_id=None, now) -> InboxAddResponse` does all of its work under the lock: the idempotency check, the merge by `merge_key` (copies clamped to 10, `version`+1, `expires_at` unchanged), the label limit after the clamp, all or nothing, `bump_revision`, and the commit. It publishes after the commit.
  - `list(session, now) -> InboxRead` hides expired lines.
  - `set_copies(session, id, version, copies)`, `remove(session, refs)` and `clear(session, revision)`. These set `released_at` on the idempotency rows of removed lines.
  - The attribute `on_incomplete: Callable[[UUID], None]`, a no-op by default; Task 17 wires it.
- Produces: `RecentRequests(window_s)` with `seen(caller, request_hash)` and `remember(...)`; it holds 60 s here.
- Errors:
  - With the source down, an item carrying `data` is parked with `snapshot_complete=False`, followed by a call to `on_incomplete`.
  - A reference-only item gives `503 integration_unavailable` with `Retry-After: 30`.
  - Not found gives `404 app-lookup-not-found` with `item_index`.
  - `503 integration_not_configured`, `422 integration_unknown_app`, the per-key `429`, `409 inbox_full`, and `409 idempotency_conflict` (which names the `index` only).
- Routes:
  - `GET /api/v1/inbox` (`read`);
  - `POST /api/v1/inbox/items` (`inbox`);
  - `PATCH /api/v1/inbox/items/{id}`, `DELETE /api/v1/inbox/items/{id}?version=`, `POST /api/v1/inbox/remove` and `DELETE /api/v1/inbox`, all `print`.
  - A stale version gives `409 inbox_item_changed` with the current lines; a missing line gives `404 inbox_item_not_found`.

- [ ] **Step 1: Write the failing tests:**
  - `test_lookup_add_stores_snapshot`.
  - `test_source_down_with_data_parks_incomplete_and_calls_on_incomplete`.
  - `test_source_down_reference_only_503_nothing_stored`. Counter-test: park reference-only items; the test then sees a line.
  - `test_data_only_is_manual`.
  - `test_same_key_twice_one_line_duplicate`.
  - `test_idempotency_header_single_item`.
  - `test_same_key_other_body_409_conflict_index_only`.
  - `test_key_reused_after_removal_no_new_line`. Counter-test: delete the record on removal.
  - `test_no_key_60s_window`.
  - `test_same_product_equal_data_merges_copies_2`.
  - `test_other_best_before_two_lines`. Counter-test: merge on `(app, ref, format)` only.
  - `test_label_per_unit_two_lines`.
  - `test_limit_counts_labels_not_lines`. Counter-test: count lines.
  - `test_merge_clamps_and_limit_counts_after_clamp`.
  - `test_not_configured_503`, `test_unknown_app_422`, `test_rate_limit_429`.
  - `test_inbox_key_403_on_get_patch_delete`.
  - `test_read_key_adds_but_403_on_patch_remove`.
  - `test_enqueue_response_has_no_snapshot_raw_json`.
  - `test_invalid_item_422_does_not_echo_marker_title`. Counter-test: remove the prefix from `answers_with_envelope`.
  - `test_body_over_256_kib_413_while_streaming`.
  - `test_every_write_publishes_increasing_revision_without_title`.
  - `test_stale_version_409_with_current_lines`.
  - `test_items_ordered_by_created_at`.
- [ ] **Step 2: Run them.** Expected: `404`, because the route does not exist yet.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify,** running each counter-test.
- [ ] **Step 5: Commit** `feat(inbox): read, add, change and remove inbox lines with idempotency and limits`.

### Task 5: Freshness resolution, tape print from the inbox, `jobs.data_source`

**Files:**
- Create: `backend/app/inbox/resolve.py`, `backend/app/inbox/print_tape.py`, `backend/app/services/batch_submit.py`, `backend/app/api/routes/inbox_print.py`, migration `20261110a2`
- Modify:
  - `backend/app/services/print_service.py`: `submit_labels`; `submit_batch_job` delegates to it.
  - `backend/app/api/routes/batch.py`: its body moves to `dispatch_resolved_batch`.
  - `backend/app/models/job.py`: `data_source`.
  - `backend/app/schemas/job.py`: `data_source` and `printed_from_snapshot`.
  - `frontend/src/features/jobs/*`: the "Printed from snapshot" badge.
- Test: `backend/tests/unit/inbox/test_resolve.py`, `backend/tests/integration/api/test_inbox_print_tape.py`, `backend/tests/integration/api/test_batch_api.py` (unchanged behaviour), the migration test, a jobs Vitest

**Interfaces:**
- Produces: `DataSource = Literal["fresh","snapshot","snapshot_fallback"]` and `ResolvedLine(item, label: LabelData, data_source, unavailable: bool)`.
- Produces: `LINE_RESOLVERS: dict[str, LineResolver]` with `LineResolver = Callable[[InboxItem, AppLookupService], Awaitable[LabelData]]`. The default is `lookup(app, item_ref)`. Task 16 registers the Grocy resolver. A line with a null `item_ref` always resolves as `snapshot`.
- Produces: `resolve_lines(items, *, freshness, lookup, cache: LookupCache | None) -> list[ResolvedLine]`. The rules of §9 per setting:
  - `snapshot`: no call.
  - `fresh`: a failure or not-found sets `unavailable`.
  - `fresh_with_fallback`: on `LookupFailedError`, `integration_not_configured` or not-found, the snapshot prints with `snapshot_fallback`.
  - `manual` lines resolve as `snapshot`.
  - A snapshot-built `LabelData` keeps `source_app`. At most 4 lookups per app are in flight.
- Produces: `LookupCache(ttl_s=60)`, which caches failures too (C7). Only previews use it; prints pass `None` (B20).
- Produces: `ResolvedLabel(content_type, label, copies, data_source)` and `PrintService.submit_labels(labels, *, half_cut) -> list[UUID]`. It writes `jobs.data_source` and the payload key `data_source`.
- Produces: `dispatch_resolved_batch(http: Request, session, auth, printer, labels: Sequence[ResolvedLabel], half_cut_override: bool | None) -> BatchResponse`. It does what `create_batch` does today: the backend lookup and `service_for` with their `503`s, the half-cut capability rule, the `PrintBatch` row, and the fixed-message error map. `POST /api/v1/print/{key}/batch` resolves its items and calls it; the batch tests stay green unchanged.
- Route: `POST /api/v1/inbox/print/{printer_key}` (`print`, printer ACL). Body: `{items: [{id, version}], half_cut_override}`. Response: `BatchResponse` plus `data_sources` and `kept_changed: [id]`. Order (C12):
  1. Under the lock: check the versions (a mismatch gives `409 inbox_item_changed`, nothing queued) and copy the lines.
  2. Refuse more than 500 labels with `422 selection_too_large` `{labels, max}`, and an IPP printer with `409 media_kind_mismatch`.
  3. Without the lock, resolve. Under `fresh`, an unavailable line gives `502` with the integration error, and nothing is printed.
  4. Without the lock, call `dispatch_resolved_batch`.
  5. Under the lock again, delete each sent line whose version is unchanged, set `released_at`, bump the revision and publish `printed`. A changed line goes into `kept_changed`.

- [ ] **Step 1: Write the failing tests:**
  - `test_snapshot_mode_makes_no_lookup_call`: the mock is called 0 times.
  - `test_fallback_prints_snapshot_and_flags_job`: the mock **was** called, and the job has `data_source == "snapshot_fallback"`.
  - `test_fallback_on_deleted_item`.
  - `test_fresh_source_down_502_nothing_printed_lines_unchanged`.
  - `test_print_removes_exactly_sent_lines`.
  - `test_print_after_concurrent_copies_edit_is_409`.
  - `test_edit_during_print_keeps_line_reported`: the lookup is held on an event, the copies are edited, then the lookup is released.
  - `test_add_during_slow_print_completes_within_200ms`: the lookups hang, and `POST /inbox/items` (data only) answers in under 200 ms. Counter-test: hold the lock across resolve; the add then times out.
  - `test_key_reused_after_print_no_new_line`. Counter-test: delete the record on print; a second line appears.
  - `test_selection_501_labels_422_nothing_queued`.
  - `test_job_payload_keeps_source_app_not_manual`.
  - `test_ipp_printer_409_media_kind_mismatch`.
  - `test_inbox_print_returns_batch_id_readable_via_batches_route`.
  - `test_job_read_printed_from_snapshot`.
  - The migration test.
  - Vitest: the badge.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** (UI protocol for the badge), then `pnpm gen:api`.
- [ ] **Step 4: Verify.** Counter-test: skip the first version check; the concurrent-edit test then prints.
- [ ] **Step 5: Commit** `feat(inbox): print inbox lines onto tape with the freshness setting and record the data source`.

### Task 6: Sheet preview and print from the inbox

**Files:**
- Create: `backend/app/inbox/print_sheet.py`
- Modify: `backend/app/sheets/print_service.py` (`print_sheets(..., item_data_sources: Sequence[DataSource | None] | None = None)`), `backend/app/api/routes/inbox_print.py`, `backend/app/schemas/inbox.py`
- Test: `backend/tests/integration/api/test_inbox_print_sheet.py`, `backend/tests/unit/sheets/test_print_service_print.py` (extend)

**Interfaces:**
- Consumes:
  - from Task 5: `resolve_lines`, `LookupCache`, the lock pattern;
  - `app.sheets.print_service.preview` and `print_sheets`;
  - `InsufficientCellsError.detail["free_cells"]`, the capacity **per placement** (`planner.py:612-614`);
  - `ItemContentMismatchError.detail["item_index"]`.
- Produces schemas:
  - `InboxSheetRequest`: `items [{id, version}]`, `placements` (`PlacementInModel`), `tray`, `overflow: "next_sheet"|"refuse"` (default `next_sheet`), `expected_cells`.
  - `InboxSheetPreview(SheetPreview)` adds:
    - `item_map[{inbox_item_id, copy, source_app, title}]`, by expanded index;
    - `next_sheet`, in the same shape;
    - `not_printable[{inbox_item_id, reason}]`;
    - `data_sources`.
  - The print response adds the same lists plus `kept_changed`.
- Produces: `build_sheet_items(lines) -> list[SheetItem]`: one item per copy in the order sent, with raw `data`, `source = source_app`, `ref = item_ref` and `purpose = title`.
- Produces: `plan_inbox_sheet(...) -> InboxSheetPlan`. The signature does not fix this algorithm, so the steps are:
  1. `unavailable` lines → `not_printable` (`unavailable`).
  2. Run `preview`. On `ItemContentMismatchError`, move the whole line of `detail["item_index"]` (all its copies) → `not_printable` (`content_type_not_supported`) and repeat. There are at most as many rounds as lines.
  3. On `InsufficientCellsError` with `next_sheet`:
     - let `caps = free_cells`;
     - keep the first `sum(caps)` expanded items and move the rest → `next_sheet`;
     - go through the placements in order: placement *i* takes `min(remaining, caps[i])`. An explicit `count` shrinks to that number, and an explicit `cells` list keeps its first that many cells;
     - drop a placement that takes 0 from the request (no placement is ever added, so C1 holds);
     - if `sum(caps) == 0`, re-raise `insufficient_cells`;
     - repeat once.
  4. With `overflow: refuse`, re-raise.
- Produces: `print_sheets` takes `item_data_sources`, one value per item. Each page job row gets `data_source` = the worst value of its cells (`snapshot_fallback` > `snapshot` > `fresh`), and each cell payload gets its own value (G3, spec §9 amended).
- Routes:
  - `POST /api/v1/inbox/sheet/preview/{printer_key}` (`read`).
  - `POST /api/v1/inbox/sheet/print/{printer_key}` (`print`). The print follows the C12 order of Task 5. It re-plans with `cache=None` and passes `expected_cells` (so `409 plan_changed` holds).
- Removal: the print removes the lines whose copies were all queued. A line with only some copies queued keeps the rest, and its version is bumped. On `502 print_interrupted`, only the queued copies are removed.

- [ ] **Step 1: Write the failing tests:**
  - `test_preview_maps_items_to_lines_and_copies`.
  - `test_overflow_keeps_sum_of_free_cells`: one placement with 3 free cells and 5 labels gives 3 placed and 2 in `next_sheet`. Counter-test: use `len(free_cells)`; only 1 is placed.
  - `test_overflow_two_placements_truncated_in_order`.
  - `test_overflow_explicit_count_shrinks`.
  - `test_overflow_zero_capacity_placement_dropped`.
  - `test_overflow_all_full_409`.
  - `test_overflow_refuse_keeps_409`.
  - `test_next_sheet_never_adds_a_placement`.
  - `test_unrenderable_line_not_printable_others_print`. Counter-test: re-raise the mismatch; the test gets `422`.
  - `test_fresh_source_down_line_unavailable_others_render`.
  - `test_second_preview_within_60s_no_new_lookup_for_failed`.
  - `test_print_removes_placed_keeps_next_sheet_and_not_printable`.
  - `test_partial_print_removes_only_queued_copies`.
  - `test_sheet_print_ignores_line_added_after_preview`.
  - `test_sheet_print_501_labels_422`.
  - `test_sheet_page_job_row_has_worst_data_source`.
  - `test_add_during_slow_sheet_print_completes_within_200ms`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement,** then `pnpm gen:api`.
- [ ] **Step 4: Verify** with the counter-tests.
- [ ] **Step 5: Commit** `feat(inbox): preview and print selected inbox lines onto a sheet with next-sheet leftovers`.

**PR 1 gate:** the full backend gate and the migrations. Then `pnpm gen:api` and the frontend gate. Then the security audit, Task 2 first. Then open the PR against the milestone branch.

---

## PR 2 — inbox UI

### Task 7: The server cart and the localStorage migration

**Files:**
- Create: `frontend/src/features/inbox/api.ts`, `frontend/src/features/inbox/migrate.ts`
- Modify:
  - `backend/app/api/routes/inbox.py`: `POST /api/v1/inbox/import`.
  - `frontend/src/features/lookup/cart.ts`: the inbox-backed cart; the `storage` sync is removed.
  - `frontend/src/api/events.ts`: on `inbox.changed`, invalidate `["inbox"]` when `revision` is greater than the cached one.
  - `CartPage.tsx`, `ItemView.tsx`, `IntegrationPage.tsx`.
- Test: `inbox/api.test.ts`, `inbox/migrate.test.ts`, `lookup/cart.test.tsx` (rewritten), `backend/tests/integration/api/test_inbox_import.py`

**Interfaces:**
- Produces, backend: `POST /api/v1/inbox/import` (`read`, B10).
  - Body: `{device_id (8–64 chars, [A-Za-z0-9-]), lines: [{app, id, name, content_type, copies}] ≤ 500}`.
  - When a lookup fails, the line is stored with the snapshot `{title: name}` and `snapshot_complete=False`.
  - The `scope_key` is `device:<device_id>:<app>:<id>` (C5); the origin is `ui`.
- Produces, frontend:
  - `useInbox()`, using query key `["inbox"]`.
  - `useInboxMutations()`, with `add`, `setCopies(id, version, copies)`, `remove(refs)` and `clear(revision)`. Any `409` triggers a refetch.
- Produces `useCart()`, which keeps `{items, add, remove, setCopies, clear}`. `items` are `InboxLine` (`CartItem` plus `lineId`, `version`, `origin`, `snapshotComplete`, `expiresInDays`).
  - `print`/`removeItems` stay as a `legacyPrint` shim (today's batch path, removing the sent lines through the inbox). `CartPage` and `SheetSection` keep working that way until Tasks 8 and 9 replace the shim, and Task 9 deletes it (review Minor 10).
- Produces `migrateLocalCart(fetcher): Promise<"none"|"done"|"failed">`.
  - Keys: `lph.cart`, `lph.cart.migrated`, `lph.device`.
  - `lph.cart` is removed only after a `2xx`.
- Copies edits are debounced for 400 ms and sent with the line's `version`. On a `409` the typed value stays, with a note (B23).

- [ ] **Step 1: Write the failing tests.**
  - Migration:
    - each line is sent once, with the key `<device>:<app>:<id>`;
    - `lph.cart` is removed after a `2xx` and kept after a `500`;
    - a second call does nothing;
    - a session without `print` (simulated; C15) still migrates.
  - Cart:
    - `add` sends a `POST` to `/api/v1/inbox/items`;
    - a newer revision triggers a refetch, an older one does not;
    - `legacyPrint` removes exactly the lines it sent.
  - pytest:
    - `test_import_lookup_failure_name_only_snapshot`;
    - `test_import_twice_one_line`;
    - `test_inbox_only_key_403_on_import`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** under the UI protocol. Run `pnpm gen:api`. i18n: add "N items from this browser could not be moved yet" (plural).
- [ ] **Step 4: Verify.**
  - Counter-test: remove `lph.cart` before the response arrives; the error-path test turns red.
  - The app builds and the existing cart e2e still passes.
- [ ] **Step 5: Commit** `feat(ui): keep the cart in the server inbox and move local carts there once`.

### Task 8: Line selection and tape print by selection (UI)

**Files:**
- Create: `frontend/src/features/inbox/selection.ts`, `frontend/src/features/inbox/InboxList.tsx`
- Modify: `CartPage.tsx`, `lookup/cart.ts` (`print(printerKey, ids)`, which posts to `/api/v1/inbox/print/{key}`; the tape path stops using `legacyPrint`)
- Test: `selection.test.ts`, `InboxList.test.tsx`, `CartPage.test.tsx`

**Interfaces:**
- Produces `useSelection(lines) -> {selected, state: "none"|"some"|"all", toggle, toggleAll, clear}`.
  - The selection lives in `lph.inbox.selection` and is pruned against the current lines on every change.
  - With no stored selection, every line is selected. Lines that arrive later are not selected (B25).
  - `toggleAll` clears when every line is selected, and selects all otherwise.
- Produces `InboxList`, which behaves as follows:
  - It is one tab stop with roving focus; Space toggles the focused row (B24).
  - A click on the row toggles it. Clicks on the name link, the copies field or Remove do not.
  - Targets are at least 44 px.
  - A session without `print` sees no copies field, no Remove and no print button, and gets a note that printing needs a print key (C15).
- Print button copy:
  - "Print {n} of {total} labels";
  - "Print {total} labels" when every line is selected;
  - disabled when nothing is selected;
  - disabled with "At most 500 labels per print" above 500 (C3).
- Origin badge "from {app}".

- [ ] **Step 1: Write the failing tests:**
  - select all, untick two: the print body has exactly the remaining ids;
  - the header shows none, some and all;
  - a header click when all are selected clears;
  - "Clear selection" appears only while something is selected;
  - Space toggles the focused row;
  - a row click toggles, a Remove click does not;
  - the selection survives a reload, and pruned ids drop out;
  - a line that arrives through SSE is unselected;
  - the selection is never sent except as the print ids;
  - a session without `print` can add and select, but has no print, remove or copies;
  - 501 labels disables the button with the reason;
  - the title `<img onerror>` renders as text.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** under the UI protocol. On phones: a sticky bottom bar with the count, "Clear selection" and print; safe-area insets; a 16 px input font.
- [ ] **Step 4: Verify,** with screenshots.
- [ ] **Step 5: Commit** `feat(ui): select inbox lines per device and print only the selection`.

### Task 9: Sheet preview from the selection, and scan to sheet (UI)

**Files:**
- Modify:
  - `frontend/src/features/sheets/print/SheetSection.tsx`: props `lines` and `selected`; calls the inbox preview and print. Remove the client-side leftover logic (`:262-282`) and the `legacyPrint` shim.
  - `SheetPreview.tsx`:
    - cell numbers on the new cells;
    - the list "Cell N → App · Name (k/n)";
    - a two-way highlight between list and sheet;
    - the groups "Next sheet" and "Not printable on this sheet type" / "Source unreachable";
    - the "snapshot" marker.
  - `frontend/src/features/sheets/resolver.ts`.
  - `CartPage.tsx`: with `?sheet=`, preselect the printer; when the inbox is empty, replace the route with `/sheet/{code}` (G5, spec §11.4 amended).
  - The theme CSS: the colour token `--color-cell-number` (reuse it if #249 lands first) and the legend "1 = cell number (not printed)".
- Test: `SheetSection.test.tsx`, `SheetPreview.test.tsx`, `resolver.test.ts`, e2e `frontend/e2e/inbox-sheet.spec.ts`

**Interfaces:**
- Consumes: `InboxSheetPreview` from Task 6.
- Produces: `sheetResolver.resolve(hit)`, which always returns `/cart?sheet=<code>`.
- Printer preselect, in this order:
  1. the page printer that last printed onto this sheet;
  2. the `intended_printer_id` of the first selected line;
  3. the only usable page printer;
  4. none.
- The preview rebuilds through `useDebounced(PREVIEW_DEBOUNCE_MS)` when the selection, a line's copies or a snapshot change.
- The print button reads "Print {placed} of {selected} labels onto {code}".
- `next_sheet` lines stay selected after the print (B38).

- [ ] **Step 1: Write the failing tests:**
  - three quick selection changes send one preview request, with exactly the selected ids;
  - `next_sheet` lists names and a count;
  - the list entry and the cell agree;
  - hovering a list entry highlights its cell and the reverse, and a tap toggles the highlight;
  - `not_printable` lines are excluded from the count;
  - the resolver goes to the cart, and an empty inbox redirects to the sheet page;
  - the preselect order.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** under the UI protocol. Use `break-ui` with long names and 60 lines.
- [ ] **Step 4: Verify** with an e2e test:
  - park a line through the API, intended for an IPP printer;
  - scan the sheet code: the cart opens with `?sheet=` and the preview;
  - print: the line is gone and the cells are used;
  - after a partial print, the unselected lines are still there after a reload.
- [ ] **Step 5: Commit** `feat(ui): preview the selected inbox lines on the scanned sheet`.

### Task 10: Expiry sweep, waiting count, notices and the inbox settings section

**Files:**
- Create: `backend/app/inbox/sweep.py`
- Modify:
  - `backend/app/services/cleanup_task.py`: `extra_sweeps: Sequence[Callable[[], Awaitable[int]]]`;
  - `backend/app/main.py`;
  - `frontend/src/shell/TopBar.tsx`;
  - `CartPage.tsx`;
  - `frontend/src/features/settings/sections.tsx`: a "Print inbox" section (review I-9).
- Test: `backend/tests/unit/inbox/test_sweep.py`, `TopBar.test.tsx`, `CartPage.test.tsx`, `settings.test.tsx`

**Interfaces:**
- Produces: `sweep_inbox(session_factory, bus, *, now) -> int`. It does three things:
  - It warns once per line, setting `expiry_warned_at` and publishing one `inbox.expiring`.
  - It deletes the expired lines, records `inbox_state.last_expired_*`, and publishes `inbox.changed reason="expired"`.
  - It deletes idempotency rows whose `released_at` is older than `inbox.idempotency_days`, and the expired refresh rows (once Task 11 exists).
- The interim until #255:
  - The top bar shows the `waiting_for_sheet` count on the cart link.
  - The cart shows two banners, "N labels expire in 3 days or less" and "N labels expired and were removed". The second one is dismissed per device through `lph.inbox.expiredSeen` = `at` (G4).
- Settings section "Print inbox":
  - `inbox.freshness` as a choice with one sentence per option (§9);
  - `inbox.max_items`, `inbox.expiry_days`, `inbox.expiry_warning_days` and `inbox.idempotency_days` as numbers.

- [ ] **Step 1: Write the failing tests:**
  - `test_warning_raised_once_not_daily_again`.
  - `test_expired_removed_with_notice`.
  - `test_no_line_disappears_without_warning_or_notice`: time travel over 31 days.
  - `test_idempotency_rows_kept_7_days_after_release`.
  - Vitest:
    - the count follows `inbox.changed`;
    - the banner appears and its dismissal is stored per device;
    - the expiry badge;
    - the settings section saves `inbox.freshness`, and a locked field shows read-only.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** under the UI protocol.
- [ ] **Step 4: Verify.** Counter-test: drop the `expiry_warned_at` check; the test then sees two events.
- [ ] **Step 5: Commit** `feat(inbox): warn before inbox lines expire, show the waiting count and the inbox settings`.

### Task 11: Refresh and accept (backend)

**Files:**
- Create: migration `20261110a3` (`inbox_refreshes`, `inbox_refresh_items` per §5.4), `backend/app/inbox/refresh.py`, `backend/app/api/routes/inbox_refresh.py`
- Test: `backend/tests/unit/inbox/test_refresh_diff.py`, `backend/tests/integration/api/test_inbox_refresh.py`

**Interfaces:**
- Produces: `diff_snapshots(before, after) -> list[FieldChange(field, before, after)]`.
  - The paths are `title`, `primary_id`, `qr_payload`, `secondary[i]`, `items[i].item` and `items[i].qr_payload`.
  - Only paths that changed are returned.
- Lookups go through `LINE_RESOLVERS` from Task 5, so Grocy lines follow C11. They run outside the inbox lock, with at most 4 in flight per app. An in-process `app.state.refresh_lock`, created in the lifespan, gives `409 refresh_running` while a refresh is held.
- Routes (§6.4). `POST /api/v1/inbox/refresh` (`print`): candidate rows expire after 15 minutes.
- Routes (§6.4). `GET /api/v1/inbox/refresh/{rid}/items/{iid}/render?side=&printer=&sheet_type=` (`read`):
  - for a tape printer it renders through the render path of `/api/v1/render/preview`;
  - for an IPP printer it renders one cell of `sheet_type` with `DEFAULT_CELL_RENDERER`; `sheet_type` is required there and its absence answers `422` (G6, spec §6.4 amended).
- Routes (§6.4). `POST /api/v1/inbox/refresh/{rid}/accept` (`print`) writes under the lock, checking each line's version. It can answer `409 inbox_item_changed` (nothing written), `409 refresh_expired`, `404 refresh_not_found` or `422 not_changed`, and it publishes `accepted`.

- [ ] **Step 1: Write the failing tests:**
  - `test_refresh_writes_no_snapshot`.
  - `test_diff_one_changed_field_one_entry`.
  - `test_accept_all_writes_only_changed`.
  - `test_accept_after_copies_edit_409_nothing_written`. Counter-test: skip the version check.
  - `test_expired_refresh_409`.
  - `test_manual_lines_unchanged`.
  - `test_deleted_vs_unavailable`.
  - `test_second_refresh_409_running`.
  - `test_render_before_after_png`.
  - `test_render_page_printer_without_sheet_type_422`.
  - `test_add_during_refresh_not_blocked`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement,** then `pnpm gen:api`.
- [ ] **Step 4: Verify,** including the migration test.
- [ ] **Step 5: Commit** `feat(inbox): refresh inbox data for review and accept changes under a version guard`.

### Task 12: Refresh and diff (UI)

**Files:**
- Create: `frontend/src/features/inbox/RefreshPanel.tsx`, `DiffView.tsx`, `fieldNames.ts`
- Modify: `CartPage.tsx`, `InboxList.tsx`
- Test: `RefreshPanel.test.tsx`, `DiffView.test.tsx`, `fieldNames.test.ts`, the e2e test `frontend/e2e/inbox-sync.spec.ts`

**Interfaces:**
- Produces `fieldLabel(app, path, t)`, a fixed mapping per app (B27):
  - `title` → "Name";
  - `primary_id` → "Code";
  - for Grocy, `secondary[*]` maps to "Best before", "Amount", "Location" and "Note";
  - an unknown path shows itself.
- Copy and behaviour follow §11.5:
  - the line badges "Changed", "Source unreachable" and "Deleted at source";
  - a summary line;
  - Accept and Keep per line, plus "Accept all changes" (sends `{all: true}`) and "Keep all" (client-side only);
  - before and after side by side, stacked below 640 px, and a full-height sheet on phones;
  - on a `409`, "This item changed since the refresh. Refresh again.";
  - one sentence per freshness mode;
  - long values wrap with `overflow-wrap: anywhere`.

- [ ] **Step 1: Write the failing tests:**
  - the summary counts;
  - only changed fields are shown;
  - accept-all sends `all: true`;
  - the note on a `409`;
  - the preview is invalidated after an accept;
  - a taint title renders as text in the diff.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** under the UI protocol.
- [ ] **Step 4: Verify** with an e2e test: two browser contexts, where a line added in one appears in the other without a reload. Take screenshots.
- [ ] **Step 5: Commit** `feat(ui): review refreshed inbox data side by side and accept or keep each change`.

**PR 2 gate:** full gate on both sides, the e2e tests, and the security audit (the import route and the UI's taint surface). Then open the PR against the milestone branch.

---

## PR 3 — integrations

### Task 13: Event rules (backend)

**Files:**
- Create: migration `20261110a4` (§7.1 tables), `backend/app/models/event_rules.py`, `backend/app/inbox/rules.py`, `backend/app/api/routes/event_rules.py`
- Modify: `error_handlers.py` (adds the prefix `/api/v1/integrations/`)
- Test: `backend/tests/unit/inbox/test_rules.py`, `backend/tests/integration/api/test_event_rules_api.py`

**Interfaces:**
- Produces `KNOWN_EVENTS`, the presets per integration:

  | Integration | Event types | Preset |
  |---|---|---|
  | Grocy | `grocy.product`, `grocy.stock_entry` | `park` |
  | Spoolman | `spoolman.created`, `spoolman.updated` | `park` |
  | Spoolman | any other `type` | unknown, so `none` |
  | Kept | as in §7.1 | defined in code, **not seeded** until #173 |

- Produces `ensure_presets(session)`, run on startup. Its default format is `{"kind":"content_type","content_type":"qr_two_lines"}`.
- Produces `CallOverride(printer, mode)` and `Decision(action, printer, fmt, reason)`.
- Produces `evaluate(session, *, integration, event_type, override, auth: AuthContext | None) -> Decision`. It applies rules 1–6 of §7.2 and the B33 bounds. `auth=None` stands for the shared secret, which has `{inbox, print}` and no printer restriction (this is how it printed before). The outcomes:
  - An override never enables a rule whose action is `none`.
  - With `mode=print` and no `print` on the printer, the event parks with `key_cannot_print`.
  - A page printer always parks.
  - An offline or disabled printer parks with `printer_unavailable` and logs a warning.
  - An unknown event type is `ignored` and logged once.
- Produces the routes `GET/PUT /api/v1/integrations/{name}/event-rules` (`admin`). `PUT` refuses `print` with an IPP target (`422 page_printer_always_parks`) and `designer_layout` (`422 format_not_supported`).

- [ ] **Step 1: Write the failing tests:**
  - `test_fresh_integration_has_presets_none_print`.
  - `test_none_ignored`.
  - `test_event_printer_and_format_override_default`.
  - `test_print_onto_ipp_parks`.
  - `test_offline_tape_printer_parks_with_reason`.
  - `test_unknown_event_ignored`.
  - `test_designer_layout_422`.
  - `test_mode_print_never_enables_none` (counter-test: let `mode` win).
  - `test_mode_print_inbox_key_parks_key_cannot_print`.
  - `test_shared_secret_may_print`.
  - `test_put_print_with_ipp_422`.
  - `test_put_invalid_422_no_echo`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify,** including the migration test.
- [ ] **Step 5: Commit** `feat(integrations): add user-defined event rules per integration and event type`.

### Task 14: Webhook call log (backend, security)

**Files:**
- Create:
  - migration `20261110a5`: table `webhook_calls` with the §8.4 fields plus `response_body` (≤ 2 KiB, the hub's own answer), `redacted_paths: JSON` and `replay_of`;
  - `backend/app/models/webhook_call.py`;
  - `backend/app/inbox/webhook_log.py`;
  - `backend/app/api/routes/admin_webhook_calls.py`.
- Modify:
  - `backend/app/main.py`: install the middleware, and attach the access-log filter at app import;
  - `error_handlers.py`: add the prefix `/api/v1/admin/webhook-calls`;
  - the `cleanup_task` wiring.
- Test: `backend/tests/unit/inbox/test_webhook_redaction.py`, `backend/tests/unit/inbox/test_access_log_filter.py`, `backend/tests/integration/api/test_webhook_call_log.py`, `backend/tests/integration/test_uvicorn_access_log.py` (a subprocess; not marked `slow`)

**Interfaces:**
- Produces `redact(value) -> tuple[Any, list[str]]`.
  - It works recursively and returns the redacted value plus the paths it replaced.
  - A key equal to, or ending in, `token`, `key`, `secret`, `signature` or `password` (case-insensitive) gets the value `"[redacted]"`.
- Produces `redact_query(qs) -> str`, which drops `token`, and `bounded_payload(raw, content_type, *, limit) -> tuple[Any, bool]`.
- Produces `class WebhookLogMiddleware`, pure ASGI.
  - **Scope.** It covers paths under `/api/v1/webhook/`, and `POST /api/v1/inbox/items` when `X-Label-Hub-Key` is present.
  - **Before the app is called,** it puts a fresh mutable `CallNote` into the ContextVar `current_call`. Handlers only change fields of that object and never call `.set()` (review Minor 20). It captures the body (≤ 64 KiB), the status, the duration and up to 2 KiB of the response body.
  - **After the response,** it writes one record in a short session. Several rules hold at write time (C14):
    - a call without `key_id` that ends in `401`/`403` keeps at most 2 KiB of payload;
    - after the insert, rows beyond the newest 2,000 are deleted in the same session;
    - a failure to write the log is logged, and the response is unaffected.
- Produces `class StripQueryForWebhooks(logging.Filter)` (C13).
  - It works on uvicorn's access records, whose `args` are `(client_addr, method, full_path, http_version, status_code)`.
  - For `/api/v1/webhook/` paths it rewrites `full_path` without the query string.
  - It is attached to `logging.getLogger("uvicorn.access")` when `app.main` is imported. Uvicorn configures logging before it imports the app, so the filter survives that configuration.
- Produces `prune_webhook_calls(session_factory, *, now)`, which deletes records older than 14 days (daily).
- Routes, all `admin`:
  - `GET /api/v1/admin/webhook-calls`, with the filters `integration`, `outcome`, `since`, `until` and `cursor`. It returns 50 per page, newest first. The final status is joined live: `parked`, `printed`, `failed: <reason>`, `expired` or `removed`.
  - `GET …/{id}`.
  - `POST …/{id}/replay`. It is allowed only when `outcome == "rejected"`, `reason ∈ {integration_not_configured, no_tape_printer}`, and `redacted_paths` contains only auth fields (`token`); otherwise `422 not_replayable`. It runs under the original key id and sets `replay_of`.

- [ ] **Step 1: Write the failing tests:**
  - Redaction, one test per path:
    - `test_token_in_body_never_stored`, counter-test: make `redact` a no-op;
    - `test_token_in_query_never_stored`, counter-test: make `redact_query` a no-op.
  - Access log:
    - `test_filter_strips_query_from_uvicorn_shaped_record`, counter-test: remove the filter;
    - `test_filter_attached_to_uvicorn_access_after_import`;
    - `test_real_uvicorn_access_log_has_no_token`: start uvicorn as a subprocess with the module and arguments parsed from the `CMD` in `backend/Dockerfile`, on 127.0.0.1 with a random port and a temporary DB. Send a request with `?token=marker`; stderr must not contain `marker`. Counter-test: disable the filter; `marker` then appears.
  - `test_rejected_401_logged_without_key_id`.
  - `test_final_status_follows_line_to_printed`.
  - `test_2100_unauthenticated_calls_leave_at_most_2000_rows_without_sweep`, counter-test: drop the write-time trim.
  - `test_unauthenticated_payload_capped_2kib`.
  - `test_log_write_failure_does_not_fail_request`.
  - `test_note_set_by_threadpool_dependency_is_kept`.
  - `test_read_and_inbox_keys_403_on_log`.
  - `test_ui_session_inbox_add_not_logged`.
  - `test_replay_only_config_rejections_without_field_redaction`.
  - `test_prune_older_than_14_days`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify** with every counter-test and the migration test.
- [ ] **Step 5: Commit** `feat(webhooks): log every webhook call with built-in redaction and admin-only access`.

### Task 15: Grocy label route in Grocy's own format (security)

**Files:**
- Create:
  - `backend/app/schemas/grocy_label.py`;
  - `backend/app/inbox/php_form.py`;
  - `backend/app/inbox/grocy_label.py`;
  - `backend/app/api/routes/webhook_grocy_label.py`;
  - fixtures `backend/tests/fixtures/grocy_label/{product_form.txt, stock_entry_form.txt, stock_entry.json, no_details.json}`. The form fixtures are encoded the way PHP's `http_build_query` encodes them (bracket notation, the way Guzzle sends `form_params`). Their fields are those cited in §8.1, from Grocy 4.5's `WebhookRunner.php` and `GetProductDetails`.
- Modify:
  - `webhooks.py`: delete `/grocy` and `GrocyWebhookPayload`;
  - `registry.py`: add `integrations.grocy.webhook_cors_origin`;
  - `test_route_auth_coverage_guardrail.py`: add `_PUBLIC_BY_DESIGN` entries for `POST` and `OPTIONS` `/api/v1/webhook/grocy/label` with the reason "authenticates the token inside the handler; Grocy cannot send headers".
- Test: `backend/tests/unit/inbox/test_php_form.py`, `backend/tests/unit/inbox/test_grocy_mapping.py`, `backend/tests/integration/api/test_webhook_grocy_label.py`

**Interfaces:**
- Produces `parse_php_form(body: bytes) -> dict[str, Any]` (C16).
  - `a[b][c]=v` becomes nested dicts.
  - `a[]=v` becomes a list.
  - For repeated scalars the last value wins.
  - Nesting stops at depth 8 and at 1,000 keys; anything beyond is ignored.
- Produces `GrocyLabelPayload` with `extra="ignore"` and these fields:
  - `product`, `grocycode`, `due_date` (never parsed), `details: dict | None`;
  - `stock_entry: GrocyStockEntry | None`, holding `amount`, `best_before_date`, `location_id`, `note` and `stock_id`;
  - `token`, `printer`, `mode`.
- Produces `map_grocy_label(p, *, language) -> GrocyMapped(snapshot, item_ref, event_type, item_meta)`. It follows §8.1.2 with C11:
  - `item_ref` is the product id, taken from `details.product.id`, else from the grocycode's second field, else `None`.
  - `item_meta` holds `{grocycode, stock_id?}`.
  - The best-before line:
    - is taken from `stock_entry.best_before_date`, else from `details.next_due_date` (B39);
    - reads en `"Best before {YYYY-MM-DD}"`, de `"MHD {DD.MM.YYYY}"`;
    - is omitted for `2999-12-31`.
  - The amount reads `"{amount} {unit}"`, with the unit's singular or plural form from `details.quantity_unit_stock.name/name_plural`.
  - The location comes from `details.location.name`, the note from `stock_entry.note`.
  - Every value is cut to the bounds of `SheetRawLabelData`; a value is never refused.
- Route `POST /api/v1/webhook/grocy/label`:
  1. `read_capped_body(64 KiB)`.
  2. Parse: JSON, or `parse_php_form`.
  3. Take the token from the query, else from the body. An unknown token gives `401` with a fixed message; an `admin` token gives `403 token_scope_too_broad`.
  4. `evaluate`.
  5. Park or print:
     - **Park** through `InboxService.add_entries` with `origin=webhook`, `origin_detail="grocy"`, `origin_event` and `intended_printer_id`. The line is `snapshot_complete=False` and `on_incomplete` is called (§8.1.3).
     - **Print** through `submit_label` with the payload data and the rule's format.
  6. Answer `200 {outcome, item_id?, job_id?, reason?}`.
- The route never calls the Grocy plugin.
- Duplicates are caught by `RecentRequests(10)` over `(key id, request hash)`.
- CORS is answered only when the `Origin` header equals the setting, on `OPTIONS` and on `POST`. It allows `POST` only, sends no credentials, and allows the header `content-type`.
- The route fills `current_call`. The token never appears in logs, error bodies or idempotency rows.

- [ ] **Step 1: Write the failing tests:**
  - `test_php_form_nested_and_lists_last_wins`.
  - `test_php_form_depth_and_key_limits`.
  - `test_form_stock_entry_maps_to_stock_entry_event_with_best_before` (counter-test: a flat form parser classifies it as `grocy.product`).
  - `test_mapping_fixtures`.
  - `test_item_ref_is_product_id_meta_has_grocycode`.
  - `test_token_in_query_and_in_body`.
  - `test_no_header_needed`.
  - `test_route_never_calls_grocy_plugin`.
  - `test_answers_within_budget_with_plugin_hanging`.
  - `test_grocy_label_during_slow_print_answers_fast`: a tape print whose lookups hang runs alongside, and the call answers in under 0.5 s and parks. Counter-test: hold the lock across the resolve step of Task 5.
  - `test_identical_within_10s_duplicate`.
  - `test_admin_token_403`.
  - `test_mode_print_inbox_key_parks_reason`.
  - `test_mode_print_page_printer_parks`.
  - `test_token_never_in_caplog_or_body`.
  - `test_cors_only_configured_origin`.
  - `test_old_grocy_route_404`.
  - `test_grocy_label_awkward_payloads_park`.
  - `test_parked_line_incomplete_and_fill_scheduled`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement,** then `pnpm gen:api`.
- [ ] **Step 4: Verify,** including the counter-tests.
- [ ] **Step 5: Commit** in two steps: `feat(webhooks): accept Grocy's label webhook as it is and park or print by event rule`, then `refactor(webhooks): remove the unused JSON Grocy webhook`.

### Task 16: Grocy line resolution (C11)

**Files:**
- Create: `backend/app/inbox/grocy_lines.py`
- Modify: `backend/app/integrations/grocy/plugin.py`
- Test: `backend/tests/unit/integrations/test_grocy_stock_entry.py`, `backend/tests/integration/api/test_inbox_grocy_freshness.py`

**Interfaces:**
- Produces `GrocyPlugin.stock_entry(product_id: int, stock_id: str) -> GrocyStockEntry | None`.
  - It calls Grocy's `GET /api/stock/products/{productId}/entries` and filters the result by `stock_id`. The Grocy OpenAPI (`grocy.openapi.json`, master, checked on 2026-11-09) confirms the endpoint exists.
  - `GET /api/stock/entry/{entryId}` also exists, but it takes the numeric row `id`, and the label webhook does not document that field.
- Produces `GrocyPlugin.location_name(location_id: int) -> str | None`, read from `GET /api/objects/locations/{id}`.
- Produces `grocy_line_label(item: InboxItem, lookup: AppLookupService) -> LabelData`, registered in `LINE_RESOLVERS["grocy"]`.
  - **Steps.** It looks the product up by `item_ref` to get the name and default location. A stock-entry line also reads the stock entry for best-before, amount and location name. `qr_payload` and `primary_id` stay set to `item_meta.grocycode`, and the secondary lines use the format of Task 15.
  - **Missing entry.** When the stock entry is gone it raises `AppLookupNotFoundError`. Under `fresh_with_fallback` such a line prints from the snapshot, and refresh reports it as "deleted at source".
  - **Product-label lines.** The plain product lookup is used, but with the grocycode as the code.

- [ ] **Step 1: Write the failing tests:**
  - `test_grocy_stock_line_fresh_print_is_fresh_not_fallback`: under `fresh_with_fallback`, with a mocked Grocy, the job has `data_source == "fresh"` and `qr_payload == grocycode`. Counter-test: the default resolver gives `snapshot_fallback`.
  - `test_fresh_best_before_comes_from_stock_entry`.
  - `test_consumed_entry_is_deleted_at_source_in_refresh`.
  - `test_product_line_keeps_grocycode`.
  - `test_stock_entry_filters_by_stock_id`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify.**
- [ ] **Step 5: Commit** `feat(inbox): look Grocy lines up by product and stock entry and keep the grocycode`.

### Task 17: Background fill for incomplete lines

**Files:**
- Create: `backend/app/inbox/fill.py`
- Modify:
  - `backend/app/integrations/grocy/plugin.py`: `enrichment(...)`;
  - `main.py`: the filler on `app.state`, cancelled on shutdown, wired to `InboxService.on_incomplete`.
- Test: `backend/tests/unit/inbox/test_fill.py`, `backend/tests/unit/integrations/test_grocy_enrichment.py`

**Interfaces:**
- Produces `GrocyPlugin.enrichment(product_group_id, shopping_location_id, product_id) -> GrocyEnrichment(product_group_name, shopping_location_name, userfields, picture_file_name)`. It reads Grocy's `/objects/{entity}/{id}` and `/userfields/products/{id}`.
- Produces `IncompleteFiller.schedule(item_id)`, with at most 2 fills in flight. A fill is retried after 1, 5 and 30 minutes, then given up.
- What one run does:
  - It resolves the line through `LINE_RESOLVERS`, which gives Grocy lines the location name from Task 16.
  - For Grocy it stores the enrichment fields in `item_meta` (B40).
  - It writes **only** if the line's `version` is unchanged, and only after its network calls are done (C12). It then sets `snapshot_complete=True`, adds 1 to `version` and publishes `updated`.
  - If the plugin is not configured, it does nothing.

- [ ] **Step 1: Write the failing tests:**
  - `test_fill_replaces_location_line_and_marks_complete`.
  - `test_fill_skips_when_version_changed`. Counter-test: drop the version check.
  - `test_fill_unconfigured_plugin_leaves_line_printable`.
  - `test_generic_incomplete_filled_when_source_back`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify.**
- [ ] **Step 5: Commit** `feat(inbox): fill incomplete inbox lines in the background under a version guard`.

### Task 18: Spoolman webhook through event rules

**Files:**
- Modify:
  - `backend/app/api/routes/webhooks.py`: the Spoolman route also accepts `X-Label-Hub-Key` with `inbox` or more. It then:
    - calls `evaluate` for `spoolman.<type>`, with `auth=None` for the shared secret;
    - parks, prints or ignores;
    - deduplicates by `Idempotency-Key`, else within a 60 s window over `(app, spool_id, type)`;
    - does not use `quantity` as copies;
    - rate-limits the shared secret to 60 per minute through `rate_limiter` (B29).
  - `backend/app/schemas/webhook.py`: `WebhookOutcomeResponse`, answered with `202`.
  - The docstrings and the OpenAPI text.
- Test: `test_webhooks_routes.py`, `backend/tests/integration/api/test_webhook_spoolman_rules.py`

- [ ] **Step 1: Write the failing tests:**
  - `test_default_parks`.
  - `test_rule_print_reaches_queue_and_prints`.
  - `test_ipp_target_parks`.
  - `test_hub_key_inbox_scope_accepted`.
  - `test_quantity_not_copies`.
  - `test_shared_secret_61st_request_429`.
  - `test_idempotency_header_dedupes`.
  - `test_response_keeps_job_id_name`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify.** Counter-test: skip `evaluate` so the route always prints; `test_default_parks` turns red.
- [ ] **Step 5: Commit** `feat(webhooks): route Spoolman events through the event rules and park by default`.

### Task 19: Event rules UI and the Grocy setup panel

**Files:**
- Create: `frontend/src/features/settings/EventRules.tsx`, `GrocyWebhookPanel.tsx`, `backend/app/api/routes/grocy_setup.py`
- Modify: `frontend/src/features/settings/Integrations.tsx`
- Test: `EventRules.test.tsx`, `GrocyWebhookPanel.test.tsx`, `backend/tests/integration/api/test_grocy_setup.py`

**Interfaces:**
- Backend routes (`admin`):
  - `GET /api/v1/integrations/grocy/label-webhook` → `{url, cors_origin, last_call}`.
    - `url` is built from `general.public_url`.
    - `last_call` is the newest record from Task 14.
  - `POST /api/v1/integrations/grocy/label-test` runs the code path of Task 15 with a fixed sample payload: product "Sample product", grocycode `grcy:p:0:test`, caller `test`.
- Frontend: the section "Incoming events" (§7.3).
  - It has the integration default and one row per event type.
  - It notes that a page printer always collects, and blocks `print` with an IPP target.
- Frontend: the Grocy panel (§8.1.4a and C13).
  - The URL, with a Copy button.
  - "Create a Grocy key" (`POST /api/v1/admin/api-keys {name:"grocy", scopes:["inbox"]}`). The value is shown once.
  - A field to **paste an existing key**. A pasted or created key fills two copyable forms:
    - the `LABEL_PRINTER_PARAMS` form, marked as recommended;
    - the `?token=` URL.
  - The config block with `LABEL_PRINTER_WEBHOOK`, `LABEL_PRINTER_RUN_SERVER=true`, `LABEL_PRINTER_HOOK_JSON=true` and `FEATURE_FLAG_LABEL_PRINTER=true`, plus the server-mode note.
  - The CORS origin field.
  - "Send test label" and "Last call received".

- [ ] **Step 1: Write the failing tests:**
  - `test_panel_url_uses_public_url_not_host`.
  - `test_test_label_parks_with_default_rule`.
  - Vitest:
    - the key value appears only after create and is gone after a reload;
    - a pasted key fills both forms and is never sent to the server;
    - a rule row saves;
    - `print` with an IPP target is blocked with the reason.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** under the UI protocol, with en and de strings.
- [ ] **Step 4: Verify.**
- [ ] **Step 5: Commit** `feat(ui): configure incoming event rules and the Grocy label webhook in the settings`.

### Task 20: Webhook log UI

**Files:**
- Create: `frontend/src/features/settings/WebhookLog.tsx`, `WebhookCallDetail.tsx`
- Modify: the settings sections and the integration page (a filtered view)
- Test: `WebhookLog.test.tsx`

- [ ] **Step 1: Write the failing tests:**
  - the columns: time, integration, event, source, outcome, final status and duration;
  - rejected rows are highlighted;
  - the filters set the query string;
  - the detail view shows the payload and the stored response as text in a `<pre>`, and a taint payload is not markup;
  - Replay appears only for replayable records;
  - sessions without admin rights do not see the page.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** under the UI protocol.
- [ ] **Step 4: Verify.**
- [ ] **Step 5: Commit** `feat(ui): show the webhook call log with payload detail and replay`.

### Task 21: Docs, decision register and release notes

**Files:**
- Modify:
  - `README.md`;
  - `docs/`: the API keys page (the `inbox` scope), the integrations page (Grocy label webhook setup, the token warning, and that proxies log query strings so the body field is preferred), the webhooks page, and a page on the print inbox;
  - `docs/decisions/register.md`: the four rows from §15;
  - the release notes source (§16).

- [ ] **Step 1:** Write the docs and the four register rows.
- [ ] **Step 2:** Write the release notes per §16. They include the follow-up note that read keys still cannot sign in to the browser (C15).
- [ ] **Step 3: Commit** `docs: document the print inbox, the inbox scope and the Grocy label webhook`.

**PR 3 gate:** run the full gate and the e2e tests, then the security audit focused on Tasks 14–16 (token taint, redaction, CORS, the flood cap). Then open the PR against the milestone branch. The release is cut from the milestone branch once all three PRs are in.

---

## Spec gaps found while planning

The spec is amended for each of these.

- **G1** `item_meta` was missing. Spec §5.1 is amended by C11.
- **G2** "The same transaction" was not achievable. Spec §6.5 is amended by C12.
- **G3** `data_source` of a page job. Spec §9 is amended: the worst value goes on the row, and the value per cell goes into the payload.
- **G4** The expired notice has no store before #255. The plan keeps it in `inbox_state`, with a read mark per device (this is the interim).
- **G5** The resolver is synchronous. Spec §11.4 is amended: the resolver always goes to the cart, which redirects when the inbox is empty.
- **G6** `sheet_type` on the render route. Spec §6.4 is amended.
- **G7** (review C-2) Grocy lines could not be looked up again. Spec §5.1, §8.1.2 and §9 are amended by C11.
