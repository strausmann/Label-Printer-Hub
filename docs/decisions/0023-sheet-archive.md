<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# 0023 — Sheet archive, physical sheets and calibration

- **Status:** Accepted
- **Date:** 2026-11-10
- **Deciders:** maintainer
- **Decision labels:** D13, D14, D15, D16, D17, D19 (D18 is [0020](0020-backend-kinds-ipp-page-printers.md))
- **Amended:** 2026-11-21 (#334, #350) — seed corrections and adoption, sheet code placement and backing designs as shipped in 1.7.0, and the open D19 violation, see "Amendment — 2026-11-21" at the end
- **Related:** [0020](0020-backend-kinds-ipp-page-printers.md) (page printers over IPP), [0005](0005-print-queue-is-mandatory.md)

## Context

Label sheets (A4 or Letter die-cut sheets) are printed on ordinary office printers. A sheet is used over several print runs, by several clients, and the hub is the only place that sees all of them. Doing this in each client would give each client its own idea of which cells are free. The detailed requirements and the full data model are in the spec (`docs/superpowers/specs/2026-11-05-sheet-archive-design.md`, sections 6 to 13 and 20); the register rows hold the one-line form of each decision. This ADR collects them in one place so that the reasoning is findable.

## Decision

**The hub owns the sheet archive: sheet types with versioned geometry, physical sheets with per-cell state, and manual calibration per printer and tray.**

- **D13 — the archive lives in the hub.** The catalogue of sheet types, the physical sheets (each with an ID made of a type prefix and a counter, never reused) and the calibration values are hub data, shared by every client and integration. A sheet stores the set of used cells (not a start cell), so gaps work, and each used cell records what it was used for.
- **D14 — geometry is versioned; sheets pin their version.** Changing the geometry of a type adds version n+1; a sheet that is already in use keeps the version and cell numbering it started with. Non-geometric fields (description, vendor, notes) change the type row, not the version. A type that has sheets is archived instead of deleted.
- **D15 — cells are reserved at job creation, used on completion, unconfirmed when the outcome is unknown.** Planning the cells and inserting the `reserved` rows happen in one transaction; the composite key is the guard, so two clients picking the same sheet cannot take the same cell (the loser gets `409 cells_taken`, or `409 plan_changed` when it sent the plan it saw). When the printer reports a job completed, its cells become `used`. A job that ends cleanly without printing frees them. A job that was interrupted after the printer started it ends with its cells `unconfirmed`: the hub does not guess whether paper was marked, and the person confirms "printed" or "not printed". Free cells are the total minus every stored cell, so reserved and unconfirmed cells are not free.
- **D16 — lengths are stored in hundredths of a millimetre** as integers and exposed in millimetres with at most two decimals. Geometry comparison, version identity and export/import identity stay exact.
- **D17 — calibration stores the printer's deviation around the page centre; the hub applies the inverse.** The stored values are what the person measured on a calibration page (offsets, scale, rotation, within bounded ranges); when rendering, the hub draws at the inverse so the print lands on the nominal position. No stored calibration means identity. Calibration belongs to printer and tray and is valid for every sheet type. The calibration page is printed without correction, on a real sheet, in black only.
- **D19 — imported sheet types are never marked verified.** A type that arrives through the export/import format is someone else's claim; `verified` is only set on this hub after a test print.
- **Export and import.** A type exports as one small JSON document (millimetre values, no sheet data). Import is strict and size-limited; identical geometry changes nothing, differing geometry needs an explicit mode.
- **Seed.** Bundled sheet types are loaded from numbers only, with their provenance and a third-party notice; a seeded type is never changed automatically once a sheet uses it.

## Options considered

### Option A — the hub owns archive, reservation and calibration (chosen)
- Pros: one truth for all clients; concurrency handled in one transaction; geometry and calibration reusable across clients.
- Cons: the hub carries more state and a larger data model.

### Option B — clients keep their own sheet state
- Pros: no hub change.
- Cons: two clients can print into the same cell; no shared reprint position; calibration duplicated.

### Option C — mark cells used when the job is accepted
- Pros: simpler.
- Cons: a failed job wastes cells; the maintainer's rule is that cells become used only when the job is reported completed.

## Consequences

- New tables for sheet types, versions, sheets, cells and calibrations; a seeder runs at start.
- The unconfirmed state needs a UI path ("printed" / "not printed") and is part of every sheet view.
- Code that follows these decisions carries the `D13`–`D19` labels, and the guard test keeps the register in step.
- Open points stay in the register as `V1`–`V4` until measured.

## References

- Issue: #150
- Spec: `docs/superpowers/specs/2026-11-05-sheet-archive-design.md` (sections 6 to 13, 20)
- Register: [register.md](register.md)
- Related ADRs: [0005](0005-print-queue-is-mandatory.md), [0020](0020-backend-kinds-ipp-page-printers.md)

## Amendment — 2026-11-21 (ADR audit): as shipped in 1.7.0

### Seed: corrections and adoption (#334)

The bullet "Seed" above still holds for an ordinary seeded type: the seeder adds a new version only when every version of the type came from the seeder, no sheet uses it and the shipped geometry differs (`backend/app/seed/sheet_seed.py:8-12`). Since 1.7.0 the seed file carries two exceptions (`sheet_seed.py:19-29`), each applied once per revision and recorded in `app_settings` (`internal.seed.adopted`, `internal.seed.corrected`):

- **`corrections`**: a shipped type whose shipped geometry was wrong gets the corrected geometry as its next version **even when sheets use it**, but only while it is still on the old shipped geometry; a locally edited geometry is left alone. Sheets keep the version they pinned (D14), so a correction never moves cells of a sheet in use; new sheets get the corrected version.
- **`adopt`**: a key that already exists as a user's own type is taken over as shipped (`origin="seed"`, verified); a different current geometry becomes the next version. Prefix, vendor, product codes, description and the QR switch stay the user's.

Each takeover leaves one notice for the notification centre (`internal.notices`). This replaces the sentence "a seeded type is never changed automatically once a sheet uses it" for the types the seed lists under `corrections`.

### Where the sheet code goes, and backing designs (#350)

A sheet type stores where the code of a new sheet goes (`id_placement`: `auto`, `margin`, `back_side` or `cell`), the preferred ID cell of a `cell` sheet (`id_cell`) and the vendor print on the back of its liner (`backing_design_id`) (`backend/app/models/sheet.py:45-46,66-76`). `auto` resolves to `margin` or `back_side`, never to `cell`: with a printer the margin check decides, without one the geometry does, assuming a 5 mm hardware margin (`backend/app/sheets/id_placement.py:4-8`). A sheet records the placement it got (`cell`, `margin`, `manual` or `back_side`; `sheet.py:125-126`).

- **Back of the liner.** A `back_side` sheet gets a 22 × 62 mm code strip with QR, sheet code, type and date on the back, placed in the first free strip of its backing design, or at (10, 10) mm without one; no calibration applies (`backend/app/sheets/back_side.py:4-14`). A tray loading test page lets the person find out which way a sheet goes into a tray (`back_side.py:16-18`).
- **Extra code and reprints.** `POST /api/v1/sheets/{code}/back-side` prints the strip again, or adds an extra code on the back of a sheet whose code is already printed; `…/back-side/confirm` confirms it (`backend/app/api/routes/sheets.py:394-405,450`). `POST /api/v1/sheets/{code}/margin-id` prints only the margin code of a printed `margin` sheet again, without reserving a cell (`sheets.py:477-483`).
- **Backing designs** are rows of their own with the free strips of the back side in hundredths of a millimetre (D16; `backend/app/models/backing_design.py`). The seed ships designs and links shipped types to them once; a design an admin deleted is not inserted again, and a user's later choice is never overwritten (`sheet_seed.py:33-41`).

### D19 is violated by one import path

D19 stands: an imported type is never marked verified. A type created by an import is stored with `verified=False` (`backend/app/sheets/exchange.py:354`), but an import in mode `new_version` into an existing, verified type adds the version and leaves the type's `verified` flag as it was (`exchange.py:412-417`, `backend/app/sheets/type_service.py:402-419`). That is a code defect against D19, not a change of the decision; milestone 1.8.0 fixes it (#204, item 5).

