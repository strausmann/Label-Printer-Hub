# API v1, Live Printer Wiring, Status Truth, Tape Colour and Test Print — Implementation Plan (1.5.0)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Revision 2 (2026-11-09)

Revised after the independent plan review of `56f0683`. Where each finding went:

| Finding | Handled in |
|---|---|
| B1 vacuous route guard | Task 2: shared `iter_routes` helper in `tests/helpers/routes.py`, known-route sanity assertion, counter-test on current code |
| B2 queued jobs lost on remove/add | Task 5: `remove_printer` purges every per-printer entry incl. `_jobs`; `_recover_printer(printer_id)` shared by `start()` and the add methods |
| B3 tape remove prints the backlog | Task 5: per-printer stop set, checked after dequeue and in the pause loop of both workers |
| I1 legacy job routes | Task 2: both deleted, reasoning recorded; `jobs.py` 501 resume stub left as is |
| I2 `spa.py` must change | Task 2: `_BrowserJobLinks`/`_JOB_LINK` removed, three SPA tests named |
| I3 SPA test green for `/print` | Task 2: test asserts only `GET /jobs/123` |
| I4 `/__e2e/` not a route | Global Constraints + Task 2: removed from the allow-list; `/docs/scalar.js` named |
| I5 non-router path literals, grep blind spots, prefix-less routers | Task 2: `error_handlers.py`, `auth/dependencies.py:66`, decorator-path routers, widened greps incl. `scripts/` |
| I6 examples, dev, scripts, live webhook resource | Task 4 + Rollout step 3 |
| I7 redundant immediate probe | Task 6: no probe in `attach`; t=0 probe verified with file:line |
| I8 missing runtime pieces | Task 6: `BackendRouter.register/unregister`, manual pause kept, startup-fatal vs runtime-degraded, patch targets, shutdown, `created_at` order |
| I9 global lock, cancellation, needless re-wire | Task 6/7: per-printer lock, `asyncio.shield`, `wiring_key` skip, tests |
| I10 existing probe-pinning tests | Task 7: `test_admin_printers_ipp.py` tests named, `hub` fixture + `Hub.override` |
| I11 Task 1 e2e cannot work | Task 1: new `manifest-link.test.ts`, CDP `Page.getAppManifest`, `allHeaders()`, icons, service worker note |
| M1–M9 | M1 Task 3 regex; M2 Task 7 files; M3 Task 7 note; M4 Task 7 assertion; M5 Task 5 note; M6 Task 7 comment; M7 Release notes; M8 Task 6 line range; M9 Task 4 grep |
| New: #227, #228, #229 | Tasks 0, 8–13 |

Rulings made while revising (not in the review or the controller notes) are marked **(R2 ruling)** in the text.

---

**Goal:** Release 1.5.0 in which every API route lives under `/api/v1/`, printer admin changes take effect live, the web app installs behind SSO, a stale status never shows as Ready, tape colour is shown truthfully, and every printer has a test print.

**Architecture:**
- **#226.** Router prefixes/decorator paths move in place; a guard over the flattened route tree and a frontend source scan enforce it.
- **#224.** The per-printer wiring from the lifespan moves into `PrinterRuntime`, used at startup and by the admin routes. `PrintQueue` gains add/remove with a shared per-printer recovery.
- **#225.** One attribute on the manifest link.
- **#227.** A freshness rule (`status_freshness.py`) applied in the status route; UI renders stale and unpolled printers as such.
- **#229.** One status-cache schema for tape printers, a stored roll record per printer with roll-change detection, an endpoint and SSE event, UI prompt.
- **#228.** One endpoint that builds a tape label or a test page and submits it through the normal queue.

**Tech Stack:** FastAPI 0.162 / Starlette 1.10, SQLModel/SQLite, Alembic, asyncio, pytest; React + Vite + vitest + Playwright, lingui.

**Spec:** the issues, with comments:
- #224 https://github.com/strausmann/Label-Printer-Hub/issues/224
- #225 https://github.com/strausmann/Label-Printer-Hub/issues/225
- #226 https://github.com/strausmann/Label-Printer-Hub/issues/226
- #227 https://github.com/strausmann/Label-Printer-Hub/issues/227
- #228 https://github.com/strausmann/Label-Printer-Hub/issues/228
- #229 https://github.com/strausmann/Label-Printer-Hub/issues/229

Maintainer rulings of 2026-11-09:
- no backwards compatibility for moved paths; release stays 1.x; all six issues ship in 1.5.0;
- #224 is solved by live wiring, not a self-restart;
- #229: PT colour is read automatically if the hardware allows it over the network; the QL asks once on a detected roll change (width or media type differs), remembers it until the next change, "skip" means no colour line; "Colour not reported" disappears; if the PT cannot report colour over the network, it uses the same ask-on-change flow;
- release notes say installed clients keep old paths until the service-worker update prompt is accepted.

## Global Constraints

- **Repo rules.** Public repo: English identifiers, comments and commits, Conventional Commits, no AI attribution. Never `git add -A`; stage explicit paths and read `git status --short` before each commit.
- **Release.** 1.5.0. Commits use `feat`/`fix`/`refactor`/`test`/`docs`, **no** `BREAKING CHANGE:` footer, no `!`.
- **Route layout.** Every API route is under `/api/v1/`. `ALLOWED_UNVERSIONED` holds exactly:
  - `/healthz`, `/readiness`, `/openapi.json`;
  - `/docs` and `/docs/scalar.js` (`BUNDLE_URL`, `app/web/api_docs.py:101`);
  - `/loc/{entity_id}`, `/asset/{entity_id}`, `/spool/{entity_id}`, `/product/{entity_id}`;
  - the SPA catch-all `/{full_path:path}` (present only when a dist exists).
  - `/__e2e/` is **not** in the list: it is served by the `E2EApp` ASGI wrapper (`tests/e2e_app.py:208`), never by `app.routes`; `tests/unit/test_e2e_control_not_in_production.py` covers it.
- **No aliases.** No alias, redirect or duplicate of an old path.
- **Tests.** Every regression test goes red against the unfixed code. Run that counter-test once and record it in the task report.
- **Backend checks.** `ruff check .`, `ruff format --check .`, `mypy app/`, `pytest -m "not slow" --cov=app --cov-fail-under=80` (gate only; per directory otherwise).
- **Frontend checks.** `pnpm typecheck`, `pnpm lint`, `pnpm test:coverage`, `pnpm build`, `pnpm e2e` (per spec).
- **Generated schema.** `frontend/src/api/schema.gen.ts` only via `pnpm gen:api`. CI checks drift (`.github/workflows/ci.yml:173-174`).
- **i18n.** Every new UI string in `frontend/src/i18n/locales/en/messages.po` and `de/messages.po`; German with real umlauts. Removed strings are removed from both catalogs.
- **UI task protocol (Tasks 7, 8, 11, 13).** Before writing UI code load the design skills `taste-skill:design-taste-frontend`, `emil-design-eng`, `mobile-native`, `break-ui`; at the end of the task run `impeccable:impeccable` on the changed screens. Take Playwright screenshots (light and dark, 1280 px and 390 px) with the existing `SHOTS` pattern (`frontend/e2e/shell.spec.ts:35`) as artifacts, not as a gate; attach them to the task report.
- **Agent limits.** Commands under 170 s each; no full suite outside the gate.

## Review Focus

1. **An admin change while a job prints on that printer.** The in-flight job finishes; jobs queued behind it stay `queued` and print after re-add; nothing is duplicated (Task 5 `test_remove_two_waiting_jobs_stay_queued`, Task 7 `test_update_during_inflight_job_keeps_job`).
2. **Two admin calls on the same printer at once.** The wiring ends in the state of the last committed row; one producer; no leaked worker (Task 7 `test_concurrent_reconcile_single_producer`).
3. **A printer whose stored connection cannot be wired at runtime** (bad URI, unresolvable tape model). The admin call succeeds, the printer is detached and degraded, the hub keeps running (Task 6 `test_attach_bad_uri_degrades`, `test_attach_unresolvable_tape_model_degrades_at_runtime`).
4. **A printer that has not been probed for days** (producer dead, printer disabled, hub clock jump). The UI never says Ready; it says the status is unknown and how old it is (Task 8 `test_status_older_than_bound_is_stale`, `describePrinter stale row is not ready`).
5. **A roll swapped while the hub was down.** The stored identity differs from the first probe after start; the colour is cleared and the prompt raised once, not on every probe (Task 10 `test_first_probe_after_restart_detects_change_once`).

---

## Ledger

| Item | Result |
|---|---|
| Task 0 spike: PT colour over the network | _to be filled by Task 0: `A` (method + evidence) or `B` (not possible)_ |

---

## Task 0: Spike — can the hub read PT tape/text colour over the network? (#229)

One question, time box 30 min, no production code. Live printer: the networked PT-P750W from the #229 comment (address from the operator, never written into the repo).

- [ ] **Step 1:** Walk the Brother private MIB read-only: `snmpwalk -v1 -c <community> <host> 1.3.6.1.4.1.2435` and look for a media/tape colour value. Change the loaded tape (if the operator can) and diff the walks.
- [ ] **Step 2:** Retry `ESC i S` on TCP 9100 with: (a) invalidate `0x00`×200 + `ESC @` + `ESC i S` in one write, read with 10 s timeout; (b) a print-free raster session start `ESC i a 0x01` (raster mode) before `ESC i S`; (c) keep the connection open after a successful SNMP poll. Record bytes received per variant.
- [ ] **Step 3:** Write the ledger row: **A** = method + the OID or framing + one captured answer (no host/IP) and the mapping to colour codes; **B** = "not possible over the network", with what was tried.
- [ ] **Step 4:** Commit only the ledger row: `docs(plan): record PT colour spike result (#229)`.

Branch rule: Tasks 9–11 have an **A** and a **B** variant where it matters; implement only the one the ledger names.

## Task 1: Installable PWA behind an auth proxy (#225)

**Files:**
- Modify: `frontend/index.html`
- Create: `frontend/src/manifest-link.test.ts` (reads `frontend/index.html`; not `build.test.ts`, which is `skipIf(!dist)` at `:7-17`)
- Modify: `frontend/e2e/shell.spec.ts` (manifest cookie check)

- [ ] **Step 1: Failing unit test** `manifest link is fetched with credentials`: parse `index.html` with `DOMParser` (jsdom, `vite.config.ts:63`); assert exactly one `link[rel="manifest"]`, `href === "/manifest.webmanifest"`, `getAttribute("crossorigin") === "use-credentials"`. Comment: a text check cannot see whether the browser sends the cookie; the e2e check does.
- [ ] **Step 2: Run** `pnpm exec vitest run src/manifest-link.test.ts` → FAIL (`crossorigin` is null).
- [ ] **Step 3: Implement** `crossorigin="use-credentials"` on the manifest link.
- [ ] **Step 4: e2e check** `manifest request carries the session cookie` in `shell.spec.ts` (signed-in fixture): `const req = page.waitForRequest(r => r.url().endsWith("/manifest.webmanifest"))`; trigger with `(await page.context().newCDPSession(page)).send("Page.getAppManifest")`; assert `(await (await req).allHeaders()).cookie` contains `lph_session=` (`app/auth/sessions.py:38`; e2e is http, no `__Host-` prefix). Second assertion `manifest icons load with credentials`: for each `icons[].src` of the manifest response, `page.request.get(src)` with the page's cookies returns 200 and an `image/*` content type. If the CDP trigger proves flaky, keep the unit test as the gate and record the manual check in the report.
- [ ] **Step 5: Write down the service worker behaviour** in the task report: VitePWA/Workbox precache (`frontend/pwa.config.ts`, `registerType: "prompt"`) serves the shell and assets from the cache; list anything else the shell fetches without credentials (grep `fetch(` / `<link` in `index.html`). No change unless one is a credentialed asset fetched without credentials.
- [ ] **Step 6: Commit** `fix(ui): load the web app manifest with credentials so the hub installs behind SSO (#225)`.

## Task 2: Backend routes under /api/v1 and the route guard (#226)

**Files:**
- Create: `backend/tests/helpers/routes.py` — **(R2 ruling: move, not import)** `iter_routes(routes) -> list[BaseRoute]` = the recursive flattening of `_iter_api_routes` (`tests/unit/api/test_route_auth_coverage_guardrail.py:85-103`) extended to keep top-level Starlette `Route`s; `iter_api_routes` keeps returning only `APIRoute`s. The guardrail test and `tests/unit/test_e2e_control_not_in_production.py:19-25` (vacuous today) switch to it.
- Create: `backend/tests/api/test_route_versioning.py`
- Move to a conftest: the `dist`/`spa` fixtures from `tests/integration/api/test_spa_serving.py:31-67` → `tests/integration/api/conftest.py`; the guard imports them via `pytest_plugins` or lives under `tests/integration/api/` **(R2 ruling: the guard lives at `backend/tests/integration/api/test_route_versioning.py`, so it gets the conftest fixtures directly)**.
- Modify, per router kind (a full path starts with the prefix only where a prefix exists):

| File | Kind | Edit |
|---|---|---|
| `admin_api_keys.py`, `batches.py`, `calibration.py`, `capabilities.py`, `jobs.py`, `lookup.py`, `printers.py`, `sheet_types.py`, `webhooks.py` | `prefix="/api/…"` | prefix → `/api/v1/…` |
| `batch.py:36`, `sheet_print.py:30`, `print.py:48` (`render_router`) | `prefix="/api"` | prefix → `/api/v1` |
| `info.py:25`, `sheets.py:47`, `print.py:43` (legacy router) | **no prefix** | rewrite the decorator paths; `info.py:86` is already `/api/v1/system/logs`, leave it |

- Modify (non-router path literals):
  - `backend/app/api/error_handlers.py:65` `SHEET_PREFIXES`, `:66` `_SHEET_PRINT_PATH` regex → `^/api/v1/print/[^/]+/sheet(/preview)?$`, `:76` `WEBHOOK_PREFIX` → `/api/v1/webhook/`;
  - `backend/app/auth/dependencies.py:66` `_BOOTSTRAP_ALLOWED` → `("POST", "/api/v1/admin/api-keys")`;
  - `backend/tests/unit/api/test_route_auth_coverage_guardrail.py:73` `("GET", "/api/info")`;
  - `backend/app/web/spa.py:73-97,130`: remove `_BrowserJobLinks` and `_JOB_LINK`;
  - `backend/app/api/routes/print.py`: docstring at `:1`, `:147-149`, module comment on backwards compatibility;
  - every backend test with an old path (≈565 literals in 43 files plus 44 legacy root literals).
- Delete tests: `tests/integration/api/test_spa_serving.py:124-142` (`test_legacy_job_route_html_for_browser_json_for_client`), `:144-157`, `:159-164` — they pin the removed legacy JSON behaviour.

**Path map:**

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
| `/api/webhook/spoolman`, `/api/webhook/grocy` | `/api/v1/webhook/…` |
| `/api/info` | `/api/v1/info` |
| `POST /print` (legacy root) | `POST /api/v1/print` |
| `POST /printer/resume` (legacy root) | `POST /api/v1/printer/resume` |
| `GET /jobs/{job_id}` (legacy root) | **removed** |
| `POST /jobs/{job_id}/resume` (legacy root) | **removed** |

**Why the two legacy job routes are removed (ruling):**
- They are not duplicates. `GET /jobs/{job_id}` (`print.py:141-187`) returns `PrintJobStatusResponse` from the in-memory queue with a live SNMP block; `GET /api/v1/jobs/{job_id}` (`jobs.py:171-183`) returns `JobRead` from the DB with the per-key printer ACL. Callers that want a job's state use the latter; the live SNMP block is available from `/api/v1/printers/{id}/status`.
- `POST /jobs/{job_id}/resume` (`print.py:241-307`) moves PAUSED→QUEUED, but nothing produces a PAUSED job any more: `queue.pause_job` has no route caller and `on_tape_mismatch` was removed in 1k.1a (`app/schemas/print_request.py:3`). The route is unreachable.
- Moving them would collide with `jobs.py` under `/api/v1/jobs/…`.
- `jobs.py:304-330` (`POST /api/v1/jobs/{job_id}/resume`, a 501 stub) stays as it is; note it in the report.
- Their tests move to the `jobs.py` routes where they test something the new route has, else they are dropped; the report lists which.

**Interfaces:**
- Produces: the path map (contract for Tasks 3, 4, 7–13); `tests/helpers/routes.py::iter_routes`, `iter_api_routes`.

- [ ] **Step 1: Write the failing tests** in `tests/integration/api/test_route_versioning.py`, app built with the `dist` fixture so the SPA catch-all exists:
  - `test_route_walk_is_not_vacuous`: the flattened walk contains `/api/v1/admin/printers` and ≥ 80 routes.
  - `test_every_api_route_is_versioned`: every route path starts with `/api/v1/` or is in `ALLOWED_UNVERSIONED`; the message lists offenders with methods.
  - `test_allow_list_has_no_dead_entries`: every `ALLOWED_UNVERSIONED` entry is a route.
  - `test_spa_owns_former_legacy_job_path`: `GET /jobs/123` with `Accept: */*` and with `Accept: application/json` → 200 `text/html` (today 401 JSON).
  - `test_bootstrap_session_creates_first_key_on_v1_path`: fresh install (empty `api_keys`), bootstrap session from the existing auth helper, `POST /api/v1/admin/api-keys` → 201 (today 403 after the move if `_BOOTSTRAP_ALLOWED` is missed).
  - `test_sheet_print_validation_does_not_echo_input`: `POST /api/v1/print/{key}/sheet` with a 20-char invalid value → 422 and the value is not in the body (catches a stale `_SHEET_PRINT_PATH`); same for `POST /api/v1/webhook/grocy` (catches a stale `WEBHOOK_PREFIX`).
- [ ] **Step 2: Run** `pytest tests/integration/api/test_route_versioning.py -v` → `test_route_walk_is_not_vacuous` passes, `test_every_api_route_is_versioned` FAILs listing ≈60 paths (56 `/api/…` + 4 legacy), the SPA and bootstrap tests FAIL. Record that the walk test passes on the current code (it proves the walk, not the move). Counter-test: replace `iter_routes` by the naive `app.routes` walk → `test_route_walk_is_not_vacuous` goes red.
- [ ] **Step 3: Implement** the table above, the literal edits and the removals.
- [ ] **Step 4: Grep** (zero hits expected outside `docs/superpowers/` and `CHANGELOG.md`):

```bash
grep -rnE "/api/(printers|jobs|batches|lookup|print|sheets|sheet-types|sheet-cells|render|info|admin/api-keys|webhook)" backend/ scripts/ 2>/dev/null
grep -rnE "[\"'^]/(print|printer/resume|jobs/)" backend/app backend/tests backend/scripts
```

- [ ] **Step 5: Verify** the new tests pass; `pytest tests/api`, `pytest tests/integration -m "not slow"`, `pytest tests/unit` each under 170 s; ruff, mypy.
- [ ] **Step 6: Commit** `feat(api): serve every API route under /api/v1 (#226)`.

## Task 3: Frontend on /api/v1 (#226)

**Files:**
- Modify: every `frontend/src/**`, `frontend/e2e/**` file with an old path, incl. template literals, `${MAIN.url}/api/…` (`e2e/fixtures.ts:58,68`) and method-prefixed mock keys (`"GET /api/printers"`, `` `GET /api/jobs/${ID}` ``); `schema.gen.ts` via `pnpm gen:api`.
- Create: `frontend/src/api/paths.test.ts`

- [ ] **Step 1: Failing guard** `no unversioned API path in the frontend source`: glob `src/**/*.{ts,tsx}` and `e2e/**/*.ts` minus `schema.gen.ts` and itself; fail on every match of `/(?<![.\w])\/api\/(?!v1\/)/` with file:line. This catches quotes, `${…}/api/`, and `GET /api/`; it excludes `../api/client`. Comment: it cannot see paths assembled without the `/api/` literal; no behaviour test can do this because there are ≈61 non-test call sites (`apiFetch`, links, `EventSource`) and no central URL builder.
  - e2e `old api path is a plain 404` in `printers.spec.ts`: `request.get("/api/printers")` → 404 with `application/json`.
- [ ] **Step 2: Run** `pnpm exec vitest run src/api/paths.test.ts` → FAIL listing files.
- [ ] **Step 3: Implement** the rewrite and `pnpm gen:api`. No URL-prefix helper (YAGNI).
- [ ] **Step 4: Verify** typecheck, lint, test:coverage, build, e2e per spec.
- [ ] **Step 5: Commit** `feat(ui): call the API under /api/v1 (#226)`.

## Task 4: Docs, examples, dev and scripts for /api/v1 (#226)

**Files:**
- Modify: `README.md`; current docs under `docs/` (≈35 files) except historical plans/specs under `docs/superpowers/`; the sheet-archive spec §15 gets the one-line note "Paths below predate #226; all API paths are now under `/api/v1/`."; ADRs get "Amended 2026-11-09 (#226)", decisions not rewritten; webhook setup docs.
- Modify: `examples/compose.traefik.yml:49` (`PathPrefix(/api/v1/webhook/)`), `examples/compose.pangolin.yml:73` (`targets[0].path=/api/v1/webhook/`), `examples/compose.backend-only.yml:19`, examples README; `dev/README.md:25`; `backend/scripts/smoke_first_print_batch.py:46`; `scripts/` if it names paths.
- Check: `tests/unit/test_examples_compose.py` for path assertions; update them.

- [ ] **Step 1: Find** with `grep -rnE "/api/(printers|jobs|batches|lookup|print|sheets|sheet-types|sheet-cells|render|info|admin/api-keys|webhook)|[\"'^ ]/print\b|/printer/resume|[\"' ]/jobs/" README.md docs/ examples/ dev/ backend/scripts/ scripts/`. Classify: current (rewrite) or history (note).
- [ ] **Step 2: Rewrite**; add "Moved API paths (1.5.0)" to `README.md` with the full map incl. the two removed routes and the reasoning in one line each.
- [ ] **Step 3: Verify** the grep again; list remaining history hits in the report; `pytest tests/unit/test_examples_compose.py`.
- [ ] **Step 4: Commit** `docs: document the /api/v1 paths in docs, examples and dev setup (#226)`.

## Task 5: PrintQueue membership — add and remove a printer while running (#224)

**Files:**
- Modify: `backend/app/services/print_queue.py`
- Test: `backend/tests/unit/services/test_print_queue_membership.py`

**Interfaces (produces):**
- `PrintQueue.add_printer(printer: _PrinterLike) -> None` (tape)
- `PrintQueue.add_page_printer(printer: PagePrinter) -> None`
- `async PrintQueue.remove_printer(printer_id: UUID, timeout_s: float) -> None`
- `async PrintQueue._recover_printer(printer_id: UUID) -> None` — the per-printer body of `start()` (`print_queue.py:298-380`): `mark_interrupted` for that queue, the legacy-payload FAIL path (`:324-345`), tape recovery loop, `_recover_page_jobs` and `_recover_in_flight_page_jobs` (`:399-445`), and re-applying a persisted manual pause for this id (`load_manual_pauses`, `:292-296`). `start()` loops over printers and calls it.
- `self._stopping_printers: set[UUID]` — per-printer stop flag.

**Rules:**
- Add: same id + same object → no-op; same id + other object → `ValueError`. When running, add creates the worker and then awaits `_recover_printer(id)`.
- Remove:
  1. Add the id to `_stopping_printers`; reject new submits for it with `KeyError` (same as unknown).
  2. Both workers (tape `_worker` after its take at `:1158`, `_page_worker` after `:1305`) check `printer_id in _stopping_printers` **right after dequeuing**: a job taken but not started is not run; it stays `queued` in the store. The pause loop (`:1170-1174` and the page equivalent) also exits on the flag.
  3. Wait up to `timeout_s` for the in-flight job; past it, cancel the worker; a tape job still printing is `mark_interrupted` (same as `stop()`), a page job at the printer stays `printing` and is picked up by `_recover_in_flight_page_jobs` on the next add.
  4. Purge every per-printer entry: `_queues`, `_worker_states`, `_worker_resume_events`, `_pause_info`, `_held`, `_to_resume`, `_resuming`, the printer dict entry, and every non-terminal `_jobs` entry of that printer, setting `_done_event` for waiters as `stop()` does (`:528-552`). Waiting jobs remain persisted with state `queued`. Then discard the id from `_stopping_printers`.
- Global `_stopping` is not touched.
- Disable (Task 7) uses remove, so a disabled printer's jobs stay persisted and frozen, exactly as after a restart today (#167 behaviour; not a bug).

- [ ] **Step 1: Failing tests:**
  - `test_add_page_printer_accepts_jobs_while_running`: start empty, add a fake page printer, submit, job reaches `done`.
  - `test_remove_two_waiting_jobs_stay_queued`: tape printer, job 1 blocks on an event, jobs 2 and 3 queued; `remove_printer` concurrently; release job 1. Assert job 1 `done`, fake printed exactly one job, jobs 2 and 3 have store state `queued`, `queue.has_job(j2) is False`. Counter-test: a `remove_printer` that mirrors `stop()` (sentinel at the back) → red (fake printed 3).
  - `test_readd_recovers_waiting_jobs`: after the above, `add_printer(new_fake)`; jobs 2 and 3 reach `done` on the new fake, in order.
  - `test_readd_resumes_printing_page_job`: page job at the printer (`printing`), remove with `timeout_s=0`, re-add with a fake reporting the IPP job completed → job `done`.
  - `test_remove_while_paused_exits`: tape worker paused with a taken job; remove returns within 1 s; job stays `queued`.
  - `test_readd_keeps_manual_pause`: printer manually paused (persisted), remove + add → `queue.is_paused(id)` is True.
  - `test_add_same_id_different_object_raises`.
  - `test_submit_during_remove_is_rejected`.
- [ ] **Step 2: Run** `pytest tests/unit/services/test_print_queue_membership.py -v` → FAIL (methods missing).
- [ ] **Step 3: Implement**; refactor `start()` onto `_recover_printer` without behaviour change (`pytest tests/unit/services -k print_queue` stays green).
- [ ] **Step 4: Verify** new + existing queue tests, ruff, mypy.
- [ ] **Step 5: Commit** `feat(queue): add and remove printers on a running queue without losing jobs (#224)`.

## Task 6: PrinterRuntime — one code path for wiring a printer (#224)

**Files:**
- Create: `backend/app/services/printer_runtime.py`
- Modify: `backend/app/services/backend_router.py` (register/unregister), `backend/app/main.py:448-648` (wiring) and `:651-675` (shutdown); DB/settings setup `:395-430` stays in the lifespan.
- Modify: `backend/tests/integration/api/test_admin_printers_ipp.py:617-619` patch targets → `app.services.printer_runtime._resolve_model_id_from_config` and `app.services.printer_runtime.StatusProbeProducer` (the function moves with the wiring).
- Test: `backend/tests/unit/services/test_printer_runtime.py`, `backend/tests/unit/services/test_backend_router_membership.py`

**Interfaces (produces):**
- `BackendRouter.register(cfg: PrinterConfig) -> None` (raises `ValueError` on a duplicate slug) and `BackendRouter.unregister(slug: str) -> None` (drops `_configs`, `_backends`, `_services`; unknown slug is a no-op). `register_service` (`:103`) unchanged.
- `class PrinterRuntime`:
  - `__init__(self, app: FastAPI, settings: Settings)`
  - `async attach(printer: Printer, *, fatal: bool = False) -> None`
  - `async detach(printer_id: UUID) -> None`
  - `async reconcile(printer_id: UUID) -> None`
  - `async stop() -> None`
  - `is_polled(printer_id: UUID) -> bool` — True iff a producer runs for the id (used by Task 8)
  - `print_service_for(printer_id: UUID) -> PrintService | None` (used by Task 12)
  - `wiring_key(printer: Printer) -> tuple[object, ...]` (module-level): `(enabled, backend, connection, model, snmp settings, tray keys for ipp)`. Name, label, cut defaults and `queue_timeout_s` are **not** in it **(R2 ruling: `queue_timeout_s` and cut defaults are read per job, so they need no re-wire)**.
- It owns: tape `BackendRouter` registration + `PrintService` per tape printer; `IppClient`/`IppPrinterState`/`IppPagePrinter` per page printer (incl. `aclose()` of the page client on detach); producers (`StatusProbeProducer` + `TapeChangeProducer` for tape with `snmp.discover`, `IppStatusProducer` for page); queue membership via Task 5; `app.state.slug_to_printer_id`, `app.state.ipp_printer_states`; the back-compat fields `app.state.print_service`, `printer_id`, `printer_host`, `printer_snmp_community` recomputed after every attach/detach as the first enabled tape printer **ordered by `created_at`** (same order as `printers_repo.list_all`, `app/repositories/printers.py:20`).
- Locking: one `asyncio.Lock` **per printer id** (`dict[UUID, asyncio.Lock]`); `reconcile` takes only that printer's lock.
- No probe in `attach`. Both producers already probe immediately: `IppStatusProducer.start()` creates the loop task (`ipp_status_producer.py:155`) whose first statement is `probe_once()` (`:171-174`); `StatusProbeProducer.start()` (`status_probe_producer.py:87`) runs `_probe_once()` before its first sleep (`:266-269`). `attach` only calls `start()`; startup never awaits a probe.
- Failure handling: `fatal=True` (lifespan only) keeps today's behaviour — an unresolvable tape model (`_resolve_model_id_from_config` raising `ValueError`/`SnmpDiscoveryError`, `main.py:308-339`) aborts startup. `fatal=False` (admin path) logs slug + exception type only (never the URI/host), leaves the printer detached, does not raise. Other wiring failures (bad IPP URI) are degraded in both modes, as today.
- `stop()`: set a closed flag (later `reconcile` calls are no-ops), stop all producers, `await queue.stop(shutdown_wait_s(...))` **once**, then `aclose()` every page client. No per-printer remove.
- Manual pause survives re-wire via `_recover_printer` (Task 5).

- [ ] **Step 1: Failing tests** (fake IPP transport `tests/helpers/fake_ipp_printer.py`, SNMP patch `app.services.producers.status_probe_producer.query_preflight`):
  - `test_attach_ipp_status_without_waiting_an_interval`: interval set to 3600 s; after `attach`, `_until` (`tests/integration/test_ipp_status_wiring.py:21-27`) sees `captured_at` set within 2 s, and exactly one probe on the fake.
  - `test_attach_does_not_await_probe`: a fake transport that blocks forever; `attach` returns within 0.5 s.
  - `test_attach_tape_with_snmp_starts_producer`.
  - `test_detach_stops_probes_and_closes_page_client`.
  - `test_attach_bad_uri_degrades`: no raise, id absent from `ipp_printer_states`, warning log without the URI.
  - `test_attach_unresolvable_tape_model_degrades_at_runtime` and `test_attach_unresolvable_tape_model_is_fatal_at_startup` (`fatal=True` raises).
  - `test_first_tape_printer_backcompat_by_created_at`: two tape printers, insert order ≠ id order; back-compat fields name the older `created_at`.
  - `test_backend_router_register_unregister` (+ duplicate slug raises).
  - `test_stop_stops_queue_once_and_closes_clients`; `test_reconcile_after_stop_is_noop`.
- [ ] **Step 2: Run** → FAIL (module missing).
- [ ] **Step 3: Implement** and switch the lifespan to `PrinterRuntime` (`attach(p, fatal=True)` for every enabled printer, `stop()` on shutdown). Existing lifespan tests keep their behaviour: degraded start, empty table, shutdown order.
- [ ] **Step 4: Verify** `pytest tests/unit`, `pytest tests/integration -m "not slow"`, ruff, mypy.
- [ ] **Step 5: Commit** `feat(printers): wire printers through one runtime used at startup and on change (#224)`.

## Task 7: Admin changes take effect live (#224)

**Files:**
- Modify: `backend/app/api/routes/admin_printers_api.py` — after the commit and before `_publish_changed` in `create_printer` (`:219`), `update_printer` (`:317`), `disable_printer` (`:367`), `enable_printer` (`:406`): `await asyncio.shield(request.app.state.printer_runtime.reconcile(printer.id))`. Comment: reconcile must precede `hub.printers_changed`, because an open SSE stream re-subscribes on that event (`events_v1.py:373-381`, `frontend/src/api/events.ts:183`).
- Modify: `PrinterRuntime.reconcile` skips detach/attach when `wiring_key` of the new row equals the attached one.
- Modify (restart hint): `frontend/src/features/settings/PrinterForm.tsx:29-72` (`restartNote`), `Printers.tsx:17-25`, `IppPrinterFields.tsx:139`, their tests and catalog entries.
- Modify tests that pin probe requests: `tests/integration/api/test_admin_printers_ipp.py` `test_update_with_new_uri_probes` (`:448-455`) and the assertions at `:208-209`, `:315`, `:420-421`, `:468`, `:630` — split into "the admin probe ran once before the save" (first recorded op) and "the runtime wired the new URI" (later calls go to `URI_2`).
- Test: `backend/tests/integration/api/test_printer_live_wiring.py` using the `hub` fixture (`test_admin_printers_ipp.py:118-140`, moved to a conftest if needed), `Hub.override` (`:112`) for two fake printers, and `PRINTER_HUB_SSE_PROBE_INTERVAL_S=0.2` + `get_settings.cache_clear()` (as `test_ipp_status_wiring.py:118`).
- There is no delete route; disable stands in for delete (#224 "disabling or deleting").

- [ ] **Step 1: Failing integration tests:**
  - `test_created_ipp_printer_has_status_without_restart`: `POST /api/v1/admin/printers` (IPP) → `GET /api/v1/printers/{id}/status` `online: true`, `printer_state` set, `captured_at` set; `GET …/capabilities` has `resolution_dpi.max` and `media` non-null.
  - `test_created_ipp_printer_prints_without_restart`: calibration page job → `done`.
  - `test_disable_stops_polling_and_refuses_jobs`: after disable, no further requests on the fake; a new calibration page job → 409 `type: "printer-unavailable"` (`calibration.py:242`).
  - `test_enable_restores_polling`.
  - `test_update_uri_moves_polling`.
  - `test_rename_does_not_rewire`: name-only `PUT`; no new factory call; an in-flight page job's tracking continues.
  - `test_update_during_inflight_job_keeps_job` (Review Focus 1).
  - `test_concurrent_reconcile_single_producer`: two `PUT`s via `asyncio.gather`; one producer for the id; probes on the fake at ≤ 1 per interval.
  - `test_reconcile_survives_client_disconnect`: cancel the request task mid-reconcile; the runtime ends fully attached (shield).
  - `test_reconcile_lock_is_per_printer`: a detach blocked on printer A's in-flight job does not delay a reconcile of printer B (B completes within 1 s).
  - `test_tape_printer_created_with_snmp_discover_has_status`.
  - Frontend: `PrinterForm` test asserts no restart note text.
- [ ] **Step 2: Run** → FAIL (null status, 409 on print).
- [ ] **Step 3: Implement** hooks, skip rule, hint removal (UI task protocol).
- [ ] **Step 4: Verify** and counter-test: remove the `reconcile` call → red for the right reason (null status / job refused, not an import error). `pytest tests/api tests/integration -m "not slow"` per directory; frontend checks.
- [ ] **Step 5: Commit** `fix(printers): apply printer create, update, enable and disable without a restart (#224)`.

## Task 8: A stale status is shown as unknown (#227)

**Files:**
- Create: `backend/app/services/status_freshness.py`
- Modify: `backend/app/schemas/printer.py` (`PrinterStatus`), `backend/app/api/routes/printers.py:363-406` (`get_printer_status`), both producers' cache writes (`status_probe_producer.py:_upsert_cache`, `_mark_offline`; `ipp_status_producer.py:_write_cache`).
- Modify UI: `frontend/src/features/printers/model.ts` (`describePrinter`, `useKindLabel`), `PrinterDetail.tsx:83,95`, `PrinterCard.tsx`, `frontend/src/features/overview/OverviewPage.tsx`; create `frontend/src/features/printers/age.ts`.
- Test: `backend/tests/unit/services/test_status_freshness.py`, `backend/tests/integration/api/test_printer_status_staleness.py`, `frontend/src/features/printers/model.test.ts`, `frontend/src/features/printers/age.test.ts`.

**Decisions:**
- Bound: `stale_after_s(probe_interval_s: float) -> float = max(90.0, 3 * probe_interval_s)`. Documented in the `PrinterStatus` docstring and `docs/` printer status page.
- Age source: `updated_at` (time of the last probe **attempt**), not `captured_at` (an offline IPP write keeps `captured_at`, `ipp_status_producer.py:283`). **(R2 ruling)** Both producers set `row.updated_at = now` explicitly on every write, because `onupdate` does not fire when no column changes.
- `is_stale(updated_at: datetime, now: datetime, probe_interval_s: float) -> bool`.
- New `PrinterStatus` fields (pinned): `stale: bool = False`, `polled: bool = True`.
- Route: `polled = runtime.is_polled(id)`. If `not polled` or stale: `online: null`, `stale: true`, `tape_loaded`, `error_state`, `printer_state`, `state_reasons`, markers, tray media → null/empty **(R2 ruling: stale values are not returned, because the cached 62 mm tape next to "no tape" was the bug)**; `captured_at` and `last_probe_age_s` stay so the UI can show the age. `note`: `"Not polled"` when unpolled, `"Status older than {bound} s"` when stale. No row → as today, plus `polled`.
- UI kinds (pinned): `"stale"` → label en "Status unknown", de "Status unbekannt", badge `idle`; `"not_polled"` → en "Not monitored", de "Nicht überwacht", badge `idle`. `describePrinter` checks `polled === false`, then `stale`, before any `online` branch (paused still wins).
- Age format: `formatAge(seconds: number, locale: string) -> string` with `Intl.RelativeTimeFormat(locale, { numeric: "always" })`, largest unit of seconds/minutes/hours/days, floored. "Last status … ago" becomes `t\`Last status ${formatAge(age, i18n.locale)}\``.

- [ ] **Step 1: Failing tests:**
  - `test_stale_after_floor_and_multiple`: `stale_after_s(5) == 90`, `stale_after_s(30) == 90`, `stale_after_s(60) == 180`.
  - `test_status_older_than_bound_is_stale`: cache row `online: True`, `loaded_tape_mm: 62`, `updated_at` = now − 12 349 795 s → `online is None`, `stale is True`, `tape_loaded is None`, `last_probe_age_s` ≥ 12 349 795. (Today: `online: true`.)
  - `test_fresh_status_is_not_stale`: `updated_at` = now − 10 s → `stale is False`, `online is True`.
  - `test_unpolled_printer_reports_polled_false`: tape printer with `snmp.discover=false` and a fresh row → `polled is False`, `online is None`.
  - `test_offline_ipp_write_refreshes_updated_at`: two identical offline writes; `updated_at` advances; status `stale is False`, `online is False`.
  - UI: `describePrinter stale row is not ready` (`{online: true, stale: true}` → kind `stale`); `describePrinter unpolled` → `not_polled`; `formatAge(12349795, "en") === "143 days ago"`, `formatAge(12349795, "de") === "vor 143 Tagen"`, `formatAge(59, "en") === "59 seconds ago"`, `formatAge(7200, "de") === "vor 2 Stunden"`.
- [ ] **Step 2: Run** backend and vitest files → FAIL.
- [ ] **Step 3: Implement** backend, `pnpm gen:api`, UI (UI task protocol).
- [ ] **Step 4: Verify**; screenshots of a stale and an unpolled printer.
- [ ] **Step 5: Commit** `fix(status): show a stale or unpolled printer status as unknown with its age (#227)`.

## Task 9: One status-cache schema for tape printers; PT colour if readable (#229)

**Files:**
- Create: `backend/app/services/tape_status.py`
- Modify: `status_probe_producer.py` (`_upsert_cache` writes the schema), `backend/app/printer_backends/snmp_helper.py` (`PreflightStatus.media_raw`), `printers.py` `get_printer_status` and `get_printer_tape` (`:414-460`), `schemas/printer.py`.
- Variant A only: the producer reads colour by the spike's method.
- Test: `backend/tests/unit/services/test_tape_status.py`, `backend/tests/integration/api/test_printer_tape.py`

**Decisions:**
- Cache schema (tape), pinned as `TapeStatusParsed(TypedDict, total=False)` in `tape_status.py`: `online: bool`, `loaded_tape_mm: int | None`, `media_raw: str | None` (trimmed `prtInputMediaType` text), `hr_printer_status: str`, `error_flags: list[str]`, `last_error: str`, and in variant A `tape_colour: str | None`, `text_colour: str | None`. `read_tape_status(parsed: Mapping[str, Any]) -> TapeStatusParsed` is the only reader. `media_width_mm` is gone.
- `GET /api/v1/printers/{id}/tape` returns `TapeRead {width_mm: int, label: str, media_raw: str | None, colour: str | None, text_colour: str | None, colour_source: Literal["printer", "operator"] | None}`; `label` from the printer model's `describe_tape(width_mm)` (`app/printer_models/base.py:52`), the same lookup `TapeChangeProducer` uses; 404 only when `loaded_tape_mm` is null or no row. `TapeRegistry.lookup_pt` is no longer used there **(R2 ruling: the route serves PT and QL, `lookup_pt` is PT-only)**.
- `PrinterStatus` keeps `tape_loaded` (`"{mm}mm"`) for other readers and adds structured `tape_width_mm`, `tape_colour`, `text_colour`, `colour_source`. The UI switches to the structured fields in Task 11 **(R2 ruling)**.
- Colour vocabulary `TapeColourName = Literal["white", "yellow", "green", "blue", "red", "black", "clear"]` in `tape_status.py`; variant A maps the printer's codes onto it (unknown code → null).

- [ ] **Step 1: Failing tests:**
  - `test_tape_endpoint_reads_snmp_cache`: row `{online: True, loaded_tape_mm: 62}` → 200, `width_mm == 62` (today 404).
  - `test_tape_endpoint_404_without_tape`.
  - `test_producer_writes_media_raw`: patched preflight `media_raw="62mm(2.44\")"` → cache has it.
  - Variant A: `test_pt_colour_flows_into_status`: producer probe with colour codes → `GET …/status` `tape_colour == "blue"`, `text_colour == "white"`, `colour_source == "printer"`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**; `pnpm gen:api`.
- [ ] **Step 4: Verify** `pytest tests/unit tests/integration -m "not slow" -k "tape or status"`, ruff, mypy.
- [ ] **Step 5: Commit** `fix(printers): one tape status schema; the tape endpoint works for SNMP-polled printers (#229)`.

## Task 10: Stored roll record, roll-change detection and the colour endpoint (#229)

**Files:**
- Create: `backend/app/models/printer_roll.py`, `backend/alembic/versions/2026_11_09_0001-20261109a1_printer_roll.py` (additive), `backend/app/repositories/printer_roll.py`, `backend/app/services/roll_tracker.py`, `backend/app/api/routes/printer_roll.py` (router prefix `/api/v1/printers`, registered in the app factory).
- Modify: `status_probe_producer.py` (call the tracker after a successful upsert), `get_printer_status` (operator colour + `roll_prompt`), `schemas/printer.py`.
- Test: `backend/tests/unit/services/test_roll_tracker.py`, `backend/tests/integration/api/test_printer_roll_api.py`, `backend/tests/integration/db/test_alembic_printer_roll.py` (pattern of `tests/integration/db/test_alembic_sheet_migration.py`).

**Decisions:**
- Table `printer_roll`: `printer_id` UUID PK FK `printers.id`; `width_mm` int null; `media_raw` str null; `colour` str null; `set_at` datetime tz null; `prompt_pending` bool not null default false; `changed_at` datetime tz not null.
- Roll identity = `(width_mm, media_raw)` **(R2 ruling: SNMP gives no media-type code, so the raw media text stands for "media type"; any text change counts as a change)**.
- `RollTracker.observe(printer_id: UUID, width_mm: int | None, media_raw: str | None, printer_colour: str | None) -> RollChange | None`:
  - identity unchanged → no write, `None`;
  - identity differs or no row → clear `colour`/`set_at`, store identity, `changed_at = now`, `prompt_pending = width_mm is not None and printer_colour is None`; publish `printer.roll_changed` on `printer:{id}:tape` with `{width_mm, media_raw, prompt_pending}`; return the change.
  - The first probe after a restart compares against the DB row, so a swap while the hub was down is detected; a first-ever observation counts as a change **(R2 ruling: one prompt per printer after the upgrade)**.
- Variant A: a PT with a printer colour never prompts; `colour_source = "printer"`. Variant B: PT and QL both use the operator flow.
- Endpoints:
  - `GET /api/v1/printers/{printer_id}/roll` (`read` scope) → `RollRead {width_mm, media_raw, colour, set_at, prompt_pending}`; 404 unknown printer.
  - `PUT /api/v1/printers/{printer_id}/roll` (`print` scope, `check_printer_access`) body `RollColourUpdate {colour: TapeColourName | None}` (extra forbid). Sets `colour`, `set_at = now` (null colour → `set_at` null), `prompt_pending = false`; `colour: null` is "skip" and "clear". 409 `type: "no-roll-loaded"` when `width_mm` is null. Publishes `printer.roll_changed`. Returns `RollRead`.
- `PrinterStatus` adds `roll_prompt: bool`; for `colour_source = "operator"` it fills `tape_colour` from the roll record.

- [ ] **Step 1: Failing tests:**
  - `test_roll_change_clears_colour_and_raises_prompt`: stored `(62, "62mm")` colour `red`; observe `(29, "29mm")` → colour null, `prompt_pending` True, one event.
  - `test_same_roll_does_not_reprompt`: observe the same identity 3× → one event total.
  - `test_first_probe_after_restart_detects_change_once`: DB row `(62, …)`, fresh tracker instance, observe `(12, …)` twice → one change.
  - `test_no_tape_clears_without_prompt`.
  - API: `test_set_colour_clears_prompt`; `test_skip_sets_no_colour` (`colour: null` → status `tape_colour is None`, `roll_prompt is False`); `test_read_key_cannot_set_colour` (403); `test_restricted_key_cannot_set_other_printer` (403) and can set its own (200); `test_set_colour_without_roll_is_409`.
  - Migration upgrade + downgrade on an empty and a populated DB.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**; `pnpm gen:api`.
- [ ] **Step 4: Verify** per directory, ruff, mypy; `alembic upgrade head` on a copy of a 1.4.0 DB fixture.
- [ ] **Step 5: Commit** `feat(printers): remember the roll colour per printer and detect roll changes (#229)`.

## Task 11: Tape colour in the UI — prompt, edit, no "Colour not reported" (#229)

**Files:**
- Create: `frontend/src/features/printers/RollColourPrompt.tsx` (+ test)
- Modify: `TapeSwatch.tsx` (props `{widthMm, colour, textColour, probed}`; no colour → no colour line), `model.ts` (`TAPE_COLOURS` + `black`, `clear`; `parseTape` removed if unused), `PrinterDetail.tsx` (prompt above Material, "Change colour" control in the Material section), `PrinterCard.tsx`, `OverviewPage.tsx`, `frontend/src/api/events.ts` (`printer.roll_changed` invalidates the printer's status and roll queries), `frontend/src/design/tokens.css` + `index.css` (`tape-black`, `tape-clear`), both catalogs (remove "Colour not reported").
- Test: `TapeSwatch.test.tsx` (replace the `:26` assertion), `RollColourPrompt.test.tsx`, `frontend/e2e/printers.spec.ts`.

- [ ] **Step 1: Failing tests:**
  - `TapeSwatch shows no colour line without a colour`: `queryByText(/colour/i)` is null and the width shows.
  - `catalogs have no "Colour not reported"`: both `.po` files lack the msgid.
  - `RollColourPrompt offers the known colours and skip`: renders when `roll_prompt` is true; choosing "Blue" sends `PUT /api/v1/printers/{id}/roll {colour: "blue"}`; "Skip" sends `{colour: null}`; a `read` user sees no prompt.
  - e2e `roll prompt after a roll change`: mock status `roll_prompt: true` → prompt visible; after skip, no colour line.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** (UI task protocol).
- [ ] **Step 4: Verify** frontend checks; screenshots with prompt, with colour, without colour.
- [ ] **Step 5: Commit** `feat(ui): ask for the roll colour on a roll change and show the tape colour truthfully (#229)`.

## Task 12: Test print endpoint (#228)

**Files:**
- Create: `backend/app/api/routes/test_print.py` (router prefix `/api/v1/printers`), `backend/app/services/test_print.py`, `backend/app/page_render/test_page.py`
- Modify: `backend/app/services/page_jobs.py:38` (`PageKind` adds `"test_page"`; renderer registered via `register_page_renderer`; the default no-op outcome handler applies, so no sheet state is touched), app factory (router).
- Test: `backend/tests/integration/api/test_test_print_api.py`, `backend/tests/unit/page_render/test_test_page.py` (with `tests/helpers/pdf_inspect.py`).

**Interfaces:**
- `POST /api/v1/printers/{printer_id}/test-print`, body `TestPrintRequest {tray: str | None = None}` (extra forbid), `202 TestPrintAccepted {job_id: UUID}`, `print` scope, `check_printer_access`.
- `build_tape_test_request(printer: Printer, width_mm: int, now: datetime, version: str, printer_url: str) -> PrintRequest`: `ContentType.QR_THREE_LINES`, `qr_payload = printer_url`, `primary_id = printer.name`, `title = f"{width_mm} mm · {now:%Y-%m-%d %H:%M}"`, `secondary = [f"Printer Hub {version}"]`; one copy. Submitted through `PrinterRuntime.print_service_for(id).submit_print_job`.
- `build_test_page_payload(printer: Printer, tray: str, margins_mm: Margins, now: datetime, version: str, printer_url: str) -> PagePayload` (kind `"test_page"`) and `render_test_page(payload: PagePayload) -> bytes`: a frame on the printable area from the tray's reported margins (status cache tray media), name, tray, date/time, one text line "Printer Hub test page {version}", a QR to `printer_url`. Title text "Test page"; it never uses the calibration renderer. Submitted through `queue.submit_page_job`.
- `printer_url = f"{settings.public_url}/printers/{printer_id}"` (SPA route `/printers/$printerId`, `router.tsx:206`). `now` is local time (`datetime.now().astimezone()`).
- Refusals, in this order, as `ProblemDetail` like `calibration.py:242`:
  - unknown printer → 404;
  - `read` key → 403; restricted key on another printer → 403;
  - disabled → 409 `printer-disabled`;
  - paused → 409 `printer-paused` **(R2 ruling: the UI disables the button while paused; the API agrees)**;
  - `polled false`, stale, no row, or `online` not true → 409 `printer-offline`;
  - tape printer with no tape loaded → 409 `no-tape-loaded`;
  - `tray` on a tape printer, or unknown/disabled tray → 422 `tray-invalid`; no tray on a page printer → the default tray.

- [ ] **Step 1: Failing tests:**
  - `test_tape_test_print_creates_one_job_done`: fake tape backend; 202; exactly one new job row; reaches `done`; rendered image width = loaded tape.
  - `test_page_test_print_creates_one_job_done`: fake IPP; 202; reaches `done`; the submitted PDF has one page whose frame rectangle matches the margins ±0.5 mm and contains the printer name and tray.
  - `test_test_print_reserves_no_sheet_cells`: row counts of sheet tables before == after.
  - `test_read_key_is_403`, `test_restricted_key_other_printer_is_403`, `test_restricted_key_own_printer_is_202`.
  - `test_disabled_is_409`, `test_paused_is_409`, `test_offline_is_409`, `test_stale_is_409`, `test_unknown_printer_is_404`, `test_tray_on_tape_printer_is_422`.
  - `test_test_page_is_not_calibration_page`: the PDF text contains "Test page" and not the calibration title.
- [ ] **Step 2: Run** → FAIL (404, route missing).
- [ ] **Step 3: Implement**; `pnpm gen:api`.
- [ ] **Step 4: Verify** per directory; the route versioning guard (Task 2) still passes; ruff, mypy.
- [ ] **Step 5: Commit** `feat(printers): test print endpoint for tape and page printers (#228)`.

## Task 13: Test print button (#228)

**Files:**
- Create: `frontend/src/features/printers/TestPrintButton.tsx` (+ test)
- Modify: `PrinterDetail.tsx` (header action next to `PauseResumeButton`), both catalogs.
- Test: `frontend/e2e/printers.spec.ts`, `frontend/e2e/page-printer.spec.ts`.

**Decisions:**
- Shown for every printer to `print` scope and up; hidden for `read`.
- Disabled with the reason as visible text (not only a tooltip) when: disabled ("Printer is disabled"), paused ("Printer is paused"), `polled false`/stale/offline ("Printer is not reachable"), tape with no tape ("No tape loaded"). The same order as the API.
- Page printers: a tray select (enabled trays, default preselected) in a small popover; tape printers: one click.
- On 202: toast with a link to `/jobs/{job_id}`; on 409/422 the API `detail` is shown.

- [ ] **Step 1: Failing tests:** `TestPrintButton is disabled with reason when offline`; `… posts once for a tape printer`; `… sends the chosen tray`; e2e `test print reaches done` on both fake printer kinds.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** (UI task protocol; `break-ui` with a 60-char printer name and many trays).
- [ ] **Step 4: Verify** frontend checks; screenshots.
- [ ] **Step 5: Commit** `feat(ui): test print button on every printer page (#228)`.

## Order and dependencies

```
Task 0 ──────────────────────────────────────────────┐
Task 1 (independent)                                 │
Task 2 → Task 3 → Task 4                             │
Task 2 → Task 5 → Task 6 → Task 7 → Task 8 → Task 9 → Task 10 → Task 11
                                     Task 9 → Task 12 → Task 13
```

- Tasks 8, 9 and 10 all change `get_printer_status` and `PrinterStatus`: strictly sequential.
- Task 12 needs `print_service_for` (6), `polled`/`stale` (8) and the tape schema (9).
- Task 0 must be in the ledger before Task 9 starts.

## Gate, review and shipping (controller)

1. Full gate in a frozen clone, no parallel load: backend `pytest -m "not slow" --cov=app --cov-fail-under=80`, ruff, mypy, `alembic upgrade head` + `downgrade -1`; frontend typecheck, lint, test:coverage, build, e2e.
2. Whole-branch review with the four lenses.
   - **Taint:** IPP URI/host never in logs or non-admin responses via the runtime; the test page QR and label carry only the public URL and printer name.
   - **Runtime/temporal:** per-printer locks, shield, shutdown order, in-flight jobs, roll tracker vs concurrent probes.
3. `security-audit` on the changed surface: admin routes triggering outbound connections, moved webhook and lookup routes, bootstrap allow-list, the new roll and test-print routes (scope and printer ACL).
4. PR with Codex review, then merge.
5. **Release and rollout,** one maintenance window, in this order:
   1. Back up the DB.
   2. Release 1.5.0 (`workflow_dispatch`); bump the Kept pin. The migration runs on start.
   3. Move the live Pangolin webhook resource (the SSO-bypass resource) from path `/api/webhook/` to `/api/v1/webhook/`; check that `POST /api/v1/webhook/grocy` without SSO reaches the hub (401/422 from the hub, not the SSO page).
   4. Change the webhook targets in Grocy and Spoolman to `/api/v1/webhook/grocy` and `/api/v1/webhook/spoolman`, if configured.
   5. Hangar companion PR (`internal/hub/client.go`: `/api/render/preview`, `/api/print/{slug}/batch`, `/api/printers?slug=`, `/api/printers`, `/api/printers/{uuid}/status`, `/api/batches/{id}` → `/api/v1/…`), released right after.
   6. On each printer page: answer the one-time roll colour prompt (or skip).
6. **Release notes** list: the path map and the two removed routes; that installed web clients keep calling the old paths until the service-worker update prompt is accepted (`registerType: "prompt"`), so they show errors until then; the new `stale`/`polled`/roll/test-print fields and endpoints.
