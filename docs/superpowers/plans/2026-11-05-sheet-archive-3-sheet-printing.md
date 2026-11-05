# Sheet archive, Plan 3 of 4: printing onto sheets

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A client (or the hub's own integrations) previews and prints labels onto physical sheets on an IPP page printer: the hub picks free cells, reserves them atomically, renders the whole page, and records the cells as used only when the printer reports the job completed — unconfirmed when the outcome is unknown.

**Architecture:** A pure **cell renderer** (the hook #178 replaces) and a pure **planner** turn a request into page plans; a **reservation** step plans and inserts `reserved` cells in one write-locked transaction; each page becomes a `sheet_page` page job (Plan 2 queue) whose renderer composes cell images, the margin ID and the calibration correction into one PDF, and whose **outcome handler** moves the job's cells to `used`, `free` or `unconfirmed`. Preview runs the same planner and renderer without writing.

**Tech Stack:** Python 3.12, FastAPI, SQLModel on SQLite, Pillow, qrcode, reportlab (from Plan 2), pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-sheet-archive-design.md` (sections 8, 10.1–10.3, 11.4 retry, 12, 15 sheet print request, 16, 19). Read it with this plan.

**Plan series:** 1 archive & sheets → 2 IPP & calibration → **3 (this)** → 4 UI. Needs Plans 1 and 2 merged, **requires [#184](https://github.com/strausmann/Label-Printer-Hub/issues/184) merged** (cancel, clear and retry routes go through the queue), and a branch rebased onto a `main` that contains `backend/app/integrations/urls.py` (`base_url`, from #180–#182).

## Global Constraints

- Everything in Plan 1's and Plan 2's Global Constraints applies; commitlint scopes here: `api`, `queue`, `integrations`, `events`, `decisions`.
- Cell numbering row-major 1…N; `first_free` = lowest free numbers ascending; `skip` is per request, never stored (OC-38).
- A cell is free iff it has no `sheet_cells` row. Reserved and unconfirmed cells are not free (spec 8).
- Items per request ≤ 500; purpose ≤ 120 characters after `sanitise_text` (Plan 1 Task 6: removes `Cc` and the bidi controls, keeps U+200D so emoji sequences stay whole — a deliberate choice), default purpose = request `purpose`, else label `title`, else `primary_id` (OC-43); `source` = integration name for lookups, request `source` (pattern `^[a-z][a-z0-9_-]{0,31}$`) for raw data, default `api`; `ref` = lookup identifier (≤ 120).
- No copies on sheet jobs (OC-3).
- Render resolution = highest `resolutions_dpi` of the printer's summary, capped at 600; 600 if unknown (OC-26). Preview: 150 dpi, never calibrated (spec 12).
- Content box inset `1.0 mm + 0.3 × corner_radius` per side, unknown radius counts as 2.0 mm (inset 1.6 mm); `round` → inscribed square inset by 1.0 mm (OC-25). Text minimum cap height 1.6 mm, then ellipsis + `truncated` (OC-27). QR module size a whole number of device pixels with a four-module quiet zone inside the box.
- `allow_qr=false` mapping (spec 12.5): `qr_only`, `qr_one_line` → `text_one_line`; `qr_two_lines`, `qr_three_lines`, `qr_with_listing` → `text_two_lines`.
- Margin ID (OC-16): usable height = `margin_top − hw_top − max(0, −offset_y) − 1.0 mm`, `hw_top` = printer's `media-top-margin` minimum, **5.0 mm** if unknown; < 4.0 mm → `422 margin_too_small`; QR next to the text only from 9.0 mm and if the QR fits at a module of ≥ 0.25 mm with its quiet zone. ID-cell label: `qr_two_lines` (`primary_id` = code, `title` = `"<vendor> <first product code> · sheet ID"`, QR = payload); `text_two_lines` on `allow_qr=false` types.
- Sheet ID scan payload (OC-15): `base_url(str(public_url)) + "/sheet/" + code` using `app.integrations.urls.base_url` (keeps a sub-path, drops the trailing slash `AnyHttpUrl` adds). `public_url` is a required setting (`app/config.py`), so the short form `sheet:{code}` is only produced by the payload builder when it is given an empty URL — tested at unit level, unreachable in operation.
- Cells in the printer's hardware margins are flagged (`hw_margin: true`), never refused (OC-44).
- Label `D15` (cells reserved at job creation, used on completion, unconfirmed when unknown) is added to the register in Task 3 and marks the reservation and outcome code.

## Review Focus

1. **Two print requests for the same sheet at the same moment** (both `first_free`, or one explicit `[5,6]` against one `first_free`). Never the same cell twice; the explicit loser gets `409 cells_taken` with `[5,6]`, a `first_free` loser is re-planned once and succeeds on the next free cells. Owner: Task 3 (`test_parallel_first_free_never_overlap`, `test_parallel_explicit_vs_first_free`).
2. **Crash or restart between committing the reservation and persisting the page job.** Reserved cells pointing at a job that does not exist would block cells forever. A startup sweep frees them; reserved cells of a terminal clean job are freed, of a started one become unconfirmed. Owner: Task 5 (`test_sweep_orphan_reservations`).
3. **The type is edited (new version) while a sheet is half used and while a job for it waits in the queue.** The sheet keeps v1 positions and cell count in plan, preview, PDF and outcome; a request explicitly naming a v2-only cell number is `422 cell_out_of_range`. Owner: Task 4 (`test_sheet_page_uses_pinned_version`) and Task 7 (`test_print_after_type_edit_uses_v1`, acceptance 9).
4. **Hostile or odd label data in a cell**: 10 000-character title, control characters and bidi overrides in purpose, emoji, an empty `primary_id` after mapping to `text_one_line`, a QR payload too long for the box. Rendering never raises outside `content_type_data_mismatch` (422 for that item), never draws outside the box, flags `truncated`. Owner: Task 1 (`test_render_edge_data` table) and Task 7 (`test_purpose_sanitised`).
5. **A lookup fails for item 37 of 40, or the printer is a tape printer, or the tray is disabled.** Nothing is reserved, no job is created, the answer names the item index or the reason (`media_kind_mismatch`, `tray_unknown`). Owner: Task 7 (`test_nothing_reserved_on_late_failure`).

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/sheets/cell_render.py` | `CellRenderer` protocol, `RasterCellRenderer`, content box, QR mapping (pure) |
| `backend/app/sheets/planner.py` | placements → page plans, capacity, ID cell, margin-ID rule, hw-margin flags (pure) |
| `backend/app/sheets/reservation.py` | write-locked plan + reserve, new sheets, `expected_cells` |
| `backend/app/sheets/sheet_page.py` | `sheet_page` payload model and PDF renderer (margin ID, ID cell) |
| `backend/app/sheets/outcome.py` | outcome handler for `sheet_page` jobs, startup sweep |
| `backend/app/sheets/print_service.py` | resolve items, preview, print, ID-only job, retry |
| `backend/app/schemas/sheet_print.py` | request/response models |
| `backend/app/api/routes/sheet_print.py` | preview and print routes |
| `backend/app/api/routes/sheets.py`, `backend/app/api/routes/jobs.py` | ID-cell creation, page-job retry (modify) |

---

### Task 1: Cell renderer

**Files:**
- Create: `backend/app/sheets/cell_render.py`
- Test: `backend/tests/unit/sheets/test_cell_render.py`

**Interfaces:**
- Consumes: `ContentType`, `LabelData`, `ContentTypeDataMismatchError` (existing), `LayoutEngine._REQUIRED_FIELDS` (reuse the same required-field table — move it to a module constant `REQUIRED_FIELDS` in `layout_engine.py` and import it; tape behaviour unchanged), `_load_font` font loading (reuse, no copy). **Not** `LayoutEngine._build_qr_image`: it renders at `box_size=10, border=0` and resizes with `NEAREST`, so modules are not whole device pixels and there is no quiet zone; the tape path keeps it unchanged; Plan 1 `Geometry`, `cell_origin`.
- Produces:
  - `@dataclass(frozen) BoxHmm(x: int, y: int, w: int, h: int)`; `def content_box(g: Geometry, n: int) -> BoxHmm` (OC-25).
  - `def map_content_type(ct: ContentType, allow_qr: bool) -> tuple[ContentType, bool]` (mapped flag).
  - `def build_qr(payload: str, edge_px: int) -> Image.Image | None` — `qrcode.QRCode(version=None, error_correction=M, border=4)`, `make(fit=True)`, module count `n`, `box_size = edge_px // (n + 8)`; `box_size < 1` → `None` (does not fit); image rendered at that `box_size` (no resize), mode `"1"`, centred in an `edge_px` square.
  - `@dataclass CellImage(image: Image.Image, truncated: bool)`.
  - `class CellRenderer(Protocol)`: `def render(self, *, box_w_mm: float, box_h_mm: float, dpi: int, content_type: ContentType, data: LabelData) -> CellImage` — image mode `"1"`, size exactly `(round(box_w_mm / 25.4 * dpi), round(box_h_mm / 25.4 * dpi))`.
  - `class RasterCellRenderer` implementing it: QR edge = box height (whole-pixel modules, quiet zone 4 modules inside), text column right of the QR, font sizes as fractions of the box height (fractions chosen by the implementer, spec 22), shrink by 1 px down to the minimum cap height, then ellipsis.
  - `DEFAULT_CELL_RENDERER: CellRenderer = RasterCellRenderer()` — the single place #178 swaps.
- [ ] **Step 1: Write the failing tests**
  - `test_content_box_l4736` — cell 1 → `BoxHmm(985 + 160, 2130 + 160, 4570 - 320, 2120 - 320)` (unknown radius → 1.6 mm inset); L4731REV radius 1.5 → inset 145; round 4000 → square side `round(4000 / sqrt(2)) - 200` centred.
  - `test_map_content_type` — every mapping row of the Global Constraints; `allow_qr=True` → unchanged, `mapped=False`.
  - `test_image_exact_size_and_mode` — box 42.5 × 18.0 mm at 600 dpi → size `(1004, 425)`, mode `"1"`.
  - `test_qr_modules_whole_pixels_and_quiet_zone` — `qr_two_lines`; the leftmost and topmost `4 × module_px` columns/rows of the QR area are white; module size inferred from the finder pattern is an integer ≥ 1. Counter-test: swapping `build_qr` for `LayoutEngine._build_qr_image` turns this test red (no quiet zone, non-integer modules).
  - `test_text_shrinks_then_truncates` — 200-character title in a 25.4 × 10 box at 600 dpi → `truncated=True`, rendered cap height ≥ 1.6 mm (measured from the font metrics used).
  - `test_missing_fields_raise_mismatch` — `qr_two_lines` without `title` → `ContentTypeDataMismatchError`.
  - `test_render_edge_data` (parametrised, each: no exception except where stated, image exact size): 10 000-char title; title with `‮` and `\x07`; emoji-only title; `qr_payload` of 3 000 characters in a 10 mm box (QR cannot fit with module ≥ 1 px → `ContentTypeDataMismatchError` naming `qr_payload`); `text_one_line` with `primary_id=""` → mismatch.
  - `test_tape_layout_engine_unchanged` — existing `tests/unit/services/test_layout_engine*.py` stay green (run, not new).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add backend/app/sheets/cell_render.py backend/app/services/layout_engine.py backend/tests/unit/sheets/test_cell_render.py && git commit -m "feat(api): cell renderer for sheet labels"`

---

### Task 2: Planner

**Files:**
- Create: `backend/app/sheets/planner.py`
- Modify: `backend/app/sheets/errors.py`
- Test: `backend/tests/unit/sheets/test_planner.py`

**Interfaces:**
- Consumes: Plan 1 `Geometry`, `cell_count`, `cell_origin`; Plan 2 `Deviation`.
- Produces:
  - `@dataclass SheetView(code: str | None, type_key: str, type_version_id: UUID, geometry: Geometry, allow_qr: bool, non_free: dict[int, str]` (cell → state), `id_placement: Literal["cell","margin","manual"], id_printed: bool, has_hub_cell: bool, margin_id_in_flight: bool, state: Literal["active","discarded"])`.
  - `@dataclass PlacementIn(sheet: SheetView, cells: Literal["first_free"] | list[int], skip: list[int], count: int | None)`.
  - `@dataclass PagePlan(index: int, sheet: SheetView, item_cells: list[int], id_cell: int | None, margin_id: bool, hw_margin_cells: list[int])`; `@dataclass Plan(pages: list[PagePlan], free_after: list[int])`.
  - `@dataclass(frozen) MarginContext(hw_top_hmm: int | None, deviation: Deviation, scan_payload: Callable[[str], str])` (payload builder from the public URL, OC-15).
  - `def plan(placements: Sequence[PlacementIn], n_items: int, *, hw_margins_hmm: Margins | None, margin: MarginContext | None) -> Plan` (`margin=None` = no printer context: margin availability is not checked).
  - `def margin_usable_hmm(g: Geometry, *, hw_top_hmm: int | None, dev: Deviation) -> int` and `def margin_qr_fits(usable_hmm: int, payload: str) -> bool` (OC-16 numbers).
  - Errors: `InsufficientCellsError` (409, `insufficient_cells`, detail `{"free_cells": [per placement], "needed": n, "shortfall": k}`), `InvalidPlacementsError` (422, `invalid_placements`, detail reason: `count_missing_not_last`, `explicit_count_mismatch`, `empty`), `CellOutOfRangeError`, `CellsTakenError` (explicit cell not free), `SheetDiscardedError`, `MarginTooSmallError` (422, `margin_too_small`, detail `{usable_mm}`).
  - Rules: placements filled in order; only the last may omit `count` and takes the rest; an explicit list must have exactly the placement's item count; the **ID cell** is needed when `id_placement == "cell"` and not `id_printed` and not `has_hub_cell` (OC-40), and is the lowest free, non-skipped cell not in an explicit list; it counts against capacity; `margin_id` is due when `id_placement == "margin"`, not `id_printed`, not `margin_id_in_flight`; a discarded sheet → `SheetDiscardedError`. `hw_margin_cells` = cells whose rectangle intersects a hardware-margin band.
- [ ] **Step 1: Write the failing tests**
  - `test_nine_into_seventeen_used` — L4736REV with cells 1–17 used, 9 items → `item_cells == [18..26]`, `free_after == [48-26]` (acceptance 1, planning side).
  - `test_gaps_and_skip` — used `{1, 2, 5}`, skip `[3]`, 3 items → `[4, 6, 7]`.
  - `test_insufficient` — 40 items onto a sheet with 31 free → `InsufficientCellsError(free_cells=[31], needed=40, shortfall=9)` (acceptance 3); two placements 31 + new sheet (48) → fits.
  - `test_explicit_cells` — `[20, 21]` for 2 items OK; `[5]` used → `CellsTakenError([5])`; `[49]` → `CellOutOfRangeError`; 3 items for `[20, 21]` → `InvalidPlacementsError("explicit_count_mismatch")`.
  - `test_id_cell_on_new_cell_sheet` — new sheet, `id_placement="cell"`, 3 items → `id_cell == 1`, `item_cells == [2, 3, 4]`; with `has_hub_cell=True` → no ID cell.
  - `test_margin_id_due_once` — new margin sheet → `margin_id=True`; `id_printed=True` → False; `margin_id_in_flight=True` → False.
  - `test_margin_usable` — L4731REV top 13.5, hw 4.23, dev dy −0.5 mm → usable `1350 − 423 − 50 − 100 = 777` hmm (text, no QR); L4736REV top 21.3 with unknown hw → `2130 − 500 − 0 − 100 = 1530` (QR if it fits); top 8.0 with hw 5.0 → `MarginTooSmallError`.
  - `test_hw_margin_flags` — synthetic type with `margin_top = 0` and hw top 4.23 → first-row cells flagged.
  - `test_last_only_may_omit_count`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add backend/app/sheets/planner.py backend/app/sheets/errors.py backend/tests/unit/sheets/test_planner.py && git commit -m "feat(api): sheet placement planner with capacity check"`

---

### Task 3: Atomic reservation

**Files:**
- Create: `backend/app/sheets/reservation.py`
- Modify: `backend/app/repositories/sheets.py`, `backend/app/sheets/errors.py`, `docs/decisions/register.md` (`D15` "Cells are reserved at job creation, used on completion, unconfirmed when the outcome is unknown"; `V3` "A QR does not scan reliably on 25.4 × 10 mm cells", To verify)
- Test: `backend/tests/unit/sheets/test_reservation.py`, `backend/tests/db/test_reservation_concurrency.py`

**Interfaces:**
- Consumes: Task 2; Plan 1 `acquire_sheet_write_lock`, `create_sheet` internals (counter), repositories.
- Produces:
  - `@dataclass NewSheetIn(type_key: str, version: int | None, id_placement: Literal["cell","margin","manual"])`; `@dataclass PlacementRequest(sheet_code: str | None, new_sheet: NewSheetIn | None, cells: Literal["first_free"] | list[int], skip: list[int], count: int | None)`.
  - `@dataclass CellAssignment(cell: int, item_index: int | None, source: str, purpose: str, ref: str | None)` (`item_index=None` for the ID cell, `source="hub"`, purpose `"Sheet ID"`).
  - `@dataclass ReservedPage(job_id: UUID, sheet_id: UUID, sheet_code: str, type_version_id: UUID, assignments: list[CellAssignment], id_cell: int | None, margin_id: bool, hw_margin_cells: list[int])`.
  - `@dataclass ExpectedPage(sheet: str, cells: list[int], id_cell: int | None)` (`sheet` = code or `"new"`).
  - `async def reserve(session, *, placements: Sequence[PlacementRequest], items: Sequence[ItemMeta], expected: Sequence[ExpectedPage] | None, hw_margins_hmm: Margins | None, margin: MarginContext | None, required_type_key: str | None, actor: str) -> list[ReservedPage]` — one transaction: lock → load sheet views (a placement's sheet of another type than `required_type_key` → `SheetTypeMismatchError` 409 `sheet_type_mismatch`; archived type for a new sheet → `SheetTypeArchivedError`) → create new sheets (counter) → `plan` → compare with `expected` (any difference in sheet, cells or id cell → `PlanChangedError` 409 `plan_changed`, detail = the new plan as `ExpectedPage` list, nothing written, new sheets rolled back) → insert `reserved` rows with pre-generated `job_id` per page → commit. An `IntegrityError` on insert: explicit cells → `CellsTakenError(cells)`; `first_free` → re-plan once inside a fresh transaction, then `CellsTakenError`.
  - `async def release(session, job_id: UUID) -> list[int]` — deletes that job's `reserved` rows (used when queue submission fails after commit).
  - `ItemMeta(source: str, purpose: str, ref: str | None)`.
- [ ] **Step 1: Write the failing tests**
  - `test_reserve_writes_reserved_rows_with_job_id` — 9 items → 9 rows `reserved`, all with the page's `job_id`, purposes and sources from `ItemMeta`.
  - `test_new_sheet_created_in_same_transaction` — new L4736REV sheet with `id_placement="cell"` → code `L4736-01`, ID row at cell 1 `source="hub"`.
  - `test_plan_changed_writes_nothing` — `expected` differs → `PlanChangedError` with the new plan; no rows; a would-be new sheet not created and the counter **not** advanced (acceptance 13).
  - `test_explicit_taken` — `[5]` already reserved → `CellsTakenError([5])`.
  - `test_type_mismatch_and_archived`.
  - `test_release`.
  - `db/test_reservation_concurrency.py` (temp-file SQLite, 2 sessions, `asyncio.gather`): `test_parallel_first_free_never_overlap` — 2 × 20 items on a 48-cell sheet with 8 used → both succeed, cell sets disjoint, union `9..48` (acceptance 12); repeat 20 times; `test_parallel_explicit_vs_first_free` — explicit `[9, 10]` vs `first_free` 2 items → one gets `[9, 10]`, the other `[11, 12]` or the explicit one fails with `cells_taken`, never both on 9/10.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**; `# D15` on the insert and on the outcome transitions later.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add backend/app/sheets/reservation.py backend/app/repositories/sheets.py backend/app/sheets/errors.py docs/decisions/register.md backend/tests/unit/sheets/test_reservation.py backend/tests/db/test_reservation_concurrency.py && git commit -m "feat(api): atomic cell reservation for sheet prints"`

---

### Task 4: Sheet page payload and PDF renderer

**Files:**
- Create: `backend/app/sheets/sheet_page.py`
- Modify: `backend/app/main.py` (register renderer for `sheet_page`)
- Test: `backend/tests/unit/sheets/test_sheet_page.py`

**Interfaces:**
- Consumes: Tasks 1–2; Plan 2 `PagePayload`, `register_page_renderer`, `write_pdf`, `PageImage`, `PageText`, `Deviation`.
- Produces:
  - `class SheetCellPayload(BaseModel)`: `cell: int, content_type: ContentType` (already mapped), `label_data: dict` (LabelData dump), `mapped: bool`.
  - `class SheetPageDetail(BaseModel)` (stored in `PagePayload.detail`): `sheet_id, sheet_code, type_key, type_version_id, geometry: dict` (hundredths, `asdict(Geometry)`), `allow_qr, cells: list[SheetCellPayload], id_cell: SheetCellPayload | None, margin_id: MarginIdPayload | None` (`text`, `qr_payload: str | None`, `usable_hmm`), `job_summary: {sheet_code, cell_count}`.
  - `def render_sheet_page(payload: PagePayload, renderer: CellRenderer = DEFAULT_CELL_RENDERER) -> bytes` — for each cell `content_box` → `renderer.render(..., dpi=payload.render_dpi)` → `PageImage` at the box; ID cell likewise; margin ID as `PageText` (and a QR `PageImage` when present) left-aligned with the grid in the top margin, vertically centred in the usable height; `write_pdf(media, correction=calibration or IDENTITY)`. Geometry comes **only** from the payload (pinned version at submit), never re-read.
  - `def render_preview_png(geometry: Geometry, cells: list[tuple[int, CellImage]], margin: MarginIdPayload | None, page: Literal["A4","Letter"]) -> bytes` — 1-bit PNG at 150 dpi, page size (A4 → 1240 × 1754), only the new content at nominal positions.
- [ ] **Step 1: Write the failing tests**
  - `test_cells_placed_at_boxes` — payload with cells 18 and 26 on L4736REV → `pdf_inspect.cm_matrices` contains the placement of each content box in pt (from `content_box` × `k`).
  - `test_sheet_page_uses_pinned_version` — payload geometry is v1 (4 × 12); renderer never touches the database (call with no session available) and places cell 5 at v1's position.
  - `test_correction_applied_from_snapshot` — snapshot `dx=+1.5, dy=−0.8` → first `cm` `(1, 0, 0, 1, −4.252, −2.268)`; `calibration=None` → no correction matrix.
  - `test_margin_id_drawn_only_when_in_payload` — with `margin_id` → one text object with the code; without → none.
  - `test_mapped_content_has_no_qr` — the PDF cannot tell a QR from text (both are 1-bit images), so the test passes a recording `CellRenderer` spy: for an `allow_qr=false` payload every call has a `text_*` content type and `build_qr` is never called.
  - `test_gray_only` — `pdf_inspect.operators` gray only (acceptance 15 for sheet pages).
  - `test_preview_png_size_and_mode` — A4 → `(1240, 1754)`, mode `"1"`; only the given cells non-white.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add backend/app/sheets/sheet_page.py backend/app/main.py backend/tests/unit/sheets/test_sheet_page.py && git commit -m "feat(api): render sheet pages to PDF"`

---

### Task 5: Outcome handler and orphan sweep

**Files:**
- Create: `backend/app/sheets/outcome.py`
- Modify: `backend/app/main.py` (register handler for `sheet_page`; run the sweep after `queue.start()`), `backend/app/sheets/sheet_service.py` (`resolve_cells`: margin ID)
- Test: `backend/tests/unit/sheets/test_outcome.py`, `backend/tests/integration/test_sheet_job_lifecycle.py`

**Interfaces:**
- Consumes: Plan 2 `PageOutcomeHandler`, `register_outcome_handler`, `FakeIppPrinter`; Plan 1 `publish_sheet_updated`.
- Produces:
  - `class SheetCellsOutcome(session_factory, bus: EventBus | None)` implementing `PageOutcomeHandler`: `on_completed` → the job's `reserved` rows → `used`, `sheets.last_used_at = now`, `id_printed = True` if the job carried an ID cell or margin ID; `on_ended(started=False)` → delete the job's `reserved` rows; `on_ended(started=True)` and `on_unknown` → `reserved` → `unconfirmed`. Each call is idempotent (a second call changes nothing) and publishes one `sheet.updated` with the changed cells. All under `acquire_sheet_write_lock`.
  - `resolve_cells(..., outcome="printed")` (Plan 1) additionally sets `id_printed = True` when one of the resolved cells' jobs carried `detail.margin_id` (looked up in `jobs.payload`; a job row already deleted by retention counts as not carrying it). Plan 1 already covers the `source="hub"` ID cell.
  - `async def sweep_orphan_reservations(session_factory) -> SweepReport` — for every `reserved` row: no `jobs` row → delete; job `done` → `used`; job `cancelled`/`failed` with `result.started` false → delete; with `started` true or `failed_restart` → `unconfirmed`; job `queued`/`printing` → untouched.
  - `margin_id_in_flight(session, sheet_id) -> bool` — true if a non-terminal `sheet_page` job for the sheet has `detail.margin_id` (used by Task 7 to build `SheetView`).
- [ ] **Step 1: Write the failing tests**
  - `test_completed_marks_used` — 9 reserved → 9 used, `last_used_at` set; 17 already used → sheet shows 26 used (acceptance 1).
  - `test_clean_failure_frees` / `test_started_failure_unconfirmed` (acceptance 2).
  - `test_idempotent`.
  - `test_resolve_printed_sets_id_printed_for_margin_job` — margin first job interrupted after start → cells unconfirmed, `id_printed=False`; resolve as `printed` → `id_printed=True`, the next job carries no margin ID; resolve as `not_printed` → stays false.
  - `test_id_printed_set_on_completion_only` — margin job fails cleanly → `id_printed` false, reservations freed (acceptance 7, outcome side).
  - `test_sweep_orphan_reservations` — the five row situations above.
  - Integration (`test_sheet_job_lifecycle.py`, real queue + `FakeIppPrinter` + SQLite): reserve 9 cells and submit a page job; script `[3, 5, 9]` → cells used; script `[3]` then cancel → cells free; script `[5]` then cancel → unconfirmed; restart the queue mid-job (`[5]` → restart → `[9]`) → used (acceptance 17).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**; `# D15` on the transitions.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add backend/app/sheets/outcome.py backend/app/main.py backend/tests/unit/sheets/test_outcome.py backend/tests/integration/test_sheet_job_lifecycle.py && git commit -m "feat(queue): sheet cells follow page job outcomes"`

---

### Task 6: Sheet print service — item resolution and preview

**Files:**
- Create: `backend/app/sheets/print_service.py`, `backend/app/schemas/sheet_print.py`, `backend/app/api/routes/sheet_print.py`
- Modify: `backend/app/sheets/errors.py` (`ItemLookupFailedError`, `PreviewTooLargeError`), `backend/app/main.py`, `backend/tests/api/test_openapi_completeness.py`, `frontend/src/api/schema.gen.ts`
- Test: `backend/tests/unit/sheets/test_print_service_preview.py`, `backend/tests/integration/api/test_sheet_preview_api.py`

**Interfaces:**
- Consumes: Tasks 1, 2, 4; `AppLookupService.lookup(app, identifier) -> LabelData` (existing), `LookupFailedError`, `UnknownAppError`; Plan 2 status cache (`summary`, margins, resolutions), calibration `snapshot`.
- Produces (`schemas/sheet_print.py`):
  - `SheetItem(PrintRequest-like: content_type, data | lookup, purpose: str | None = Field(max_length=120), source: str | None, ref: str | None = Field(max_length=120))` — reuses `RawLabelData` and `PrintLookupRequest`; `options` not accepted.
  - `PlacementOut` / `PlacementInModel` (either `{sheet: code, cells: "first_free" | list[int], skip?: list[int] ≤ 400, count?: int ≥ 1}` or `{new_sheet: {type, version?, id_placement}, count?}`, exactly one of `sheet`/`new_sheet`).
  - `SheetPrintRequest(items: list[SheetItem] = Field(min_length=1, max_length=500), placements: list[PlacementInModel] = Field(min_length=1, max_length=50), tray: str | None, expected_cells: list[ExpectedPageModel] | None = Field(default=None, max_length=50))` (each `ExpectedPageModel.cells` ≤ 400).
  - `SheetPreview(pages: list[PreviewPage], free_after: list[int], expected_cells: list[ExpectedPageModel], reprint_hints: list[ReprintHint])`; `PreviewPage(sheet_code: str | None, new_code_hint: str | None, type_key, version, geometry: GeometryMm, cells: list[PreviewCell], png_base64: str, margin_id: bool, load_hint: str | None)`; `PreviewCell(cell, state: Literal["used","reserved","unconfirmed","new","free"], is_id: bool, purpose: str | None, item_index: int | None, truncated: bool, mapped: bool, hw_margin: bool)`; `ReprintHint(item_index, sheet_code, cell, printed_at)`.
- Produces (`print_service.py`):
  - `async def resolve_items(items: Sequence[SheetItem], lookup: AppLookupService) -> list[ResolvedItem]` (`label: LabelData`, `content_type`, `meta: ItemMeta`) — lookups run **before** any write and outside the lock; the first failure → `ItemLookupFailedError` (422 or 502 per existing mapping, detail `{"item_index": i}`).
  - `async def preview(session, *, printer: Printer, request: SheetPrintRequest, lookup, renderer) -> SheetPreview` — page printer only (`MediaKindMismatchError`), tray resolved (default if omitted, `TrayUnknownError` if unknown/disabled); builds `SheetView`s (Plan 1 repository + `margin_id_in_flight`), runs `plan` (no write; new sheets get `new_code_hint` from `peek_next_code`), renders the new cells in a thread at **150 dpi**, `reprint_hints` from `find_cells(source, ref)` for lookup items. Calibration is not applied. Load bound (spec 18 "CPU"; preview needs only `read`): a preview plans all pages but renders PNGs for at most **10** pages — a plan with more pages answers `422 preview_too_large` (`PreviewTooLargeError`, detail `{"pages": n, "max": 10}`); lookups run with at most 8 in flight. *(Plan decision; the spec sets no number.)*
- Route: `POST /api/print/{printer_key}/sheet/preview` (read + `check_printer_access`).
- [ ] **Step 1: Write the failing tests**
  - `test_preview_plan_and_png` — 9 Grocy items (fake lookup) on a sheet with 17 used → 9 `new` cells 18–26, `free_after == [22]`, `png_base64` decodes to a 1240 × 1754 1-bit PNG.
  - `test_preview_marks_mapped_cells` — `qr_two_lines` on L4731REV → `mapped=True` (acceptance 21, preview side).
  - `test_preview_has_no_side_effects` — row counts of `sheets`, `sheet_cells`, `sheet_id_counters`, `jobs` unchanged.
  - `test_preview_reprint_hint` — item `grocy/42` printed before on `L4736-02` cell 5 → hint.
  - `test_preview_new_sheet_hint` — `new_sheet` → `new_code_hint == "L4736-03"` and an ID cell `is_id=True` when `id_placement="cell"`.
  - `test_preview_page_bound` — a plan of 11 pages → 422 `preview_too_large`, no render.
  - API: scope `read` OK; printer-restricted key for another printer → 403 `printer_not_allowed`; tape printer → 409 `media_kind_mismatch`; unknown tray → 422 `tray_unknown`; 501 items → 422.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**; raise endpoint bound; `pnpm gen:api`.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add backend/app/sheets/print_service.py backend/app/schemas/sheet_print.py backend/app/api/routes/sheet_print.py backend/app/main.py backend/tests/api/test_openapi_completeness.py backend/tests/unit/sheets/test_print_service_preview.py backend/tests/integration/api/test_sheet_preview_api.py frontend/src/api/schema.gen.ts && git commit -m "feat(api): sheet print preview"`

---

### Task 7: Sheet print

**Files:**
- Modify: `backend/app/sheets/print_service.py`, `backend/app/schemas/sheet_print.py`, `backend/app/api/routes/sheet_print.py`, `frontend/src/api/schema.gen.ts`, `backend/tests/api/test_openapi_completeness.py`
- Test: `backend/tests/unit/sheets/test_print_service_print.py`, `backend/tests/integration/api/test_sheet_print_api.py`

**Interfaces:**
- Consumes: Tasks 3–6; Plan 2 `PrintQueue.submit_page_job`, `PagePayload`, calibration `snapshot`; `print_batches` repository.
- Produces:
  - `SheetPrintResponse(batch_id: UUID, pages: list[PrintedPage])`, `PrintedPage(job_id, sheet_code, cells: list[int], id_cell: int | None, margin_id: bool)`.
  - `async def print_sheets(session_factory, *, printer, request, lookup, queue, actor, api_key_id, source_ip) -> SheetPrintResponse` — order: resolve items → validate printer kind and tray → `reserve(...)` (expected cells honoured) → for each page build `PagePayload(kind="sheet_page", media=geometry.page_size, tray, render_dpi, job_name="Sheet <code> · <n> labels", calibration=await calibration_service.snapshot(session, printer.id, tray), detail=SheetPageDetail)` and `queue.submit_page_job(..., job_id=page.job_id)`; a submission failure releases that page's reservation and every later page's (pages already submitted stay); one `print_batches` row with all job ids; `job_name` carries no personal data.
  - Purposes sanitised per Global Constraints.
- Route: `POST /api/print/{printer_key}/sheet` (print + printer access), `202`.
- [ ] **Step 1: Write the failing tests**
  - `test_print_end_to_end_cells_used` — fake printer script `[3, 5, 9]`; 9 items onto a sheet with 17 used → response cells 18–26; after the job completes `GET /api/sheets/{code}` shows 26 used with purposes (acceptance 1); the fake received one PDF with `media-type=labels` and `print-scaling=none`.
  - `test_print_two_sheets_one_batch` — 60 items, placements `[existing (31 free), new]` → two jobs, one batch, page 1 completes while page 2 is aborted before start → page 1 cells used, page 2 cells free.
  - `test_print_after_type_edit_uses_v1` — sheet on v1, type edited to v2 (different pitch), print → PDF positions from v1 (acceptance 9).
  - `test_expected_cells_mismatch` → 409 `plan_changed` with the new plan (acceptance 13).
  - `test_insufficient_over_http` → 409 `insufficient_cells` with `free_cells` (acceptance 3).
  - `test_qr_mapped_on_small_type_printed_as_text` (acceptance 21, print side: payload content types are text types).
  - `test_other_client_reads_same_sheet` — Grocy print with key A, `GET /api/sheets/{code}` with key B shows the cells and purposes (acceptance 11).
  - `test_nothing_reserved_on_late_failure` — lookup fails for item 37 of 40 → 4xx with `item_index=36`, zero new rows; tape printer → `media_kind_mismatch`, zero rows; disabled tray → `tray_unknown`, zero rows.
  - `test_purpose_sanitised` — purpose with `\x07` and `‮` stored without them; 130 characters → 422.
  - `test_submit_failure_releases` — queue raising on page 2 → page 2 and later reservations deleted, page 1 job exists.
  - Scopes: `read` key → 403; printer-restricted key for another printer → 403.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**; raise endpoint bound; `pnpm gen:api`.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add backend/app/sheets/print_service.py backend/app/schemas/sheet_print.py backend/app/api/routes/sheet_print.py backend/tests/api/test_openapi_completeness.py backend/tests/unit/sheets/test_print_service_print.py backend/tests/integration/api/test_sheet_print_api.py frontend/src/api/schema.gen.ts && git commit -m "feat(api): print labels onto sheets through the page queue"`

---

### Task 8: Sheet ID on creation (cell option) and margin checks

**Files:**
- Modify: `backend/app/sheets/sheet_service.py`, `backend/app/schemas/sheets.py`, `backend/app/api/routes/sheets.py`, `backend/app/sheets/print_service.py`, `frontend/src/api/schema.gen.ts`
- Test: `backend/tests/integration/api/test_sheet_id_label.py`

**Interfaces:**
- Consumes: Tasks 3, 5, 7.
- Produces: `SheetCreate.id_placement: Literal["cell","margin","manual"]` plus `printer: str | None`, `tray: str | None`. `cell` requires a page printer (print scope + printer access) and creates the sheet, reserves the ID cell (first free after the hand-marked cells) and submits an ID-only `sheet_page` job in the same request; the response gains `job_id: UUID | None`. `margin` with a printer given runs the margin check and refuses `margin_too_small`; without a printer it is stored unchecked (the print dialog checks later). `GET /api/sheets/margin-check?type=&printer=&tray=` (read + printer access) → `{usable_mm, qr: bool, allowed: bool, reason: str | None}` for the UI's disabled-with-reason radio (spec 17.1). *(Plan decision: the spec's API table has no endpoint that tells the UI whether the margin option is available for a printer; this read-only route adds it. It is declared before `/{code}`; the code pattern cannot match it anyway.)*
- [ ] **Step 1: Write the failing tests**
  - `test_create_cell_queues_id_label` — L4736REV with 5 hand-marked cells → ID cell 6 reserved `source="hub"`, job printed by the fake → cell 6 used, `id_printed=True` (acceptance 6); the PDF's ID cell is `qr_two_lines` with payload `<public_url>/sheet/L4736-01`; on L4731REV the ID cell is text only.
  - `test_id_job_clean_failure_then_next_job_carries_id` — ID-only job aborted before start → cell 6 free, `id_printed=False`; next print onto the sheet reserves an ID cell at its first free cell (OC-40).
  - `test_margin_only_first_completed_job` — margin sheet: job 1 completes → `id_printed`; job 2 payload has no `margin_id`; a fresh margin sheet whose first job fails cleanly → the next job draws the margin ID again (acceptance 7).
  - `test_margin_too_small` — L4731REV on a printer reporting hw top 10 mm → 422 `margin_too_small`; `margin-check` returns `allowed=false` with the reason.
  - `test_scan_payload_short_form_without_public_url`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**; `pnpm gen:api`.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add backend/app/sheets/sheet_service.py backend/app/schemas/sheets.py backend/app/api/routes/sheets.py backend/app/sheets/print_service.py backend/tests/integration/api/test_sheet_id_label.py frontend/src/api/schema.gen.ts && git commit -m "feat(api): sheet ID label in the first free cell or the margin"`

---

### Task 9: Retry of page jobs

**Files:**
- Modify: `backend/app/api/routes/jobs.py` (after #184 the retry route enqueues through the queue; Plan 2 Task 7 refuses `sheet_page` there with `409 job_not_retryable` — this task replaces that refusal with `retry_sheet_page`), `backend/app/sheets/print_service.py`, `backend/app/sheets/errors.py`
- Test: `backend/tests/integration/api/test_page_job_retry.py`

**Interfaces:**
- Consumes: Tasks 3, 5, 7; Plan 2 `calibration_service.snapshot(session, printer_id, tray)`; the #184 retry route.
- Produces: `async def retry_sheet_page(session_factory, queue, job: DbJob, *, actor) -> UUID` — allowed for a `sheet_page` job in `failed` or `cancelled` with **no** `unconfirmed` cell still pointing at it (OC-42); re-reserves exactly the job's cells (`detail.cells` + `id_cell`) for a new job id, refusing `409 cells_taken` with the cell numbers if any is no longer free; fresh calibration snapshot; `margin_id` re-evaluated by the planner rule; the new job goes to `queue.submit_page_job` at once (the #184 route never writes a bare `queued` row for page jobs). `done` → `409 job_not_retryable`; a job with unconfirmed cells → `409 cells_unconfirmed` (`CellsUnconfirmedError`). `calibration_page` retry stays as Plan 2 Task 7 built it. Tape retry unchanged (#184).
- [ ] **Step 1: Write the failing tests** (through `POST /api/jobs/{id}/retry`, fake printer) — clean failure → retry reserves the same cells and the fake receives the new PDF without a restart; cells taken meanwhile → `cells_taken` with numbers; interrupted job with unconfirmed cells → `cells_unconfirmed`; after resolving them `not_printed` → retry allowed; `done` → `job_not_retryable`; tape retry regression test green.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS** — add `tests/api/test_openapi_completeness.py::test_sheet_archive_endpoints_listed` (every method + path of spec 15, with the probe under `/api/v1/admin/printers/ipp/probe` and the added `GET /api/sheets/margin-check`; acceptance 19), then the full backend suite with coverage, `mypy app/`, ruff, `pnpm typecheck`.
- [ ] **Step 5: Commit** — `git add backend/app/api/routes/jobs.py backend/app/services/print_queue.py backend/app/sheets/print_service.py backend/app/sheets/errors.py backend/tests/integration/api/test_page_job_retry.py backend/tests/api/test_openapi_completeness.py && git commit -m "feat(queue): retry sheet page jobs onto the same cells"`

---

## Operator-verified (not task gates)

- Acceptance 5: an L4736REV sheet printed on the real IPP printer from PDF without a dialog, aligned within ±0.5 mm at every cell after calibration (Plan 2).
- `V3`: whether a QR on 25.4 × 10 mm cells scans; until proven, L4731REV keeps `allow_qr=false`.

## Plan review 2026-11-05

Findings of the independent plan review worked in, each checked against the code: P3-M1 (own `build_qr`), P3-M2, P3-M3 (retry premise after #184), P3-m1 … P3-m7. None rejected.
