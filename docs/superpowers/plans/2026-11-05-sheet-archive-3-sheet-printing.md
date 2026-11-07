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
- Margin ID (OC-16, spec 10.2 as changed 2026-11-07): `id_placement` defaults to **`margin`**; `cell` only when chosen. The margin ID goes into the best of four bands. Depth per band: top `margin_top − hw.top − max(0, −dy)`, bottom `page_h − grid_bottom − hw.bottom − max(0, dy)`, right `page_w − grid_right − hw.right − max(0, dx)`, left `margin_left − hw.left − max(0, −dx)`, each minus 1.0 mm safety; hardware margins from the printer's `margins_hmm`, **5.0 mm per side** if unknown. Text from 4.0 mm; QR next to the text from 9.0 mm if `margin_qr_allowed` at the job's render dpi and the band is ≥ depth + 2 mm + 10 mm long. Choice: QR possible, then larger depth, then top, bottom, right, left. Below 4.0 mm everywhere: printed without the ID, no cell, `id_printed` stays false, page flagged `id_not_printed`; nothing is refused (`margin_too_small` retired). Band, corner, depth and QR are decided in the reservation and stored in the payload; renderer and preview obey them. *Changed 2026-11-07 (operator decision); was: top margin only, < 4.0 mm → `422 margin_too_small`.* ID-cell label: `qr_two_lines` (`primary_id` = code, `title` = `"<vendor> <first product code> · sheet ID"`, QR = payload); `text_two_lines` on `allow_qr=false` types.
- Sheet ID scan payload (OC-15): `base_url(str(public_url)) + "/sheet/" + code` using `app.integrations.urls.base_url` (keeps a sub-path, drops the trailing slash `AnyHttpUrl` adds). `public_url` is a required setting (`app/config.py`), so the short form `sheet:{code}` is only produced by the payload builder when it is given an empty URL — tested at unit level, unreachable in operation.
- Cells in the printer's hardware margins are flagged (`hw_margin: true`), never refused (OC-44).
- Label `D15` (cells reserved at job creation, used on completion, unconfirmed when unknown) is added to the register in Task 3 and marks the reservation and outcome code.

## Review Focus

1. **Two print requests for the same sheet at the same moment** (both `first_free`, or one explicit `[5,6]` against one `first_free`). Never the same cell twice; the explicit loser gets `409 cells_taken` with `[5,6]`, a `first_free` loser is re-planned once and succeeds on the next free cells. Owner: Task 3 (`test_parallel_first_free_never_overlap`, `test_parallel_explicit_vs_first_free`).
2. **Crash or restart between committing the reservation and persisting the page job.** Reserved cells pointing at a job that does not exist would block cells forever. A startup sweep frees them; reserved cells of a terminal clean job are freed, of a started one become unconfirmed. Owner: Task 5 (`test_sweep_orphan_reservations`).
3. **The type is edited (new version) while a sheet is half used and while a job for it waits in the queue.** The sheet keeps v1 positions and cell count in plan, preview, PDF and outcome; a request explicitly naming a v2-only cell number is `422 cell_out_of_range`. Owner: Task 4 (`test_sheet_page_uses_pinned_version`) and Task 7 (`test_print_after_type_edit_uses_v1`, acceptance 9).
4. **Hostile or odd label data in a cell**: 10 000-character title, control characters and bidi overrides in purpose, emoji, an empty `primary_id` after mapping to `text_one_line`, a QR payload too long for the box. Rendering never raises outside `content_type_data_mismatch` (422 for that item), never draws outside the box, flags `truncated`. Owner: Task 1 (`test_render_edge_data` table) and Task 7 (`test_purpose_sanitised`).
5. **A lookup fails for item 37 of 40, or the printer is a tape printer, or the tray is disabled.** Nothing is reserved, no job is created, the answer names the item index or the reason (`media_kind_mismatch`, `tray_unknown`). Owner: Task 7 (`test_nothing_reserved_on_late_failure`).
6. **The margin ID lands where the stored decision says, and nowhere when there is no room.** A calibration that eats into the top band moves the ID to the bottom band; a wide right margin puts it in the right band with rotated text; the renderer never chooses a band again; a sheet with every band below 4 mm prints its labels without the ID, takes no cell and keeps `id_printed=false`. Owner: Task 5b (`test_choose_bottom_when_calibration_eats_top`, `test_choose_right_on_wide_right_margin`, `test_stored_band_wins`, `test_plan_margin_unprintable_prints_without_id`). *Added 2026-11-07.*

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/sheets/cell_render.py` | `CellRenderer` protocol, `RasterCellRenderer`, content box, QR mapping (pure) |
| `backend/app/sheets/planner.py` | placements → page plans, capacity, ID cell, margin-ID rule, hw-margin flags (pure) |
| `backend/app/sheets/reservation.py` | write-locked plan + reserve, new sheets, `expected_cells` |
| `backend/app/sheets/sheet_page.py` | `sheet_page` payload model and PDF renderer (margin ID in its stored band, ID cell) |
| `backend/app/page_render/pdf.py` | rotated text for the left and right margin bands (modify, Task 5b) |
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

*Amended 2026-11-07: done as written. Its margin-ID rule (top margin only, `MarginTooSmallError`) is replaced by Task 5b.*

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
  - `test_new_sheet_created_in_same_transaction` — new L4736REV sheet with `id_placement="cell"` → code `L4736-0001`, ID row at cell 1 `source="hub"`.
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

*Amended 2026-11-07: done as written. The margin ID's band, corner and the rotated layout are added by Task 5b.*

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

### Task 5b: Margin ID placement in the best margin band

*Inserted 2026-11-07 (operator decision; spec requirement 17, sections 7 and 10.2, OC-16 and OC-45 to OC-51 as changed). Runs after Task 5 and before Task 6. Task 5 changes `resolve_cells` in `sheet_service.py`; this task changes only `create_sheet`'s default there, so rebase onto Task 5 first.*

**Files:**
- Modify: `backend/app/sheets/planner.py`, `backend/app/sheets/sheet_page.py`, `backend/app/page_render/pdf.py`, `backend/app/sheets/reservation.py`, `backend/app/sheets/errors.py` (remove `MarginTooSmallError`), `backend/app/schemas/sheets.py`, `backend/app/sheets/sheet_service.py`, `frontend/src/api/schema.gen.ts`
- Test: `backend/tests/unit/sheets/test_planner.py`, `backend/tests/unit/sheets/test_sheet_page.py`, `backend/tests/unit/sheets/test_reservation.py`, `backend/tests/db/test_reservation_concurrency.py` (the `MarginContext` constant only), `backend/tests/unit/page_render/test_pdf.py`, `backend/tests/integration/api/test_sheets_api.py`

**Interfaces:**
- Consumes (as built at `55e5181`):
  - `planner.py:46-51` constants `DEFAULT_HW_TOP_HMM = 500`, `SAFETY_HMM = 100`, `MIN_MARGIN_TEXT_HMM = 400`, `MIN_MARGIN_QR_HMM = 900`, `MIN_QR_MODULE_HMM = 25`; `:54-75` `SheetView`; `:86-93` `PagePlan(index, sheet, item_cells, id_cell, margin_id, hw_margin_cells)`; `:104-108` `MarginContext(hw_top_hmm: int | None, deviation: Deviation, scan_payload: Callable[[str], str])`; `:111-115` `margin_usable_hmm(g, *, hw_top_hmm, dev) -> int`; `:118-137` `margin_qr_allowed(usable_hmm: int, payload: str, dpi: int) -> bool` and `:140` its alias `margin_qr_fits`; `:242-251` the margin block of `_draft` (raises `MarginTooSmallError`); `:305-316` the `id_done` bookkeeping in `plan`; `:277-347` `plan(placements, n_items, *, hw_margins_hmm: Margins | None, margin: MarginContext | None) -> Plan`.
  - `geometry.py:44-57` `Geometry` (hmm); `:78-82` `remaining_margins(g) -> tuple[int, int]` (right, bottom).
  - `printer_backends/ipp/attributes.py:118-124` `Margins(top, left, bottom, right)` in hmm.
  - `page_render/transform.py:73-84` `Deviation(offset_x_hmm, offset_y_hmm, scale_x_ppm, scale_y_ppm, rotation_udeg)`.
  - `sheet_page.py:55` `_TEXT_GAP_HMM = 200`; `:72-91` `MarginIdPayload(text, qr_payload, usable_hmm, qr_allowed)` with `draws_qr(render_dpi)`; `:94-104` `margin_id_payload(text, qr_payload, usable_hmm, render_dpi) -> MarginIdPayload`; `:138-144` `_MarginLayout(qr, text, text_x, baseline_y, size_pt)`; `:165-180` `_margin_layout(g, margin, *, with_qr)`; `:183-227` `render_sheet_page`; `:230-239` `_preview_qr`; `:242-281` `render_preview_png(geometry, cells, margin, *, render_dpi=600)`.
  - `page_render/pdf.py:105-111` `PageText(x_hmm, baseline_y_hmm, size_pt, text)`; `:256-261` the text loop of `write_pdf`.
  - `reservation.py:101-110` `ReservedPage`; `:347-357` its construction in `_attempt`; `:380-400` `reserve` (docstring cites ruling T2-1).
  - `errors.py:214-222` `MarginTooSmallError`.
  - `schemas/sheets.py:179-185` `SheetCreate.id_placement: Literal["margin", "manual"]` (required); `sheet_service.py:48` `_ID_PLACEMENTS`, `:259-268` `create_sheet(..., id_placement: Literal["margin", "manual"], ...)`.
  - Read side only, unchanged: `schemas/capabilities.py:38-49` `HardwareMargins` (mm) in `PageMedia.hardware_margins_mm`, filled from `summary.margins_hmm` (`api/routes/capabilities.py:72`).
- Produces (`planner.py`):
  - `MarginBand = Literal["top", "bottom", "right", "left"]`; `MarginCorner = Literal["top_left", "top_right", "bottom_left"]`; `BAND_ORDER: Final[tuple[MarginBand, ...]] = ("top", "bottom", "right", "left")` (OC-46); `BAND_CORNER: Final[dict[MarginBand, MarginCorner]] = {"top": "top_left", "bottom": "bottom_left", "right": "top_right", "left": "top_left"}` (OC-45).
  - Constants: `DEFAULT_HW_HMM = 500` replaces `DEFAULT_HW_TOP_HMM` and applies to each side; `MARGIN_TEXT_GAP_HMM = 200` moves here from `sheet_page._TEXT_GAP_HMM` (the renderer imports it, one value); `MIN_MARGIN_TEXT_RUN_HMM = 1000` (OC-48); the others unchanged.
  - `def margin_bands_hmm(g: Geometry, *, hw: Margins | None, dev: Deviation) -> dict[MarginBand, int]` — keys in `BAND_ORDER`; with `right, bottom = remaining_margins(g)` and `hw` replaced by 500 on every side when `None`: top `g.margin_top − hw.top − max(0, −dev.offset_y_hmm) − SAFETY_HMM`; bottom `bottom − hw.bottom − max(0, dev.offset_y_hmm) − SAFETY_HMM`; right `right − hw.right − max(0, dev.offset_x_hmm) − SAFETY_HMM`; left `g.margin_left − hw.left − max(0, −dev.offset_x_hmm) − SAFETY_HMM`. Values may be negative. Scale and rotation are ignored (OC-51).
  - `def band_length_hmm(g: Geometry, band: MarginBand) -> int` — `(cols − 1) × pitch_x + label_w` for top and bottom, `(rows − 1) × pitch_y + label_h` for right and left.
  - `@dataclass(frozen=True) MarginPlacement(band: MarginBand, corner: MarginCorner, depth_hmm: int, qr: bool)`.
  - `def choose_margin_placement(g: Geometry, *, hw: Margins | None, dev: Deviation, payload: str | None, dpi: int) -> MarginPlacement | None` — candidates are bands with depth ≥ `MIN_MARGIN_TEXT_HMM`; per candidate `qr = payload is not None and margin_qr_allowed(depth, payload, dpi) and band_length_hmm(g, band) >= depth + MARGIN_TEXT_GAP_HMM + MIN_MARGIN_TEXT_RUN_HMM`; the winner is the minimum of `(not qr, −depth, BAND_ORDER.index(band))`; `None` when there is no candidate. Pure.
  - `margin_usable_hmm` is removed (its formula is `margin_bands_hmm(...)["top"]`). `margin_qr_allowed` and `margin_qr_fits` stay as they are.
  - `MarginContext(deviation: Deviation, scan_payload: Callable[[str], str], render_dpi: int)` — `hw_top_hmm` is removed; the bands take their hardware margins from `plan(hw_margins_hmm=…)`, where `None` means 5.0 mm per side for the bands (cells are still not flagged without it, as today).
  - `SheetView.code_hint: str | None = None` (new last field): the probable code of a new sheet in a preview (Task 6). The planner's QR payload is `margin.scan_payload(view.code or view.code_hint)`; with neither, `payload=None` and the placement is text only.
  - `PagePlan` gains `margin_placement: MarginPlacement | None = None` and `id_not_printed: bool = False`.
  - Rule in `_draft`, replacing `:242-251`: the "due" predicate is unchanged (`id_placement == "margin"`, not `id_printed`, not `margin_id_in_flight`, not `id_done`). With a `MarginContext`: `placement = choose_margin_placement(g, hw=hw_margins_hmm, dev=margin.deviation, payload=…, dpi=margin.render_dpi)`, `margin_id = placement is not None`, `id_not_printed = placement is None`. Without one (`margin=None`): `margin_id = due`, `margin_placement = None`, `id_not_printed = False`. Nothing is raised. In `plan`, a placement whose ID was due adds the sheet to `id_done` whether it was printable or not, so the flag shows once per sheet per request. A zero-item request whose only due ID is not printable is `InvalidPlacementsError("empty")` (existing rule, since `margin_id` is false).
- Produces (`sheet_page.py`):
  - `MarginIdPayload` gains `band: MarginBand = "top"` and `corner: MarginCorner = "top_left"`; `usable_hmm` now holds the band depth (name kept, so payloads stored before this task stay valid and render in the top band exactly as today, OC-50).
  - `def margin_id_payload(text: str, qr_payload: str | None, placement: MarginPlacement) -> MarginIdPayload` — copies `band`, `corner` and `depth_hmm` (as `usable_hmm`); `qr_allowed = placement.qr and bool(qr_payload)`; `qr_payload` kept only when allowed. It never evaluates the QR rule again; `draws_qr` keeps its fallback for old payloads. Contract for Task 7: `qr_payload` is `margin.scan_payload(code)`, the string the planner decided on.
  - `_MarginLayout` gains `rotation: Literal[0, 90]`. `_margin_layout(g, margin, *, with_qr)` places by `margin.band`, with `D = usable_hmm`, `S = SAFETY_HMM`, `G = MARGIN_TEXT_GAP_HMM`, `right, bottom = remaining_margins(g)`, `grid_right = page_w − right`, `grid_bottom = page_h − bottom`:

    | Band | QR box `(x, y, D, D)` | Text start | Text room ends at | Rotation |
    |---|---|---|---|---|
    | top | `(margin_left, margin_top − S − D)` | x = `margin_left + (D + G if QR else 0)`, baseline centred in `[margin_top − S − D, margin_top − S]` (as built) | `grid_right` | 0 |
    | bottom | `(margin_left, grid_bottom + S)` | as top, centred in `[grid_bottom + S, grid_bottom + S + D]` | `grid_right` | 0 |
    | right | `(grid_right + S, margin_top)` | y = `margin_top + (D + G if QR else 0)`, baseline x = band centre `grid_right + S + D/2` − half the cap height | `grid_bottom` | 90 |
    | left | `(margin_left − S − D, margin_top)` | as right, band centre `margin_left − S − D/2` | `grid_bottom` | 90 |

    Font start size, shrinking and the ellipsis are as built (`_fit_margin_text`), measured along the text's own direction.
  - `render_sheet_page` passes `rotation` into `PageText`; `render_preview_png` draws the same layout, rendering rotated text into its own 1-bit image turned a quarter turn clockwise before pasting. Neither reads anything but the payload (OC-50).
- Produces (`pdf.py`): `PageText.rotation: Literal[0, 90] = 0` — 90 is a quarter turn **clockwise as seen on the page**, about the text origin `(x_hmm, baseline_y_hmm)`. `write_pdf` draws rotated text as save state → translate to the origin → rotate −90° (PDF y points up) → `drawString(0, 0, …)` → restore; `rotation=0` keeps today's operators unchanged.
- Produces (`reservation.py`): `ReservedPage` gains `margin_placement: MarginPlacement | None` and `id_not_printed: bool`, copied from the page plan. The `reserve` docstring's T2-1 reason reads: the margin context is required because it chooses the band; a print without it would store no band.
- Produces (`errors.py`): `MarginTooSmallError` removed; the code `margin_too_small` is retired (spec OC-49).
- Produces (create default): `SheetCreate.id_placement: Literal["margin", "manual"] = "margin"`, `create_sheet(..., id_placement: Literal["margin", "manual"] = "margin", ...)`. Task 8 adds `"cell"` to both. `pnpm gen:api`.

- [ ] **Step 1: Write the failing tests**
  - Planner, bands (`test_planner.py`; the `margin_ctx` helper becomes `margin_ctx(dev=None, dpi=600)` with `scan_payload=lambda c: f"https://hub.example/sheet/{c}"`):
    - `test_margin_bands_l4736_unknown_hw` — L4736REV, `hw=None`, identity → `{"top": 1530, "bottom": 1530, "right": 385, "left": 385}`.
    - `test_margin_bands_per_side_hw_and_calibration` — L4736REV, `Margins(top=423, left=300, bottom=600, right=450)`, `Deviation(offset_x_hmm=120, offset_y_hmm=-80)` → top `2130 − 423 − 80 − 100 = 1527`, bottom `2130 − 600 − 0 − 100 = 1430`, right `985 − 450 − 120 − 100 = 315`, left `985 − 300 − 0 − 100 = 585`; the same margins with `Deviation(offset_x_hmm=-120, offset_y_hmm=80)` → top `1607`, bottom `1350`, right `435`, left `465`; L4731REV with `Margins(423, 423, 423, 423)` and `Deviation(offset_y_hmm=-50)` → top `777` (the as-built `test_margin_usable` value), bottom `827`, right and left `337`.
    - `test_band_length` — L4736REV → top and bottom `19030`, right and left `25440`.
  - Planner, choice (`payload = "https://hub.example/sheet/<code>"`, dpi 600):
    - `test_choose_top_on_l4736_with_qr` — `hw=None`, identity → `MarginPlacement("top", "top_left", 1530, True)` (top and bottom tie, top wins by order).
    - `test_choose_bottom_when_calibration_eats_top` — `Deviation(offset_y_hmm=-80)` → `MarginPlacement("bottom", "bottom_left", 1530, True)`; `offset_y_hmm=+80` → top with depth 1530.
    - `test_choose_right_on_wide_right_margin` — synthetic A4 type `label 4000 × 2000`, `cols 4`, `rows 14`, `pitch 4600 / 2050`, `margin_top 600`, `margin_left 600`, `hw=None` → bands top 0, bottom −150, right 2000, left 0 → `MarginPlacement("right", "top_right", 2000, True)`.
    - `test_qr_band_beats_a_larger_text_only_band` — synthetic A4 type `label 6000 × 3500`, `1 × 1`, `pitch 6000 / 3500`, `margin_top 1700`, `margin_left 1000`, payload `"https://hub.example/sheet/TEST-0001"` (precondition: `margin_qr_allowed(1100, payload, 600) is True`) → bands top 1100 (QR, length 6000), bottom 23900 (length 6000 < 25100 → text), right 13400 (length 3500 → text), left 400 → `MarginPlacement("top", "top_left", 1100, True)`.
    - `test_text_only_from_four_mm` — L4736REV, `Margins(top=1630, left=500, bottom=1630, right=500)` → `MarginPlacement("top", "top_left", 400, False)`; with `top=bottom=1631` → `None` (all bands < 400).
    - `test_l4731_text_only_on_typical_laser` — L4731REV, `Margins(423, 423, 423, 423)` → `MarginPlacement("top", "top_left", 827, False)`; `Margins(300, 300, 300, 300)` (precondition `margin_qr_allowed(950, payload, 600) is True`) → `MarginPlacement("top", "top_left", 950, True)`.
    - `test_no_payload_means_text_only` — `payload=None` on L4736REV → `MarginPlacement("top", "top_left", 1530, False)`.
  - Planner, `plan` (the `TIGHT` type: A4, `label 19900 × 28600`, `1 × 1`, `margin_top 550`, `margin_left 550`; all four bands −50 at the default hardware margins):
    - `test_plan_carries_margin_placement` — new margin L4736REV view, `margin_ctx()`, `hw_margins_hmm=None` → `pages[0].margin_id is True`, `margin_placement == MarginPlacement("top", "top_left", 1530, True)`, `id_not_printed is False`.
    - `test_plan_margin_unprintable_prints_without_id` — margin `TIGHT` view, 1 item, `margin_ctx()` → no exception, `item_cells == [1]`, `margin_id is False`, `margin_placement is None`, `id_not_printed is True`; with `margin=None` → `margin_id is True`, `id_not_printed is False`.
    - `test_unprintable_flag_once_per_sheet` — one margin L4736REV view in two placements (1 item each), `hw_margins_hmm=Margins(2000, 2000, 2000, 2000)` (all bands < 400) → `[p.id_not_printed for p in pages] == [True, False]`.
    - `test_unprintable_margin_id_alone_is_empty` — `TIGHT`, `n_items=0`, `margin_ctx()` → `InvalidPlacementsError("empty")`.
    - `test_payload_code_falls_back_to_code_hint` — a recording `scan_payload`; view `code=None, code_hint="L4736-0003"` → called with `"L4736-0003"`; `code=None, code_hint=None` → not called and `margin_placement.qr is False`.
    - Removed: `test_margin_usable` (its values live on in `test_margin_bands_per_side_hw_and_calibration` and `test_margin_bands_l4736_unknown_hw`) and `test_margin_too_small_raises_only_when_an_id_is_due` (replaced by `test_plan_margin_unprintable_prints_without_id`).
  - Reservation (`test_reservation.py`; the `MARGIN` constants here and in `tests/db/test_reservation_concurrency.py` become `MarginContext(deviation=Deviation(), scan_payload=lambda c: f"sheet:{c}", render_dpi=600)`):
    - `test_reserve_carries_margin_placement` — new margin sheet of the file's `G48` type (bands top 1550, bottom 1510), `hw_margins_hmm=None` → `ReservedPage.margin_id is True`, `margin_placement.band == "top"`, `margin_placement.depth_hmm == 1550`, `id_not_printed is False`.
    - `test_margin_context_is_required_and_checked` becomes `test_margin_context_is_required_and_unprintable_reserves_without_id` — type `TIGHT` (geometry above) created through `ts.create_type(session, _fields("tight", "TIGHT"), …)` as the current test does, margin sheet, 1 item → one `reserved` row at cell 1, `margin_id is False`, `margin_placement is None`, `id_not_printed is True`; the `inspect.signature(reserve).parameters["margin"].default is inspect.Parameter.empty` assertion stays.
  - PDF (`test_pdf.py`):
    - `test_rotated_text_is_a_quarter_turn_clockwise` — `PageText(5000, 6000, 8.0, "L4736-0001", rotation=90)` on A4, `compress=False` → `inspect.texts == ["L4736-0001"]`; `inspect.cm_matrices` contains a matrix ≈ `(0, −1, 1, 0, 0, 0)` (abs 1e-6); `inspect.text_positions[0] ≈ (50.0 × PT_PER_MM, (297.0 − 60.0) × PT_PER_MM)`.
    - `test_unrotated_text_has_no_extra_matrix` — the same text with `rotation` left out, `compress=False` → `inspect.cm_matrices(pdf) == []` and `text_positions[0] ≈ (141.732, 671.811)` (checked against `55e5181`: today's output for that page).
  - Sheet page (`test_sheet_page.py`; `k = PT_PER_MM / 100`; the existing top-band tests stay green unchanged, because a payload without `band` is top):
    - `test_margin_id_payload_takes_planner_decision` — `margin_id_payload("X", "https://h/sheet/L4736-0001", MarginPlacement("bottom", "bottom_left", 1530, False))` → `qr_payload is None`, `qr_allowed is False`, `band == "bottom"`, `corner == "bottom_left"`, `usable_hmm == 1530`; with `qr=True` → payload kept, `qr_allowed is True`.
    - `test_margin_id_bottom_band_geometry` — L4736REV, payload `band="bottom"`, `usable_hmm=1530`, `qr_allowed=True` → QR `cm == (1530k, 0, 0, 1530k, 985k, (29700 − 29200)k)` (abs 1e-3); text origin x > `(985 + 1530) / 100` mm and its y (from the top, in mm) inside `(276.70, 292.00)`.
    - `test_margin_id_right_band_rotated` — the `test_choose_right_on_wide_right_margin` geometry, `band="right"`, `corner="top_right"`, `usable_hmm=2000`, `qr_allowed=True` → QR `cm == (2000k, 0, 0, 2000k, 18500k, (29700 − 600 − 2000)k)`; a rotation `cm` ≈ `(0, −1, 1, 0, 0, 0)`; text origin x in `(185.0, 205.0)` mm and y from the top `≈ 28.0` mm (`600 + 2000 + 200` hmm).
    - `test_margin_id_left_band_text_only` — L4736REV, `band="left"`, `usable_hmm=585`, no QR → one rotated text; origin x in `(3.0, 8.85)` mm, y from the top `≈ 21.3` mm.
    - `test_stored_band_wins` — L4736REV, where top and bottom are equally deep, payload `band="bottom"` → the QR is at the bottom position; the renderer reads no hardware margins and makes no choice.
    - `test_preview_draws_stored_band` — `render_preview_png(L4736, [], <bottom payload>)` → ink bounding box rows within `[round(27670 × 150 / 2540) − 1, round(29200 × 150 / 2540) + 1]`; right-band payload on the right-band geometry → ink columns within `[round(18500 × 150 / 2540) − 1, round(20500 × 150 / 2540) + 1]`.
  - API (`test_sheets_api.py`): `test_create_sheet_defaults_to_margin` — `POST /api/sheets {"type": "acme-t1"}` → 201, `id_placement == "margin"`, `id_printed is False`. The existing `{"type": "acme-t1", "id_placement": "cell"}` → 422 case stays until Task 8.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Remove `MarginTooSmallError` and every import of it; grep `margin_too_small`, `MarginTooSmallError`, `margin_usable_hmm`, `hw_top_hmm`, `DEFAULT_HW_TOP_HMM` and `_TEXT_GAP_HMM` afterwards — none may remain in `backend/app` or `backend/tests`. Module docstrings of `planner.py` and `sheet_page.py` name the four bands instead of "the top margin". `pnpm gen:api`.
- [ ] **Step 4: Run, expect PASS** — `pytest tests/unit/sheets tests/unit/page_render tests/db/test_reservation_concurrency.py tests/integration/api/test_sheets_api.py -v`, then `pytest -m "not slow"`, `mypy app/`, `ruff check . && ruff format --check .`, `cd frontend && pnpm typecheck`.
- **Counter-checks** (each one, alone, must turn the named test red for the stated reason; revert afterwards):
  - drop `not qr` from the sort key → `test_qr_band_beats_a_larger_text_only_band` picks bottom;
  - order `("bottom", "top", …)` → `test_choose_top_on_l4736_with_qr` picks bottom;
  - any side without its calibration term (for example bottom without `max(0, dev.offset_y_hmm)`) → `test_margin_bands_per_side_hw_and_calibration` (its second case: bottom `1430` instead of `1350`);
  - unknown hardware margin counted as 0 instead of 500 → `test_margin_bands_l4736_unknown_hw`;
  - drop the length rule → `test_qr_band_beats_a_larger_text_only_band` picks bottom with a QR;
  - raise when no band fits → `test_plan_margin_unprintable_prints_without_id`;
  - add the sheet to `id_done` only when printable → `test_unprintable_flag_once_per_sheet`;
  - `_margin_layout` ignoring `band` (always top) → `test_margin_id_bottom_band_geometry`, `test_margin_id_right_band_rotated`, `test_stored_band_wins`;
  - `margin_id_payload` deciding the QR again with `margin_qr_allowed` instead of copying `placement.qr` → `test_margin_id_payload_takes_planner_decision` (its `qr=False` case with a payload that would fit);
  - `write_pdf` ignoring `rotation` → `test_rotated_text_is_a_quarter_turn_clockwise`;
  - remove the `"margin"` default from `SheetCreate` → `test_create_sheet_defaults_to_margin` (422).
- [ ] **Step 5: Commit** — `git add backend/app/sheets/planner.py backend/app/sheets/sheet_page.py backend/app/page_render/pdf.py backend/app/sheets/reservation.py backend/app/sheets/errors.py backend/app/schemas/sheets.py backend/app/sheets/sheet_service.py frontend/src/api/schema.gen.ts backend/tests/unit/sheets/test_planner.py backend/tests/unit/sheets/test_sheet_page.py backend/tests/unit/sheets/test_reservation.py backend/tests/db/test_reservation_concurrency.py backend/tests/unit/page_render/test_pdf.py backend/tests/integration/api/test_sheets_api.py && git commit -m "feat(api): sheet ID in the best margin band by default"`

---

### Task 6: Sheet print service — item resolution and preview

**Files:**
- Create: `backend/app/sheets/print_service.py`, `backend/app/schemas/sheet_print.py`, `backend/app/api/routes/sheet_print.py`
- Modify: `backend/app/sheets/errors.py` (`ItemLookupFailedError`, `PreviewTooLargeError`), `backend/app/main.py`, `backend/tests/api/test_openapi_completeness.py`, `frontend/src/api/schema.gen.ts`
- Test: `backend/tests/unit/sheets/test_print_service_preview.py`, `backend/tests/integration/api/test_sheet_preview_api.py`

**Interfaces:**
- Consumes: Tasks 1, 2, 4, 5b; `AppLookupService.lookup(app, identifier) -> LabelData` (existing), `LookupFailedError`, `UnknownAppError`; Plan 2 status cache (`summary`, margins, resolutions), calibration `snapshot`.
- Produces (`schemas/sheet_print.py`):
  - `SheetItem(PrintRequest-like: content_type, data | lookup, purpose: str | None = Field(max_length=120), source: str | None, ref: str | None = Field(max_length=120))` — reuses `RawLabelData` and `PrintLookupRequest`; `options` not accepted.
  - `PlacementOut` / `PlacementInModel` (either `{sheet: code, cells: "first_free" | list[int], skip?: list[int] ≤ 400, count?: int ≥ 1}` or `{new_sheet: {type, version?, id_placement: Literal["cell","margin","manual"] = "margin"}, count?}`, exactly one of `sheet`/`new_sheet`; the default is spec 15 as changed 2026-11-07).
  - `SheetPrintRequest(items: list[SheetItem] = Field(min_length=1, max_length=500), placements: list[PlacementInModel] = Field(min_length=1, max_length=50), tray: str | None, expected_cells: list[ExpectedPageModel] | None = Field(default=None, max_length=50))` (each `ExpectedPageModel.cells` ≤ 400).
  - `SheetPreview(pages: list[PreviewPage], free_after: list[int], expected_cells: list[ExpectedPageModel], reprint_hints: list[ReprintHint])`; `PreviewPage(sheet_code: str | None, new_code_hint: str | None, type_key, version, geometry: GeometryMm, cells: list[PreviewCell], png_base64: str, margin_id: bool, margin_band: Literal["top","bottom","right","left"] | None, id_not_printed: bool, load_hint: str | None)` (`margin_band`/`id_not_printed` from `PagePlan.margin_placement`/`id_not_printed`, Task 5b; *added 2026-11-07*); `PreviewCell(cell, state: Literal["used","reserved","unconfirmed","new","free"], is_id: bool, purpose: str | None, item_index: int | None, truncated: bool, mapped: bool, hw_margin: bool)`; `ReprintHint(item_index, sheet_code, cell, printed_at)`.
- Produces (`print_service.py`):
  - `async def resolve_items(items: Sequence[SheetItem], lookup: AppLookupService) -> list[ResolvedItem]` (`label: LabelData`, `content_type`, `meta: ItemMeta`) — lookups run **before** any write and outside the lock; the first failure → `ItemLookupFailedError` (422 or 502 per existing mapping, detail `{"item_index": i}`).
  - `async def preview(session, *, printer: Printer, request: SheetPrintRequest, lookup, renderer) -> SheetPreview` — page printer only (`MediaKindMismatchError`), tray resolved (default if omitted, `TrayUnknownError` if unknown/disabled); builds `SheetView`s (Plan 1 repository + `margin_id_in_flight`; a new sheet's view carries `code_hint = new_code_hint`, Task 5b), runs `plan` with `MarginContext(deviation=<snapshot of the tray>, scan_payload=…, render_dpi=<the job's render dpi, never 150>)` and the printer's `margins_hmm` (no write; new sheets get `new_code_hint` from `peek_next_code`), draws the margin ID with `margin_id_payload(text, scan_payload(code), page.margin_placement)` and `render_preview_png(..., render_dpi=<the job's render dpi>)`, renders the new cells in a thread at **150 dpi**, `reprint_hints` from `find_cells(source, ref)` for lookup items. Calibration is not applied. Load bound (spec 18 "CPU"; preview needs only `read`): a preview plans all pages but renders PNGs for at most **10** pages — a plan with more pages answers `422 preview_too_large` (`PreviewTooLargeError`, detail `{"pages": n, "max": 10}`); lookups run with at most 8 in flight. *(Plan decision; the spec sets no number.)*
- Route: `POST /api/print/{printer_key}/sheet/preview` (read + `check_printer_access`).
- [ ] **Step 1: Write the failing tests**
  - `test_preview_plan_and_png` — 9 Grocy items (fake lookup) on a sheet with 17 used → 9 `new` cells 18–26, `free_after == [22]`, `png_base64` decodes to a 1240 × 1754 1-bit PNG.
  - `test_preview_marks_mapped_cells` — `qr_two_lines` on L4731REV → `mapped=True` (acceptance 21, preview side).
  - `test_preview_has_no_side_effects` — row counts of `sheets`, `sheet_cells`, `sheet_id_counters`, `jobs` unchanged.
  - `test_preview_reprint_hint` — item `grocy/42` printed before on `L4736-0002` cell 5 → hint.
  - `test_preview_new_sheet_hint` — `new_sheet` → `new_code_hint == "L4736-0003"` and an ID cell `is_id=True` when `id_placement="cell"`; `new_sheet` without `id_placement` → no ID cell, `margin_id=True`, `margin_band == "top"` (default `margin`, *added 2026-11-07*).
  - `test_preview_margin_band_and_unprintable` — a margin sheet on a printer with `margins_hmm=None` → `margin_band == "top"`; with `Margins(2000, 2000, 2000, 2000)` → `margin_band is None`, `id_not_printed is True`, no `422`. *(Added 2026-11-07.)*
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
- Consumes: Tasks 3–6 and 5b; Plan 2 `PrintQueue.submit_page_job`, `PagePayload`, calibration `snapshot`; `print_batches` repository.
- Produces:
  - `SheetPrintResponse(batch_id: UUID, pages: list[PrintedPage])`, `PrintedPage(job_id, sheet_code, cells: list[int], id_cell: int | None, margin_id: bool, margin_band: Literal["top","bottom","right","left"] | None, id_not_printed: bool)` (*fields added 2026-11-07*).
  - `async def print_sheets(session_factory, *, printer, request, lookup, queue, actor, api_key_id, source_ip) -> SheetPrintResponse` — order: resolve items → validate printer kind and tray → `reserve(...)` (expected cells honoured) → for each page build `PagePayload(kind="sheet_page", media=geometry.page_size, tray, render_dpi, job_name="Sheet <code> · <n> labels", calibration=await calibration_service.snapshot(session, printer.id, tray), detail=SheetPageDetail)` and `queue.submit_page_job(..., job_id=page.job_id)`; `reserve` gets `MarginContext(deviation=snapshot_to_deviation(<that snapshot>), scan_payload=…, render_dpi=<that render_dpi>)` and the printer's `margins_hmm`, so the snapshot is taken **before** the reservation (pre-flight finding C12); `detail.margin_id = margin_id_payload(<code and type text>, margin.scan_payload(page.sheet_code), page.margin_placement)` when `page.margin_placement` is set, else `None`; a submission failure releases that page's reservation and every later page's (pages already submitted stay); one `print_batches` row with all job ids; `job_name` carries no personal data.
  - Purposes sanitised per Global Constraints.
- Route: `POST /api/print/{printer_key}/sheet` (print + printer access), `202`.
- [ ] **Step 1: Write the failing tests**
  - `test_print_end_to_end_cells_used` — fake printer script `[3, 5, 9]`; 9 items onto a sheet with 17 used → response cells 18–26; after the job completes `GET /api/sheets/{code}` shows 26 used with purposes (acceptance 1); the fake received one PDF with `media-type=labels` and `print-scaling=none`.
  - `test_print_two_sheets_one_batch` — 60 items, placements `[existing (31 free), new]` → two jobs, one batch, page 1 completes while page 2 is aborted before start → page 1 cells used, page 2 cells free.
  - `test_print_after_type_edit_uses_v1` — sheet on v1, type edited to v2 (different pitch), print → PDF positions from v1 (acceptance 9).
  - `test_expected_cells_mismatch` → 409 `plan_changed` with the new plan (acceptance 13).
  - `test_insufficient_over_http` → 409 `insufficient_cells` with `free_cells` (acceptance 3).
  - `test_qr_mapped_on_small_type_printed_as_text` (acceptance 21, print side: payload content types are text types).
  - `test_print_margin_id_in_stored_band` — calibration `dy = −0.8 mm` on L4736REV → `detail.margin_id.band == "bottom"`, `PrintedPage.margin_band == "bottom"`; after completion `id_printed=True`. *(Added 2026-11-07.)*
  - `test_print_without_room_prints_without_id` — printer `margins_hmm = Margins(2000, 2000, 2000, 2000)`, margin sheet, 3 items → `202`, `detail.margin_id is None`, `PrintedPage.id_not_printed is True`, 3 cells reserved and no ID cell; after completion `id_printed` stays false (acceptance 7). *(Added 2026-11-07.)*
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

### Task 8: Sheet ID on creation (explicit cell option) and the margin check

**Files:**
- Modify: `backend/app/sheets/sheet_service.py`, `backend/app/schemas/sheets.py`, `backend/app/api/routes/sheets.py`, `backend/app/sheets/print_service.py`, `frontend/src/api/schema.gen.ts`
- Test: `backend/tests/integration/api/test_sheet_id_label.py`

**Interfaces:**
- Consumes: Tasks 3, 5, 7.
- Produces: `SheetCreate.id_placement: Literal["cell","margin","manual"] = "margin"` (the default is Task 5b's; this task adds `"cell"`) plus `printer: str | None`, `tray: str | None`. `cell` is used only when sent; it requires a page printer (print scope + printer access) and creates the sheet, reserves the ID cell (first free after the hand-marked cells) and submits an ID-only `sheet_page` job in the same request; the response gains `job_id: UUID | None`. `margin` (also when left out) is never refused: with or without a printer the sheet is stored, and the margin ID is placed by the job that prints first (Task 5b). `GET /api/sheets/margin-check?type=&printer=&tray=` (read + printer access) → `{bands_mm: {top, bottom, right, left}, band: "top" | "bottom" | "right" | "left" | null, corner: str | null, usable_mm: float | null, qr: bool, printable: bool, reason: str | null}` from `margin_bands_hmm` and `choose_margin_placement` with the printer's `margins_hmm`, the tray's calibration and the printer's render dpi; `printable=false` with `reason` "no margin band is 4 mm deep on this printer" when the choice is `None`. The UI shows the band, or the "add it by hand" hint, next to the margin radio (spec 17.1). *(Plan decision: the spec's API table has no endpoint that tells the UI where the margin ID would go on a printer; this read-only route adds it. It is declared before `/{code}`; the code pattern cannot match it anyway. Changed 2026-11-07: was `{usable_mm, qr, allowed, reason}` for a top-only margin that could be refused.)*
- [ ] **Step 1: Write the failing tests**
  - `test_create_cell_queues_id_label` — L4736REV with 5 hand-marked cells and `id_placement="cell"` sent → ID cell 6 reserved `source="hub"`, job printed by the fake → cell 6 used, `id_printed=True` (acceptance 6); the PDF's ID cell is `qr_two_lines` with payload `<public_url>/sheet/L4736-0001`; on L4731REV the ID cell is text only.
  - `test_id_job_clean_failure_then_next_job_carries_id` — ID-only job aborted before start → cell 6 free, `id_printed=False`; next print onto the sheet reserves an ID cell at its first free cell (OC-40).
  - `test_margin_only_first_completed_job` — margin sheet: job 1 completes → `id_printed`; job 2 payload has no `margin_id`; a fresh margin sheet whose first job fails cleanly → the next job draws the margin ID again (acceptance 7).
  - `test_create_without_placement_is_margin_and_queues_nothing` — `POST /api/sheets {"type": …, "printer": …}` → `id_placement == "margin"`, `job_id is None`, no cell reserved. *(Added 2026-11-07.)*
  - `test_margin_never_refused` (replaces `test_margin_too_small`) — L4731REV on a printer reporting `Margins(1000, 1000, 1000, 1000)` (bands 250 / 250 / −240 / −240) → create with `margin` and the printer → `201`; `margin-check` → `printable=false`, `band=null`, `reason` set, `bands_mm == {top: 2.5, bottom: 2.5, right: -2.4, left: -2.4}`; on a printer without reported margins → `band="top"`, `usable_mm=7.5`, `qr=false`, `printable=true`. *(Changed 2026-11-07.)*
  - `test_scan_payload_short_form_without_public_url`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**; `pnpm gen:api`.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add backend/app/sheets/sheet_service.py backend/app/schemas/sheets.py backend/app/api/routes/sheets.py backend/app/sheets/print_service.py backend/tests/integration/api/test_sheet_id_label.py frontend/src/api/schema.gen.ts && git commit -m "feat(api): sheet ID label in the first free cell on request, margin check"`

---

### Task 9: Retry of page jobs

**Files:**
- Modify: `backend/app/api/routes/jobs.py` (after #184 the retry route enqueues through the queue; Plan 2 Task 7 refuses `sheet_page` there with `409 job_not_retryable` — this task replaces that refusal with `retry_sheet_page`), `backend/app/sheets/print_service.py`, `backend/app/sheets/errors.py`
- Test: `backend/tests/integration/api/test_page_job_retry.py`

**Interfaces:**
- Consumes: Tasks 3, 5, 7; Plan 2 `calibration_service.snapshot(session, printer_id, tray)`; the #184 retry route.
- Produces: `async def retry_sheet_page(session_factory, queue, job: DbJob, *, actor) -> UUID` — allowed for a `sheet_page` job in `failed` or `cancelled` with **no** `unconfirmed` cell still pointing at it (OC-42); re-reserves exactly the job's cells (`detail.cells` + `id_cell`) for a new job id, refusing `409 cells_taken` with the cell numbers if any is no longer free; fresh calibration snapshot; the margin ID re-decided with `choose_margin_placement` (Task 5b) for the retry's printer, tray, calibration and render dpi when it is still due (`margin_id_in_flight` and `id_printed` read inside the lock), stored as a new `margin_id_payload` (the old job's band is not reused, since the printer may differ); the new job goes to `queue.submit_page_job` at once (the #184 route never writes a bare `queued` row for page jobs). `done` → `409 job_not_retryable`; a job with unconfirmed cells → `409 cells_unconfirmed` (`CellsUnconfirmedError`). `calibration_page` retry stays as Plan 2 Task 7 built it. Tape retry unchanged (#184).
- [ ] **Step 1: Write the failing tests** (through `POST /api/jobs/{id}/retry`, fake printer) — clean failure → retry reserves the same cells (and, on a margin sheet whose first job failed, carries a margin ID with a band again) and the fake receives the new PDF without a restart; cells taken meanwhile → `cells_taken` with numbers; interrupted job with unconfirmed cells → `cells_unconfirmed`; after resolving them `not_printed` → retry allowed; `done` → `job_not_retryable`; tape retry regression test green.
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

## Plan amendment 2026-11-07

Operator decision of 2026-11-07: the sheet ID goes into the sheet's free margin by default, in the band where name and QR fit largest, and never uses up a label cell unless `cell` is chosen. Spec requirement 17, sections 7, 10.1, 10.2, 15, 17.1, 17.4, acceptance 6 and 7, and OC-16, OC-40, OC-45 to OC-51 were changed with it. Changes to this plan:

- **Global Constraints:** the margin-ID bullet now states the four-band rule, the default `margin`, the unprintable case and the stored decision; `422 margin_too_small` is gone.
- **Review Focus:** item 6 added (band choice, stored decision, unprintable sheet), owner Task 5b.
- **File Structure:** `backend/app/page_render/pdf.py` added (rotated text); the `sheet_page.py` row names the stored band.
- **Tasks 2 and 4:** a note that they are done as written and that Task 5b replaces their margin rule; their text is left as built.
- **Task 5b (new):** `margin_bands_hmm`, `band_length_hmm`, `MarginPlacement`, `choose_margin_placement`; `MarginContext` loses `hw_top_hmm` and gains `render_dpi`; `SheetView.code_hint`; `PagePlan` and `ReservedPage` gain `margin_placement` and `id_not_printed`; `MarginIdPayload` gains `band` and `corner`; `margin_id_payload` takes a `MarginPlacement`; `PageText.rotation`; `MarginTooSmallError` and `margin_usable_hmm` removed; `SheetCreate` and `create_sheet` default to `margin`.
- **Task 6:** `new_sheet.id_placement` defaults to `margin`; the preview passes `code_hint`, a `MarginContext` with the job's render dpi and the printer's margins; `PreviewPage` gains `margin_band` and `id_not_printed`; new test `test_preview_margin_band_and_unprintable`, `test_preview_new_sheet_hint` extended.
- **Task 7:** the calibration snapshot is taken before `reserve` so the margin context can carry it; `detail.margin_id` is built from `page.margin_placement`; `PrintedPage` gains `margin_band` and `id_not_printed`; new tests `test_print_margin_id_in_stored_band` and `test_print_without_room_prints_without_id`.
- **Task 8:** retitled; `cell` only when sent; `margin` is never refused; `margin-check` answers bands, the chosen band and `printable`; `test_margin_too_small` replaced by `test_margin_never_refused`; new test `test_create_without_placement_is_margin_and_queues_nothing`; commit message adjusted.
- **Task 9:** a retried page job re-decides the margin band with `choose_margin_placement` instead of reusing the old one.
- **Not changed:** Task 5 (in progress). Its `id_printed` rule (set when the completed job's `detail.margin_id` is present) already gives "stays false when printed without the ID", because such a page stores `margin_id = None`. `margin_id_in_flight` (Task 3) is unchanged for the same reason.
