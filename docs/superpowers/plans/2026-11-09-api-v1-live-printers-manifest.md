<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# API v1, Live Printer Wiring, Status Truth, Tape Colour, Test Print, Hardware Identity and Sheet Feedback — Implementation Plan (1.5.0)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Revision 4 (2026-11-09)

Second independent plan review of `3a6f41f` (READY WITH FIXES). Every finding and where it went:

| Finding | Handled in |
|---|---|
| 1 lifespan order / page jobs settled as unknown | Task 6: pinned startup order, `PrinterRuntime.start()`, `test_page_job_restart.py` as regression net; Task 5: add on a stopped queue does no recovery |
| 2 order inside `add_*printer`, pause source | Task 5: pause → `_recover_printer` → worker last; `paused_since` argument read by the runtime; stronger pause test |
| 3 stop flag vs `BatchJob` | Task 5: check after `queue.get()` before the batch branch, between batch items, resume event set; `test_remove_keeps_queued_batch_items` |
| 4 `queue_timeout_s` (controller) | Task 6: in `wiring_key` for IPP only; `stop()` uses attached timeouts; tests |
| 5 shared IPP limiter, route without runtime | Task 6: one semaphore per runtime; Task 8: `get_printer_runtime` dependency, no-runtime = unpolled, six assertions named |
| 6 SSE snapshot sends stale cache | Task 8: same rule in `sse_snapshot.py`; `test_snapshot_omits_stale_status` |
| 7 `/tape` driver, vocabulary | Task 6: `describe_tape_for`; Task 9: label from it, "media name text", no second OID |
| 8 identity writes bump `printers.updated_at` (controller) | Task 14: own table `printer_identity` in the one #231 migration; `seen_at` throttled; test |
| 9 identity OIDs on the print path (controller) | Task 14: separate `query_identity`, producer only; `query_preflight` unchanged; tests renamed |
| 10 kind upgrade can hide a swap (controller) | Task 14: `record_identity` takes `ObservedIdentity`; upgrade only with matching MAC; `kept`; swap test |
| 11 admin connection change (controller) | Task 14: identity kept; same → silent `seen`, other → mismatch; `test_connection_change_keeps_identity` |
| 12 test print refused for unpolled tape printers (controller) | Task 12: tape decided by the submit preflight, width from it, `submit_test_label`; page unpolled → `printer-status-unknown`; Task 13 reason texts |
| 13 Jobs UI / retry / payload sources (controller) | Task 12: `test_page` retryable, `media` and `render_dpi=600` sources pinned, `template_key="test_label"`; Task 13: jobs model, `PageJobInfo`, `useJobTitle` |
| 14 retry bypass, dispatch read, failure path | Task 15: guard on both retry paths, in-memory hold set, not-started failure path |
| 15 `printer-uuid` in the status cache (controller) | Task 14: uuid returned next to the record to the sink only; `test_status_cache_has_no_identity` |
| M1 two `PrinterRead` classes | Task 16 |
| M2 `replaced` not atomic (controller) | Task 16: one transaction over stored rows; `test_replaced_is_atomic` |
| M3 roll PUT race, GET ACL | Task 10: optional `width_mm`, 409 `roll-changed`; ACL on GET |
| M4 cassette out/in, die-cut limitation | Task 10 |
| M5 `down_revision`, fixture, batch | Task 10 (`20261108a1`, DB built in the test); Task 14 (`20261109a1`; a new table needs no batch mode) |
| M6 `public_url` double slash | Task 12 |
| M7 refusal order | Task 12 |
| M8 `PrinterYAMLConfig` | Task 6 |
| M9 clock jump | Task 8: future tolerance 60 s; `test_future_updated_at_is_stale` |
| M10 guard false positives | Task 3 |
| M11 `EVENT_TYPES` | Tasks 11 and 17 |
| M12 identity in logs and error bodies | Tasks 14–16: never logged, `caplog` tests, `detail` names only the id |
| M13 printers without a producer | Tasks 14 and 17 |
| M14 user-entered `source_url` (controller) | Task 18: URL only for `seed` types; test |
| M15 `yaml` pin | Task 18: `2.9.1` |

Rulings made in this revision are marked **(R4 ruling)**; controller rulings are marked as such.

## Revision 3 (2026-11-09)

Follow-up from the controller after `d9f021f`:

| Change | Where |
|---|---|
| Task 0 spike done live, result **B** (no tape colour over the network) | Ledger; Task 0 marked done; variant A removed from Tasks 9–11; PT and QL both use ask-on-roll-change |
| #231 hardware identity, spike done live | Ledger; Tasks 14–17 |
| #230 sheet-type feedback link | Task 18 |
| Release covers #224–#231 | Gate, review and shipping |

Rulings made in this revision are marked **(R3 ruling)**.

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

**Goal:** Release 1.5.0 in which every API route lives under `/api/v1/`, printer admin changes take effect live, the web app installs behind SSO, a stale status never shows as Ready, tape colour is shown truthfully, every printer has a test print, a swapped device behind the same address holds calibration-dependent jobs, and a sheet type's dimensions can be reported or confirmed through a pre-filled GitHub issue.

**Architecture:**
- **#226.** Router prefixes/decorator paths move in place; a guard over the flattened route tree and a frontend source scan enforce it.
- **#224.** The per-printer wiring from the lifespan moves into `PrinterRuntime`, used at startup and by the admin routes. `PrintQueue` gains add/remove with a shared per-printer recovery.
- **#225.** One attribute on the manifest link.
- **#227.** A freshness rule (`status_freshness.py`) applied in the status route; UI renders stale and unpolled printers as such.
- **#229.** One status-cache schema for tape printers, a stored roll record per printer with roll-change detection, an endpoint and SSE event, UI prompt.
- **#228.** One endpoint that builds a tape label or a test page and submits it through the normal queue.
- **#231.** Both producers capture a hardware identity into a separate `printer_identity` table; a different identity sets a mismatch that holds sheet and calibration page jobs until an admin resolves it.
- **#230.** A frontend URL builder with a fixed field list opens a pre-filled issue form; no request leaves the hub.

**Tech Stack:** FastAPI 0.162 / Starlette 1.10, SQLModel/SQLite, Alembic, asyncio, pytest; React + Vite + vitest + Playwright, lingui.

**Spec:** the issues, with comments:
- #224 https://github.com/strausmann/Label-Printer-Hub/issues/224
- #225 https://github.com/strausmann/Label-Printer-Hub/issues/225
- #226 https://github.com/strausmann/Label-Printer-Hub/issues/226
- #227 https://github.com/strausmann/Label-Printer-Hub/issues/227
- #228 https://github.com/strausmann/Label-Printer-Hub/issues/228
- #229 https://github.com/strausmann/Label-Printer-Hub/issues/229
- #230 https://github.com/strausmann/Label-Printer-Hub/issues/230
- #231 https://github.com/strausmann/Label-Printer-Hub/issues/231

Maintainer rulings of 2026-11-09:
- no backwards compatibility for moved paths; release stays 1.x; #224–#231 all ship in 1.5.0;
- #224 is solved by live wiring, not a self-restart;
- #229: PT colour is read automatically if the hardware allows it over the network; the QL asks once on a detected roll change (width or media type differs), remembers it until the next change, "skip" means no colour line; "Colour not reported" disappears; if the PT cannot report colour over the network, it uses the same ask-on-change flow;
- release notes say installed clients keep old paths until the service-worker update prompt is accepted;
- #229 spike result B: neither PT nor QL reports tape colour over the network; **both families ask on a roll change**;
- #231: identity order `prtGeneralSerialNumber` (SNMP) → `printer-uuid` (IPP) → `ifPhysAddress.1` (fallback only); `hardware_id_kind ∈ {serial, ipp_uuid, mac}`; on a mismatch only sheet print and the calibration page are held, tape and plain page jobs keep running; the serial is shown with `admin` scope only (inventory data); task order: capture → detect → resolve → UI;
- #230: issue form `.github/ISSUE_TEMPLATE/sheet-type-feedback.yml`, label `area:sheets` (exists), fixed-field URL builder with privacy by construction, 8000-character cap with a fixed degrade, a test that YAML ids equal the builder ids; setting `verified` locally is a separate, explicit admin action, optional step.

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
- **UI task protocol (Tasks 7, 8, 11, 13, 17, 18).** Before writing UI code load the design skills `taste-skill:design-taste-frontend`, `emil-design-eng`, `mobile-native`, `break-ui`; at the end of the task run `impeccable:impeccable` on the changed screens. Take Playwright screenshots (light and dark, 1280 px and 390 px) with the existing `SHOTS` pattern (`frontend/e2e/shell.spec.ts:35`) as artifacts, not as a gate; attach them to the task report.
- **Agent limits.** Commands under 170 s each; no full suite outside the gate.

## Review Focus

1. **An admin change while a job prints on that printer.** The in-flight job finishes; jobs queued behind it stay `queued` and print after re-add; nothing is duplicated (Task 5 `test_remove_two_waiting_jobs_stay_queued`, Task 7 `test_update_during_inflight_job_keeps_job`).
2. **Two admin calls on the same printer at once.** The wiring ends in the state of the last committed row; one producer; no leaked worker (Task 7 `test_concurrent_reconcile_single_producer`).
3. **A printer whose stored connection cannot be wired at runtime** (bad URI, unresolvable tape model). The admin call succeeds, the printer is detached and degraded, the hub keeps running (Task 6 `test_attach_bad_uri_degrades`, `test_attach_unresolvable_tape_model_degrades_at_runtime`).
4. **A printer that has not been probed for days** (producer dead, printer disabled, hub clock jump). The UI never says Ready; it says the status is unknown and how old it is (Task 8 `test_status_older_than_bound_is_stale`, `describePrinter stale row is not ready`).
5. **A roll swapped while the hub was down.** The stored identity differs from the first probe after start; the colour is cleared and the prompt raised once, not on every probe (Task 10 `test_first_probe_after_restart_detects_change_once`).
6. **A printer that answers a probe without any identity** (SNMP agent hiccup, firmware that drops `prtGeneralSerialNumber` once). No mismatch, the stored identity stays (Task 14 `test_probe_without_identity_keeps_stored`, Task 15 `test_missing_identity_never_mismatches`).

---

## Ledger

| Item | Result |
|---|---|
| Task 0 spike: tape colour over the network (#229), run live read-only by the controller, 2026-11-09 | **B — not possible.** `ESC i S` on TCP 9100: no answer within 8 s on PT-P750W and QL-820NWB, raw and with the `0x00`×100 + `ESC @` prefix. SNMP v2c: `prtInputMediaName.1` = `12mm(0.47")` (PT) / `62mm / 2.4"` (QL); `prtInputMediaColor.1` = `stationery` on both (not a tape colour); `prtMarkerColorant.1` = `black`; Brother private `1.3.6.1.4.1.2435.2.3.9.4.2.1.5.5` holds undocumented hex blocks, no recognisable colour. **Both families use ask-on-roll-change.** |
| #231 spike: hardware identity, run live by the controller, 2026-11-09 | **PT-P750W:** `prtGeneralSerialNumber` (`1.3.6.1.2.1.43.5.1.1.17.1`) returns the serial (also under Brother private `…2435.2.3.9.4.2.1.5.5…`); `ifPhysAddress` returns the MAC. **QL-820NWB:** `prtGeneralSerialNumber` returns the serial; three `ifPhysAddress` entries, so the MAC is ambiguous. **HP CP1525N (IPP):** `printer-uuid` present (`urn:uuid:…`); `printer-device-id` has no `SN:`; `printer-serial-number`, `media-source-default`, `media-col-default` not reported, only `media-default` (A4). **Order:** serial (SNMP) → `printer-uuid` (IPP) → `ifPhysAddress.1` only if neither. |

---

## Task 0: Spike — tape colour over the network (#229) — DONE

Result **B** (see Ledger). No production code. Tasks 9–11 implement the ask-on-roll-change flow for PT and QL alike; nothing reads a colour from the printer.

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
  - Known matches that are not API calls (M10), fixed in this task: the regex literal in `frontend/src/pwa.test.ts:30` (`.not.toMatch(/api/)` → `/\/api\//`, which the guard does not match), and prose in `settings.test.tsx:341`, `Integrations.tsx:56`, `e2e/shell.spec.ts:29` (rewritten to `/api/v1/`). No exemption list.
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
- `async PrintQueue.add_printer(printer: _PrinterLike, *, paused_since: datetime | None = None) -> None` (tape)
- `async PrintQueue.add_page_printer(printer: PagePrinter, *, paused_since: datetime | None = None) -> None`
  - `paused_since` is the persisted manual pause; `PrinterRuntime` reads it from `printer_state` (the queue has no session, `load_manual_pauses` needs one, `print_queue.py:1612`). `start(initially_paused=…)` keeps working for the lifespan. **(Rev 4, finding 2)**
- `async PrintQueue.remove_printer(printer_id: UUID, timeout_s: float) -> None`
- `async PrintQueue._recover_printer(printer_id: UUID) -> None` — the per-printer body of `start()` (`print_queue.py:298-380`): `mark_interrupted` for that queue, the legacy-payload FAIL path (`:324-345`), tape recovery loop, `_recover_page_jobs` and `_recover_in_flight_page_jobs` (`:399-445`, fills `_to_resume`). It does **not** apply the pause; the caller does that first. `start()` applies `initially_paused` for all ids before any worker exists (as today, `:284-296`), then loops over printers calling it, then creates the workers.
- `self._stopping_printers: set[UUID]` — per-printer stop flag.

**Rules:**
- Add: same id + same object → no-op; same id + other object → `ValueError`.
  - **Queue not running** (lifespan): add only registers the printer (dicts, queue); no recovery, no worker. `start()` does both later.
  - **Queue running**, in this order **(Rev 4, finding 2)**: (1) apply `paused_since` (pause info + worker state) so no recovered job can print; (2) `await _recover_printer(id)` (mark_interrupted, recovery, `_to_resume`); (3) create the worker **last**, because `_page_worker` pops `_to_resume` once before its loop (`:1292`, `:1368`).
- Remove:
  1. Add the id to `_stopping_printers`; reject new submits for it with `KeyError` (same as unknown).
  2. Both workers (tape `_worker` after its take at `:1158`, `_page_worker` after `:1305`) check `printer_id in _stopping_printers` **immediately after `queue.get()`, before the `BatchJob` branch** (`:1159-1162`): a job or batch taken but not started is not run; it stays `queued` in the store. `_process_batch` checks the flag between items; the remaining items stay `queued` **(Rev 4, finding 3)**. `remove_printer` sets `_worker_resume_events[id]`, so a paused worker wakes up, sees the flag and exits the pause loop (`:1170-1174` and the page equivalent).
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
  - `test_readd_keeps_manual_pause`: one queued tape job and a persisted manual pause; remove, then `add_printer(fake, paused_since=…)` → the fake printed **nothing** and `queue.is_paused(id)` is True. Counter: apply the pause after recovery → red (job printed).
  - `test_remove_keeps_queued_batch_items`: a batch of 3 behind a blocked job; remove; release → nothing of the batch printed, all 3 items `queued`. Counter: check the flag after the `BatchJob` branch → red.
  - `test_add_on_stopped_queue_does_no_recovery`: add before `start()` → no store reads, no worker.
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
- Regression net that must stay green **unchanged**: `tests/integration/test_page_job_restart.py::test_restart_mid_job_ends_done` (real lifespan twice). **(Rev 4, finding 1)**

**Interfaces (produces):**
- `BackendRouter.register(cfg: PrinterYAMLConfig) -> None` (the type at `backend_router.py:85`) (raises `ValueError` on a duplicate slug) and `BackendRouter.unregister(slug: str) -> None` (drops `_configs`, `_backends`, `_services`; unknown slug is a no-op). `register_service` (`:103`) unchanged.
- `class PrinterRuntime`:
  - `__init__(self, app: FastAPI, settings: Settings)`
  - `async attach(printer: Printer, *, fatal: bool = False) -> None`
  - `async detach(printer_id: UUID) -> None`
  - `async reconcile(printer_id: UUID) -> None`
  - `async start() -> None` — starts every attached producer; after it, `attach` starts producers immediately
  - `async stop() -> None`
  - `describe_tape_for(printer_id: UUID, width_mm: int) -> TapeDescription` — uses the attached model driver (`printer_models/base.py:52`, built at `main.py:462-463`); falls back to the generic `"{N}mm"` label when the printer is not attached **(Rev 4, finding 7; used by Task 9)**
  - `is_polled(printer_id: UUID) -> bool` — True iff a producer runs for the id (used by Task 8)
  - `print_service_for(printer_id: UUID) -> PrintService | None` (used by Task 12)
  - `wiring_key(printer: Printer) -> tuple[object, ...]` (module-level): `(enabled, backend, connection, model, snmp settings, tray keys for ipp, queue_timeout_s for ipp only)`. Name, label and cut defaults are **not** in it (cut defaults come from the request, `print_service.py:106`). **Rev 4, finding 4 (controller ruling, replaces the R2 ruling):** for IPP printers `queue_timeout_s` is in the key, because both IPP clients take it at construction (`main.py:488-494`, `:579-588`); for tape printers it is not (used only for the shutdown wait, which `stop()` reads from the attached rows).
- It owns: tape `BackendRouter` registration + `PrintService` per tape printer; `IppClient`/`IppPrinterState`/`IppPagePrinter` per page printer (incl. `aclose()` of the page client on detach); producers (`StatusProbeProducer` + `TapeChangeProducer` for tape with `snmp.discover`, `IppStatusProducer` for page); queue membership via Task 5; `app.state.slug_to_printer_id`, `app.state.ipp_printer_states`; the back-compat fields `app.state.print_service`, `printer_id`, `printer_host`, `printer_snmp_community` recomputed after every attach/detach as the first enabled tape printer **ordered by `created_at`** (same order as `printers_repo.list_all`, `app/repositories/printers.py:20`).
- Locking: one `asyncio.Lock` **per printer id** (`dict[UUID, asyncio.Lock]`); `reconcile` takes only that printer's lock.
- One `asyncio.Semaphore(_IPP_PROBE_CONCURRENCY)` **per runtime**, passed to every `IppStatusProducer` (as `main.py:574` does today); never one per attach. **(Rev 4, finding 5)**
- **Startup order (lifespan), pinned (Rev 4, finding 1):** construct the queue → `attach(p, fatal=True)` for every enabled printer (queue not running, so add only registers; backends, services, producers built but not started) → `register_outcome_handler("sheet_page", …)` (`main.py:521-524`) → `queue.start(initially_paused=load_manual_pauses(…))` (`:518-520`) → `sweep_orphan_reservations` (`:526-529`) → `cleanup_task.start()` → `runtime.start()` (producers). This keeps today's restart behaviour: a page job at the printer is resumed, not settled as unknown (`print_queue.py:297-302`).
- No probe in `attach`. Both producers already probe immediately: `IppStatusProducer.start()` creates the loop task (`ipp_status_producer.py:155`) whose first statement is `probe_once()` (`:171-174`); `StatusProbeProducer.start()` (`status_probe_producer.py:87`) runs `_probe_once()` before its first sleep (`:266-269`). `attach` only calls `start()`; startup never awaits a probe.
- Failure handling: `fatal=True` (lifespan only) keeps today's behaviour — an unresolvable tape model (`_resolve_model_id_from_config` raising `ValueError`/`SnmpDiscoveryError`, `main.py:308-339`) aborts startup. `fatal=False` (admin path) logs slug + exception type only (never the URI/host), leaves the printer detached, does not raise. Other wiring failures (bad IPP URI) are degraded in both modes, as today.
- `stop()`: set a closed flag (later `reconcile` calls are no-ops), stop all producers, `await queue.stop(shutdown_wait_s(...))` **once** with the timeouts of the **currently attached** rows, then `aclose()` every page client. No per-printer remove.
- Manual pause survives re-wire: `attach` reads `printer_state.paused`/`paused_at` and passes `paused_since` to `add_*printer` (Task 5).

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
  - `test_ipp_probes_share_one_semaphore`: two IPP printers attached; both producers hold the same semaphore object.
  - `test_shutdown_wait_uses_attached_timeouts`: an IPP printer re-wired from 30 s to 90 s → `shutdown_wait_s` covers 90 s.
  - `test_describe_tape_for_uses_model_driver` (QL driver label for 62 mm differs from the generic `62mm`).
- [ ] **Step 2: Run** → FAIL (module missing).
- [ ] **Step 3: Implement** and switch the lifespan to `PrinterRuntime` in the pinned startup order, `stop()` on shutdown. Existing lifespan tests keep their behaviour: degraded start, empty table, shutdown order.
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
- Modify: `backend/app/schemas/printer.py` (`PrinterStatus`), `backend/app/api/routes/printers.py:363-406` (`get_printer_status`), both producers' cache writes (`status_probe_producer.py:_upsert_cache`, `_mark_offline`; `ipp_status_producer.py:_write_cache`), `backend/app/services/sse_snapshot.py:77-112` (same rule, finding 6).
- Create: `get_printer_runtime(request: Request) -> PrinterRuntime | None` dependency in `backend/app/api/dependencies/printer_runtime.py` (next to `webhook_auth.py`), overridable in tests **(Rev 4, finding 5)**.
- Modify existing assertions that build the app without a runtime or call the route directly (they assert `online is True` and would go red with `polled=False`): `tests/unit/api/test_printers_routes.py:204`, `:749`; `tests/integration/test_status_endpoint_cached.py:161`, `:182`; `tests/integration/api/test_printer_status_ipp.py:116`, `:189`. Each gets a `FakeRuntime(polled={printer_id})` through `app.dependency_overrides[get_printer_runtime]` (direct calls pass `runtime=FakeRuntime(...)`).
- Modify UI: `frontend/src/features/printers/model.ts` (`describePrinter`, `useKindLabel`), `PrinterDetail.tsx:83,95`, `PrinterCard.tsx`, `frontend/src/features/overview/OverviewPage.tsx`; create `frontend/src/features/printers/age.ts`.
- Test: `backend/tests/unit/services/test_status_freshness.py`, `backend/tests/integration/api/test_printer_status_staleness.py`, `frontend/src/features/printers/model.test.ts`, `frontend/src/features/printers/age.test.ts`.

**Decisions:**
- Bound: `stale_after_s(probe_interval_s: float) -> float = max(90.0, 3 * probe_interval_s)`. Documented in the `PrinterStatus` docstring and `docs/` printer status page.
- Age source: `updated_at` (time of the last probe **attempt**), not `captured_at` (an offline IPP write keeps `captured_at`, `ipp_status_producer.py:283`). **(R2 ruling)** Both producers set `row.updated_at = now` explicitly on every write, because `onupdate` does not fire when no column changes.
- `is_stale(updated_at: datetime, now: datetime, probe_interval_s: float) -> bool`; an `updated_at` more than `FUTURE_TOLERANCE_S = 60` in the future also counts as stale (clock jump, M9).
- SSE snapshot (`sse_snapshot.py`): for a stale or unpolled row, the `printer.status` frame carries `online: null`, `stale: true` and no tape/state values, and no `printer.tape_changed` frame is sent **(Rev 4, finding 6)**.
- New `PrinterStatus` fields (pinned): `stale: bool = False`, `polled: bool = True`.
- No-runtime case: `get_printer_runtime` returns `None` when `app.state.printer_runtime` is absent; the route then reports `polled: false` (no producer can exist without a runtime).
- Route: `polled = runtime.is_polled(id)`. If `not polled` or stale: `online: null`, `stale: true`, `tape_loaded`, `error_state`, `printer_state`, `state_reasons`, markers, tray media → null/empty **(R2 ruling: stale values are not returned, because the cached 62 mm tape next to "no tape" was the bug)**; `captured_at` and `last_probe_age_s` stay so the UI can show the age. `note`: `"Not polled"` when unpolled, `"Status older than {bound} s"` when stale. No row → as today, plus `polled`.
- UI kinds (pinned): `"stale"` → label en "Status unknown", de "Status unbekannt", badge `idle`; `"not_polled"` → en "Not monitored", de "Nicht überwacht", badge `idle`. `describePrinter` checks `polled === false`, then `stale`, before any `online` branch (paused still wins).
- Age format: `formatAge(seconds: number, locale: string) -> string` with `Intl.RelativeTimeFormat(locale, { numeric: "always" })`, largest unit of seconds/minutes/hours/days, floored. "Last status … ago" becomes `t\`Last status ${formatAge(age, i18n.locale)}\``.

- [ ] **Step 1: Failing tests:**
  - `test_stale_after_floor_and_multiple`: `stale_after_s(5) == 90`, `stale_after_s(30) == 90`, `stale_after_s(60) == 180`.
  - `test_status_older_than_bound_is_stale`: cache row `online: True`, `loaded_tape_mm: 62`, `updated_at` = now − 12 349 795 s → `online is None`, `stale is True`, `tape_loaded is None`, `last_probe_age_s` ≥ 12 349 795. (Today: `online: true`.)
  - `test_fresh_status_is_not_stale`: `updated_at` = now − 10 s → `stale is False`, `online is True`.
  - `test_unpolled_printer_reports_polled_false`: tape printer with `snmp.discover=false` and a fresh row → `polled is False`, `online is None`.
  - `test_offline_ipp_write_refreshes_updated_at`: two identical offline writes; `updated_at` advances; status `stale is False`, `online is False`.
  - `test_future_updated_at_is_stale`: `updated_at` = now + 1 h → `stale is True`. Counter: drop the tolerance check → red.
  - `test_no_runtime_reports_unpolled`.
  - `test_snapshot_omits_stale_status`: subscribe to `/api/v1/events` with a stale row → the snapshot `printer.status` has `online: null` and there is no `printer.tape_changed` frame.
  - UI: `describePrinter stale row is not ready` (`{online: true, stale: true}` → kind `stale`); `describePrinter unpolled` → `not_polled`; `formatAge(12349795, "en") === "143 days ago"`, `formatAge(12349795, "de") === "vor 143 Tagen"`, `formatAge(59, "en") === "59 seconds ago"`, `formatAge(7200, "de") === "vor 2 Stunden"`.
- [ ] **Step 2: Run** backend and vitest files → FAIL.
- [ ] **Step 3: Implement** backend, `pnpm gen:api`, UI (UI task protocol).
- [ ] **Step 4: Verify**; screenshots of a stale and an unpolled printer.
- [ ] **Step 5: Commit** `fix(status): show a stale or unpolled printer status as unknown with its age (#227)`.

## Task 9: One status-cache schema for tape printers (#229)

**Files:**
- Create: `backend/app/services/tape_status.py`
- Modify: `status_probe_producer.py` (`_upsert_cache` writes the schema), `backend/app/printer_backends/snmp_helper.py` (`PreflightStatus.media_raw: str | None = None` — a defaulted field, so the existing three-argument constructions in tests stay valid; no new OID), `printers.py` `get_printer_status` and `get_printer_tape` (`:414-460`), `schemas/printer.py`.
- Test: `backend/tests/unit/services/test_tape_status.py`, `backend/tests/integration/api/test_printer_tape.py`

**Decisions:**
- Cache schema (tape), pinned as `TapeStatusParsed(TypedDict, total=False)` in `tape_status.py`: `online: bool`, `loaded_tape_mm: int | None`, `media_raw: str | None` (the trimmed **media name text** already read from `PRT_INPUT_MEDIA_TYPE_OID` = `1.3.6.1.2.1.43.8.2.1.12.1.1`, column 12 of `prtInputTable` = `prtInputMediaName`, `snmp_helper.py:82`; no second OID), `hr_printer_status: str`, `error_flags: list[str]`, `last_error: str`. No colour keys: the printer reports none (Ledger, Task 0). `read_tape_status(parsed: Mapping[str, Any]) -> TapeStatusParsed` is the only reader. `media_width_mm` is gone.
- `GET /api/v1/printers/{id}/tape` returns `TapeRead {width_mm: int, label: str, media_raw: str | None, colour: TapeColourName | None}` (`colour` from the roll record once Task 10 exists; `None` until then); `label` from `PrinterRuntime.describe_tape_for(printer_id, width_mm)` (Task 6; the attached model driver, generic `"{N}mm"` fallback) **(Rev 4, finding 7)**; 404 only when `loaded_tape_mm` is null or no row. `TapeRegistry.lookup_pt` is no longer used there **(R2 ruling: the route serves PT and QL, `lookup_pt` is PT-only)**.
- `PrinterStatus` keeps `tape_loaded` (`"{mm}mm"`) for other readers and adds structured `tape_width_mm` and `tape_colour` (filled by Task 10 from the operator's roll record). The UI switches to the structured fields in Task 11 **(R2 ruling)**.
- Colour vocabulary `TapeColourName = Literal["white", "yellow", "green", "blue", "red", "black", "clear"]` in `tape_status.py`.

- [ ] **Step 1: Failing tests:**
  - `test_tape_endpoint_reads_snmp_cache`: row `{online: True, loaded_tape_mm: 62}` → 200, `width_mm == 62` (today 404).
  - `test_tape_endpoint_404_without_tape`.
  - `test_producer_writes_media_raw`: patched preflight `media_raw="62mm(2.44\")"` → cache has it.
  - `test_tape_label_comes_from_model_driver`: QL printer attached → `label` is the QL driver's text, not `62mm`.
  - `test_status_has_structured_width`: row `loaded_tape_mm: 12` → `tape_width_mm == 12`, `tape_colour is None`.
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
- Roll identity = `(width_mm, media_raw)` **(R2 ruling: SNMP gives no media-type code, so the raw media text stands for "media type"; any text change counts as a change)**. Known limitation (M4): the spike saw only width text in `prtInputMediaName`, so a die-cut and a continuous DK roll of the same width may not register as a change; the edit control covers it.
- Taking the cassette out and putting it back counts as a change (`(None, None)` in between) and prompts again — intended, the same cassette cannot be proven (M4).
- Migration `20261109a1`: `down_revision = "20261108a1"` (`alembic/versions/2026_11_08_0001-20261108a1_jobs_page_sheet_index.py`, the single head at `3a6f41f`).
- `RollTracker.observe(printer_id: UUID, width_mm: int | None, media_raw: str | None) -> RollChange | None`:
  - identity unchanged → no write, `None`;
  - identity differs or no row → clear `colour`/`set_at`, store identity, `changed_at = now`, `prompt_pending = width_mm is not None`; publish `printer.roll_changed` on `printer:{id}:tape` with `{width_mm, media_raw, prompt_pending}`; return the change.
  - The first probe after a restart compares against the DB row, so a swap while the hub was down is detected; a first-ever observation counts as a change **(R2 ruling: one prompt per printer after the upgrade)**.
- PT and QL use the same flow (Ledger, Task 0).
- Endpoints:
  - `GET /api/v1/printers/{printer_id}/roll` (`read` scope, `check_printer_access`) → `RollRead {width_mm, media_raw, colour, set_at, prompt_pending}`; 404 unknown printer.
  - `PUT /api/v1/printers/{printer_id}/roll` (`print` scope, `check_printer_access`) body `RollColourUpdate {colour: TapeColourName | None, width_mm: int | None = None}` (extra forbid); when `width_mm` is given and differs from the stored roll → 409 `type: "roll-changed"` (a PUT racing a detected change, M3); the UI always sends it. Sets `colour`, `set_at = now` (null colour → `set_at` null), `prompt_pending = false`; `colour: null` is "skip" and "clear". 409 `type: "no-roll-loaded"` when `width_mm` is null. Publishes `printer.roll_changed`. Returns `RollRead`.
- `PrinterStatus` adds `roll_prompt: bool` and fills `tape_colour` from the roll record; `/tape` fills `colour` the same way.

- [ ] **Step 1: Failing tests:**
  - `test_pt_and_ql_both_prompt`: one PT and one QL printer each see a new roll → both `prompt_pending`.
  - `test_roll_change_clears_colour_and_raises_prompt`: stored `(62, "62mm")` colour `red`; observe `(29, "29mm")` → colour null, `prompt_pending` True, one event.
  - `test_same_roll_does_not_reprompt`: observe the same identity 3× → one event total.
  - `test_first_probe_after_restart_detects_change_once`: DB row `(62, …)`, fresh tracker instance, observe `(12, …)` twice → one change.
  - `test_no_tape_clears_without_prompt`.
  - API: `test_set_colour_clears_prompt`; `test_skip_sets_no_colour` (`colour: null` → status `tape_colour is None`, `roll_prompt is False`); `test_read_key_cannot_set_colour` (403); `test_restricted_key_cannot_set_other_printer` (403) and can set its own (200); `test_set_colour_without_roll_is_409`; `test_set_colour_for_old_roll_is_409` (stored 29 mm, body `width_mm: 62`); `test_restricted_key_cannot_read_other_roll` (403).
  - Migration upgrade + downgrade on an empty and a populated DB.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**; `pnpm gen:api`.
- [ ] **Step 4: Verify** per directory, ruff, mypy. The migration test builds its 1.4.0-shaped DB in the test (`alembic upgrade 20261108a1` + inserted printers/cache rows), then `upgrade head` and `downgrade -1`.
- [ ] **Step 5: Commit** `feat(printers): remember the roll colour per printer and detect roll changes (#229)`.

## Task 11: Tape colour in the UI — prompt, edit, no "Colour not reported" (#229)

**Files:**
- Create: `frontend/src/features/printers/RollColourPrompt.tsx` (+ test)
- Modify: `TapeSwatch.tsx` (props `{widthMm, colour, probed}`; no colour → no colour line), `model.ts` (`TAPE_COLOURS` + `black`, `clear`; `parseTape` removed if unused), `PrinterDetail.tsx` (prompt above Material, "Change colour" control in the Material section), `PrinterCard.tsx`, `OverviewPage.tsx`, `frontend/src/api/events.ts` (add `printer.roll_changed` to `EVENT_TYPES`, `:13-20`, otherwise no listener exists; it invalidates the printer's status and roll queries, M11), `frontend/src/design/tokens.css` + `index.css` (`tape-black`, `tape-clear`), both catalogs (remove "Colour not reported").
- Test: `TapeSwatch.test.tsx` (replace the `:26` assertion), `RollColourPrompt.test.tsx`, `frontend/e2e/printers.spec.ts`.

- [ ] **Step 1: Failing tests:**
  - `TapeSwatch shows no colour line without a colour`: `queryByText(/colour/i)` is null and the width shows.
  - `catalogs have no "Colour not reported"`: both `.po` files lack the msgid.
  - `RollColourPrompt offers the known colours and skip`: renders when `roll_prompt` is true; choosing "Blue" sends `PUT /api/v1/printers/{id}/roll {colour: "blue", width_mm: <shown width>}`; "Skip" sends `{colour: null}`; a `read` user sees no prompt.
  - `events listen for printer.roll_changed` (`EVENT_TYPES` contains it).
  - e2e `roll prompt after a roll change`: mock status `roll_prompt: true` → prompt visible; after skip, no colour line.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** (UI task protocol).
- [ ] **Step 4: Verify** frontend checks; screenshots with prompt, with colour, without colour.
- [ ] **Step 5: Commit** `feat(ui): ask for the roll colour on a roll change and show the tape colour truthfully (#229)`.

## Task 12: Test print endpoint (#228)

**Files:**
- Create: `backend/app/api/routes/test_print.py` (router prefix `/api/v1/printers`), `backend/app/services/test_print.py`, `backend/app/page_render/test_page.py`
- Modify: `backend/app/services/page_jobs.py:38` (`PageKind` adds `"test_page"`; renderer registered via `register_page_renderer`; the default no-op outcome handler applies, so no sheet state is touched), `backend/app/services/print_service.py` (`submit_test_label`), `backend/app/api/routes/jobs.py:447` (retry accepts `test_page` like `calibration_page`), app factory (router).
- Test: `backend/tests/integration/api/test_test_print_api.py`, `backend/tests/unit/page_render/test_test_page.py` (with `tests/helpers/pdf_inspect.py`).

**Interfaces:**
- `POST /api/v1/printers/{printer_id}/test-print`, body `TestPrintRequest {tray: str | None = None}` (extra forbid), `202 TestPrintAccepted {job_id: UUID}`, `print` scope, `check_printer_access`.
- **Tape: the submit-time preflight decides, not the status cache (Rev 4, finding 12, controller ruling).** `async PrintService.submit_test_label(build: Callable[[int], RawLabelData]) -> UUID` runs the same path as `submit_print_job` (`print_service.py:56-100`: enabled check, **one** `preflight_check()`, `NoTapeLoadedError`/`PrinterOfflineError`, render, persist, queue) and calls `build(preflight.loaded_tape_mm)` for the label data; the job is stored with `template_key="test_label"` and `content_type=QR_THREE_LINES`. The two methods share one private helper; no second preflight.
- `tape_test_label(printer: Printer, width_mm: int, now: datetime, version: str, printer_url: str) -> RawLabelData`: `qr_payload = printer_url`, `primary_id = printer.name`, `title = f"{width_mm} mm · {now:%Y-%m-%d %H:%M}"`, `secondary = [f"Printer Hub {version}"]`; one copy. Called through `PrinterRuntime.print_service_for(id).submit_test_label`.
- `build_test_page_payload(printer: Printer, tray: str, media: str, margins_mm: HardwareMargins | None, now: datetime, version: str, printer_url: str) -> PagePayload` (kind `"test_page"`, `render_dpi=600` like the calibration page `calibration/page.py:396`, `job_name=f"Test page · {tray}"`) and `render_test_page(payload: PagePayload) -> bytes`: a frame on the printable area from the reported hardware margins (capabilities `hardware_margins_mm`, `capabilities.py:70-85`; when not reported: a 5 mm inset frame and the line "Margins not reported"), name, tray, date/time, one text line "Printer Hub test page {version}", a QR to `printer_url`. Title text "Test page"; it never uses the calibration renderer. Submitted through `queue.submit_page_job`.
- `media` source **(Rev 4, finding 13)**: the tray's media from the status cache (`TrayStatusRead.media`); else the printer's `media-default` from its capabilities probe (the HP reports only that, Ledger #231); else 409 `media-unknown`.
- Test-page jobs are retryable like calibration pages (controller ruling): the retry route re-submits the stored payload.
- `printer_url = f"{str(settings.public_url).rstrip('/')}/printers/{printer_id}"` (`public_url` is `AnyHttpUrl`, `config.py:67`, usually ending in `/`; M6; SPA route `/printers/$printerId`, `router.tsx:206`). `now` is local time (`datetime.now().astimezone()`).
- Refusals, in this order (M7: the scope dependency runs first, as in `get_printer_status`, `printers.py:376-378`), as `ProblemDetail` like `calibration.py:242`:
  - `read` key → 403 (dependency);
  - unknown printer → 404;
  - restricted key on another printer → 403 (`check_printer_access`);
  - disabled → 409 `printer-disabled`;
  - paused → 409 `printer-paused` **(R2 ruling: the UI disables the button while paused; the API agrees)**;
  - `tray` on a tape printer, or unknown/disabled tray → 422 `tray-invalid`; no tray on a page printer → the default tray;
  - **page printers only:** unpolled → 409 `printer-status-unknown` (no `IppPrinterState` without a producer); stale, no row, or `online` not true → 409 `printer-offline`;
  - **tape printers:** no status-cache check; the preflight raises `PrinterOfflineError` → 409 `printer-offline`, `NoTapeLoadedError` → 409 `no-tape-loaded` (existing mapping).
  - Not held by an identity mismatch (Task 15): the test print uses no calibration.

- [ ] **Step 1: Failing tests:**
  - `test_tape_test_print_creates_one_job_done`: fake tape backend; 202; exactly one new job row with `template_key == "test_label"`; reaches `done`; rendered image width = the preflight's tape; the preflight ran once.
  - `test_unpolled_tape_printer_test_print_is_202`: tape printer with `snmp.discover=false`, preflight answers → 202. Counter: refuse on `polled false` → red.
  - `test_unpolled_page_printer_is_409_status_unknown`.
  - `test_test_page_media_falls_back_to_media_default`; `test_test_page_without_margins_draws_inset_frame`; `test_test_page_retry_resubmits`; `test_printer_url_has_single_slash`.
  - `test_page_test_print_creates_one_job_done`: fake IPP; 202; reaches `done`; the submitted PDF has one page whose frame rectangle matches the margins ±0.5 mm and contains the printer name and tray.
  - `test_test_print_reserves_no_sheet_cells`: row counts of sheet tables before == after.
  - `test_read_key_is_403`, `test_restricted_key_other_printer_is_403`, `test_restricted_key_own_printer_is_202`.
  - `test_disabled_is_409`, `test_paused_is_409`, `test_offline_is_409` (tape via preflight, page via cache), `test_stale_page_printer_is_409`, `test_unknown_printer_is_404`, `test_read_key_on_unknown_printer_is_403`, `test_tray_on_tape_printer_is_422`.
  - `test_test_page_is_not_calibration_page`: the PDF text contains "Test page" and not the calibration title.
- [ ] **Step 2: Run** → FAIL (404, route missing).
- [ ] **Step 3: Implement**; `pnpm gen:api`.
- [ ] **Step 4: Verify** per directory; the route versioning guard (Task 2) still passes; ruff, mypy.
- [ ] **Step 5: Commit** `feat(printers): test print endpoint for tape and page printers (#228)`.

## Task 13: Test print button (#228)

**Files:**
- Create: `frontend/src/features/printers/TestPrintButton.tsx` (+ test)
- Modify: `PrinterDetail.tsx` (header action next to `PauseResumeButton`), both catalogs.
- Modify (Jobs UI, finding 13): `frontend/src/features/jobs/model.ts:8` (`PageKind` adds `"test_page"`; `pageInfoOf`, `:51`, handles it), `PageJobInfo.tsx` (tray, media), `useJobTitle.ts` (`test_page` → "Test page · {tray}"; tape job with `template_key == "test_label"` → "Test label"), their tests.
- Test: `frontend/e2e/printers.spec.ts`, `frontend/e2e/page-printer.spec.ts`.

**Decisions:**
- Shown for every printer to `print` scope and up; hidden for `read`.
- Disabled with the reason as visible text (not only a tooltip) when: disabled ("Printer is disabled"), paused ("Printer is paused"); for page printers additionally unpolled ("Printer status unknown") and stale/offline ("Printer is not reachable"). Tape printers are **not** disabled on status; their 409 (`printer-offline`, `no-tape-loaded`) is shown after the click, because the preflight decides (Task 12).
- Page printers: a tray select (enabled trays, default preselected) in a small popover; tape printers: one click.
- On 202: toast with a link to `/jobs/{job_id}`; on 409/422 the API `detail` is shown.

- [ ] **Step 1: Failing tests:** `TestPrintButton is disabled with reason when a page printer is offline`; `… is enabled for an unpolled tape printer`; `useJobTitle names a test page and a test label`; `pageInfoOf returns info for test_page`; `… posts once for a tape printer`; `… sends the chosen tray`; e2e `test print reaches done` on both fake printer kinds.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** (UI task protocol; `break-ui` with a 60-char printer name and many trays).
- [ ] **Step 4: Verify** frontend checks; screenshots.
- [ ] **Step 5: Commit** `feat(ui): test print button on every printer page (#228)`.

## Task 14: Capture a hardware identity in both producers (#231)

**Files:**
- Create: `backend/alembic/versions/2026_11_09_0002-20261109b1_printer_identity.py` (additive: one new table, `down_revision = "20261109a1"`; downgrade drops the table, so no `batch_alter_table` is needed), `backend/app/models/printer_identity.py`, `backend/app/repositories/printer_identity.py`, `backend/app/services/hardware_identity.py`
- Modify: `backend/app/printer_backends/snmp_helper.py` (new `query_identity`; `query_preflight` and `PreflightStatus` **unchanged**), `status_probe_producer.py`, `ipp_status_producer.py` (`_query` returns the uuid next to the record), `backend/app/printer_backends/ipp/attributes.py` (`PRINTER_ATTRS:40` + `"printer-uuid"`; `IppStatusRecord` **unchanged**), `printer_runtime.py` (builds the sink).
- Test: `backend/tests/unit/services/test_hardware_identity.py`, `backend/tests/unit/printer_backends/test_snmp_identity.py`, `backend/tests/integration/db/test_alembic_printer_identity.py`, `backend/tests/integration/test_identity_capture.py`

**Decisions:**
- **Own table `printer_identity`** (controller ruling, finding 8), PK `printer_id` FK `printers.id`, all others nullable: `hardware_id`, `hardware_id_kind` (`serial` | `ipp_uuid` | `mac`), `hardware_id_seen_at`, `observed_id`, `observed_kind`, `mismatch_since`. It replaces the R3 "columns on `printers`" ruling; `printers.updated_at` never moves on a probe. All #231 schema lives in this one migration.
- `seen_at` is written at most every 600 s for an unchanged identity **(R4 ruling: one write per printer per 30 s buys nothing)**.
- **SNMP (controller ruling, finding 9):** `query_identity(host: str, *, community: str = "public", timeout_s: float = 3.0) -> ObservedIdentity` in `snmp_helper.py`, one `get_cmd` with `prtGeneralSerialNumber.1` (`1.3.6.1.2.1.43.5.1.1.17.1`) and `ifPhysAddress.1` (`1.3.6.1.2.1.2.2.1.6.1`). Only `StatusProbeProducer` calls it, after a successful preflight. Any failure (transport, `error_status`, `noSuchObject`) yields an empty `ObservedIdentity` and is never raised; the probe result is unaffected. The print path (`PTouchBackend.preflight_check`, QL backend) does not change.
- **IPP (controller ruling, finding 15):** `printer-uuid` is requested on every status probe; `IppStatusProducer._query` returns `(record, printer_uuid)`; the uuid goes to the sink, **never** into `IppStatusRecord` or `printer_status_cache.parsed`.
- `ObservedIdentity(serial: str | None, ipp_uuid: str | None, mac: str | None)` (frozen dataclass, all candidates of one probe) and `HardwareIdentity(kind, value)`.
- `normalise(observed) -> ObservedIdentity`: serial `strip()` (empty → `None`); uuid lower-case without `urn:uuid:`; MAC lower-case `aa:bb:cc:dd:ee:ff`, all-zero → `None`.
- `pick_identity(observed) -> HardwareIdentity | None`: serial → ipp_uuid → mac.
- **`async record_identity(printer_id: UUID, observed: ObservedIdentity, now: datetime) -> IdentityOutcome`** (controller ruling, finding 10, replaces R3-2), `IdentityOutcome = Literal["none", "stored", "seen", "kind_upgraded", "kept", "different"]`:
  - `pick_identity` is `None` → `none`, no write at all;
  - no stored row → `stored`;
  - observed value of the **stored kind** equals the stored value → `seen`; if additionally a higher-ranked kind is observed (`mac` < `ipp_uuid` < `serial`) → `kind_upgraded` (store the higher kind);
  - observed value of the stored kind is absent → `kept` (no write, no upgrade, no mismatch);
  - observed value of the stored kind differs → `different` (acted on in Task 15).
- **Connection change by an admin (controller ruling, finding 11):** `update_printer` never touches `printer_identity`. After re-wire, the same identity is confirmed silently (`seen`); a different one is `different` → mismatch (Task 15), resolved by the admin (Task 16). This protects the calibration when the new address is another device.
- Producers call an injected `identity_sink: Callable[[UUID, ObservedIdentity], Awaitable[IdentityOutcome]]` after a **successful** probe only. Creation-time capture is the t=0 probe (Task 6).
- **Printers without a producer** (tape with `snmp.discover=false`) get no identity and therefore no swap detection (M13); the printer page says so for admins (Task 17), and rollout step 7 checks it.
- **Logs (M12):** identity values are never logged at any level; outcomes are logged by kind only.

- [ ] **Step 1: Failing tests** (counter-test noted where not obvious):
  - `test_pick_identity_order` and `test_normalise` (uuid prefix, MAC bytes `b"\x00\x80\x77\x12\x34\x56"` → `"00:80:77:12:34:56"`, all-zero → `None`). Counter: swap the order → red.
  - `test_query_identity_reads_serial_and_mac` (patched `get_cmd`, 2 varbinds) and `test_identity_query_failure_never_fails_probe` (`get_cmd` raises / returns `error_status` → probe still writes `online: True`, observed is empty).
  - `test_preflight_unchanged`: `query_preflight` still sends exactly the three OIDs. Counter: add an OID → red.
  - `test_first_probe_stores_identity` (SNMP → `serial`), `test_ipp_probe_stores_printer_uuid` (→ `ipp_uuid`).
  - `test_status_cache_has_no_identity`: after an IPP probe with a `printer-uuid`, `parsed` has no key or value containing the uuid. Counter: put it on `IppStatusRecord` → red.
  - `test_probe_without_identity_keeps_stored`: stored serial; probe reports nothing → row unchanged. Counter: write `None` → red.
  - `test_failed_probe_does_not_touch_identity`.
  - `test_mac_to_serial_upgrade_requires_matching_mac`: stored `mac=X`; observed `serial=S, mac=X` → `kind_upgraded`; observed `serial=S, mac=Y` → `different`; observed `serial=S, mac=None` → `kept`. Counter: the R3-2 rule (upgrade without comparison) → the second case is green-wrong → red.
  - `test_swap_with_first_contact_as_mac`: printer A stored as `mac=X` (serial OID silent at first contact); device B behind the address reports `serial=S, mac=Y` → `different`, never `kind_upgraded` (the reviewer's scenario).
  - `test_connection_change_keeps_identity`: `PUT` with a new host; next probe reports the stored serial → `seen`, no mismatch; reports another serial → `different`.
  - `test_probe_does_not_change_printer_updated_at`: 3 probes → `printers.updated_at` unchanged.
  - `test_seen_at_throttled`: two `seen` within 600 s → one write.
  - `test_identity_never_logged`: `caplog` across store/seen/different contains no test serial/uuid/MAC.
  - Migration: upgrade from `20261109a1` and downgrade, empty and populated.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify** per directory; the nine existing files that mock three-varbind preflights (review 2, finding 9) pass unchanged; ruff, mypy.
- [ ] **Step 5: Commit** `feat(printers): capture a hardware identity from SNMP and IPP probes (#231)`.

## Task 15: Detect a device swap and hold sheet and calibration jobs (#231)

**Files:**
- Modify: `hardware_identity.py` (act on `different`), `printers.py` `get_printer_status`, `schemas/printer.py`, `backend/app/api/routes/sheet_print.py` (`print_sheet:166`), `calibration.py` (`print_calibration_page:181`), `jobs.py` (`_retry_sheet_page`, `_retry_page_job`, `:425-466`), `print_queue.py` (`_page_worker:1283`; `set_identity_hold`).
- Test: `backend/tests/integration/test_identity_mismatch.py`, `backend/tests/integration/api/test_identity_hold.py`

**Decisions:**
- `different`: set `observed_id`, `observed_kind`, `mismatch_since = now` (kept if already set); stored identity untouched; publish `printer.identity_mismatch` on `printer:{id}:state` with `{mismatch: true, since}` — no identity values (SSE is readable with `read` scope).
- A later `seen` (the stored identity is back) clears the mismatch and publishes `{mismatch: false}` (R3 ruling, unchanged).
- `PrinterStatus.identity_mismatch: bool` for every scope; values stay admin-only (Task 16).
- Held kinds: sheet print and calibration page. Refused with 409 `ProblemDetail type="printer-identity-mismatch"`, `detail` names only the printer id (M12), at **submit and at retry** (`_retry_sheet_page`, `_retry_page_job`; finding 14). Tape jobs, plain page jobs and the test print are not held.
- **Dispatch check (finding 14):** an in-memory set in the queue, `PrintQueue.set_identity_hold(printer_id: UUID, held: bool) -> None`, kept by the identity sink and loaded at `attach` from `printer_identity.mismatch_since`. The page worker checks it right before dispatching a `sheet_page`/`calibration_page` job; no DB read in the worker.
- **How a held queued job ends (finding 14, R3-4 kept):** through the runner's not-started failure path — the job ends `failed` with error code `printer-identity-mismatch` and the outcome handler's `on_ended(started=False)` runs, so the sheet rows are deleted (`sheets/outcome.py:6-8`). Never a bare `mark_failed`.
- The mismatch survives a restart (it is in `printer_identity`).

- [ ] **Step 1: Failing tests:**
  - `test_different_identity_sets_mismatch`: stored `A`, observed `B` → `identity_mismatch is True`, stored stays `A`, one event whose data contains neither value.
  - `test_missing_identity_never_mismatches`.
  - `test_stored_identity_back_clears_mismatch`.
  - `test_sheet_print_refused_on_mismatch`, `test_calibration_page_refused_on_mismatch`, `test_retry_refused_on_mismatch` (both retry kinds).
  - `test_tape_and_plain_page_jobs_still_print_on_mismatch`; `test_test_print_not_held_on_mismatch`.
  - `test_queued_sheet_job_fails_at_dispatch_on_mismatch`: job queued, then mismatch, then dispatch → `failed` with that code and its sheet rows gone. Counter: `mark_failed` directly → rows remain → red.
  - `test_mismatch_survives_restart` (hold reloaded at attach).
  - `test_mismatch_detail_has_no_identity`.
  - Counter for each guard: remove it → the job prints / no event → red.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement;** `pnpm gen:api`.
- [ ] **Step 4: Verify** per directory, ruff, mypy.
- [ ] **Step 5: Commit** `feat(printers): detect a swapped device and hold sheet and calibration jobs (#231)`.

## Task 16: Admin resolves a device swap; identity visible to admins only (#231)

**Files:**
- Modify: `backend/app/api/routes/admin_printers_api.py` (new route; admin `PrinterRead`, `:80`), `backend/app/services/printer_admin_service.py`, `backend/app/schemas/printer.py` (read-scope `PrinterRead`, `:31`), `printers.py` (view next to `_connection_view:76`).
- Test: `backend/tests/integration/api/test_identity_resolve.py`

**Interfaces:**
- `POST /api/v1/admin/printers/{printer_id}/identity/resolve`, `admin` scope, body `IdentityResolve {resolution: Literal["same_device", "replaced"]}` (extra forbid) → 200 **admin** `PrinterRead` (`admin_printers_api.py:80`, M1).
  - `same_device`: stored := observed (kind + value), `seen_at = now`, mismatch cleared; calibration kept.
  - `replaced`: **one transaction (controller ruling, M2):** delete every stored `PrinterCalibration` row of the printer (iterate the rows, not "every tray"; `calibration.service.delete` commits per tray, `service.py:169-180`, so the route uses a repository-level delete inside the transaction), then set stored := observed and clear the mismatch; commit once. Any failure rolls back everything and the hold stays.
  - 409 `no-identity-mismatch` when none is pending; 404 unknown printer.
  - Writes a `printers_audit` row (action `identity_resolved`, resolution, **no** identity values); publishes `printer.identity_mismatch {mismatch: false}` and `hub.printers_changed`; calls `queue.set_identity_hold(id, False)`.
- Both `PrinterRead` classes (`schemas/printer.py:31` read scope, `admin_printers_api.py:80` admin) gain `hardware_id`, `hardware_id_kind`, `hardware_id_seen_at`, filled **explicitly** from `printer_identity` — never via `from_attributes` — and only for `admin` callers; `null` otherwise (decision: serial is inventory data, M1).

- [ ] **Step 1: Failing tests:** `test_resolve_same_device_keeps_calibration`; `test_resolve_replaced_resets_calibration` (all stored rows gone, other printers' untouched); `test_replaced_is_atomic` (make the second delete fail → every calibration row still there and `identity_mismatch` still true); `test_resolve_without_mismatch_is_409`; `test_resolve_needs_admin` (print key → 403); `test_jobs_allowed_after_resolve`; `test_read_key_sees_no_hardware_id` (read-scope list and detail) and `test_admin_sees_hardware_id`; `test_audit_row_has_no_identity_value`; `test_resolve_logs_no_identity` (`caplog`).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement;** `pnpm gen:api`.
- [ ] **Step 4: Verify;** the route guard (Task 2) still passes.
- [ ] **Step 5: Commit** `feat(printers): let an admin resolve a device swap, keeping or resetting calibration (#231)`.

## Task 17: Hardware identity and swap state in the UI (#231)

**Files:**
- Create: `frontend/src/features/printers/IdentityMismatchBanner.tsx` (+ test)
- Modify: `PrinterDetail.tsx` (Connection section row "Serial number" / "IPP UUID" / "MAC address" by kind, admin only; banner at the top), `PrinterCard.tsx` (a warn badge "Different device"), `frontend/src/api/events.ts` (add `printer.identity_mismatch` to `EVENT_TYPES`, `:13-20`, M11; it invalidates status and printer queries), sheet print error mapping (`frontend/src/features/sheets/print/errors.ts`: `printer-identity-mismatch` → readable text), both catalogs.
- Test: `IdentityMismatchBanner.test.tsx`, `frontend/e2e/printers.spec.ts`.

**Decisions:** banner text (en) "Different device detected at this address. Sheet printing and the calibration page are held until an admin confirms." (de with real umlauts). Admins see "Same device" and "Device replaced"; "Device replaced" opens a confirm dialog naming that the calibration of every tray is reset. Non-admins see the banner only. An admin viewing a printer without an identity (no producer, or nothing reported) sees "No hardware identity — device swaps are not detected" in the Connection section (M13).

- [ ] **Step 1: Failing tests:** `EVENT_TYPES` contains `printer.identity_mismatch`; banner shown when `identity_mismatch`; admin sees the no-identity note; admin buttons post the two resolutions; replaced needs the confirm; `read` user sees no buttons and no serial row; sheet print shows the mapped text; e2e mismatch → resolve → banner gone.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** (UI task protocol; `break-ui` with a 64-char serial).
- [ ] **Step 4: Verify** frontend checks; screenshots.
- [ ] **Step 5: Commit** `feat(ui): show the printer's hardware identity and a device swap (#231)`.

## Task 18: Sheet-type feedback through a pre-filled GitHub issue (#230)

**Files:**
- Create: `.github/ISSUE_TEMPLATE/sheet-type-feedback.yml`, `frontend/src/features/archive/feedbackLink.ts`, `frontend/src/features/archive/feedbackLink.test.ts`, `frontend/src/features/archive/FeedbackLinks.tsx` (+ test)
- Modify: `frontend/src/features/archive/TypeDetail.tsx` (the type detail is the archive page with `?type=<key>`, `search.ts:40`; the issue's `/sheets/archive/{key}` is that page), `frontend/package.json` (devDependency `yaml` pinned `2.9.1`, already in `pnpm-lock.yaml:4465` as a transitive dependency — promoted, not new; M15), both catalogs.
- Repo label: create `type:feedback` (`gh label create type:feedback`); `area:sheets` and `type:bug` exist.

**Interfaces:**
- `FEEDBACK_FIELD_IDS` (readonly tuple, pinned): `kind`, `type_key`, `type_version`, `version_note`, `vendor`, `product_codes`, `geometry`, `allow_qr`, `verified`, `provenance`, `printer_model`, `tray`, `calibration`, `observed`, `hub_version`, `scheme`, `browser`, `privacy_check`. `observed` and `privacy_check` are never pre-filled (user writes / ticks them).
- `type FeedbackKind = "wrong" | "confirmed"`.
- `interface FeedbackInput { kind; sheetType: SheetTypeRead; version: VersionRead; hubVersion: string; scheme: "http" | "https"; printer?: { model: string; tray: string; calibration: "calibrated" | "uncalibrated" }; browser?: string }` — typed values only; nothing from page state is read by the builder.
- `buildFeedbackUrl(input: FeedbackInput) -> string`: base `https://github.com/strausmann/Label-Printer-Hub/issues/new?template=sheet-type-feedback.yml`; `title` = `[sheet type] {key} v{version}: dimensions wrong` / `… dimensions confirmed`; `labels` = `area:sheets,type:bug` (wrong) or `area:sheets,type:feedback` (confirmed); each field via `URLSearchParams`. `geometry` = one line per stored number, `name: value mm` (counts without unit).
- `MAX_URL = 8000`. Degrade, in this order, until the URL fits: drop `browser`; drop `printer_model`, `tray`, `calibration`; drop `version_note`; drop the provenance URL (keep its name); replace `geometry` with `See the export: /api/v1/sheet-types/{key}/export (paste it here)`. Each step is tested; the result is always ≤ 8000.
- `provenance`: the source name always; the source **URL only when `origin == "seed"`** (shipped with the hub). For `custom` and `imported` types the URL is omitted, because it is user-entered and may point into an intranet (controller ruling, M14). The privacy checkbox text also says "I checked the vendor, product codes and note for anything internal".
- Privacy by construction: the builder takes only `FeedbackInput`; there is no parameter for host, URI, keys, user names, sheet codes or integration URLs. The relative export path contains no host.
- Buttons "Report a problem with the dimensions" and "Confirm the dimensions" as `<a target="_blank" rel="noopener noreferrer">`, visible to every role.
- Optional step (admin only, separate explicit action): "Mark as verified locally" → `PATCH /api/v1/sheet-types/{key}` `{verified: true}` (existing route, `sheet_types.py:232`) after a confirm dialog. It is never triggered by the link.

- [ ] **Step 1: Failing tests:**
  - `yaml ids equal builder ids`: parse the YAML with `yaml`, collect `body[].id`; `toEqual([...FEEDBACK_FIELD_IDS])` (order included). Counter: rename one id in the YAML → red.
  - `geometry has every stored number with units`.
  - `encodes umlauts, &, # and newlines` (round-trip through `new URL(...).searchParams`).
  - `degrades in the documented order under 8000` (a product-code list long enough to force each step; assert which fields remain and `url.length <= 8000`).
  - `omits source_url for custom and imported types`: a custom type with `source_url = "http://wiki.intranet.local/labels"` → that string is not in the URL; a seed type's URL is. Counter: always include it → red.
  - `carries no host, uri or key`: an input built from a page state that includes `location.host`, a printer URI and an API key in neighbouring objects → none of those strings in the URL. Counter: a builder that serialises `sheetType` wholesale → red.
  - e2e: both links have `href` starting with `https://github.com/strausmann/Label-Printer-Hub/issues/new?template=sheet-type-feedback.yml`, `target="_blank"`, `rel="noopener noreferrer"`; a `read` user sees them; the verify button is admin-only and sends the PATCH only after confirm.
  - Issue form validity: `gh api repos/strausmann/Label-Printer-Hub/contents/.github/ISSUE_TEMPLATE` lists it after push, and the form renders on the branch (manual check recorded in the report).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** (UI task protocol).
- [ ] **Step 4: Verify** frontend checks; screenshots.
- [ ] **Step 5: Commit** `feat(sheets): report or confirm sheet type dimensions through a pre-filled issue (#230)`.

## Order and dependencies

```
Task 0 (done, B)
Task 1 (independent)
Task 2 → Task 3 → Task 4
Task 3 → Task 18
Task 2 → Task 5 → Task 6 → Task 7 → Task 8 → Task 9 → Task 10 → Task 11
                                     Task 9 → Task 12 → Task 13
                                     Task 10 → Task 14 → Task 15 → Task 16 → Task 17
```

- Tasks 8, 9, 10, 15 change `get_printer_status` and `PrinterStatus`: strictly sequential in that order.
- Tasks 10 and 14 both add a migration: 14 goes after 10 so the Alembic chain is linear (`20261109a1` → `20261109b1`).
- Task 12 needs `print_service_for` (6), `polled`/`stale` (8) and the tape schema (9); it is not held by a mismatch (15).
- Task 14 needs the runtime (6) to inject the identity sink.
- Task 18 needs only the `/api/v1` frontend (3).

## Gate, review and shipping (controller)

1. Full gate in a frozen clone, no parallel load: backend `pytest -m "not slow" --cov=app --cov-fail-under=80`, ruff, mypy, `alembic upgrade head` + `downgrade -1`; frontend typecheck, lint, test:coverage, build, e2e.
2. Whole-branch review with the four lenses.
   - **Taint:** IPP URI/host never in logs or non-admin responses via the runtime; the test page QR and label carry only the public URL and printer name.
   - **Taint (#231):** serial/MAC/UUID only in admin responses; never in SSE data, logs (any level), audit rows, error bodies, `printer_status_cache.parsed` or the test-print label.
   - **Taint (#230):** the feedback URL carries only the fixed fields.
   - **Runtime/temporal:** per-printer locks, shield, shutdown order, in-flight jobs, roll tracker and identity sink vs concurrent probes, mismatch set between submit and dispatch.
3. `security-audit` on the changed surface: admin routes triggering outbound connections, moved webhook and lookup routes, bootstrap allow-list, the new roll, test-print and identity-resolve routes (scope and printer ACL), exposure of identity values.
4. PR with Codex review, then merge.
5. **Release and rollout,** one maintenance window, in this order:
   1. Back up the DB.
   2. Release 1.5.0 (#224–#231) via `workflow_dispatch`; bump the Kept pin. Both migrations (`20261109a1` roll, `20261109b1` `printer_identity`) run on start. On the first probe each printer stores its identity; no mismatch can occur on first contact.
   3. Move the live Pangolin webhook resource (the SSO-bypass resource) from path `/api/webhook/` to `/api/v1/webhook/`; check that `POST /api/v1/webhook/grocy` without SSO reaches the hub (401/422 from the hub, not the SSO page).
   4. Change the webhook targets in Grocy and Spoolman to `/api/v1/webhook/grocy` and `/api/v1/webhook/spoolman`, if configured.
   5. Hangar companion PR (`internal/hub/client.go`: `/api/render/preview`, `/api/print/{slug}/batch`, `/api/printers?slug=`, `/api/printers`, `/api/printers/{uuid}/status`, `/api/batches/{id}` → `/api/v1/…`), released right after.
   6. On each printer page: answer the one-time roll colour prompt (or skip), PT and QL alike.
   7. As admin, check each printer page shows a serial (PT, QL) or IPP UUID (HP); a printer without one keeps working without swap detection.
6. **Release notes** cover #224–#231 and list: the path map and the two removed routes; that installed web clients keep calling the old paths until the service-worker update prompt is accepted (`registerType: "prompt"`), so they show errors until then; the new `stale`/`polled`/roll/test-print fields and endpoints; that tape colour is asked once per roll change on PT and QL (the printers do not report it over the network); hardware identity, the swap hold for sheet and calibration jobs and the resolve action; the sheet-type feedback links.

---

## Task 19: Searchable sheet type picker (#237) — added by controller ruling 2026-11-09

**Spec:** https://github.com/strausmann/Label-Printer-Hub/issues/237 (read it with `gh issue view 237 --repo strausmann/Label-Printer-Hub`).

**Files:**
- Create: `frontend/src/features/sheets/SheetTypeCombobox.tsx` (+ `SheetTypeCombobox.test.tsx`), unless the project already has a combobox primitive (search `frontend/src` first; reuse it if present)
- Modify: every sheet-type `SelectField` use: `features/calibration/CalibrationPage.tsx`, `features/sheets/AddSheetDialog.tsx`, `features/sheets/print/SheetSection.tsx`, and any further sheet-type select found by grep (`SheetsPage.tsx`, archive filters) — list them in the report
- e2e: extend `frontend/e2e/calibration.spec.ts`
- i18n: de + en catalogs

**Interfaces:**
- Produces: `SheetTypeCombobox({ label, types, value, onChange, disabled? })`. `types` is the same list the pickers pass today. The label format is unchanged. Filtering lives in a pure `matchSheetType(type, query): boolean`, exported for tests.

**Decisions:**
- **Match** on key, vendor, product codes, description and label size. Matching is case-insensitive and accent-insensitive (NFD + strip). The size accepts `101,6 × 38,1`, `101.6x38.1` and `101,6x38,1`.
- **ARIA:** the WAI-ARIA 1.2 combobox with listbox pattern. Arrow keys move the active option; Enter selects; Escape closes and restores the previous value; Home/End jump to the first and last option.
- **Touch:** the input font-size is at least 16 px (no iOS zoom), options are at least 44 px high, and the list scrolls inside its popover.
- **Dependencies:** no new runtime dependency.
- **Archived types:** the existing availability rules stay as each picker has them today. The combobox only displays the options it is given.

- [ ] Step 1: failing tests:
  - `matchSheetType` matches by key, vendor, product code and the three size spellings, and matches no unrelated query;
  - `keyboard selects a type`: type "4736", ArrowDown, Enter, `onChange` called with the L4736REV id;
  - `escape restores previous value`.
- [ ] Step 2: run them red.
- [ ] Step 3: implement, and replace the selects.
- [ ] Step 4: green. Then e2e: on the calibration page, type `4736`, only matching options show, Enter, and the preview legend updates. Then `pnpm typecheck`, `lint`, `test:coverage`, `build`.
- [ ] Step 5: design skills (`taste-skill:design-taste-frontend`, `emil-design-eng`, `mobile-native`, `break-ui`). Take screenshots of light and dark at 1280 px and 390 px into the workspace `shots/task-19/`.
- [ ] Step 6: commit `fix(ui): searchable sheet type picker (#237)`.

### Also in Task 19: #238 — calibration page keeps the chosen sheet type across tray/printer changes
Cause: `CalibrationPage.tsx` renders the per-tray section with `key={`${printer.id}/${tray}`}` (~l.122) and holds the type in local state (`typeChoice`, ~l.155), so a tray change remounts it and resets the type. Decision: keep the type in the URL search as `type=<key>` next to `printer`/`tray`; `chooseTray`/`choosePrinter` preserve it; unknown/archived key → current default fallback. Tests (red first): `type survives a tray change`, `type survives a printer change`, `type survives a reload` (e2e). Separate commit: `fix(ui): keep the chosen sheet type when the calibration tray changes (#238)`.

### Also in Task 19: #239 — calibration print result: no button shift, live job status
Spec: `gh issue view 239`. Decisions: result line rendered below the button row (outside the `flex flex-wrap` button container, ~l.191 and ~l.252), height reserved / aria-live polite; status follows the submitted job via the existing SSE job events and hooks (`useJobStateBadge`, `usePageJobStatus`; reuse, no polling); done → "printed — measure the crossings" hint; failed → localised error + Retry where the job's retry rule allows. Tests (red first): `result does not sit in the button row`, `status follows job events queued→printing→done`, `failed shows error and retry`; e2e: bounding box of the PDF button unchanged after submit, line reaches done without reload. Separate commit: `fix(ui): show the live job status below the calibration print buttons (#239)`.

### Also in Task 19 (built first, #239 uses it): #245 — live print status notification for every print action
Spec: `gh issue view 245`. One shared notification stack in the app shell fed by the existing SSE job events (no polling); every print action (item print, sheet print, cart, calibration/check page, test print from Task 13) registers its job ids; states queued → printing → done (auto-dismiss) / failed (stays, error, retry where allowed); batches show progress; survives navigation; resync after SSE reconnect; mobile: bottom stack above the tab bar, swipe to dismiss; aria-live polite / assertive for failures; reduced motion. Library: if Sonner (MIT) is used, licence check + `ask-sonner` skill; otherwise small in-house stack — decide and report. #239's calibration status line reads the same state. Commit: `feat(ui): live print status notification for every print action (#245)`.
