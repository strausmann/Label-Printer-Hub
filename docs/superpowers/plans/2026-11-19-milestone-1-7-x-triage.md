<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Milestone 1.7.x — Triage of the Open Issues

**Date:** 2026-11-19, revision 2 (after the plan review of `f4ab0a05` and the maintainer's decisions). **Checked against:** `main` = release 1.7.0, commit `d5961d04` (branch `milestone/1.7.x`).
**Plan:** [`2026-11-19-milestone-1-7-x.md`](2026-11-19-milestone-1-7-x.md) — the task numbers below refer to it.

Each issue, and each finding of a collection issue (#398, #222, #221, #212, #211), gets exactly one outcome:

- **implement** — in the plan, task named.
- **close-done** — already done, with the evidence.
- **operator-check** — only the maintainer can check it on the device; what to check is named.
- **move-1.8.0** — not patch material; reason given. Done by the maintainer on 2026-11-19.

## Patch or feature

1.7.x is a patch milestone: `fix`, `docs`, `ci`, `chore`, `test`, `refactor`, `perf` only. Ruling of 2026-11-19: **a new refusal that prevents a defect — a memory, DoS or security bound — is a `fix`** (the 2 MiB body limit, the model validation on create, the 2500-cell calibration cap, the field bounds). A new setting, a new response field, a new user-facing capability or a data-model change (migration) is a `feat`. The queue cap of #168 is in 1.8.0 because it comes with the `copies` migration (#402).

## Summary

| Outcome | Issues | Findings of collection issues |
|---|---|---|
| implement | 24 | 25 (#398: 7, #222: 4, #221: 6, #212: 4, #211: 4) |
| close-done | 1 (#302, closed) | 2 (#211) |
| operator-check | 2 (#390, #381) | — |
| move-1.8.0 | 2 (#247, #352) | 1 (#212 → #403) |
| collection issues | 5 (#398, #222, #221, #212, #211), triaged per finding | |

Two implemented issues have a feature part that is now its own issue in 1.8.0: #166 → #401, #168 → #402. #256 is implemented and also needs the maintainer's device check before the release (Task 21).

## Single issues

| Issue | Outcome | Evidence on 1.7.0 | Task |
|---|---|---|---|
| #160 sign-in limit behind a proxy | implement (tests only) | Behaviour is done: uvicorn runs with `--proxy-headers --forwarded-allow-ips` (`backend/Dockerfile:271-272`), the limiter keys on `request.client.host` (`api/routes/auth_session.py:138-140`); the comment and the examples were fixed in `9409198`. Missing: the three tests the issue lists. | 6 |
| #164 text length / body size | implement | Tape field caps done (`schemas/print_request.py:52-57`, #258). Open: no ASGI body limit (only per route, `api/bounded_body.py:17`, `settings_api.py:89`, `sheet_types.py:190`); `spool_id`, `product_id`, `type` unbounded (`schemas/webhook.py:41-66`). Limit 2 MiB (maintainer). | 2 |
| #166 one unwireable printer aborts startup | implement (fix part; UI state is #401) | `main.py:399` attaches with `fatal=True`; `printer_runtime.py:473,511` re-raise; `_resolve_model_id_from_config` catches only `SnmpDiscoveryError` (`printer_runtime.py:153`), `find_by_pjl`'s `ModelNotFoundError` escapes (`:163`); no model validation on create (`schemas/printer_admin.py:160`). | 3 |
| #168 large backlog blocks startup | implement (fix part; cap and `copies` count are #402) | `PrintQueue.start` re-renders every queued row before the workers exist (`services/print_queue.py:601-603`, `:902`); `main.py:410` awaits it inside the lifespan. | 4 |
| #189 cancel windows | implement | `repositories/jobs.py:297-310` `mark_cancelled` reads, checks, updates by id, reached from `JobStore.mark_cancelled` (`job_store_sqlite.py:115-134`) after `queue.cancel` and from both clear paths; both clear paths await `list_active` before `has_job` (`api/routes/printers.py:~695-718`, `:760-770`). The worker write is conditional already (`c9aac1b`). | 7 |
| #206 `captured_at` on a never-answered printer | implement | New-row branch stamps `captured_at=now` (`services/producers/ipp_status_producer.py:325`); the existing-row branch stamps it too when it is null (`:315`). With `captured_at=None` the status route says "No probe yet" (`api/routes/printers.py:423-432`), so the fix also reports such a row as offline. | 12 |
| #207 QL driver as entry point | implement | `pyproject.toml:77-78` registers only `pt-series`; fallback in `api/routes/capabilities.py:112-122`. | 3 |
| #208 one page-printer discriminator | implement | `backend == "ipp"` and `backend == IPP_BACKEND` in 20+ places (`capabilities.py:251`, `batch.py:133`, `printer_runtime.py:179,444`, `admin_printers_api.py:200`, `printer_admin_service.py:365,368,621`, `sheets/print_service.py:1094,1736,…`); the status route decides by the cache row's `kind` (`printers.py:459,464`). Model validation moved to #166. | 12 |
| #213 WAL for worker-cancelling tests | implement | `tests/conftest.py:83-103` uses the default journal. The integration fixtures already attach `_apply_pragmas` (`tests/integration/conftest.py:65,140`); WAL otherwise only in two unit modules. | 19 |
| #215 re-check the ID cell after `reserve` | implement | `check_id_cell_fits` runs only on the dry plan (`sheets/print_service.py:1335`); `reserve()` results at `:1773`, `:1867` are not re-checked. | 11 |
| #223 camera stays on after a reader failure | implement | `scan/CameraScanner.tsx:168,196` set `reader-failed`; the camera effect does not rerun, tracks stay live. | 13 |
| #234 tape connection reaches non-admin keys | implement (patch with upgrade note, maintainer) | `api/routes/printers.py:90-91` returns `snmp_view(connection)` (host, port, `snmp`) to every caller for a tape printer. The tape status producer stores `str(exc)` as `last_error` (`services/producers/status_probe_producer.py:235`), which names the host for an SNMP or TCP error, and the status route hands it to every key (`printers.py:502`). The IPP probe guard moved to #353 (1.10.0). | 1 |
| #247 "Open in Snipe-IT" uses the internal URL | **move-1.8.0** (done) | The fix is a new per-integration setting `web_url` — a `feat`. | — |
| #249 cell numbers look like printed content | implement | Numbers share `fill-ink-2` with content (`sheets/SheetGrid.tsx:161-172`); no legend. | 15 |
| #250 "That is not a sheet code" on an item QR | implement | `sheets/print/SheetPicker.tsx:85-90` closes the scanner on the first hit; `:42` answers "That is not a sheet code." | 14 |
| #253 quantity not visible for sheet prints | implement | The only quantity is "Copies" in the Print panel (`lookup/ItemView.tsx:129,209-217`). The cart already has a copies field per line; it is not changed. A field for a quantity the print already uses is a fix, not a capability. | 16 |
| #256 brother-ql → brother-ql-next | implement + device check | `pyproject.toml:38` `brother-ql>=0.9.4`; shim `printer_backends/_pillow_compat.py`. Package facts: plan Task 5. | 5, 21 |
| #274 empty vs low material | implement (remaining scope) | Done on 1.7.0: marker `empty` flag, swatch word, notification text. Open: material card counts low and empty together (`overview/OverviewPage.tsx:115`, `printers/PageStatus.tsx:20-22` `runningOut`); the card says plain "Ready" (`printers/model.ts:122`). | 18 |
| #275 readable sheet type names | implement | Archive card heading is the key (`archive/ArchivePage.tsx:85`); `typeLabel` has no description (`sheets/typeLabel.ts:7-11`). | 17 |
| #297 ruff on `scripts/` | implement | CI runs ruff only in `backend/` (`.github/workflows/ci.yml:74,79`); the scripts job installs no ruff (`:190-206`). | 20 |
| #299 tests that fail under load | implement | Cases in the issue comments (Vitest, `version-reload.spec.ts`, one backend test); Vitest has no explicit pool or worker setting (`frontend/vite.config.ts:99-109`). | 19 |
| #302 Dependabot auto-merge under the licence ruleset | **close-done** (closed) | PR #360 (Dependabot, `website-minor-and-patch` group) was merged by `github-actions` through the auto-merge workflow on 2026-11-15, after the ruleset (2026-11-05), with no manual step. | — |
| #315 notice on a licence change between allowed licences | implement | No snapshot exists; gates only check the allow list (`licence-policy.yml`). | 20 |
| #352 README roadmap from the milestones | **move-1.8.0** (done) | Open design questions (progress column, mockup); moved by the maintainer. | — |
| #355 e2e flake: "New sheet" never appears | implement | `e2e/fixtures.ts:13-16` `signInWith` clicks and returns without waiting for the signed-in state. | 19 |
| #358 calibration PDF has no cap | implement | `api/routes/calibration.py:237-256` renders with `asyncio.to_thread`, outside the render slots; grids up to 400 × 400 (`sheets/exchange.py:72-73`). Cap 2500 cells (maintainer). | 10 |
| #364 e2e ports fixed | implement | `frontend/e2e/env.ts:7-16,36-40` hard-codes 8765, 8766, 8795. | 19 |
| #381 12 mm DK on the QL with the P-touch geometry | **operator-check** | Code maps 12 mm (`printer_backends/brother_ql_backend.py:64-71`); only a print shows whether size, position, cut and QR are right. | 21 |
| #390 29 mm roll refused as "wrong roll type" | **operator-check** | Cause found in the issue (the roll is a die-cut 29 × 90 mm sample, DK-11201). The QL reports `29mm x 90mm` over SNMP, and the pre-send check of #389 is on 1.7.0. | 21 |

## Collection issues, per finding

### #398 Print confirmation hardening (1.7.0 audits) — all implement, Task 8

| # | Finding | Evidence | Outcome |
|---|---|---|---|
| 1 | IPP answer decoded on the event loop | `printer_backends/ipp/client.py:409` `decode(raw)` synchronous; cap 1 MiB (`:88`) | implement |
| 2 | Failed record write never retried | `printer_backends/tape_confirmation.py:639-657` sets `self.record` first, logs a failed sink | implement |
| 3 | Failed test print leaves "counter off" stored | `reset_counter_gate` (`tape_confirmation.py:490-496`) changes memory only | implement |
| 4 | Stale "counter does not answer" after a restart | `services/printer_runtime.py:720` loads the stored `counter_off`; the live gate starts on | implement |
| 5 | QL length over-estimated | `label_length_mm` takes the long side (`tape_confirmation.py:146-153`), measured on the fitted image (`brother_ql_backend.py:247-250`); an image left wider than the printable width (`_fit_to_printable_width`, docstring `:102-103`) is scaled down later by `convert`, so its length is its height scaled by `printable / width` | implement |
| 6 | Address check and write not atomic | `printer_runtime.py:735-745` reads, compares, then commits without a write lock | implement |
| 7 | `STORE_TIMEOUT_S` docstring overstates; timeouts conflated | `tape_confirmation.py:96-100`, `:643-650` | implement |

### #222 Test hygiene (Plan 4 reviews) — all implement, Tasks 15 and 19

| # | Finding | Evidence | Outcome |
|---|---|---|---|
| 1 | e2e cleanup ignores the disable status | `frontend/e2e/settings.spec.ts:302-305`, `:362` | implement (19) |
| 2 | Lenient focus-ring check | `frontend/e2e/keyboard.spec.ts:145` | implement (19) |
| 3 | Keyboard activation tested on Calibrate only | `frontend/e2e/calibration.spec.ts:352` is the only keyboard-activation case | implement (19) |
| 4 | `SheetGrid` trailing space; new and reserved cells differ only by stroke and marker | `sheets/SheetGrid.tsx:346` | implement (15) |

### #221 Hardening notes (audit run 15) — all implement, Tasks 6 and 13

| # | Finding | Evidence | Outcome |
|---|---|---|---|
| 1 | Route ids not `encodeURIComponent`-ed | `jobs/api.ts:27,51,67,77,86,98`, `printers/api.ts:39,46,51,66,77,85,96,115,125,140,156` | implement (13) |
| 2 | `baseUrlOf` has no scheme check | `integrations/baseUrl.ts:14-22` | implement (13) |
| 3 | `httpUrl` returns the raw string | `archive/search.ts:56-64` | implement (13) |
| 4 | No `Cache-Control: no-store` on authenticated API responses | only SSE/docs/SPA set it (`events_v1.py:535`, `web/spa.py:76`); `/readiness` neither | implement (6) |
| 5 | e2e-control test checks only `COPY` lines | `tests/unit/test_e2e_control_not_in_production.py:40-75` (no `ADD`, no glob sources) | implement (6) |
| 6 | Cart loses memory-only lines after a failed `setItem` | `lookup/cart.ts:62-75` | implement (13) |

### #212 Sheet-state follow-ups (Plan 3 review) — Task 11

| # | Finding | Evidence | Outcome |
|---|---|---|---|
| 1 | Discarded sheets with unconfirmed cells pin job rows | `repositories/jobs.py:467-472` keeps every job with an `unconfirmed` cell; resolving on a discarded sheet is refused (`sheets/errors.py:132-134`) | implement |
| 2 | No signal while the ID or feed mark waits | a new response flag next to `id_not_printed` (`schemas/sheet_print.py:204,274`) | **move-1.8.0** → #403 |
| 3 | Spec wording 10.2 / OC-39 | `docs/superpowers/specs/2026-11-05-sheet-archive-design.md` | implement |
| 4 | Batch lists jobs that never ran (P7-1) | `sheets/print_service.py:1533-1548` `_settle_batch` only logs a failed write | implement |
| 5 | Printer lookup duplicated (P8-2) | `api/routes/sheet_print.py:130-135`, `:226-231`, `api/routes/sheets.py:200-211` (`_usable_printer`) | implement |

### #211 Sheet print hardening (Plan 3 audits) — Tasks 2 and 9

| # | Finding | Evidence | Outcome |
|---|---|---|---|
| 1 | Preview headroom | `MAX_PREVIEW_PAGES = MAX_SHEETS_PER_RUN` (`sheets/print_service.py:218`), #277 | **close-done** |
| 2 | Per-key preview concurrency cap | `OWNER_LIMIT` in `services/render_slots.py`, commit `033eabd` | **close-done** |
| 3 | Total deadline on integration lookups | per-call timeout only (`integrations/live_config.py:56,95`); three entry points (`services/lookup_service.py:26-95`) | implement (9) |
| 4 | Response size cap on integration lookups | `response.json()` on the whole body (`integrations/*/plugin.py`) | implement (9) |
| 5 | Pin Pillow's text layout | `ImageFont.truetype` without `layout_engine` in five call sites (`services/layout_engine.py:188`, `ql_layout.py`, `sheets/cell_render.py`, `sheets/sheet_page.py`); the swatch already pins `BASIC` (`services/spool_swatch/font.py:38`) | implement (9) |
| 6 | Tape path parity | `RawLabelData` has the caps (`schemas/print_request.py:57-84`, #258), but the tape lookup request has none (`PrintLookupRequest`, `:23-28`; the sheet path bounds the identifier to 120, `schemas/sheet_print.py:105-106`) | implement (2) |

## Corrections in revision 2

- #234: the `last_error` flow was missing (plan review B1).
- #398 finding 5: the measurement is already on the fitted image; the defect is the long-side rule for an image left wider than the printable width (W4).
- #213: the integration fixtures were wrongly listed as default journal (W10).
- #211 finding 5: five call sites, the swatch is pinned already (W5); finding 6: not done for the lookup request (W12).
- #189: the cancel path runs through `queue.cancel` and `JobStore`, and there are two clear paths (W3).
- #247, #352 and the feature parts of #166, #168 and #212 are in 1.8.0 (#401, #402, #403); #302 is closed.
