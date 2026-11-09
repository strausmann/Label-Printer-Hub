# API v1, Live Printer Wiring and Installable PWA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every API route lives under `/api/v1/`. A printer added, changed, enabled or disabled at runtime is wired, polled and printable without a restart. The web app installs behind an SSO proxy.

**Architecture:**
- **#226 (route move).** It changes router prefixes in place and adds a guard test over `app.routes`. The frontend keeps literal paths, rewritten to `/api/v1/…` and guarded by a source scan.
- **#224 (live wiring).** The per-printer wiring that `main.py`'s lifespan does once at startup moves into a `PrinterRuntime` service. The lifespan and the admin routes both call it, so startup and runtime share one code path.
- **#225 (installable PWA).** One attribute on the manifest link.

**Tech Stack:** FastAPI, SQLModel/SQLite, asyncio, pytest; React + Vite + vitest + Playwright.

**Spec:** the issues are the spec:
- #226 https://github.com/strausmann/Label-Printer-Hub/issues/226
- #224 https://github.com/strausmann/Label-Printer-Hub/issues/224
- #225 https://github.com/strausmann/Label-Printer-Hub/issues/225

Maintainer rulings of 2026-11-09:
- no backwards compatibility for moved paths;
- release stays 1.x;
- #224 is solved by live wiring, not by a self-restart.

## Global Constraints

- **Repo rules.** Public repo: English identifiers, comments and commits, Conventional Commits, no AI attribution. Never `git add -A`.
- **Release.** Release stays 1.x. Commits use `feat`/`fix`/`refactor`/`test`/`docs` and **no** `BREAKING CHANGE:` footer, and no `!`.
- **Route layout.** Every API route is under `/api/v1/`. The only unversioned paths allowed are:
  - `/healthz` and `/readiness`;
  - `/docs` and the docs bundle route from `app/web/api_docs.py`;
  - `/openapi.json`;
  - the QR deep links `/loc/{entity_id}`, `/asset/{entity_id}`, `/spool/{entity_id}` and `/product/{entity_id}`;
  - the SPA catch-all from `app/web/spa.py`;
  - the e2e-only control routes under `/__e2e/`, which exist only in `tests/e2e_app.py`.
- **No aliases.** No alias, redirect or duplicate of an old path. Old paths answer what any unknown path answers.
- **Tests.** Every regression test must go red against the unfixed code. Run that counter-test once and record it in the task report.
- **Backend checks.** `ruff check .`, `ruff format --check .`, `mypy app/`, `pytest -m "not slow" --cov=app --cov-fail-under=80`.
- **Frontend checks.** `pnpm typecheck`, `pnpm lint`, `pnpm test:coverage`, `pnpm build`, `pnpm e2e`.
- **Generated schema.** `frontend/src/api/schema.gen.ts` is regenerated with `pnpm gen:api`, never edited by hand.
- **Agent limits.** Commands under 170 s each. Run tests per file or per directory; the full suite runs only in the gate.

## Review Focus

1. **An admin change while a job prints on that printer.** The in-flight job finishes or fails exactly as it does at shutdown. It is never lost or duplicated, and its cells/reservation state is not orphaned (Task 6 test `test_update_during_inflight_job_keeps_job`).
2. **Two admin calls on the same printer at the same time** (double click, two tabs). The wiring ends in the state of the last committed DB row. There is no second producer and no leaked worker (Task 6 test `test_concurrent_reconcile_single_producer`).
3. **A printer whose stored connection cannot be wired** (bad URI, SNMP host down). The admin call still succeeds because the DB row is committed. The printer shows offline, and the hub keeps running (Task 5 test `test_attach_bad_uri_degrades`).
4. **A browser on an old tab that still calls `/api/…` after the update.** It gets the normal unknown-path answer, `404` JSON for a reserved `api/` prefix, and the SPA shows its error state rather than a blank page (Task 3 e2e `old api path is a plain 404`).
5. **SPA client routes that collided with the legacy root API routes** (`/jobs/{id}`, `/print`). After the move, a reload on such an SPA URL serves `index.html` (Task 2 test `test_spa_owns_former_legacy_paths`).

---

## Task 1: Installable PWA behind an auth proxy (#225)

**Files:**
- Modify: `frontend/index.html` (manifest link)
- Test: `frontend/src/build.test.ts` (extend; it already reads the built `index.html`) or a new `frontend/src/manifest-link.test.ts` that reads `frontend/index.html`

**Interfaces:** none.

- [ ] **Step 1: Write the failing test** `manifest link is fetched with credentials`. Read `frontend/index.html`, parse it with `DOMParser`, and assert:
  - exactly one `link[rel="manifest"]` exists;
  - its `href` is `/manifest.webmanifest`;
  - its `crossorigin` attribute is `use-credentials`.
  A comment on the test states what a text check cannot see, namely whether the browser actually sends the cookie. That part is covered by Step 4.
- [ ] **Step 2: Run** `pnpm exec vitest run <test file>`. Expect it to FAIL because `crossorigin` is null.
- [ ] **Step 3: Implement.** Add `crossorigin="use-credentials"` to the manifest link in `frontend/index.html`.
- [ ] **Step 4: Verify.** The test passes. In the e2e suite, add a check in an existing spec: the request for `/manifest.webmanifest` carries the session cookie (`page.waitForRequest` + `request.headers()["cookie"]` contains the session cookie name).
- [ ] **Step 5: Commit**

```bash
git add frontend/index.html <test files>
git commit -m "fix(ui): load the web app manifest with credentials so the hub installs behind SSO (#225)"
```

## Task 2: Backend routes under /api/v1 and the route guard (#226)

**Files:**
- Create: `backend/tests/api/test_route_versioning.py`
- Modify:
  - router prefixes in `backend/app/api/routes/`: `admin_api_keys.py`, `batch.py`, `batches.py`, `calibration.py`, `capabilities.py`, `info.py`, `jobs.py`, `lookup.py`, `print.py`, `printers.py`, `sheet_print.py`, `sheet_types.py`, `sheets.py`, `webhooks.py`;
  - every backend test that names an old path (about 565 literals in 43 files under `backend/tests/`).
- Do not touch: `qr.py`, `/healthz`, `/readiness`, `app/web/*`.

**Path map** (the old path drops `/api` where present, then the new one is `/api/v1` + rest):

| Old | New |
|---|---|
| `/api/admin/api-keys…` | `/api/v1/admin/api-keys…` |
| `/api/printers…` (printers, calibration, capabilities) | `/api/v1/printers…` |
| `/api/jobs…` | `/api/v1/jobs…` |
| `/api/batches/{batch_id}` | `/api/v1/batches/{batch_id}` |
| `/api/print/{printer_key}/batch`, `…/sheet`, `…/sheet/preview` | `/api/v1/print/{printer_key}/…` |
| `/api/render/preview` | `/api/v1/render/preview` |
| `/api/lookup/{app}/{entity_id}` | `/api/v1/lookup/{app}/{entity_id}` |
| `/api/sheet-types…`, `/api/sheets…`, `/api/sheet-cells` | `/api/v1/…` |
| `/api/webhook/spoolman`, `/api/webhook/grocy` | `/api/v1/webhook/spoolman`, `/api/v1/webhook/grocy` |
| `/api/info` | `/api/v1/info` |
| `POST /print` (legacy root) | `POST /api/v1/print` |
| `POST /printer/resume` (legacy root) | `POST /api/v1/printer/resume` |
| `GET /jobs/{job_id}` and `POST /jobs/{job_id}/resume` (legacy root) | **deleted** — duplicates of `/api/v1/jobs/{job_id}` and `/api/v1/jobs/{job_id}/resume` |

Ruling on the two deleted legacy routes:
- Moving them would collide with `jobs.py` under the same new prefix.
- Before deleting, compare each handler with its `jobs.py` counterpart (response model, status codes, auth scope). If the legacy one returns something the `jobs.py` one does not, report it as `DONE_WITH_CONCERNS` and do not delete. The controller rules on it.
- Their tests move to the `jobs.py` routes or are dropped as duplicates; say which in the report.

**Interfaces:**
- Produces: the path map above, which is the contract Tasks 3, 4 and 6 use.
- Produces: `ALLOWED_UNVERSIONED: frozenset[str]` in the guard test, which holds the route path templates from Global Constraints.

- [ ] **Step 1: Write the failing guard** `test_every_api_route_is_versioned`:
  - Build the app the way the existing API tests do.
  - Walk `app.routes`. For each `APIRoute`/`Route` with a `path`, assert `path.startswith("/api/v1/")` or `path in ALLOWED_UNVERSIONED`.
  - The failure message lists every offending path with its methods.
  - Second test `test_allow_list_has_no_dead_entries`: every `ALLOWED_UNVERSIONED` entry exists in `app.routes`, so the list cannot rot.
  - Third test `test_spa_owns_former_legacy_paths`: with a built-SPA fixture (as in the existing SPA tests), `GET /jobs/123` and `GET /print` return `index.html` (200, `text/html`).
- [ ] **Step 2: Run** `pytest tests/api/test_route_versioning.py -v`. Expect a FAIL that lists about 60 paths.
- [ ] **Step 3: Implement.** Change the prefixes per the path map, move the two legacy routes and delete the two duplicates. Update the `print.py` module comment, which claims the legacy routes exist for backwards compatibility. Rewrite the path literals in `backend/tests/` with the map. Grep the old forms afterwards; zero hits are expected outside this plan and the changelog:

```bash
grep -rnE '"/api/(printers|jobs|batches|lookup|print|sheets|sheet-types|sheet-cells|render|info|admin/api-keys|webhook)' backend/
```

- [ ] **Step 4: Verify.** The guard passes. Then run per directory, each under 170 s: `pytest tests/api`, `pytest tests/integration -m "not slow"`, `pytest tests/unit`. Also run `ruff check .`, `ruff format --check .` and `mypy app/`.
- [ ] **Step 5: Commit**

```bash
git add <changed files, listed explicitly>
git commit -m "feat(api): serve every API route under /api/v1 (#226)"
```

## Task 3: Frontend on /api/v1 (#226)

**Files:**
- Modify:
  - every `frontend/src/**` and `frontend/e2e/**` file with an old path literal (see Task 2 map). Template literals count too: `` `/api/sheets/${…}` ``, `` `/api/print/${…}` ``, `` `/api/printers/${…}` ``, `` `/api/jobs/${…}` ``;
  - `frontend/src/api/schema.gen.ts` via `pnpm gen:api`;
  - the e2e fixtures in `frontend/e2e/fixtures.ts` and the route mocks in `jobs.spec.ts`, `printers.spec.ts`, `settings.spec.ts` and `calibration.spec.ts`.
- Create: `frontend/src/api/paths.test.ts` (source guard).

**Interfaces:**
- Consumes: the Task 2 path map.

- [ ] **Step 1: Write the failing guard** `no unversioned API path in the frontend source`:
  - Glob `src/**/*.{ts,tsx}` and `e2e/**/*.ts`, excluding `schema.gen.ts` and this test file.
  - Fail on every match of `/(["'\`])\/api\/(?!v1\/)/`, and report file:line.
  - A comment states what it cannot see: paths built by string concatenation without the `/api/` literal, and paths inside strings that are not URLs. It also states why no behaviour test can do this: there are 28 `apiFetch` call sites plus links and `EventSource`, with no central URL builder.
  - Second test `old api path is a plain 404` in an existing e2e spec: `await request.get('/api/printers')` returns 404 and JSON (not `index.html`).
- [ ] **Step 2: Run** `pnpm exec vitest run src/api/paths.test.ts`. Expect a FAIL that lists the files.
- [ ] **Step 3: Implement.** Rewrite the literals and run `pnpm gen:api`. Do not add a URL-prefix helper; the guard is the enforcement (YAGNI).
- [ ] **Step 4: Verify.** Run `pnpm typecheck`, `pnpm lint`, `pnpm test:coverage`, `pnpm build`, then `pnpm e2e` in blocks per spec under 170 s.
- [ ] **Step 5: Commit**

```bash
git add <changed files, listed explicitly>
git commit -m "feat(ui): call the API under /api/v1 (#226)"
```

## Task 4: Docs for /api/v1 (#226)

**Files:**
- Modify:
  - `README.md`;
  - every file under `docs/` that names an old path (about 35 files), **except** historical plans/specs under `docs/superpowers/` that describe a past state. Those get no rewrite. Instead, a one-line note goes at the top of the sheet-archive spec §15 tables: "Paths below predate #226; all API paths are now under `/api/v1/`.";
  - ADRs that state the route layout: add an "Amended 2026-11-09 (#226)" line, never rewrite the decision;
  - the integration setup docs that tell operators the Grocy/Spoolman webhook URL.

**Interfaces:**
- Consumes: the Task 2 path map.

- [ ] **Step 1: Find** with `grep -rnE '/api/(printers|jobs|batches|lookup|print|sheets|sheet-types|sheet-cells|render|info|admin/api-keys|webhook)|"/print"|/printer/resume' README.md docs/`. Classify each hit as current docs (rewrite) or history (leave, or add a note).
- [ ] **Step 2: Rewrite** the current docs per the map. Add a "Moved API paths (1.5.0)" section to `README.md` with the full map table, so operators with scripts can follow.
- [ ] **Step 3: Verify.** Re-run the grep. Every remaining hit is history, and you list them in the report.
- [ ] **Step 4: Commit**

```bash
git commit -m "docs: document the /api/v1 paths and the moved routes (#226)"
```

## Task 5: PrinterRuntime — one code path for wiring a printer (#224)

**Files:**
- Create: `backend/app/services/printer_runtime.py`
- Modify:
  - `backend/app/services/print_queue.py`: add the add/remove methods below;
  - `backend/app/main.py`: the lifespan uses `PrinterRuntime` for every enabled printer instead of its inline loops, roughly lines 395–660 at 1.4.0.
- Test: `backend/tests/unit/services/test_printer_runtime.py`, `backend/tests/unit/services/test_print_queue_membership.py`

**Interfaces:**
- **Produces, in `print_queue.py`:**
  - `PrintQueue.add_printer(printer: _PrinterLike) -> None`
  - `PrintQueue.add_page_printer(printer: PagePrinter) -> None`
  - `async PrintQueue.remove_printer(printer_id: UUID, timeout_s: float) -> None`

  Membership rules:
  - Add is idempotent for an id already present only if it is the same object; otherwise it raises `ValueError`. When the queue is running, add creates the worker at once.
  - Remove stops accepting work for that id, lets the in-flight job end the way `stop()` lets it end (same timeout semantics), cancels the worker and drops the per-printer dicts.
  - Queued, not-started jobs stay persisted and are not failed. They are recovered on the next add, the same way `start()` recovers persisted jobs, through `enqueue_persisted`.
- **Produces, in `printer_runtime.py`:**
  - `class PrinterRuntime` with
    - `async attach(printer: Printer) -> None`
    - `async detach(printer_id: UUID) -> None`
    - `async reconcile(printer_id: UUID) -> None`, which reads the row and then detaches, then attaches if the row is enabled
    - `async stop() -> None`
  - It owns: the tape `BackendRouter` registration and `PrintService` per tape printer, the `IppClient`/`IppPrinterState`/`IppPagePrinter` per page printer, the producers (`StatusProbeProducer` with `TapeChangeProducer` for tape printers with `snmp.discover`, `IppStatusProducer` for page printers), `app.state.slug_to_printer_id` and `app.state.ipp_printer_states`, and the "first tape printer" back-compat fields `app.state.print_service`, `printer_id`, `printer_host` and `printer_snmp_community`. Those fields are recomputed after every attach/detach with the same rule as today: the first enabled tape printer by the current ordering, or `None`.
  - All public methods serialise on one `asyncio.Lock`.
  - `attach` starts the producer and triggers one immediate probe (`probe_once()` for IPP, the equivalent first probe for SNMP) before returning. That way a new printer has status right away, without waiting a full `sse_probe_interval_s`.
  - A wiring failure is logged with the slug and the exception type only (never the URI) and leaves the printer detached. `attach` does not raise. This is the same degraded behaviour the startup has today.
- **Consumes:** the existing constructors exactly as `main.py` calls them at 1.4.0, including `ipp_transport_factory` from `app.state`, `ModelRegistry` model resolution via `_resolve_model_id_from_config`, `tape_registry`, `event_bus`, `job_store`, `shared_engine`, `settings.sse_probe_interval_s` and `_IPP_PROBE_CONCURRENCY`.

- [ ] **Step 1: Write the failing tests.**
  - **Queue membership** (`test_print_queue_membership.py`):
    - `test_add_page_printer_accepts_jobs_while_running`: start the queue with no printers, add a fake page printer, submit a page job, and the job reaches `done`.
    - `test_remove_printer_finishes_inflight_job`: a fake printer blocks on an event; remove while it is printing; release; the job ends `done` and the worker is gone.
    - `test_remove_keeps_queued_jobs_persisted`: a queued job is still in the store with state `queued` after remove, and is recovered after add.
    - `test_add_same_id_different_object_raises`.
  - **Runtime** (`test_printer_runtime.py`, with the fake IPP transport already used in `tests/`):
    - `test_attach_ipp_probes_immediately`: after `attach`, the status cache has `captured_at` set, with no sleep.
    - `test_attach_tape_with_snmp_starts_producer`: patched SNMP.
    - `test_detach_stops_probes`: no further requests on the fake transport after detach plus one interval.
    - `test_reconcile_uri_change_probes_new_address`.
    - `test_reconcile_disabled_row_detaches`.
    - `test_attach_bad_uri_degrades`: no raise, printer absent from `ipp_printer_states`, and the warning log has no URI.
    - `test_first_tape_printer_backcompat_recomputed`.
- [ ] **Step 2: Run them.** Expect FAILs, because the methods and the module do not exist yet.
- [ ] **Step 3: Implement** the queue methods and `PrinterRuntime`. Then switch the lifespan to construct `PrinterRuntime`, `attach` every enabled printer and `stop()` it on shutdown.
  - The existing lifespan tests must pass unchanged in behaviour: degraded start, empty table, and the shutdown order. The queue still stops after the producers.
  - `shutdown_wait_s` gets its timeouts from the runtime's current printers.
- [ ] **Step 4: Verify.** The new tests pass. Then run `pytest tests/unit tests/integration -m "not slow"` per directory, plus `mypy app/` and ruff.
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(printers): wire printers through one runtime used at startup and on change (#224)"
```

## Task 6: Admin changes take effect live (#224)

**Files:**
- Modify: `backend/app/api/routes/admin_printers_api.py`. After the DB commit in `create_printer`, `update_printer`, `disable_printer` and `enable_printer`, and before `_publish_changed`, it calls `await request.app.state.printer_runtime.reconcile(printer.id)`.
- Modify: the frontend printer admin view, only if it shows a "restart required" or similar hint today. Check this with grep, and remove such a hint if it exists.
- Test: `backend/tests/integration/api/test_printer_live_wiring.py`

**Interfaces:**
- Consumes: `PrinterRuntime.reconcile` (Task 5); the Task 2 paths (`/api/v1/admin/printers…`, `/api/v1/printers/{id}/status`, `/api/v1/printers/{id}/capabilities`, `/api/v1/print/{printer_key}/sheet`).

- [ ] **Step 1: Write the failing integration tests**, against the full app with the fake IPP printer and no restart between steps:
  - `test_created_ipp_printer_has_status_without_restart`: `POST /api/v1/admin/printers` (IPP), then `GET /api/v1/printers/{id}/status` has `online: true`, `printer_state` set and `captured_at` not null. `GET …/capabilities` has `resolution_dpi.max` set.
  - `test_created_ipp_printer_prints_without_restart`: a calibration page job (`POST /api/v1/printers/{id}/calibration/{tray}/page`) reaches `done` on the fake printer.
  - `test_disable_stops_polling_and_refuses_jobs`: after `POST …/disable`, the fake printer sees no further requests, and a new page job is refused with a 4xx (pin the exact `error_code` the route returns for a printer the queue does not know; #167 notes the disabled flag itself is not enforced today, so this test is what enforces it now).
  - `test_enable_restores_polling`.
  - `test_update_uri_moves_polling` (two fake printers).
  - `test_update_during_inflight_job_keeps_job`: Review Focus 1.
  - `test_concurrent_reconcile_single_producer`: Review Focus 2. Two `PUT`s at the same time with `asyncio.gather`; afterwards exactly one producer runs for the id. Assert this through the runtime's producer map size, and through one probe per interval on the fake.
  - `test_tape_printer_created_with_snmp_discover_has_status`: patched SNMP.
- [ ] **Step 2: Run them.** Expect FAILs: status is null and the job is refused, because the queue does not know the printer.
- [ ] **Step 3: Implement** the four route hooks.
- [ ] **Step 4: Verify.** The tests pass. Run the counter-test: remove the `reconcile` call and the tests go red for the right reason (null status or job refused, not an import error). Then run `pytest tests/api tests/integration -m "not slow"` per directory.
- [ ] **Step 5: Commit**

```bash
git commit -m "fix(printers): apply printer create, update, enable and disable without a restart (#224)"
```

## Gate, review and shipping (controller)

1. Run the full gate in a frozen clone, with no parallel load: backend `pytest -m "not slow" --cov=app --cov-fail-under=80`, ruff and mypy; frontend typecheck, lint, test:coverage, build and e2e.
2. Whole-branch review with the four lenses.
   - **Taint:** the IPP URI and host must never reach logs or non-admin responses through the new runtime.
   - **Runtime/temporal:** the reconcile lock, the shutdown order and in-flight jobs.
3. Run the `security-audit` skill on the changed surface. Focus on the admin routes now triggering outbound connections and on the moved webhook and lookup routes.
4. PR with Codex review, then merge.
5. **Release and rollout,** in the same maintenance window, in this order:
   1. Back up the DB.
   2. Release 1.5.0 (`workflow_dispatch`) and bump the Kept pin.
   3. Hangar companion PR (`internal/hub/client.go`: `/api/render/preview`, `/api/print/{slug}/batch`, `/api/printers?slug=`, `/api/printers`, `/api/printers/{uuid}/status`, `/api/batches/{id}` → `/api/v1/…`), released right after.
   4. Change the webhook targets in Grocy and Spoolman to `/api/v1/webhook/grocy` and `/api/v1/webhook/spoolman`, if configured.
   5. The release notes list the path map.
