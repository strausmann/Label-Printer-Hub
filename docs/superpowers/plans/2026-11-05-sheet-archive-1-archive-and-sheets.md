# Sheet archive, Plan 1 of 4: archive, seed, physical sheets and their API

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The hub stores sheet types with versioned geometry, ships 38 seed types, records physical sheets with their non-free cells, and exposes all of it over a REST API — without printing anything yet.

**Architecture:** A new `app/sheets/` package holds the pure geometry core, the type and sheet services and the export/import format; SQLModel tables and one Alembic migration add six tables (five from the spec plus a one-row write lock); two routers (`sheet_types`, `sheets`) expose them. Sheet writes are serialised through a one-row write-lock table so the parallel guarantees of Plan 3 (reservations) rest on a mechanism this plan already proves.

**Tech Stack:** Python 3.12, FastAPI, SQLModel/SQLAlchemy async on SQLite (aiosqlite, WAL), Alembic, Pydantic v2, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-11-05-sheet-archive-design.md` (sections 5–10, 15, 16, 19, 25). Read it with this plan.

**Plan series (order is binding).** Part A is split into four plans, because one plan would carry ~40 tasks and two unrelated failure domains (database bookkeeping vs. a network protocol). Each plan ends with software that runs and is tested on its own:

1. **This plan** — archive, seed, sheets, cells, API (no printing; `id_placement` `manual` and `margin` only).
2. `2026-11-05-sheet-archive-2-ipp-and-calibration.md` — IPP page-printer backend, PDF writer, page jobs in the queue, manual calibration with the calibration page, capabilities.
3. `2026-11-05-sheet-archive-3-sheet-printing.md` — cell renderer, planner and reservations, preview, sheet print, ID label/margin ID, retry. Needs 1 and 2.
4. `2026-11-05-sheet-archive-4-ui.md` — all screens, feature flags on, browser tests. Needs 1–3.

## Global Constraints

- Python `>=3.12`; `mypy --strict app/` and `ruff check .` / `ruff format --check .` (line length 100) stay green; `logging`, never `print()`; `httpx`, never `requests`.
- Single container, single process (ADR 0015); no new dependency in this plan.
- SQLite + Alembic. This plan adds exactly one migration, revision `20261105a1`, `down_revision = "20261104a3"`, file `backend/alembic/versions/2026_11_05_0001-20261105a1_sheet_archive.py`. `tests/db/test_alembic_consistency.py::test_no_pending_autogenerate_diff` stays green.
- All lengths stored as **integer hundredths of a millimetre**; the API speaks millimetres with **at most two decimals** (OC-4, label `D16`). More decimals → `422 invalid_geometry`.
- Page sizes `A4` (21000 × 29700) and `Letter` (21590 × 27940) only (OC-1).
- Key pattern `^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$`; prefix pattern `^[A-Z][A-Z0-9]{1,9}$`; client source tag pattern `^[a-z][a-z0-9_-]{0,31}$`; purpose ≤ 120 characters, plain text.
- `cols × rows ≤ 400` (OC-7); `round` requires `label_w == label_h`, corner radius ignored (OC-6).
- Sheet code = `prefix` + `-` + counter zero-padded to at least 2 digits (`L4736-02`, `L4736-100`); counters never decrease, never reset, survive archive (spec 7.1).
- Scopes (OC-11, OC-37): reads `read` (no printer restriction applies to sheets/types); sheet-type writes `admin`; sheet writes `print`.
- Errors use the existing shape `HTTPException(status, detail={"error_code", "error_message", "error_detail"})`; messages are fixed English text, never echo raw input beyond identifiers.
- Every new route carries a `require_read` / `require_print` / `require_admin` dependency so `tests/unit/api/test_route_auth_coverage_guardrail.py` passes without allowlist entries; `tests/api/test_openapi_completeness.py::test_endpoint_count_in_range` upper bound is raised by the number of routes added.
- Any task that changes the API regenerates `frontend/src/api/schema.gen.ts` (`cd frontend && pnpm gen:api`) and commits it with the change (CI checks it).
- Coverage: backend `pytest --cov-fail-under=80` (project) and Codecov patch ≥ 80 %. Mutation modules of this plan (`app/sheets/*_service.py`, `app/sheets/exchange.py`) target ≥ 85 %.
- English prose everywhere; no hostnames, IPs, serials or captures (`docs/policies/privacy.md`); vendor names only to identify a sheet ("for Avery Zweckform L4731REV", `docs/policies/trademarks.md`).
- Decision labels: code that exists because of a decision carries a `# D13` / `# D14` / `# D16` comment; rows added to `docs/decisions/register.md` in Task 2 (`tests/unit/test_decision_register.py` enforces it).
- Conventional Commits, scopes from `commitlint.config.cjs` (`api`, `events`, `decisions`, `docs`, `config`); explicit `git add <paths>`; no AI attribution trailers or footers.
- Every test step below is written first and must fail for the stated reason before the implementation step (TDD). Every mutation (DB write) has a happy path, an error path and — where a network or lock is involved — a contention path.

## Review Focus

1. **Type geometry changes while sheets are in use.** A sheet created under version 1 keeps version-1 cell positions and cell count after version 2 changes `cols`; cells marked under v1 stay valid. Owner: Task 3 (`test_new_version_does_not_move_existing_sheets`) and Task 6 (`test_mark_uses_pinned_version_cell_count`).
2. **Broken or hostile import JSON.** 64 KB + 1 byte, unknown fields, nested depth bombs, `NaN`/`Infinity`, negative or 3-decimal lengths, a `format_version` of 2, a `key` that matches but a different prefix, non-object top level — all answer `4xx` with a fixed message and write nothing. Owner: Task 4 (`test_import_rejects_*` table).
3. **Two sheets created at the same moment for the same prefix.** Never the same code, never a gap reused after a discard. Owner: Task 6 (`test_parallel_create_gives_distinct_codes`, `test_discarded_code_never_reissued_after_archive_cycle`).
4. **Marking cells by hand that another request is marking at the same time, or that are already non-free.** One wins, the other gets `409 cells_taken` with the cell numbers; nothing half-written. Owner: Task 6 (`test_parallel_mark_same_cell_one_conflict`).
5. **Seed loaded into a database where a seed type was edited locally, or where its prefix was taken by a custom type.** Local edits are never overwritten; the prefix collision is logged and that one seed type skipped, startup continues. Owner: Task 5 (`test_seeder_skips_on_prefix_taken`, `test_seeder_leaves_edited_type_alone`).

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/sheets/__init__.py` | package marker |
| `backend/app/sheets/geometry.py` | `Geometry` value object, mm ↔ hundredths, validation, hash, cell numbering (pure) |
| `backend/app/sheets/naming.py` | key/prefix derivation, default `allow_qr` (pure) |
| `backend/app/sheets/errors.py` | `SheetApiError` and its subclasses with `error_code` and HTTP status |
| `backend/app/models/sheet.py` | tables `sheet_types`, `sheet_type_versions`, `sheet_id_counters`, `sheets`, `sheet_cells`, `sheet_write_lock` |
| `backend/alembic/versions/2026_11_05_0001-20261105a1_sheet_archive.py` | the migration |
| `backend/app/repositories/sheet_types.py`, `backend/app/repositories/sheets.py` | queries |
| `backend/app/sheets/locking.py` | `acquire_sheet_write_lock(session)` |
| `backend/app/sheets/type_service.py` | create, patch, new version, archive, unarchive, delete |
| `backend/app/sheets/exchange.py` | export document model, import with modes |
| `backend/app/sheets/sheet_service.py` | create sheet, next code, mark/unmark/resolve, discard, list, lookup, cell lookup |
| `backend/app/sheets/events.py` | `sheet.updated` publisher on channel `sheets` |
| `backend/app/seed/sheet_types.json` | 38 seed documents + `seed_revision` |
| `backend/app/seed/sheet_seed.py` | startup seeder |
| `backend/app/schemas/sheets.py` | request/response models (mm floats) |
| `backend/app/api/routes/sheet_types.py`, `backend/app/api/routes/sheets.py` | routers |
| `THIRD_PARTY_NOTICES.md`, `docs/decisions/register.md` | notices, labels |

Tests mirror this under `backend/tests/unit/sheets/`, `backend/tests/unit/seed/`, `backend/tests/db/`, `backend/tests/integration/api/`.

---

### Task 1: Geometry core and naming rules

**Files:**
- Create: `backend/app/sheets/__init__.py`, `backend/app/sheets/geometry.py`, `backend/app/sheets/naming.py`, `backend/app/sheets/errors.py`
- Test: `backend/tests/unit/sheets/test_geometry.py`, `backend/tests/unit/sheets/test_naming.py`

**Interfaces:**
- Produces (`geometry.py`):
  - `PAGE_SIZES: dict[str, tuple[int, int]] = {"A4": (21000, 29700), "Letter": (21590, 27940)}`
  - `MAX_CELLS = 400`
  - `def mm_to_hmm(value: float | int | str | Decimal, *, field: str) -> int` — via `Decimal(str(value))`; non-finite, negative or more than 2 decimals raise `InvalidGeometryError(field, reason)`.
  - `def hmm_to_mm(value: int) -> float` — `value / 100`, exact to 2 decimals.
  - `@dataclass(frozen=True) class Geometry` with fields `page_size: Literal["A4","Letter"]`, `page_w, page_h, label_w, label_h, cols, rows, pitch_x, pitch_y, margin_top, margin_left: int`, `corner_radius: int | None`, `shape: Literal["rectangle","round"]`.
  - `def normalise(g: Geometry) -> Geometry` — `round` → `corner_radius=None`; page_w/page_h set from `PAGE_SIZES`.
  - `def validate_geometry(g: Geometry) -> list[str]` — raises `InvalidGeometryError` on rule failure; returns hint codes (`"margins_asymmetric_x"`, `"margins_asymmetric_y"`) when the remaining right/bottom margin differs from left/top by more than 0.5 mm.
  - `def geometry_hash(g: Geometry) -> str` — sha256 hex of `json.dumps(asdict(normalise(g)), sort_keys=True, separators=(",", ":"))`.
  - `def cell_count(g: Geometry) -> int`; `def cell_origin(g: Geometry, n: int) -> tuple[int, int]` (raises `CellOutOfRangeError`); `def remaining_margins(g: Geometry) -> tuple[int, int]`.
- Produces (`naming.py`): `def derive_prefix(vendor: str, first_code: str) -> str`, `def derive_key(vendor: str, first_code: str) -> str`, `def default_allow_qr(g: Geometry) -> bool` (shorter label side ≥ 1500, OC-28).
- Produces (`errors.py`): `class SheetApiError(Exception)` with `status: int`, `error_code: str`, `message: str`, `detail: dict[str, Any] | None`, and `def to_http(self) -> HTTPException`. Subclasses (one per code of spec 15 that this plan raises): `SheetTypeNotFoundError` 404 `sheet_type_not_found`, `SheetTypeArchivedError` 409, `TypeExistsError` 409 `type_exists`, `PrefixTakenError` 409, `InvalidGeometryError` 422, `SheetNotFoundError` 404, `SheetDiscardedError` 409, `SheetBusyError` 409, `CellsTakenError` 409 (detail `{"cells": [...]}`), `CellOutOfRangeError` 422 (detail `{"cells": [...], "max": N}`). Plans 2–3 add their own subclasses here.

- [ ] **Step 1: Write the failing tests**

`test_geometry.py`:
- `test_mm_to_hmm_two_decimals` — `mm_to_hmm(9.85, field="margin_left") == 985`, `mm_to_hmm("21.2", ...) == 2120`.
- `test_mm_to_hmm_rejects` — parametrised `[9.855, -1, float("nan"), float("inf"), "x"]` → `InvalidGeometryError` with `.detail["field"] == "margin_left"`.
- `test_l4736rev_valid_and_symmetric` — geometry `A4, 4570×2120, 4×12, pitch 4820/2120, top 2130, left 985, radius None` → `validate_geometry(...) == []`, `remaining_margins == (985, 2130)`, `cell_count == 48`.
- `test_l4731rev_valid` — `2540×1000, 7×27, 2790/1000, top 1350, left 860, radius 150` → valid, `cell_count == 189`, `remaining_margins == (860, 1350)`.
- `test_cell_origin_row_major` — on L4736REV `cell_origin(g, 1) == (985, 2130)`, `cell_origin(g, 9) == (985, 6370)`, `cell_origin(g, 48) == (985 + 3*4820, 2130 + 11*2120)`; `cell_origin(g, 0)` and `(g, 49)` raise `CellOutOfRangeError`.
- `test_validation_rules` — parametrised, each raises `InvalidGeometryError` naming the field: `pitch_x < label_w`, `pitch_y < label_h`, `cols = 0`, `21×20 = 420 cells`, grid wider than page (`margin_left + (cols-1)*pitch_x + label_w > page_w`), grid taller than page, `round` with `label_w != label_h`, page_w not matching `PAGE_SIZES`.
- `test_asymmetric_margins_are_hints_not_errors` — gLabels Avery 7160 values (`6399×3810, 3×7, 6604/3810, top 1549, left 748, radius 176`) → returns `["margins_asymmetric_x"]`.
- `test_geometry_hash_canonical` — `geometry_hash(l4736) == sha256('{"cols":4,"corner_radius":null,"label_h":2120,"label_w":4570,"margin_left":985,"margin_top":2130,"page_h":29700,"page_size":"A4","page_w":21000,"pitch_x":4820,"pitch_y":2120,"rows":12,"shape":"rectangle"}')`.
- `test_hash_ignores_radius_on_round` — two `round` geometries differing only in `corner_radius` hash equal; two `rectangle` ones do not.

`test_naming.py`:
- `test_derive_prefix` — `("Avery Zweckform", "L4731REV-25") → "L4731"`, `("Avery Zweckform", "L4736REV-25") → "L4736"`, `("Herma", "4097") → "H4097"`, `("Avery", "5160") → "A5160"`, `("Endisch", "6500040x") → "E6500040X"`, `("Herma", "10001") → "H10001"`.
- `test_derive_key` — `("Avery Zweckform", "L4731REV-25") → "avery-zweckform-l4731rev"`, `("Herma", "4097") → "herma-4097"`, result matches the key pattern.
- `test_default_allow_qr` — L4736REV → `True`, L4731REV → `False`, a 1500 × 3000 label → `True`.

- [ ] **Step 2: Run, expect FAIL** — `cd backend && pytest tests/unit/sheets -v` → `ModuleNotFoundError: app.sheets`.

- [ ] **Step 3: Implement** the three modules with the signatures above. Prefix rule (spec 9.4): strip a trailing `-<digits>` pack suffix, then a trailing `REV`, drop non-alphanumerics, uppercase; if the result starts with a digit, prepend the vendor's first letter uppercased; longer than 10 characters → `ValueError` (resolved by hand in the seed). Key rule: lowercase, `[^a-z0-9]+` → `-`, strip pack suffix only, `vendor-code`.

- [ ] **Step 4: Run, expect PASS** — same command.

- [ ] **Step 5: Commit** — `git add backend/app/sheets backend/tests/unit/sheets && git commit -m "feat(api): sheet geometry core and naming rules"`

---

### Task 2: Tables, migration, decision labels

**Files:**
- Create: `backend/app/models/sheet.py`, `backend/alembic/versions/2026_11_05_0001-20261105a1_sheet_archive.py`, `backend/app/sheets/locking.py`
- Modify: `backend/app/models/__init__.py` (register), `docs/decisions/register.md`
- Test: `backend/tests/db/test_sheet_tables.py`, `backend/tests/integration/db/test_alembic_sheet_migration.py`

**Interfaces:**
- Produces tables exactly as spec 7.1 (`sheet_types`, `sheet_type_versions`, `sheet_id_counters`, `sheets`, `sheet_cells`) plus `sheet_write_lock(id INTEGER PK CHECK id = 1, seq INTEGER NOT NULL)` seeded with one row by the migration. SQLModel classes `SheetType`, `SheetTypeVersion`, `SheetIdCounter`, `Sheet`, `SheetCell`, `SheetWriteLock`.
- Constraints: `sheet_types.key` unique, `sheet_types.prefix` unique; `(type_id, version)` unique; `sheets.code` unique; `sheet_cells` PK `(sheet_id, cell_no)`; CHECKs `sheets.state IN ('active','discarded')`, `sheets.id_placement IN ('cell','margin','manual')`, `sheet_cells.state IN ('reserved','used','unconfirmed')`, `sheet_types.origin IN ('seed','custom','imported')`, `sheet_type_versions.shape IN ('rectangle','round')`, `page_size IN ('A4','Letter')`. Indexes `ix_sheet_cells_source_ref (source, ref)`, `ix_sheets_type_state (type_id, state)`, `ix_sheet_cells_job_id (job_id)`. `sheet_cells.job_id` is a plain nullable UUID column, **not** a foreign key (OC-39). `product_codes` JSON list.
- Produces (`locking.py`): `async def acquire_sheet_write_lock(session: AsyncSession) -> None` — executes `UPDATE sheet_write_lock SET seq = seq + 1 WHERE id = 1` as the **first statement** of every sheet write transaction, so SQLite takes the write lock before any read (a deferred reader upgrading to a writer can fail with `database is locked` at once in WAL mode; busy_timeout only helps a writer waiting for a writer).

- [ ] **Step 1: Write the failing tests**
  - `test_sheet_cells_composite_pk_blocks_double_take` — insert `(sheet, 5, reserved)`, a second insert of `(sheet, 5)` raises `IntegrityError`.
  - `test_check_constraints` — parametrised invalid `state`, `id_placement`, `origin`, `shape` → `IntegrityError`.
  - `test_sheet_cells_job_id_not_fk` — insert a cell with a random `job_id` that has no `jobs` row → succeeds with `PRAGMA foreign_keys = ON`.
  - `test_write_lock_row_present_after_migration` (integration, temp-file DB, `alembic upgrade head`) — `SELECT seq FROM sheet_write_lock WHERE id = 1` returns one row; `alembic downgrade 20261104a3` removes all six tables; upgrade again works.
- [ ] **Step 2: Run, expect FAIL** — `pytest tests/db/test_sheet_tables.py tests/integration/db/test_alembic_sheet_migration.py -v` → import error / no such table.
- [ ] **Step 3: Implement** models, migration (hand-written, no autogenerate leftovers), locking helper. Add register rows: `D13` "Sheet archive, physical sheets and calibration live in the hub (#150)", `D14` "Sheet type geometry is versioned; sheets pin their version", `D16` "Lengths stored in hundredths of a millimetre", `V2` "L4731REV has no vertical gap (pitch 10 mm)", `V4` "Corner radius of L4736REV (unknown, to measure)" — date 2026-11-05, status `Accepted` / `To verify`, ADR `—`. Label comments: `# D16` on the length columns, `# D14` on `Sheet.type_version_id`.
- [ ] **Step 4: Run, expect PASS** — the two files plus `pytest tests/db/test_alembic_consistency.py tests/unit/test_decision_register.py -v`.
- [ ] **Step 5: Commit** — `git add backend/app/models/sheet.py backend/app/models/__init__.py backend/alembic/versions/2026_11_05_0001-20261105a1_sheet_archive.py backend/app/sheets/locking.py backend/tests/db/test_sheet_tables.py backend/tests/integration/db/test_alembic_sheet_migration.py docs/decisions/register.md && git commit -m "feat(api): tables for sheet types, versions, sheets and cells"`

---

### Task 3: Sheet type service (create, edit, versions, archive, delete)

**Files:**
- Create: `backend/app/repositories/sheet_types.py`, `backend/app/sheets/type_service.py`
- Test: `backend/tests/unit/sheets/test_type_service.py`

**Interfaces:**
- Consumes: Task 1 (`Geometry`, `validate_geometry`, `geometry_hash`, `default_allow_qr`, errors), Task 2 (models, `acquire_sheet_write_lock`).
- Produces (`type_service.py`), all `async`, first parameter `session: AsyncSession`, writes commit inside:
  - `@dataclass class TypeFields`: `key, prefix, vendor, product_codes: list[str], description, allow_qr: bool | None` (None → `default_allow_qr`), `verified: bool = False`, `source_name, source_url, notes: str | None`.
  - `create_type(session, fields: TypeFields, geometry: Geometry, *, actor: str, origin: Literal["seed","custom","imported"] = "custom", change_note: str | None = None) -> tuple[SheetType, SheetTypeVersion]`
  - `get_type(session, key: str) -> SheetType` (raises `SheetTypeNotFoundError`); `current_version(session, type_id: UUID) -> SheetTypeVersion`; `get_version(session, key: str, n: int) -> SheetTypeVersion`; `list_versions_with_sheet_counts(session, type_id) -> list[tuple[SheetTypeVersion, int]]`.
  - `patch_type(session, key, changes: dict[str, Any], *, actor) -> SheetType` — allowed keys: `vendor, product_codes, description, allow_qr, verified, source_name, source_url, notes, prefix`; `prefix` only while no sheet of the type exists (OC-5) else `409 prefix_taken`-family error `PrefixLockedError` (409, `prefix_taken`, detail `{"reason": "sheets_exist"}`); a prefix used by another type → `PrefixTakenError`.
  - `add_version(session, key, geometry, *, actor, change_note: str) -> SheetTypeVersion` — version = max + 1; identical hash to the current version → `InvalidGeometryError(reason="unchanged")`.
  - `archive_type`, `unarchive_type(session, key, *, actor) -> SheetType`.
  - `delete_type(session, key, *, actor) -> None` — only `origin == "custom"` and zero sheets (OC-10); otherwise `409` `SheetTypeInUseError` (`error_code="type_in_use"`; add to `errors.py`).
  - `list_types(session, *, page: str | None, vendor: str | None, q: str | None, w: float | None, h: float | None, include_archived: bool) -> list[SheetType]` — `w`/`h` match the **current** version's label size ± 0.5 mm; `q` matches key, product codes, description (case-insensitive).

- [ ] **Step 1: Write the failing tests**
  - `test_create_type_version_1` — returns version 1 with hash; `origin="custom"`; `allow_qr` defaulted from geometry when `None`.
  - `test_create_duplicate_key_and_prefix` — second create with same key → `TypeExistsError`; same prefix, other key → `PrefixTakenError`.
  - `test_new_version_does_not_move_existing_sheets` — create type (4×12), insert a `Sheet` row pinned to v1, `add_version` with 5×12 → v2 exists, `current_version` is v2, the sheet's `type_version_id` still v1 and `cell_count(v1 geometry) == 48`; `list_versions_with_sheet_counts` → `[(v1, 1), (v2, 0)]`.
  - `test_add_version_unchanged_rejected`.
  - `test_patch_non_geometry_does_not_add_version` — patch `description` → still one version.
  - `test_prefix_editable_only_without_sheets` — patch prefix succeeds with no sheets; after a sheet exists → `PrefixLockedError`.
  - `test_delete_rules` — custom without sheets deleted; custom with a sheet → `SheetTypeInUseError`; seed without sheets → `SheetTypeInUseError` (seed types are only archived).
  - `test_list_filters` — `w=45.7, h=21.2` finds L4736-like within ±0.5 mm and not 25.4 × 10; archived hidden unless `include_archived`.
  - `test_write_error_rolls_back` — `add_version` with invalid geometry leaves version count unchanged (error path).
- [ ] **Step 2: Run, expect FAIL** — `pytest tests/unit/sheets/test_type_service.py -v`.
- [ ] **Step 3: Implement** repository queries and service; every write starts with `acquire_sheet_write_lock`.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add backend/app/repositories/sheet_types.py backend/app/sheets/type_service.py backend/app/sheets/errors.py backend/tests/unit/sheets/test_type_service.py && git commit -m "feat(api): sheet type service with versioned geometry"`

---

### Task 4: Export and import format

**Files:**
- Create: `backend/app/sheets/exchange.py`
- Test: `backend/tests/unit/sheets/test_exchange.py`

**Interfaces:**
- Consumes: Task 3.
- Produces:
  - Pydantic `GeometryMm` (all fields mm floats, `page_size`, `shape`, `corner_radius: float | None`), `TypeDoc`, `VersionDoc(version: int, geometry: GeometryMm)`, `ExportDoc(format: Literal["label-printer-hub.sheet-type"], format_version: Literal[1], type: TypeDoc, version: VersionDoc, exported_at: datetime, exported_by_hub: str)` — every model `extra="forbid"`, strings bounded (`key` ≤ 64, `vendor`/`description`/`source_name` ≤ 200, `notes` ≤ 2000, `source_url` ≤ 500 and `http`/`https` only, `product_codes` ≤ 50 items of ≤ 40 chars).
  - `def geometry_from_doc(g: GeometryMm) -> Geometry`, `def geometry_to_doc(g: Geometry) -> GeometryMm`.
  - `async def export_type(session, key: str, version: int | None) -> ExportDoc` — `exported_by_hub` = `HUB_VERSION` string only.
  - `MAX_IMPORT_BYTES = 65536`
  - `@dataclass class ImportResult: outcome: Literal["created","unchanged","version_added","created_as_new_key"]; key: str; version: int`
  - `def parse_import(raw: bytes) -> ExportDoc` — size check first (`413`-mapped `ImportTooLargeError`, `error_code="import_too_large"`), then `json.loads` with `parse_constant` refusing `NaN`/`Infinity`, then model validation; all failures → `InvalidImportError` (422, `invalid_import`, detail `{"errors": [<pydantic loc paths only, no input values>]}`).
  - `async def import_type(session, doc: ExportDoc, *, mode: Literal["strict","new_version","as_new_key"] = "strict", new_key: str | None = None, new_prefix: str | None = None, actor: str) -> ImportResult` — cases of spec 9.3 / OC-12; `origin="imported"`.
  - The seed file uses the same `ExportDoc` model (Task 5).

- [ ] **Step 1: Write the failing tests**
  - `test_roundtrip_identical_hash` — export L4736-like type, import into an empty second database → `created`, `geometry_hash` equal (acceptance 10).
  - `test_import_same_geometry_unchanged` — import the export again → `unchanged`, names version 1, no new rows.
  - `test_import_changed_geometry_strict_conflict` → `TypeExistsError`; `mode="new_version"` → `version_added`, version 2; `mode="as_new_key", new_key="my-l4736", new_prefix="ML4736"` → `created_as_new_key`.
  - `test_import_prefix_taken` → `PrefixTakenError`; with `new_prefix` → created.
  - `test_import_rejects_*` (parametrised, each asserts the error class and that the type count is unchanged): 65537 bytes; top-level list; unknown field `"type.colour"`; `format_version: 2`; `margin_top: 9.855`; `NaN` literal; `label_w: -1`; 400-deep nested arrays inside `notes` (refused by the schema type, no recursion error); `source_url: "javascript:alert(1)"`; geometry failing `validate_geometry`.
  - `test_import_error_detail_has_no_input_values` — the hostile string `"<script>"` in an unknown field does not appear in `error_detail`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add backend/app/sheets/exchange.py backend/tests/unit/sheets/test_exchange.py && git commit -m "feat(api): sheet type export and import"`

---

### Task 5: Seed file, seeder, third-party notice

**Files:**
- Create: `backend/app/seed/sheet_types.json`, `backend/app/seed/sheet_seed.py`
- Modify: `backend/app/main.py` (lifespan: call the seeder after migrations, before the queue starts), `THIRD_PARTY_NOTICES.md`
- Test: `backend/tests/unit/seed/test_sheet_seed_file.py`, `backend/tests/unit/seed/test_sheet_seeder.py`

**Input (not in the repository).** The operator hands the implementer the research seed: a JSON list of 42 entries with fields `vendor, product_codes, description, page, label_w_mm, label_h_mm, cols, rows, labels_per_sheet, pitch_x_mm, pitch_y_mm, margin_top_mm, margin_left_mm, margin_right_calc_mm, margin_bottom_calc_mm, corner_radius_mm, shape, material_note, plausible, plausibility_notes, verified_against_manufacturer, source_url, source_name`. Its location is given in the execution brief and is never written into the repository. The conversion is a one-off done in a scratch script that is **not** committed.

**Conversion rules (decisions):**
- Drop the four entries whose first product code is `7163`, `8658`, `L4730`, `L4770` (OC-13) → 38 documents.
- Each document is an `ExportDoc` with `version.version = 1`, `exported_at` = `2026-11-05T00:00:00Z`, `exported_by_hub = "seed"`.
- `type.key = derive_key(vendor, product_codes[0])`, `type.prefix = derive_prefix(...)`; a collision or a prefix longer than 10 is resolved by hand and noted in the test's expected-prefix table.
- Drop `labels_per_sheet`, `*_calc_mm`, `plausible`, `verified_against_manufacturer` (computed or replaced by `verified=false`). `verified = false` everywhere. `allow_qr = default_allow_qr(geometry)`.
- `notes`: English only (the input's notes, material note and two descriptions are not in English and are translated). The recurring note about uneven remaining margins becomes `"Left and right remaining margins differ (a / b mm)."` or `"Top and bottom remaining margins differ (a / b mm)."`; a material note "removable" becomes `"Material: removable."`; the L4731REV/L4736REV description becomes `"Mini labels, removable"`. Notes are joined with a space.
- **L4731REV** (hand-added, spec 9.5): geometry `25.4 × 10, 7 × 27, pitch 27.9 / 10.0, top 13.5, left 8.6, radius 1.5, A4, rectangle`, `allow_qr=false`; `source_name = "Labelplanet LP189/25; MR-Label MR111"`, `source_url` = the Labelplanet LP189/25 template page URL from the input; `notes = "Vendor page not reachable; values agree between two third-party sources for this size (Labelplanet LP189/25, MR-Label MR111, listed there as the L4731 size; second source: <MR-Label URL from the input>). Corner radius 1.47 mm from MR-Label MR111, rounded to 1.5. No vertical gap (pitch 10 = label height). Material: removable."`
- **L4736REV**: `45.7 × 21.2, 4 × 12, pitch 48.2 / 21.2, top 21.3, left 9.85, radius null, A4, rectangle`, `allow_qr=true`; `source_name = "Labelplanet LP48/45"`, `source_url` from the input; `notes = "Vendor page not reachable; values from Labelplanet LP48/45 only. Corner radius unknown (comparable templates range from 2.0 to 4.25 mm); measure. Commercial variation: an alternative layout of 45.5 × 21.1, top 21.9, side 9.8, pitch 48.3 × 21.1 is also listed. Material: removable."`
- gLabels entries keep `source_name = "gLabels-qt templates (MIT) @ 37901c1"` and their permalink `source_url`.
- Top level of the file: `{"seed_revision": 1, "types": [ ...38 ExportDoc... ]}`.

**Interfaces:**
- Consumes: Tasks 3–4.
- Produces (`sheet_seed.py`): `SEED_FILE = importlib.resources.files("app.seed") / "sheet_types.json"`; `def load_seed() -> tuple[int, list[ExportDoc]]`; `async def run_sheet_seed(session_factory: async_sessionmaker[AsyncSession]) -> SeedReport` with `SeedReport(inserted: list[str], versions_added: list[str], skipped: dict[str, str])`. Rules (OC-14): insert missing keys with `origin="seed"`; for an existing key add a new version only if every version of the type has `origin="seed"`-provenance (`created_by == "seed"`), no sheet uses the type, and the seed geometry hash differs from the current version; otherwise leave it and log at INFO. A seed whose prefix is taken by another type is skipped with `skipped[key] = "prefix_taken"` and a WARNING. The seeder keeps no state of its own: every start compares the 38 keys and hashes (one query per table), which is cheap; `seed_revision` is logged and only changes when the file's geometry does.

- [ ] **Step 1: Write the failing tests**
  - `test_seed_has_38_valid_documents` — `load_seed()` returns 38 docs, each parses as `ExportDoc`, each geometry passes `validate_geometry`, keys and prefixes unique and pattern-valid, `verified` all false.
  - `test_seed_excludes_held_back_types` — no doc has first product code in `{"7163","8658","L4730","L4770"}`.
  - `test_seed_first_types_exact` — L4731REV and L4736REV geometry equal the values above; L4736REV `corner_radius is None`, `allow_qr` true/false as stated.
  - `test_seed_is_english_and_private_clean` — every string in the file is ASCII apart from the characters `× · – —` (catches untranslated text); no IPv4 pattern; every `source_url` starts with `https://`.
  - `test_seed_file_ships_in_package` — `SEED_FILE.is_file()`.
  - `test_seeder_inserts_once` — fresh DB → 38 inserted; second run → 0 inserted, 0 versions.
  - `test_seeder_adds_version_for_untouched_seed_type` — bump revision with changed geometry for one key in a patched seed → one version added.
  - `test_seeder_leaves_edited_type_alone` — after a local `add_version` by `actor="admin"`, changed seed geometry → no version added, INFO logged.
  - `test_seeder_skips_on_prefix_taken` — a custom type already owns `L4731` → that seed skipped, others inserted, startup does not raise.
  - `test_notices_list_glabels` — `THIRD_PARTY_NOTICES.md` contains `gLabels-qt`, `37901c1`, `Copyright (C) 2001-2026 Jaye Evins`, and `Permission is hereby granted, free of charge`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** the converted seed file, seeder, lifespan call (failures are logged, never block startup), and a "Sheet type data" section in `THIRD_PARTY_NOTICES.md`: project URL `https://github.com/j-evins/glabels-qt`, commit `37901c1`, the copyright line, the full MIT text; a line that L4731REV/L4736REV cite Labelplanet and MR-Label as sources of facts only.
- [ ] **Step 4: Run, expect PASS** — `pytest tests/unit/seed -v`.
- [ ] **Step 5: Commit** — `git add backend/app/seed/sheet_types.json backend/app/seed/sheet_seed.py backend/app/main.py THIRD_PARTY_NOTICES.md backend/tests/unit/seed && git commit -m "feat(api): seed 38 sheet types from gLabels-qt and third-party sources"`

---

### Task 6: Sheet service (create, next code, mark, unmark, resolve, discard, list, lookups, events)

**Files:**
- Create: `backend/app/repositories/sheets.py`, `backend/app/sheets/sheet_service.py`, `backend/app/sheets/events.py`
- Modify: `backend/app/api/routes/events_v1.py` (every stream also subscribes to channel `sheets`, like `hub`)
- Test: `backend/tests/unit/sheets/test_sheet_service.py`, `backend/tests/db/test_sheet_concurrency.py`, `backend/tests/unit/sheets/test_sheet_events.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces (`sheet_service.py`):
  - `@dataclass class MarkedCell: cell: int; purpose: str | None = None`
  - `create_sheet(session, *, type_key: str, version: int | None, id_placement: Literal["margin","manual"], used_cells: list[MarkedCell], note: str | None, actor: str) -> Sheet` — one transaction: lock, refuse archived type, read-increment `sheet_id_counters` (insert row at 1 if missing), insert sheet pinned to the version, insert `used` cells with `source="manual"`, `marked_by_hand=True`, purpose default `"marked by hand"`. Plan 3 widens `id_placement` to `"cell"`.
  - `peek_next_code(session, type_key: str) -> str` — no write.
  - `get_sheet(session, code: str) -> SheetDetail` (`sheet`, `type`, `version`, `cells: list[SheetCell]`, `free: int`, `total: int`, counts per state). Unknown → `SheetNotFoundError`; discarded is returned, not raised.
  - `mark_cells(session, code, cells: list[MarkedCell], *, actor) -> SheetDetail` — cells in `1…cell_count(pinned version)` else `CellOutOfRangeError` (all bad numbers listed); any non-free → `CellsTakenError` with those numbers; discarded → `SheetDiscardedError`.
  - `unmark_cells(session, code, cells: list[int], *, actor) -> SheetDetail` — only `marked_by_hand=True` `used` cells; others → `CellsTakenError`-shaped `409 cells_not_marked_by_hand` (`CellsNotMarkedByHandError`).
  - `resolve_cells(session, code, cells: list[int], outcome: Literal["printed","not_printed"], *, actor) -> SheetDetail` — only `unconfirmed` cells; `printed` → `used` (keeps source/purpose/job_id), `not_printed` → row deleted.
  - `discard_sheet(session, code, *, actor) -> Sheet` — any `reserved` cell → `SheetBusyError`; sets `discarded_at/by`.
  - `list_sheets(session, *, type_key: str | None, free_at_least: int | None, state: Literal["active","full","discarded","all"] = "active", q: str | None) -> list[SheetListRow]` (`SheetListRow` dataclass: sheet, type, version, counts per state, free) — `full` = active with 0 free; order OC-34: rows with `free >= free_at_least` first, then by free descending, then code.
  - `find_cells(session, *, source: str, ref: str) -> list[CellHit]` (`code, cell, state, purpose, updated_at`), newest first.
- Produces (`events.py`): `SHEETS_CHANNEL = "sheets"`; `def publish_sheet_updated(bus: EventBus | None, *, code: str, free: int, total: int, changed: list[int], state: str) -> None` — event type `sheet.updated`; called by the service after commit (service functions accept `bus: EventBus | None = None`).

- [ ] **Step 1: Write the failing tests**
  - `test_create_manual_sheet_codes` — first sheet of prefix `L4736` → `L4736-01`; `peek_next_code` before → `L4736-01`, after → `L4736-02`; counter row 100 → code `L4736-100`.
  - `test_create_with_used_cells` — 17 hand-marked cells → `free == 31` on L4736REV.
  - `test_create_on_archived_type_refused` → `SheetTypeArchivedError`.
  - `test_create_old_version` — `version=1` after v2 exists → pinned to v1.
  - `test_mark_uses_pinned_version_cell_count` — sheet on a 48-cell v1, type at v2 with 60 cells → marking cell 49 → `CellOutOfRangeError(max=48)`.
  - `test_mark_taken_and_out_of_range` — mark `[5, 5]` duplicates collapse; mark used cell → `CellsTakenError(cells=[5])` and nothing else written (error path).
  - `test_unmark_only_hand_marked` — a `used` cell with `marked_by_hand=False` → `CellsNotMarkedByHandError`.
  - `test_resolve_unconfirmed` — insert two `unconfirmed` rows (job id set) → `printed` keeps the row as `used` with purpose; `not_printed` deletes; resolving a `used` cell → `409 cells_not_unconfirmed` (`CellsNotUnconfirmedError`).
  - `test_discard_busy_and_ok` — a `reserved` row → `SheetBusyError`; after removing it → discarded; `get_sheet` returns `state="discarded"`; `list_sheets()` hides it, `state="discarded"` shows it.
  - `test_discarded_code_never_reissued_after_archive_cycle` — create `-01`, discard, archive type, unarchive, create → `-02` (acceptance 4).
  - `test_list_order_fits_first` — sheets with free 3, 31, 9 and `free_at_least=9` → order 31, 9, 3.
  - `test_find_cells_by_ref` — two cells with `source="grocy", ref="42"` → both, newest first.
  - `test_events_published_after_commit` — fake bus records `sheet.updated` with `changed=[...]`; a failed mark publishes nothing.
  - `db/test_sheet_concurrency.py` (temp-file SQLite, two sessions from one engine, `asyncio.gather`):
    - `test_parallel_create_gives_distinct_codes` — 10 parallel `create_sheet` → 10 distinct codes `-01…-10`, no `database is locked`.
    - `test_parallel_mark_same_cell_one_conflict` — two parallel `mark_cells(cell 7)` → exactly one success, one `CellsTakenError([7])`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** If the concurrency test shows `database is locked` despite the lock row, switch `acquire_sheet_write_lock` to an explicit `BEGIN IMMEDIATE` issued through the connection (keep the function name) and record the finding in `docs/learnings/code-review-patterns.md`.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add backend/app/repositories/sheets.py backend/app/sheets/sheet_service.py backend/app/sheets/events.py backend/app/api/routes/events_v1.py backend/tests/unit/sheets/test_sheet_service.py backend/tests/unit/sheets/test_sheet_events.py backend/tests/db/test_sheet_concurrency.py && git commit -m "feat(api): physical sheets with used cells, discard and events"`

---

### Task 7: Sheet type API

**Files:**
- Create: `backend/app/schemas/sheets.py` (type part), `backend/app/api/routes/sheet_types.py`
- Modify: `backend/app/main.py` (`include_router`), `backend/tests/api/test_openapi_completeness.py` (bound), `frontend/src/api/schema.gen.ts` (regenerated)
- Test: `backend/tests/integration/api/test_sheet_types_api.py`

**Interfaces:**
- Consumes: Tasks 3–5.
- Produces the routes of spec 15 for `/api/sheet-types…` (list, get, get version, create, patch, new version, archive, unarchive, delete, export, import). Schemas: `GeometryMm` (reuse from `exchange.py`), `SheetTypeRead` (all type fields, `current_version: int`, `geometry: GeometryMm`, `hints: list[str]`, `sheets_in_use: int`), `SheetTypeDetail(SheetTypeRead + versions: list[VersionRead])`, `VersionRead(version, geometry, geometry_hash, change_note, created_at, sheets: int)`, `SheetTypeCreate(fields + geometry)`, `SheetTypePatch` (all optional), `VersionCreate(geometry, change_note: str = Field(min_length=1, max_length=500))`, `ImportResponse(outcome, key, version)`. Import endpoint takes the raw body (`Request.body()`, content type `application/json`), query `mode`, `new_key`, `new_prefix`, and calls `parse_import` so the 64 KB limit is checked before parsing. Export answers `application/json` with `Content-Disposition: attachment; filename="<key>-v<n>.json"`.

- [ ] **Step 1: Write the failing tests** — one per route for the happy path; scope matrix parametrised over all write routes: `read` key → 403, `print` key → 403, `admin` → 2xx; `GET` routes with a `read` key that is restricted to one printer → 200 (OC-37); error codes `sheet_type_not_found` (404), `type_exists`, `prefix_taken`, `invalid_geometry` (422 with `error_detail.field`), `import_too_large` (413), `invalid_import` (422); `test_export_import_roundtrip_over_http`; `test_openapi_lists_sheet_type_routes` (every path of spec 15 under `/api/sheet-types` present).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** routes (thin: parse → service → map `SheetApiError.to_http()`), register router, raise the endpoint-count bound, `cd frontend && pnpm gen:api`.
- [ ] **Step 4: Run, expect PASS** — the new file plus `pytest tests/api tests/unit/api/test_route_auth_coverage_guardrail.py -v`; `cd frontend && pnpm typecheck`.
- [ ] **Step 5: Commit** — `git add backend/app/schemas/sheets.py backend/app/api/routes/sheet_types.py backend/app/main.py backend/tests/api/test_openapi_completeness.py backend/tests/integration/api/test_sheet_types_api.py frontend/src/api/schema.gen.ts && git commit -m "feat(api): sheet type endpoints with export and import"`

---

### Task 8: Sheets and sheet-cells API

**Files:**
- Modify: `backend/app/schemas/sheets.py` (sheet part), `backend/app/main.py`, `backend/tests/api/test_openapi_completeness.py`, `frontend/src/api/schema.gen.ts`
- Create: `backend/app/api/routes/sheets.py`
- Test: `backend/tests/integration/api/test_sheets_api.py`

**Interfaces:**
- Consumes: Task 6.
- Produces routes: `GET /api/sheets`, `GET /api/sheets/next-code?type=`, `GET /api/sheets/{code}`, `POST /api/sheets`, `POST /api/sheets/{code}/discard`, `POST /api/sheets/{code}/cells/mark`, `/unmark`, `/resolve`, `GET /api/sheet-cells?source=&ref=`. Path param `code` pattern `^[A-Z][A-Z0-9]{1,9}-[0-9]{2,}$`. Schemas: `SheetSummary(code, type_key, type_label, version, label_w, label_h, total, used, reserved, unconfirmed, free, state, last_used_at)`, `SheetRead(SheetSummary + id_placement, id_printed, note, geometry: GeometryMm, cells: list[CellRead], discarded_at)`, `CellRead(cell, state, source, purpose, ref, marked_by_hand, job_id, updated_at)`, `SheetCreate(type: str, version: int | None, id_placement: Literal["margin","manual"], used_cells: list[MarkedCellIn] = Field(max_length=400), note: str | None = Field(max_length=500))`, `MarkedCellIn(cell: int = Field(ge=1), purpose: str | None = Field(max_length=120))`, `CellNumbers(cells: list[int] = Field(min_length=1, max_length=400))`, `ResolveRequest(cells, outcome)`, `CellHitRead`, `NextCode(code: str, hint: Literal["probable"])`. `next-code` route is declared before `/{code}`.

- [ ] **Step 1: Write the failing tests** — happy path per route; `test_scope_matrix` (writes: `read` → 403, `print` → 2xx); `test_other_client_sees_same_cells` (two different API keys: key A marks cell 5 with purpose `"Grocy · flour 1 kg"`-style purpose, key B `GET /api/sheets/{code}` sees it — acceptance 11 at the data level); `test_discarded_lookup_200_unknown_404` (acceptance 8, data side); `test_code_pattern_rejects_lowercase` (422); `test_purpose_over_120_rejected`; `test_sheet_updated_event_on_stream` (open `/api/v1/events`, mark a cell, receive `sheet.updated` on channel `sheets`).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**, register, raise bound, regenerate frontend types.
- [ ] **Step 4: Run, expect PASS** — new file, `tests/api`, guardrail, full `pytest -m "not slow" --cov=app --cov-fail-under=80`, `mypy app/`, `ruff check . && ruff format --check .`, `cd frontend && pnpm typecheck`.
- [ ] **Step 5: Commit** — `git add backend/app/schemas/sheets.py backend/app/api/routes/sheets.py backend/app/main.py backend/tests/api/test_openapi_completeness.py backend/tests/integration/api/test_sheets_api.py frontend/src/api/schema.gen.ts && git commit -m "feat(api): sheet endpoints, cell marking and reprint lookup"`

---

## Plan-level verification

- `cd backend && pytest -m "not slow" --cov=app --cov-fail-under=80 && mypy app/ && ruff check . && ruff format --check .`
- `cd frontend && pnpm gen:api && git diff --exit-code src/api/schema.gen.ts && pnpm typecheck`
- Fresh container start logs `inserted 38` once, nothing on the second start.
