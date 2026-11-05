# Sheet archive, Plan 4 of 4: web UI for sheets, archive, page printers and calibration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** People manage sheet types and sheets, add and watch page printers, calibrate them and print onto sheets from the item view and the cart — in English and German, at phone width, keyboard only, never relying on colour alone — and the `sheets` and `calibration` feature flags turn on.

**Architecture:** First the browser-test hub learns a page printer (a fake IPP printer on loopback with a control path that only exists in the test server), seeded types and sheets. Then feature folders under `frontend/src/features/` (`sheets`, `archive`, `calibration`) with TanStack Query hooks over the generated API types, one shared accessible SVG `SheetGrid` used by every screen that shows a sheet, live updates from the `sheet.updated` event, a `sheet` scan resolver, the page-printer branch of the existing print dialog, and page-job details in the job views. The existing design system, tokens and shell are reused; no new token set.

**Tech Stack:** React 19, TypeScript 6, TanStack Router/Query, react-aria-components, Tailwind 4 with the existing tokens, Lingui 6 (en, de), Vitest + Testing Library + jsdom, Playwright against `backend/tests/e2e_app.py`.

**Spec:** `docs/superpowers/specs/2026-11-05-sheet-archive-design.md` sections 17, 10.3, 11.5, 16, 19 (23), 21, and the mockups linked there (screens 1–4). Builds on `2026-11-03-web-ui-redesign-design.md` (slots, flags, scan resolver, design system).

**Plan series:** 1 → 2 → 3 → **4 (this)**. Needs Plans 1–3 merged (all API routes exist and `schema.gen.ts` is current) and #184.

## Global Constraints

- Frontend gates: `pnpm typecheck`, `pnpm lint`, `pnpm test:coverage` (thresholds lines/functions/branches/statements **70**), `pnpm build` (Lingui compile `--strict`: every message translated), `src/build.test.ts` (no external font URLs), `pnpm e2e`. Backend gates of Plans 1–3 stay green.
- No new npm dependency. No external fetch at runtime, no CDN; strict CSP of the foundation unchanged (no inline styles that CSP forbids, no `eval`).
- All copy through Lingui `t` / `<Trans>`; English source, German translation in `src/i18n/locales/de/messages.po` with real umlauts; `pnpm i18n:extract` after each task; `src/i18n/catalog.test.ts` green.
- **State and action get separate message IDs** (lesson from #182, `docs/learnings/code-review-patterns.md`): a button "Printed" / "Not printed" (resolve action) and the cell state "printed", "Discard" (action) and "Discarded" (state), "used up" — give each its own explicit `id` (or `context`) so German can differ.
- Design system tokens only (`src/design/tokens.css`); dark and light themes.
- Cell states are never colour alone (spec 17.6): used = hatched + "used", new = filled accent + bold number, reserved = clock glyph, unconfirmed = question glyph + outline, free = dashed outline. The grid is an ARIA grid; each cell's label reads like "Cell 5, used, Grocy · flour 1 kg".
- **Tap targets at phone width (spec 17.6, decided here):** in `view` mode the grid fits the width at the sheet's true aspect ratio — L4731REV's 7 columns at 360 px give ~44 px wide cells, rows only ~17 px tall; the page scrolls vertically, never horizontally. Tapping cells (`select`/`skip` modes) at widths below 640 px opens the grid zoomed so that every cell is at least 44 × 44 px, inside its own scroll container (pan both ways); the page itself still has no horizontal scroll.
- Toner and markers: swatch as material plus name and percentage words — never colour alone.
- Writes the user's scope cannot do are hidden or shown read-only (types and calibration need `admin`; sheets and prints need `print`).
- Whether a printer is a page printer is decided from `PrinterRead.backend === "ipp"` (the printer list carries `backend`; `kind` lives only in `PrinterStatus` and confirms it).
- Per-browser memory uses the existing `lph.` key scheme (`lph.printer`, `lph.cart`) and is treated on sign-out the same way `lph.printer` is (`src/app/session.ts`).
- Design skills, loaded with the `Skill` tool before building each UI task: `taste-skill:design-taste-frontend` and `emil-design-eng` (building screens), `mobile-native` (phone layout), `break-ui` with the edge data set below (reviewing), `review-animations` only if motion is added, `impeccable:impeccable` for the final acceptance (Task 12). If a skill is not available in the session, say so in the task report; do not build without it silently.
- **Edge data set** (seeded by Task 1, used by `break-ui` and the screenshot steps): a 189-cell L4731REV sheet with 120 used, purposes of 120 characters, a sheet with 0 free, a discarded sheet, a type with unknown corner radius, a stopped page printer with `toner-empty` and a marker at "some remaining", a printer with no trays reported (`auto` only).
- **Screenshot check per UI task:** a Playwright test in that task's spec file renders the screen in German (UI language de) at 360 × 780 and in English at 1280 × 800, saves screenshots with `testInfo.outputPath(...)` as artifacts, and asserts only structure (headings, roles, no horizontal overflow: `document.documentElement.scrollWidth <= innerWidth`). Pixel comparison is not a gate.
- Commits: scopes `ui`, `web`, `api` (flag flip), `events`; explicit `git add`; no AI attribution.

## Review Focus

1. **Another client changes the sheet while the print dialog shows a preview.** A `sheet.updated` event for the picked sheet re-fetches the preview; a print answered with `409 plan_changed` re-renders the new plan and asks again instead of failing. Owner: Task 9 (`plan_changed re-renders and keeps the dialog open`, `live event refreshes the preview`).
2. **Scanning a code that is not a usable sheet** — discarded, another type, full, unknown, a lowercase code, the short form `sheet:L4736-02`. The picker selects only a matching, active sheet with room and otherwise says why. Owner: Task 2 (resolver tests) and Task 9 (`scan explains why a sheet cannot be used`).
3. **Very large and very small grids at phone width**: 189 cells with long purposes and 0 free; a 1 × 7 lever-arch type; a round type. No horizontal page scroll, every cell reachable by keyboard and labelled, every tappable cell ≥ 44 × 44 px in the zoomed tap view. Owner: Task 3 (`grid keyboard navigation and labels`, `round cells`, `tap view cells are 44 px`).
4. **Archive import of a file that is too large, not JSON, or conflicts.** The UI shows the server's case (`type_exists`, `prefix_taken`, `invalid_import`, `import_too_large`) and offers `new_version` / `as_new_key` only where it applies; nothing is half-saved. Owner: Task 4 (`import conflict offers the two modes`, `import errors are shown, not thrown`).
5. **A page printer that is stopped, offline or reports odd values** (no markers, `some remaining`, unknown reason keyword) in card, detail, overview, job views and print dialog. The print button reads "Add to print queue", the unknown reason is shown as its keyword, nothing crashes. Owner: Task 8 (`unknown reason keyword shown verbatim`, `some remaining marker`), Task 9 (`stopped printer label`), Task 10 (`stopped at the printer`).

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/tests/e2e_app.py` | page printer on a `FakeIppPrinter`, seeded types and sheets, test-only control routes |
| `backend/tests/unit/test_e2e_control_not_in_production.py` | guard: no control route in the real app, tests never copied into the image |
| `frontend/e2e/fake-camera.ts`, `frontend/playwright.config.ts` | a `sheet:` code video and its camera project |
| `frontend/src/features/sheets/api.ts` | hooks for `/api/sheets…`, `/api/sheet-cells`, preview/print, margin-check |
| `frontend/src/features/archive/api.ts` | hooks for `/api/sheet-types…`, export/import |
| `frontend/src/features/calibration/api.ts` | hooks for calibration, fit, page, capabilities |
| `frontend/src/features/sheets/resolver.ts` | `sheet` scan resolver |
| `frontend/src/api/events.ts` | `sheet.updated` in `EVENT_TYPES` and its invalidation (modify) |
| `frontend/src/features/sheets/SheetGrid.tsx`, `GeometryDiagram.tsx`, `cellState.ts` | the accessible SVG grid and the dimensions diagram (shared) |
| `frontend/src/features/archive/ArchivePage.tsx`, `TypeDetail.tsx`, `TypeForm.tsx`, `ImportDialog.tsx` | `/sheets/archive` |
| `frontend/src/features/sheets/SheetsPage.tsx`, `AddSheetDialog.tsx`, `SheetDetail.tsx` | `/sheets`, `/sheets/$code`, `/sheet/$code` |
| `frontend/src/features/settings/PrinterForm.tsx`, `IppPrinterFields.tsx` | IPP printer form |
| `frontend/src/features/printers/MarkerSwatch.tsx`, `PageStatus.tsx`, `reasons.ts` | toner, reasons and page-printer status |
| `frontend/src/features/sheets/print/SheetSection.tsx`, `SheetPicker.tsx`, `SheetPreview.tsx`, `CapacityAlert.tsx`, `lastType.ts` | page-printer branch of the print dialog |
| `frontend/src/features/jobs/PageJobInfo.tsx` | page-job sub-state, sheet, cells in job views |
| `frontend/src/features/calibration/CalibrationPage.tsx`, `ReadingsHelper.tsx`, `CalibrationSchematic.tsx` | `/calibration` |
| `frontend/src/app/router.tsx`, `src/pages/placeholders.tsx` | real pages replace the placeholders |
| `backend/app/api/routes/info.py` | flags on |
| `frontend/e2e/sheets.spec.ts`, `archive.spec.ts`, `calibration.spec.ts`, `print-sheet.spec.ts` | browser tests |

---

### Task 1: Browser-test hub with a page printer and a test-only control path

**Files:**
- Modify: `backend/tests/e2e_app.py`, `frontend/e2e/fixtures.ts` (control helper), `frontend/e2e/fake-camera.ts`, `frontend/playwright.config.ts`
- Create: `backend/tests/unit/test_e2e_control_not_in_production.py`, `frontend/e2e/page-printer.spec.ts` (smoke)

**Interfaces:**
- Consumes: Plan 2 `FakeIppPrinter`, `serve_on_loopback`, `app.state.ipp_transport_factory` is **not** used here (a real loopback socket, like production); Plan 1–3 services for seeding.
- Produces:
  - A third printer in `E2E_PRINTERS`: name `"Office page printer"`, slug `office-page`, backend `ipp`, trays `main-tray` (default, load hint "written side down, top edge first") and `auto`. The fake is started inside the app **lifespan** (`e2e_app` builds the app on import, so starting it at import time would bind a port in every importer), on `127.0.0.1:<free port>`; the printer row is created with that URI after the fake is up.
  - Seed data through the services (no raw SQL): one L4736REV sheet with cells 1–17 used (purposes like "Grocy · item n"), the 189-cell L4731REV edge sheet with 120 used and 120-character purposes, one full sheet, one discarded sheet, a custom type with unknown corner radius; the Grocy fake gains 9 items for the print test.
  - Test-only control routes, mounted by `e2e_app.py` **only**: `GET /__e2e/page-printer` (the fake's `ipp://` URI and current state), `POST /__e2e/page-printer/state` (body `{printer_state?, reasons?, markers?, accepting_jobs?, job_script?}`) and `POST /__e2e/page-printer/reset`. They exist so Playwright can switch the fake (e.g. to `toner-empty`). They carry no auth because the server only listens on loopback in tests; their path is outside `/api/`.
  - `frontend/e2e/fixtures.ts`: `setPagePrinter(page, state)` helper calling the control route.
  - A fake-camera video showing `sheet:L4736-01`, generated like the existing QR video, and a Playwright project `scan-sheet` (`testMatch: /scan\.spec\.ts/`, `grep: /@sheet/`).
- [ ] **Step 1: Write the failing tests**
  - `test_e2e_control_route_absent_in_production_app` — `app.main.create_app()` mounts no route whose path starts with `/__e2e`.
  - `test_tests_never_copied_into_image` — `backend/Dockerfile` has no `COPY` of `backend/tests` or `tests/` (the image copies `backend/app/` only).
  - `page-printer.spec.ts` smoke: the printers page lists "Office page printer"; `setPagePrinter({reasons: ["toner-empty-error"], printer_state: 5})` → its card shows a stopped state after the next status event (state word assertions come later in Task 8; here only that the status changed).
- [ ] **Step 2: Run, expect FAIL** — `cd backend && pytest tests/unit/test_e2e_control_not_in_production.py -v`; `cd frontend && pnpm e2e -- page-printer.spec.ts`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS** — plus the existing `pnpm e2e` suites unchanged (two tape printers still present).
- [ ] **Step 5: Commit** — `git add backend/tests/e2e_app.py backend/tests/unit/test_e2e_control_not_in_production.py frontend/e2e/fixtures.ts frontend/e2e/fake-camera.ts frontend/playwright.config.ts frontend/e2e/page-printer.spec.ts && git commit -m "test(web): browser-test hub with a fake page printer and seeded sheets"`

---

### Task 2: Data layer, live updates, scan resolver, routes

**Files:**
- Create: `frontend/src/features/sheets/api.ts`, `resolver.ts`, `frontend/src/features/archive/api.ts`, `frontend/src/features/calibration/api.ts`, tests alongside
- Modify: `frontend/src/api/events.ts`, `frontend/src/app/router.tsx`, `frontend/src/pages/placeholders.tsx`, `frontend/src/features/scan/resolvers.ts`

**Interfaces:**
- Consumes: `apiFetch`, `components["schemas"]` from `schema.gen.ts` (`SheetRead`, `SheetSummary`, `SheetTypeDetail`, `SheetPreview`, `SheetPrintRequest`, `SheetPrintResponse`, `CalibrationRead`, `FitResponse`, `Capabilities`), `registerScanResolver`.
- Produces: query keys `sheetsKey(filters)`, `sheetKey(code)`, `typesKey(filters)`, `typeKey(key)`, `calibrationKey(printerId)`, `capabilitiesKey(printerId)`; hooks `useSheets`, `useSheet`, `useNextCode(typeKey)`, `useCreateSheet`, `useDiscardSheet`, `useMarkCells`, `useUnmarkCells`, `useResolveCells`, `useCellHits(source, ref)`, `useMarginCheck`, `useSheetPreview(printerId, request)`, `usePrintSheets(printerId)`, `useSheetTypes`, `useSheetType`, `useCreateType`, `usePatchType`, `useAddVersion`, `useArchiveType`, `useDeleteType`, `exportTypeUrl(key, version?)`, `useImportType`, `useCalibration`, `useSaveCalibration`, `useResetCalibration`, `useFit`, `usePrintCalibrationPage`, `calibrationPdfUrl(printerId, tray, {type, version?, corrected})` → `/api/printers/{id}/calibration/{tray}/page/pdf?…`, `useCapabilities`. `parseSheetCode(text: string): string | null` — accepts `{any origin}/sheet/{CODE}` (sub-path and trailing slash allowed) and `sheet:{CODE}`, code pattern `^[A-Z][A-Z0-9]{1,9}-[0-9]{2,}$` (uppercase only). Resolver id `sheet` → route `/sheet/{code}`. `sheet.updated` is added to `EVENT_TYPES` (the client filters by event type, not by channel) and its handler invalidates `sheetsKey`, `sheetKey(code)` and active previews that name that code. Routes `/sheets/$code` and `/sheet/$code` are registered now with a placeholder page (`SheetDetailPlaceholder` in `placeholders.tsx`) that Task 6 replaces.
- [ ] **Step 1: Write the failing tests** — `parseSheetCode` table (URL with path, with sub-path, with trailing slash, short form, lowercase → null, `L4736-2` → null, other path → null); `resolveScan` over **all** registered resolvers: `https://hub.example.invalid/sheet/L4736-02` and `sheet:L4736-02` → `{resolverId: "sheet", route: "/sheet/L4736-02"}`, and an asset label link still resolves to `label-link`; `sheet.updated` frame → `invalidateQueries` with the three keys; mutation hooks surface `error_code` from the API error body; `calibrationPdfUrl` path ends in `/page/pdf`.
- [ ] **Step 2: Run, expect FAIL** — `cd frontend && pnpm exec vitest run src/features/sheets src/api`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS** — plus `pnpm typecheck && pnpm lint`.
- [ ] **Step 5: Commit** — `git add frontend/src/features/sheets frontend/src/features/archive/api.ts frontend/src/features/calibration/api.ts frontend/src/api/events.ts frontend/src/app/router.tsx frontend/src/pages/placeholders.tsx frontend/src/features/scan/resolvers.ts && git commit -m "feat(ui): data layer, live updates and scan resolver for sheets"`

---

### Task 3: `SheetGrid` and `GeometryDiagram`

**Design skills:** `taste-skill:design-taste-frontend`, `emil-design-eng`, `mobile-native`; review with `break-ui` (edge data set).

**Files:**
- Create: `frontend/src/features/sheets/SheetGrid.tsx`, `GeometryDiagram.tsx`, `cellState.ts`, tests

**Interfaces:**
- Produces:
  - `type GridCellState = "free" | "used" | "reserved" | "unconfirmed" | "new" | "skipped"`; `interface GridCell { cell: number; state: GridCellState; purpose?: string; isId?: boolean; truncated?: boolean; mapped?: boolean; hwMargin?: boolean }`.
  - `<SheetGrid geometry={GeometryMm} cells={GridCell[]} mode="view" | "select" | "skip" onToggle?={(cell) => void} overlayPng?={string} zoom?={1 | 2} label={string} />` — SVG at true aspect ratio (mm units), `round` cells as circles, states per the Global Constraints, `<SheetLegend counts={...} />`, ARIA grid (`role="grid"`, rows, `gridcell` with `aria-label`), arrow-key navigation, Space/Enter toggles in `select`/`skip`, `overlayPng` as an `<image>` scaled to the page; tap view for `select`/`skip` below 640 px as in the Global Constraints.
  - `cellLabel(cell: GridCell, t): string` in `cellState.ts`.
  - `<GeometryDiagram geometry={GeometryMm} />` — read-only diagram labelling label size, pitch, gaps, margins (computed right/bottom), radius ("unknown" when null), asymmetric-margin hint.
- [ ] **Step 1: Write the failing tests** — `grid keyboard navigation and labels` (arrow keys move by row/column; label `"Cell 5, used, Grocy · flour 1 kg"`); every state has a non-colour marker (pattern or glyph element); `round cells` render circles; `select` mode toggles call `onToggle(5)`; `view fits 360` (container 360 px → SVG width ≤ 360 and L4731REV cell width ≥ 44 px); `tap view cells are 44 px` (`select` mode at 360 → every cell's hit rectangle ≥ 44 × 44 px, the scroll container — not the page — overflows); diagram shows "unknown" radius and the asymmetry hint.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** (load the design skills first).
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add frontend/src/features/sheets/SheetGrid.tsx frontend/src/features/sheets/GeometryDiagram.tsx frontend/src/features/sheets/cellState.ts frontend/src/features/sheets/SheetGrid.test.tsx frontend/src/features/sheets/GeometryDiagram.test.tsx frontend/src/i18n/locales && git commit -m "feat(ui): accessible sheet grid and geometry diagram"`

---

### Task 4: `/sheets/archive`

**Design skills:** `taste-skill:design-taste-frontend`, `emil-design-eng`, `mobile-native`; `break-ui`.

**Files:**
- Create: `frontend/src/features/archive/ArchivePage.tsx`, `TypeDetail.tsx`, `TypeForm.tsx`, `ImportDialog.tsx`, tests; `frontend/e2e/archive.spec.ts`
- Modify: `frontend/src/app/router.tsx`, `frontend/src/pages/placeholders.tsx` (remove `SheetArchivePage`)

**Interfaces:**
- Consumes: Task 2 hooks, Task 3 `GeometryDiagram`.
- Produces: list with search, page size, vendor and label-size filters; badges `seed` / `custom` / `imported`, `unverified`, `archived`; detail with diagram, geometry table, versions with change notes and sheet counts, provenance (source name + link, `rel="noopener noreferrer"`), `allow_qr`; admin actions: edit geometry (new version; warns "N sheets keep version n"), edit details, archive/unarchive, export (download link), delete (custom without sheets). Create and import (paste or file ≤ 64 KB, checked client-side too); import shows `created` / `unchanged` / `version_added` / `created_as_new_key`; on `type_exists` offers "Add as new version" and "Import under a new key" (key + prefix fields); on `prefix_taken` asks for a prefix. Non-admin: read-only.
- [ ] **Step 1: Write the failing tests** — filters send the right query; `import conflict offers the two modes` (mocked `409 type_exists` → two choices; new key sends `mode=as_new_key&new_key=…`); `import errors are shown, not thrown` (`invalid_import`, `import_too_large`, non-JSON paste); edit geometry shows the older-version warning; non-admin sees no write buttons. E2E `archive.spec.ts`: export a seed type, import it back → "unchanged"; screenshot check.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS** — vitest for the folder; `pnpm e2e -- archive.spec.ts`.
- [ ] **Step 5: Commit** — `git add frontend/src/features/archive frontend/src/app/router.tsx frontend/src/pages/placeholders.tsx frontend/e2e/archive.spec.ts frontend/src/i18n/locales && git commit -m "feat(ui): sheet type archive with versions, export and import"`

---

### Task 5: `/sheets` list and the Add-a-sheet dialog

**Design skills:** `taste-skill:design-taste-frontend`, `emil-design-eng`, `mobile-native`; `break-ui`.

**Files:**
- Create: `frontend/src/features/sheets/SheetsPage.tsx`, `AddSheetDialog.tsx`, tests; `frontend/e2e/sheets.spec.ts`
- Modify: `frontend/src/app/router.tsx`, `frontend/src/pages/placeholders.tsx` (remove `SheetsPage`)

**Interfaces:**
- Consumes: Tasks 2–3.
- Produces: table (code in mono, type with label size, used n/N with bar plus numbers, last used, state words `used up` / `discarded`), filters hide-used-up (default on), type, code search, discarded behind a filter; Discard with the mockup's confirmation text ("leaves the picker; its number is never given out again; labels already printed stay printed"); "+ New sheet" → dialog: type select (current version), grid in `select` mode for cells already used, `GeometryDiagram`, ID placement radios — margin disabled with the reason from `margin-check` when a printer is chosen, "first free cell" needs printer + tray and the button reads "Add and print ID label"; small-cell hint when `allow_qr=false`; the probable code from `next-code` ("becomes L4736-04"), and the real code from the response if it differs.
- [ ] **Step 1: Write the failing tests** — hide-used-up default; discard confirmation text and API call; dialog sends `used_cells` from the grid; margin radio disabled with reason when `allowed=false`; cell option requires printer and tray and shows the job link after success; code from the response when higher than the hint. E2E: add a sheet with 3 used cells, listed with 45 free; screenshot check.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add frontend/src/features/sheets/SheetsPage.tsx frontend/src/features/sheets/AddSheetDialog.tsx frontend/src/features/sheets/SheetsPage.test.tsx frontend/src/features/sheets/AddSheetDialog.test.tsx frontend/src/app/router.tsx frontend/src/pages/placeholders.tsx frontend/e2e/sheets.spec.ts frontend/src/i18n/locales && git commit -m "feat(ui): sheet list and add-a-sheet dialog"`

---

### Task 6: Sheet detail and the scan route

**Design skills:** `taste-skill:design-taste-frontend`, `emil-design-eng`, `mobile-native`; `break-ui`.

**Files:**
- Create: `frontend/src/features/sheets/SheetDetail.tsx`, test
- Modify: `frontend/src/app/router.tsx` and `frontend/src/pages/placeholders.tsx` (replace `SheetDetailPlaceholder`), `frontend/e2e/sheets.spec.ts`, `frontend/e2e/scan.spec.ts`

**Interfaces:**
- Consumes: Tasks 2–3.
- Produces: `/sheets/$code` and `/sheet/$code` render `SheetDetail`: grid to scale (`view`), purpose on focus/tap, list "Cell n → purpose · source", actions: mark cells used (grid `select` + optional purpose), un-mark (only hand-marked cells offered), resolve unconfirmed ("Printed" / "Not printed", separate message IDs), discard, "Print onto this sheet" — a link to `/cart?sheet=<code>` (the cart reads the parameter from Task 9 on; this task only builds the link). Discarded: "Discarded on <date>, this ID is not used again." Unknown code: not-found state.
- [ ] **Step 1: Write the failing tests** — discarded text; un-mark offers only `marked_by_hand` cells; resolve sends the outcome; the print link is `/cart?sheet=L4736-01`; live `sheet.updated` re-renders a newly reserved cell with the clock glyph (acceptance 11, UI side). E2E: open `/sheet/<code>` directly (scanned URL) and via the scan screen in project `scan-sheet` (`@sheet`, fake camera shows `sheet:L4736-01`) (acceptance 8, UI side); screenshot check.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add frontend/src/features/sheets/SheetDetail.tsx frontend/src/features/sheets/SheetDetail.test.tsx frontend/src/app/router.tsx frontend/src/pages/placeholders.tsx frontend/e2e/sheets.spec.ts frontend/e2e/scan.spec.ts frontend/src/i18n/locales && git commit -m "feat(ui): sheet detail with marking, resolving and scan route"`

---

### Task 7: Page printers in Settings › Printers

**Design skills:** `taste-skill:design-taste-frontend`, `emil-design-eng`, `mobile-native`.

**Files:**
- Create: `frontend/src/features/settings/IppPrinterFields.tsx`, test
- Modify: `frontend/src/features/settings/PrinterForm.tsx`, `frontend/src/features/settings/api.ts`, `frontend/e2e/settings.spec.ts`

**Interfaces:**
- Consumes: admin printer API with `backend: "ipp"`, `POST /api/v1/admin/printers/ipp/probe`.
- Produces: backend choice "Page printer (IPP)"; fields IPP URI, verify TLS (off shows a warning), name, slug, enabled, queue timeout; no `model` field for IPP (filled from the probe); "Read printer" runs the probe and shows the summary (make and model, PDF yes/no, resolutions, media sizes and types, trays, colour modes, margins, state); tray table from `media_sources` plus `auto` (enabled, label, load hint, default; at least one enabled, one default); save errors `ipp_pdf_unsupported`, `ipp_unreachable`, `tray_unknown` as words. No SNMP or cut fields for IPP. After saving a **new** printer: "The printer is ready after the hub restarts." (printers are wired at startup, Plan 2 runtime note).
- [ ] **Step 1: Write the failing tests** — probe summary rendered; save disabled until a probe succeeded on a new URI; TLS-off warning; tray rules enforced client-side; server errors shown; the restart note after create. E2E: add a second page printer against the Task 1 fake (URI from `GET /__e2e/page-printer`), see it listed; screenshot check.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add frontend/src/features/settings frontend/e2e/settings.spec.ts frontend/src/i18n/locales && git commit -m "feat(ui): add and edit IPP page printers in settings"`

---

### Task 8: Page-printer status in cards, detail and overview

**Design skills:** `taste-skill:design-taste-frontend`, `emil-design-eng`; `break-ui`.

**Files:**
- Create: `frontend/src/features/printers/MarkerSwatch.tsx`, `PageStatus.tsx`, `reasons.ts`, tests
- Modify: `frontend/src/features/printers/PrinterCard.tsx`, `PrinterDetail.tsx`, `model.ts`, `frontend/src/features/overview/OverviewPage.tsx`, `frontend/e2e/printers.spec.ts`

**Interfaces:**
- Consumes: `PrinterStatus` new fields, `useCapabilities`, `useCalibration`.
- Produces: `reasonWord(keyword: string, t): string` (translated words for `toner-empty`, `toner-low`, `media-empty`, `media-jam`, `door-open`, `cover-open`, `paused`, `offline`, `marker-supply-empty`, `marker-supply-low`, `media-low`, `unknown-state`, `not_accepting`; any other keyword verbatim); `<MarkerSwatch marker />` (swatch + name + "0 %, low" / "empty" / "some remaining" / "unknown"); card: state word, blocking reason, toner where tape is shown; detail: trays with load hints, calibration summary with a link to `/calibration?printer=<id>&tray=<key>`, "n jobs from other computers ahead"; overview "material running out" counts toner low/empty like tape.
- [ ] **Step 1: Write the failing tests** — `unknown reason keyword shown verbatim`; `some remaining marker`; stopped + `toner-low` warning shows "Stopped" and "black 0 %, low" (spec 11.3 example); overview counts a low toner; tape printer card unchanged (regression). E2E: `setPagePrinter` to `toner-empty` → card shows "toner empty" through the event stream; clear it → the printer resumes by itself (acceptance 16, UI side); screenshot check.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add frontend/src/features/printers frontend/src/features/overview frontend/e2e/printers.spec.ts frontend/src/i18n/locales && git commit -m "feat(ui): page printer state, toner and trays"`

---

### Task 9: Print dialog — the sheet branch

**Design skills:** `taste-skill:design-taste-frontend`, `emil-design-eng`, `mobile-native`; `break-ui`.

**Files:**
- Create: `frontend/src/features/sheets/print/SheetSection.tsx`, `SheetPicker.tsx`, `SheetPreview.tsx`, `CapacityAlert.tsx`, `lastType.ts`, tests; `frontend/e2e/print-sheet.spec.ts`
- Modify: `frontend/src/features/lookup/ItemView.tsx`, `CartPage.tsx`, `PrinterPicker.tsx` (list shows kind and state), `frontend/src/app/router.tsx` (`/cart` gets `validateSearch` for `sheet?: string`)

**Interfaces:**
- Consumes: Tasks 2–3, 8; `usePrinterChoice`; cart items.
- Produces: when the chosen printer is a page printer (`backend === "ipp"`), the tape preview is replaced by `<SheetSection items printer preselectedSheet? />`: printer row (state dot + word, toner per marker, "n jobs from other computers ahead" when `jobs_ahead > 0`); stopped printer alert and the button label "Add to print queue"; tray select (default preselected) and its load hint under the preview ("Put L4736-02 into the manual tray, written side down, top edge first"); sheet type (default `lastType.get(printerId)`, key `lph.sheetType.<printerId>`, try/catch, OC-36); `<SheetPicker>` combobox (search by code; fitting sheets first with free count and "fits 9" / "too small"; "+ New … sheet (becomes …)"; scan button using the camera scanner — selects the scanned sheet if its type matches and it is active with room, else explains: other type, discarded, full, unknown); `/cart?sheet=<code>` preselects that sheet (and its type); fill: first free cells or choose cells (grid `select`), tap to skip; `<CapacityAlert>` on `insufficient_cells` with the three choices (rest onto another sheet of the type, rest onto a new sheet, a sheet with enough room) building the next `placements`; `<SheetPreview>` (whole page and 200 % zoom, legend with counts used / printed now / free, list "Cell 5 → …", reprint hints, "code only on this sheet type" where `mapped`, shortened text marked, hardware-margin warning); `422 preview_too_large` shown as words; footer note "PDF on A4, media type labels, no scaling"; print sends `expected_cells`; on `plan_changed` re-renders the returned plan and keeps the dialog open; after printing links to the job(s).
- [ ] **Step 1: Write the failing tests** — tape printer keeps the tape preview (regression); page printer shows the sheet section; `plan_changed re-renders and keeps the dialog open`; `live event refreshes the preview`; `scan explains why a sheet cannot be used` (four cases); capacity choices produce the right `placements`; `stopped printer label` reads "Add to print queue"; last type remembered per printer; `/cart?sheet=L4736-01` preselects the sheet. E2E `print-sheet.spec.ts`: print 9 Grocy items onto the seeded sheet with 17 used, wait for the job → sheet detail shows 26 used (acceptance 1, through the UI); screenshot check with the 189-cell edge sheet.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add frontend/src/features/sheets/print frontend/src/features/lookup frontend/src/app/router.tsx frontend/e2e/print-sheet.spec.ts frontend/src/i18n/locales && git commit -m "feat(ui): print onto sheets from the item view and the cart"`

---

### Task 10: Page jobs in the job views

**Design skills:** `taste-skill:design-taste-frontend`, `emil-design-eng`; `break-ui`.

**Files:**
- Create: `frontend/src/features/jobs/PageJobInfo.tsx`, test
- Modify: `frontend/src/features/jobs/JobDetail.tsx`, `JobsPage.tsx`, `model.ts`, `frontend/e2e/jobs.spec.ts`

**Interfaces:**
- Consumes: job events with `kind`, `at_printer`, `summary` (Plan 2 Task 7), job `payload`/`result`, `useSheet`.
- Produces: for page jobs: the sub-state while tracked — "waiting at the printer", "printing", "stopped at the printer" with reason words (`reasonWord`) — the sheet code (link to `/sheets/<code>`), the cells of the job, a calibration-page label for `calibration_page` jobs; a failed `interrupted` job lists its unconfirmed cells with a link to resolve them on the sheet (spec 11.5, 16, 21). Tape jobs unchanged.
- [ ] **Step 1: Write the failing tests** — `stopped at the printer` with "toner empty"; `waiting at the printer`; interrupted job shows unconfirmed cells and the resolve link; calibration job label; tape job regression. E2E: a page job with `job_script` `[3, 3, 5, 9]` shows the sub-states in order on the job detail; screenshot check.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add frontend/src/features/jobs frontend/e2e/jobs.spec.ts frontend/src/i18n/locales && git commit -m "feat(ui): page job state, sheet and cells in the job views"`

---

### Task 11: `/calibration`

**Design skills:** `taste-skill:design-taste-frontend`, `emil-design-eng`, `mobile-native`; `break-ui`.

**Files:**
- Create: `frontend/src/features/calibration/CalibrationPage.tsx`, `ReadingsHelper.tsx`, `CalibrationSchematic.tsx`, tests; `frontend/e2e/calibration.spec.ts`
- Modify: `frontend/src/app/router.tsx`, `frontend/src/pages/placeholders.tsx` (remove `CalibrationPage`)

**Interfaces:**
- Consumes: Task 2 calibration hooks, Plan 1 types (S/Z naming).
- Produces: printer (page printers only) and tray choice (search params `printer`, `tray`), current values with "last changed"; Step 1: type choice (types with ≥ 2 columns and ≥ 2 rows), schematic of the calibration page with legend (black only, S/Z numbering, mini scales, rulers, checkerboard hint where no gap), "Print calibration page", "Download PDF" (`calibrationPdfUrl` → `…/page/pdf`); Step 2: magnified gap-crossing example ("Gap crossing S2 · Z6") explaining across/down with signs, direct entry (offset X/Y mm, scale X/Y, rotation °, with the sign meaning in words: "+ = printed too far right"), or the readings helper (crossing + across + down rows; the four outermost crossings suggested; "Fit"; result table with residuals, readings > 0.3 mm flagged "check this reading"; out-of-range values named), "Save for this printer and tray" (admin only); Step 3: "Check print with correction". Server range errors as words.
- [ ] **Step 1: Write the failing tests** — suggested crossings for L4736REV are S1/Z1, S3/Z1, S1/Z11, S3/Z11; fit result table shows residuals and flags; save disabled for non-admin; fewer than 3 readings → "Fit" disabled; `readings_insufficient` shown as words; one-column types not offered; the download link ends in `/page/pdf`. E2E: print a calibration page to the fake (job appears), fit four readings, save, capabilities show the values; screenshot check.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add frontend/src/features/calibration frontend/src/app/router.tsx frontend/src/pages/placeholders.tsx frontend/e2e/calibration.spec.ts frontend/src/i18n/locales && git commit -m "feat(ui): manual calibration with readings fit and calibration page"`

---

### Task 12: Feature flags and final acceptance

**Design skills:** `impeccable:impeccable` (final acceptance across all new screens), `break-ui` with the edge data set.

**Files:**
- Modify: `backend/app/api/routes/info.py` (`"sheets": True`, `"calibration": True`), `backend/tests/integration/api/test_info.py`, `frontend/src/shell/features.test.ts`, `frontend/e2e/shell.spec.ts` (`CHANGELOG.md` is not edited; semantic-release owns it)

**Interfaces:**
- Consumes: everything above.
- Produces: navigation entries for Sheets, Sheet archive and Calibration visible; `GET /api/info` features `sheets` and `calibration` true.
- [ ] **Step 1: Write the failing tests** — `test_info` expects both flags true; `features.test.ts` shows the three entries; `shell.spec.ts` sees them in the sidebar (desktop) and tab bar/menu (phone).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**; run `impeccable:impeccable` over Tasks 3–11's screens with the edge data set and fix what it finds (each fix in its own commit with the owning task's scope).
- [ ] **Step 4: Run, expect PASS** — full gates: backend `pytest -m "not slow" --cov=app --cov-fail-under=80`, `mypy app/`, ruff; frontend `pnpm typecheck && pnpm lint && pnpm test:coverage && pnpm build && pnpm e2e`; acceptance 23 checked: every new page in English and German, at 360 px, keyboard only (Playwright tab-through in each spec), no colour-only state.
- [ ] **Step 5: Commit** — `git add backend/app/api/routes/info.py backend/tests/integration/api/test_info.py frontend/src/shell/features.test.ts frontend/e2e/shell.spec.ts && git commit -m "feat(api): turn on the sheets and calibration features"`

---

## Operator-verified (not task gates)

- The phone layout on a real phone (scan a printed sheet ID with the camera, open the sheet, print onto it).
- Visual judgement of the screens against the mockups after `impeccable:impeccable`.

## Plan review 2026-11-05

Findings of the independent plan review worked in, each checked against the code: P4-B1 (new Task 1: browser-test hub and test-only control path), P4-M1 (44 px tap view), P4-M2 (new Task 10: job views), P4-m1 … P4-m8. None rejected. Tasks renumbered: old 1–10 are now 2–9, 11, 12.
