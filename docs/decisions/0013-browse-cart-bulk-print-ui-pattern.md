# 0013 — Browse + cart + bulk-print UI pattern

- **Status:** Accepted
- **Date:** 2026-05-10
- **Deciders:** maintainer

## Context

ADRs 0001-0012 establish that integrations (Snipe-IT, Grocy, Spoolman) are surfaced as tabs in the hub UI with a search-and-print flow:

> Open hub → switch to integration tab → search by ID/name/barcode → pick result → print

Pure search has two ergonomic limits, especially on a phone:

1. You have to remember (or read) what the asset is called or what its tag/barcode is. Visual recognition ("the spool that's almost empty", "the rugged laptop bag I always forget the asset tag of") is faster than typing — but only if you can see the items.
2. Printing several labels at once requires N independent search-print cycles. Common workflows ("I just received a delivery, let me label all 8 new boxes") become tedious.

The maintainer wants:

> Instead of just a search for an inventory item, scrolling through is also a nice option, with items shown as tiles — e.g. two columns with title, picture, and ID. Click an item, view it, choose a layout you defined earlier, see a sample rendered with the item's metadata, and print. Or like a shop, drop into a basket and add more items so you can fire one combined job for all the labels.

## Decision

Each integration tab supports **three coexisting modes** for finding what to print, plus a **cart** for batch operations:

| Mode | UI |
|---|---|
| **Search** | text input → results list (existing behaviour) |
| **Browse / grid** | paginated grid of tiles (mobile: 2 columns; desktop: 4 columns), each tile shows picture + title + ID; click → detail view |
| **Scan** | camera or barcode-scanner input → direct jump to detail view of that item |

The **detail view** shows the full item metadata, a layout dropdown (filtered to the integration's compatible layouts — see [ADR 0012](0012-label-layout-management.md)), a live label preview rendered with the item's actual data, and two action buttons:

- **Print now** — submits a single print job (existing flow)
- **Add to cart** — appends the item to the cart with its chosen layout; user keeps browsing

The **cart** is integration-agnostic. It can hold items from Snipe-IT, Grocy, and Spoolman simultaneously. It persists per browser via `localStorage` (no server state in MVP). Each cart entry has its own **quantity** (how many copies of that label to print) — defaults to 1, can be increased/decreased in the cart screen. When the user hits **Print all**, the hub:

1. Groups cart items by `(printer_id, tape_mm)`
2. Within each group, expands each cart entry to N pages where N = its `quantity`
3. Submits one **batch job** per group — Brother printers support multi-page jobs natively (`0Ch` between pages, `1Ah` after the last)
4. If the cart spans multiple tape widths or printers, the user sees the resulting set of jobs and confirms before submission

### Cart icon and overview screen

A persistent **printer/cart icon** lives in the top-right corner of the app shell, with a badge showing the total quantity (sum of all `quantity` values, not the number of distinct items — printing 5× of one item shows badge `5`).

Tapping the icon opens the **cart overview**:

- Items grouped by integration
- Per item: thumbnail · title · ID · chosen layout (dropdown to change) · tape size (auto, derived from layout) · **quantity stepper** (`−` and `+` buttons, plus direct number entry) · remove button
- Cart total: total label count, estimated tape consumption per tape size, target printer breakdown
- **Print all** primary button → confirmation modal → batch submission
- **Clear cart** secondary button (with confirmation)
- If cart is empty: friendly empty state with a link back to browse mode

The cart icon is sticky and visible from any view (search, browse, detail, queue, settings) so the user can always tell how many items are queued and jump there.

### Cart entry schema (localStorage)

```json
{
  "version": 1,
  "items": [
    {
      "id": "ulid-of-cart-entry",
      "integration": "snipeit",
      "lookup_id": "ASSET-12345",
      "layout_id": "<uuid>",
      "quantity": 3,
      "title_snapshot": "MacBook Pro 16",
      "thumbnail_url": "/api/lookup/snipeit/ASSET-12345/image",
      "added_at": "2026-05-10T19:00:00Z"
    }
  ],
  "updated_at": "2026-05-10T19:01:23Z"
}
```

`title_snapshot` and `thumbnail_url` let the cart render quickly on load without re-fetching from the integration API. The actual print data is re-fetched at submission time so changes in the source system are picked up.

A batch job is **one PrintQueue job** from the user's perspective (one job_id, one history entry, one set of state-machine transitions) but contains N pages internally. The job's lifecycle still follows ADR 0005 (no mid-print cancel; pause/resume operate on the queued batch as a whole).

## Options considered

### Option A — Browse + cart + bulk-print, all three modes (chosen)
- Pros: solves both maintainer requirements (visual scrolling + bulk operations); each mode addresses a different real-world workflow; no mode forced — user picks
- Cons: more UI surface to design and test; image fetching/caching adds backend work; cart state needs careful UX (clear-on-print? explicit clear button? expiry?)

### Option B — Search only (status quo before this ADR)
- Pros: simplest UI
- Cons: fails the maintainer's stated requirement; misses obvious phone use cases

### Option C — Browse but no cart (no bulk)
- Pros: visual flow without bulk-print complexity
- Cons: doesn't solve the "label 8 new items at once" workflow; cart is the bigger value-add for the user

### Option D — Cart but server-side persistence (DB-backed sessions)
- Pros: cart survives device switch (start on phone, finish on desktop)
- Cons: adds session model, expiry, GC, multi-user-mismatch concerns; localStorage is enough for MVP — server-side cart is a candidate for v2 if real multi-device need emerges

## Consequences

### Backend

- **New listing endpoints** (paginated):
  - `GET /api/lookup/snipeit?page=1&page_size=24&category=…&sort=name`
  - `GET /api/lookup/grocy?page=1&page_size=24&location=…&sort=name`
  - `GET /api/lookup/spoolman?page=1&page_size=24&material=…&sort=name`
  - All return `{items: [...], page, page_size, total}` with stable ordering
- **Item-image proxy + cache** at `GET /api/lookup/{integration}/{id}/image`
  - Backend fetches the integration's image URL using its API token (avoids exposing tokens to the browser)
  - Caches on disk under the data volume with ETag/last-modified validation
  - Falls back to a placeholder for items without images (Spoolman items get a colour swatch from `filament.color_hex`)
- **Bulk print endpoint**: `POST /api/print/{printer_id}/batch` with body
  ```json
  {
    "items": [
      {"integration": "snipeit", "lookup_id": "ASSET-12345", "layout_id": "<uuid>", "quantity": 3},
      {"integration": "grocy",   "lookup_id": "42",          "layout_id": "<uuid>", "quantity": 1}
    ]
  }
  ```
  Returns one `job_id`. Each item is rendered once and that page is repeated `quantity` times in the multi-page raster stream. The job's `image_payload` is the assembled stream; total pages = sum of all `quantity` values. `quantity` defaults to 1 if omitted; valid range 1-99 (Brother spec page-per-cut limit).
- **PrintQueue** does not need to know "this is a batch" — to it the job is one stream of bytes. The batch concept lives in the API layer.
- **Layout compatibility check**: the backend validates that every item's chosen layout matches the printer's tape width before accepting the batch.

### Frontend

- New views per integration tab: `Search` / `Browse` / `Cart`
- Grid component with virtual-scroll or pagination (mobile: 2-col masonry-style)
- Detail view with layout dropdown + live preview (re-uses `/api/render/preview`)
- Cart icon with badge count, persistent across the app session via `localStorage` (key `lph.cart`)
- Cart screen lists items grouped by integration; per-item: thumbnail, title, chosen layout (editable), tape (auto-derived), remove button
- "Print all" → confirmation modal showing the batch breakdown (which printer, which tape, how many items per job) → submits

### Data model

No new persistent table for the cart in MVP. If Option D is later adopted, add:
```sql
CREATE TABLE cart_sessions (
  id TEXT PRIMARY KEY,         -- UUID per browser
  user_id TEXT,                -- nullable in single-user mode
  items_json TEXT NOT NULL,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  expires_at DATETIME
);
```

### Tests

- Pagination correctness for each integration (stable sort, no duplicates between pages)
- Image-cache: cache hit/miss, ETag-based revalidation, placeholder fallback
- Batch job: layout-compatibility validation, multi-page raster assembly, single-job-id response
- LocalStorage cart: add/remove/clear/persist-across-reload (e2e test)

## References

- Issue [#5](https://github.com/strausmann/label-printer-hub/issues/5) — browser notifications (cart-print-complete uses these)
- Issue [#15](https://github.com/strausmann/label-printer-hub/issues/15) — PWA (cart icon in app shell)
- Issue [#16](https://github.com/strausmann/label-printer-hub/issues/16) — AppLookupService (gets new listing endpoints)
- Issue [#17](https://github.com/strausmann/label-printer-hub/issues/17) — visual layout editor
- Related: ADR 0005 (queue — batch is one job to it), ADR 0010 (PWA — cart is mobile-first), ADR 0012 (layout selection in detail view)
