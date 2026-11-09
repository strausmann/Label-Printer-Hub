# Print inbox: a server-side cart that other apps can fill

- **Date:** 2026-11-09
- **Status:** Draft, awaiting maintainer review.
- **Issue:** #27 (the comments of 2026-11-09 hold the maintainer's decisions verbatim). Blocked by #188. Related: #173 (Kept lookup), #255 (notification centre), #249 (cell-number colour), #242 (free-text search), #244 (item details), ADR [0013](../../decisions/0013-browse-cart-bulk-print-ui-pattern.md) (cart pattern; this document adopts its "Option D").
- **Builds on:** [`2026-06-04-multi-label-batch-design.md`](2026-06-04-multi-label-batch-design.md) (batch print), [`2026-11-05-sheet-archive-design.md`](2026-11-05-sheet-archive-design.md) (sheets, sheet preview and print), [`2026-05-16-phase6b-sse-eventbus-design.md`](2026-05-16-phase6b-sse-eventbus-design.md) (event bus), [`2026-05-17-phase-7c-api-auth-design.md`](2026-05-17-phase-7c-api-auth-design.md) (scopes).
- **API paths:** every path is written as it will be after 1.5.0 (#226, branch `feat/api-v1-status-manifest`), which moves all routes under `/api/v1`. Where this document cites today's code it names today's path.
- **Also related:** #11 (Grocy labels use case).
- **How decisions are marked:** the maintainer's decisions are listed in section 4 and followed as written. Rulings of the controller from the builder check (2026-11-09) are marked **(controller's call: …)** and are decided. A smaller decision this document makes on its own is marked inline as **(builder's call: …)**; all of them are collected in section 17. Questions only the maintainer can answer are in section 18.

## 1. Intent

The cart is a per-browser list in `localStorage`. What is collected on the phone cannot be printed from the desktop, and no other app can put anything in it. Integrations that fire a webhook print at once, onto the first tape printer.

That does not work for sheets. A die-cut label sheet has to be loaded into the laser before anything can print onto it, and nobody wants a sheet per purchase. The natural flow is: collect labels during the week, from the phone, from Grocy after a shopping scan, later from Kept; then stand at the laser, load a sheet, scan its QR code, and print what was collected onto exactly that sheet.

The print inbox is that collection, kept by the hub. It replaces the local cart, so every device sees the same list, and it is the place where integrations park items instead of printing them.

## 2. Goals, non-goals, anti-goals

**Goals**

1. A label added on the phone appears on the desktop's cart page without a reload, and the other way round.
2. A Grocy webhook after a shopping scan parks the product in the inbox when its route says so; a webhook routed to a page printer always parks.
3. At the laser: load a sheet, scan its QR code, see the selected inbox items placed on that sheet, print; only what was printed leaves the inbox.
4. The user chooses per device which lines go onto a print; the preview, the capacity check and the print button follow that choice.
5. The user decides in the hub settings whether parked items print the data captured when they were added, current data, or current data with the captured data as fallback.
6. The user can review, before printing, what changed at the source since an item was added, and accept or keep each change.
7. A retried webhook never adds an item twice.
8. A key handed to another app can add to the inbox and do nothing else.

**Non-goals** (this release)

- Named or multiple carts, "save for later" lists, per-user inboxes. The hub has no user records: API keys, sessions and SSO users all share one hub (section 5.5), so there is one inbox per hub.
- A per-integration override of the freshness setting (the decision allows it "optional/later"; section 9 leaves room for it).
- The global cart icon and the grouping/confirmation step decided for 1.6.1 in #27; this design keeps them possible (section 11.1) but does not specify them.
- A Kept lookup plugin. That is #173; the Kept receiver in section 8.3 needs it.
- Free-text search (#242) and item details (#244).
- Changes to Grocy itself. Possible later feature requests to grocy/grocy are listed in section 8.1.6, to be filed only after a positive reaction from the Grocy maintainer.

**Anti-goals** (must not happen)

- An item added to the inbox printing by itself. Parking means waiting for a person.
- A refresh changing a stored snapshot without the user accepting it.
- An enqueue-only key reading the inbox, printing, or deleting anything.
- A selection made on one device changing what another device prints.
- Upstream text (item names, titles, QR payloads) reaching the UI as markup or a link target, or a secret or request body appearing in an error message.

## 3. What exists today

All references are to `main`.

| Area | Today | Where |
|---|---|---|
| Cart storage | Client-side only, `localStorage` key `lph.cart`; a line is `{app, id, name, content_type, copies}`; same `(app, id)` merges and adds copies; copies clamped to 1–10 (`MAX_COPIES = 10`); apps `snipeit`, `grocy`, `spoolman` | `frontend/src/features/lookup/cart.ts:9-45` |
| Cart print (tape) | The **whole** cart is sent as one batch; no selection. Each line is sent as a `lookup`, so the server looks the item up again at print time (`toBatchItem`) — in the terms of this design, always `fresh` without fallback. Lines leave the cart only after `202`; copies added meanwhile stay (`removeItems`) | `cart.ts:122-182`, `CartPage.tsx:36-50` |
| Cart print (sheet) | When the chosen printer is IPP, `SheetSection` takes the whole cart, expands copies into items, renders a server preview (debounced) and prints; a partial print (`print_interrupted`) takes out only the queued copies | `features/sheets/print/SheetSection.tsx:78-290`, `CartPage.tsx:135-149` |
| Sheet preselect | `/cart?sheet=<code>`, linked from the sheet page; a scanned sheet QR opens the sheet page (`/sheet/{code}`), not the cart | `CartPage.tsx:29`, `features/sheets/SheetDetail.tsx:222`, `features/sheets/resolver.ts:49-53` |
| Sheet preview | `POST /api/print/{printer}/sheet/preview` (read scope, writes nothing): per page the cells with state `used/reserved/unconfirmed/new/free`, `item_index` for new cells, a PNG of the new content only, ID/feed-mark flags, `expected_cells`. Too many items for the target → `409 insufficient_cells`; the UI then offers another sheet or a split (`CapacityAlert`) | `backend/app/api/routes/sheet_print.py`, `schemas/sheet_print.py:160-247`, `SheetPreview.tsx`, `CapacityAlert.tsx` |
| Sheet preview list | Already lists "Cell N → label" per new cell; no app name, no highlight between list and image; cell numbers share the ink colour (#249) | `SheetPreview.tsx:70-81` |
| Batch print | `POST /api/print/{printer}/batch`, `print` scope, ≤ 500 items, each `data` (raw) **or** `lookup`; raw data is stored with `source_app = "manual"` | `api/routes/batch.py`, `schemas/print_batch.py`, `schemas/print_request.py:37-50` |
| Item bounds | Sheet items cap raw text: 512 per field, 10 secondary lines, 100 listing rows, QR payload 512 | `schemas/sheet_print.py:44-90` |
| Webhooks | `POST /api/webhook/spoolman` and `/grocy`, shared secret in the **required** header `X-API-Key` = setting `access.webhook_api_key`; look the item up, take the first enabled non-IPP printer, write a `queued` row. **The row never reaches the print queue (#188)** and its payload cannot be re-rendered. No idempotency, no content type, `quantity` is a stock delta, not copies | `api/routes/webhooks.py`, `api/dependencies/webhook_auth.py:43-46`, `schemas/webhook.py` |
| Grocy webhook format mismatch | `/grocy` expects JSON `{product_id, type, quantity}` (`GrocyWebhookPayload`, strict) and the `X-API-Key` header. Grocy's label-printer webhook sends neither (section 8.1): its fields are `product`, `grocycode`, `due_date` …, form-encoded by default, and it cannot set headers. **Every real Grocy call answers `422`** (a missing required header is already a `422` in FastAPI, before the body is read). Nothing working uses this path today | `schemas/webhook.py:40-55`, `webhook_auth.py` |
| Scopes | `read` ⊂ `print` ⊂ `admin`, linear. The effective scope is the highest of those three in the key's `scopes`; a key with none of them is refused `401 key_no_scopes`. Keys carry `allowed_printer_ids` and `rate_limit_per_minute` | `auth/dependencies.py:50-110, 236-305`, `models/api_key.py`, `auth/scope_deps.py` |
| Tenancy | No user model. Credentials are API keys, browser sessions minted from a key or an SSO trust header, and the Basic bypass. Everything a credential may see is hub-wide, restricted only by printer | `auth/dependencies.py:1-21`, `auth/sessions.py` |
| Settings | Flat key/value store, kinds `str/int/float/bool/url/secret/enum`, env locks a field (D4), secrets encrypted (D5); admin API `GET/PUT /api/v1/settings` | `settings_store/registry.py`, `api/routes/settings_api.py` |
| Integrations | Plugin contract `lookup(identifier) -> LabelData`; settings exist for `snipeit`, `grocy`, `spoolman`, `paperless`; no Kept plugin | `integrations/base.py`, `settings_store/registry.py:28-49` |
| Events | `GET /api/v1/events` SSE: channels `hub`, `sheets`, `printer:{id}:{queue,state,tape}` | `api/routes/events_v1.py` |
| Single-label render | `POST /api/render/preview` (PNG) | `api/routes/print.py:318` |
| Job history | Jobs store `payload`, `source_ip`, the API key; nothing says where the label data came from | `models/job.py` |

## 4. Maintainer decisions (binding)

1. **Server-side cart = print inbox**, replacing the localStorage cart, so phone and desktop share it and other apps can add to it. Existing local carts migrate to the server once on first load, then local storage is cleared. → sections 5, 13.
2. **Other apps park instead of printing.** Grocy (after a shopping scan), later Kept, put items into the inbox via API or webhook. A **routing rule per printer/integration** decides "print now" vs "park in inbox"; **page (sheet) printers always park**, because a sheet must be loaded first. → sections 7, 8.
3. **Flow at the laser:** load sheet → scan the sheet's QR → the inbox selection is applied onto that sheet. → section 11.4.
4. **Selection in the cart UI:** checkbox per line; header "select all" tri-state; typical flow select all then untick some; deselect all in one click (header box when all are selected, plus an always-visible "Clear selection" while anything is selected); the print button names the count ("Print 7 of 12 labels"); only printed lines leave the cart, the rest stays; the sheet capacity check counts selected labels × copies; selection is per device, not part of cart data; the whole row toggles, 44 px targets, Space toggles. → section 11.2.
5. **Sheet preview shows the selected items placed on the sheet:** rebuilt (debounced) on selection or copies change; cell number in the image plus a list "cell → item (app, name)" with two-way highlight; labels that do not fit shown as "next sheet"; used cells, new labels and the sheet ID stay distinct; cell numbers in their own colour (#249). → section 11.3.
6. **Data freshness is a hub setting:** `snapshot` | `fresh` | `fresh_with_fallback` (default). Every item always stores a snapshot; on fallback the print result and the job history flag "printed from snapshot". Per-integration override optional/later. → section 9.
7. **Manual "Refresh data":** re-looks up all items without changing snapshots; marks changed items ("4 of 12 changed"), flags unreachable/deleted separately; per item before/after rendered label side by side plus a field diff with only the changed fields; Accept / Keep per item; "Accept all changes" without per-item confirmation and "Keep all"; the preview rebuilds after accepting; with `snapshot` this is the only way data changes. Accept is guarded by a version token from the refresh → `409` if data changed in between. → sections 6.4, 11.5.
8. **Idempotency key per enqueued item** so retried webhooks never duplicate; inbox limits (max entries, expiry); an API key scope that may only enqueue, not print. → sections 5.3, 5.4, 12.
9. **Notification** "N labels wait for sheet printing" via #255. → section 10.
10. **#188 is fixed first.** → section 15.

## 5. Data model

### 5.1 `inbox_items`

One row per inbox line. (builder's call: a new SQLModel table with an Alembic migration, like the sheet tables; not the settings store and not a JSON blob, because lines are changed one at a time from several devices.)

| Field | Type | Meaning |
|---|---|---|
| `id` | UUID | Line id; the client's selection refers to it |
| `source_app` | enum `snipeit`, `grocy`, `spoolman`, `kept`, `manual` | Where the item lives. `kept` only once #173 ships a plugin; `manual` for raw data from the API (builder's call: `paperless` is left out until the cart can add Paperless items; the enum is the lookup route's `AppLiteral` plus `kept` and `manual`) |
| `item_ref` | str ≤ 120 | The identifier the plugin's `lookup` takes (same cap as `SheetItem.lookup.identifier`); null for `manual` |
| `content_type` | `ContentType` | How the label is laid out |
| `copies` | int 1–10 | Same bounds as `MAX_COPIES` and `PrintOptions.copies` |
| `snapshot` | JSON, the `SheetRawLabelData` shape (title, primary_id, qr_payload, secondary, items) with its bounds | The label data captured when the item was added or last accepted. **Always present** (decision 6) |
| `snapshot_at` | datetime | When the snapshot was captured |
| `snapshot_complete` | bool | False when the snapshot holds less than a lookup would give: items migrated from `localStorage` whose lookup failed (section 13, name only), and Grocy label webhooks parked from the payload alone while enrichment is pending or failed (section 8.1.3) |
| `version` | int, starts at 1 | Bumped by every write to the row (copies, snapshot accept, merge). Guards print and accept against concurrent changes |
| `origin` | enum `ui`, `webhook`, `api` | Who added it |
| `origin_detail` | str ≤ 64, nullable | Webhook source (`grocy`, `kept`, …) or the API key's name; never the key itself |
| `intended_printer_id` | UUID, nullable | The printer the routing rule named when it parked the item (section 7); null for UI adds. Used for the notification and the default printer choice, never as a restriction |
| `created_at`, `updated_at` | datetime | |
| `expires_at` | datetime | `created_at` + `inbox.expiry_days`; a merge does not extend it (builder's call: so a webhook firing daily cannot keep an item forever) |

**Line identity.** Like today's cart, a line is unique per `(source_app, item_ref, content_type)`; `manual` lines are never merged. Adding an item that already has a line adds the copies (clamped to 10), replaces the snapshot with the newly captured one and bumps `version`. (builder's call: the newer capture is the newer truth; open question Q2 carries the recommendation to split into two lines when a print-relevant field such as the best-before date differs.) A Grocy stock-entry label (section 8.1.2) uses the grocycode as `item_ref`, so two stock entries of one product are two lines anyway.

**Single process.** The hub runs as one backend process (D1). `revision` (section 6.1) is a counter persisted in the database (a one-row table, incremented in the same transaction as the write) (controller's call). Several workers would break three things: SSE events are published on the in-process event bus, so a second worker's clients would miss them; the 60-second preview lookup cache (section 9) and the duplicate windows (sections 6.2, 8.1) are in memory per process; the "one refresh at a time" rule (section 12.2) is an in-process lock. All three would need a shared store before the hub could scale out.

### 5.2 Selection is not data

The selection lives only in the browser (decision 4). The server has no field for it, and no endpoint accepts or returns it. See section 11.2 for where the client keeps it.

### 5.3 `inbox_idempotency`

| Field | Type | Meaning |
|---|---|---|
| `scope_key` | str | `<caller>:<idempotency key>`, so two callers cannot collide. `<caller>` is the API key id; for a browser session the id of the key it was minted from; for an SSO session the SSO user; for the shared webhook secret the literal `webhook`; for the localStorage migration the device id (section 13) (controller's call) |
| `request_hash` | str | SHA-256 of the normalised item request |
| `item_id` | UUID, nullable | The line the request created or merged into |
| `outcome` | enum `parked`, `printed`, `merged` | What happened the first time |
| `job_ids` | JSON, nullable | For `printed` (a webhook routed to print now) |
| `created_at` | datetime | |

Kept for `inbox.idempotency_days` (default 7) **after** the line is printed or removed, so a retry that arrives after the label was printed does not park it again. (builder's call: 7 days; Kept retries for about 24 hours, section 8.3, so 7 days is a wide margin.)

### 5.4 `inbox_refreshes` (short-lived)

One row per "Refresh data" run: `id`, `created_at`, `expires_at` (15 minutes, builder's call), and per item `item_id`, `item_version` at refresh time, `status` (`unchanged`, `changed`, `unavailable`, `deleted`), and for `changed` the candidate data. Accept writes the candidate the user saw, never data sent by the client (section 12.3). Rows are deleted on expiry.

### 5.5 Tenancy

One inbox per hub. Every credential that may read sees all lines; printer restrictions (`allowed_printer_ids`) limit where a credential can print, not which lines it sees. This matches the hub's model today (section 3, "Tenancy").

## 6. API

All routes under `/api/v1`. Errors use the hub's existing envelope `{error_code, error_message, error_detail?}`; validation errors name field paths only, like the sheet routes (`error_handlers`).

### 6.1 Reading

`GET /api/v1/inbox` — `read`.

Response:

```json
{
  "revision": 42,
  "items": [
    {
      "id": "…", "source_app": "grocy", "item_ref": "17", "content_type": "qr_two_lines",
      "copies": 2, "title": "…", "snapshot": { "title": "…", "primary_id": "…" },
      "snapshot_at": "…", "snapshot_complete": true, "version": 3,
      "origin": "webhook", "origin_detail": "grocy",
      "intended_printer_id": "…", "created_at": "…", "expires_at": "…"
    }
  ],
  "limits": { "max_items": 500, "expiry_days": 30 },
  "freshness": "fresh_with_fallback"
}
```

`revision` is a hub-wide counter, persisted in the database (section 5.1, "Single process"), bumped by every inbox write; the SSE event carries it (section 10), so a client knows whether its list is current. Order: `created_at` ascending, like today's cart.

### 6.2 Adding

`POST /api/v1/inbox/items` — `inbox` scope (section 12.1).

```json
{
  "items": [
    {
      "content_type": "qr_two_lines",
      "copies": 1,
      "lookup": { "app": "grocy", "identifier": "17" },
      "idempotency_key": "evt-…"
    },
    { "content_type": "text_one_line", "data": { "title": "…" }, "idempotency_key": "…" }
  ]
}
```

- `items`: 1–50 per request (builder's call: small enough that one request's lookups stay within a webhook caller's timeout).
- Each item has exactly one of `lookup` or `data`, like `SheetItem`. For `lookup` the server looks the item up **now** and stores the result as the snapshot. `data` is stored as given, bounded like `SheetRawLabelData`, with `source_app = "manual"`.
- `idempotency_key`: optional, 1–128 printable ASCII characters. An `Idempotency-Key` header is accepted for single-item requests and means the same.
- Without a key, a request with the same `(caller, request_hash)` within 60 seconds counts as a duplicate (builder's call: protects callers that cannot send a key, such as a plain Grocy webhook).
- `copies`: 1–10, default 1.

Response `200` (builder's call: `200` rather than `202`, nothing is queued):

```json
{ "revision": 43, "results": [ { "index": 0, "outcome": "parked", "item_id": "…", "duplicate": false } ] }
```

`outcome` is `parked` or `merged`; `duplicate: true` when the idempotency record answered. The response never includes the stored snapshot (an enqueue-only key must not read inventory data back, section 12.1).

Errors:

| Status | `error_code` | When |
|---|---|---|
| 409 | `inbox_full` | The add would exceed `inbox.max_items` **labels** (copies counted, section 12.2). Nothing of the request is stored (all or nothing) |
| 409 | `idempotency_conflict` | The key was used before with a different request body. `error_detail` names the item `index` only |
| 422 | `invalid_request` | Schema error (field paths only) |
| 422 | `integration_unknown_app` | Unknown or not installed integration |
| 404 | `app-lookup-not-found` | The integration has no such item; carries `item_index` |
| 502 | `integration_lookup_failed` | The source failed or is unreachable; nothing stored, safe to retry with the same keys (builder's call: this route's callers can retry, so refusing keeps snapshots complete; see Q3. The Grocy label webhook, which never retries, parks from its payload instead, section 8.1.3) |
| 503 | `integration_not_configured` | |
| 429 | existing rate-limit error | Per-key `rate_limit_per_minute` |

### 6.3 Changing and removing

All `print` scope (builder's call: changing the shared inbox is closer to printing than to reading; an enqueue-only key must not delete what others parked, and a read-only session must not either; see Q5).

| Route | Body | Effect |
|---|---|---|
| `PATCH /api/v1/inbox/items/{id}` | `{ "version": 3, "copies": 4 }` | Sets copies |
| `DELETE /api/v1/inbox/items/{id}?version=3` | — | Removes the line |
| `POST /api/v1/inbox/remove` | `{ "items": [{ "id": "…", "version": 3 }] }` | Removes several lines (the cart's "Remove selected") |
| `DELETE /api/v1/inbox` | `{ "revision": 43 }` | Empties the inbox ("Empty the cart") |

A stale `version` (or `revision`) gives `409 inbox_item_changed` with the current line(s) in `error_detail`; a missing line gives `404 inbox_item_not_found`.

### 6.4 Refresh and accept

`POST /api/v1/inbox/refresh` — `print`. Body: optional `{ "item_ids": [...] }`, default all lines. Looks every item up again (concurrency bounded, builder's call: at most 4 lookups in flight per integration). **Writes no snapshot.** Creates an `inbox_refreshes` row and answers:

```json
{
  "refresh_id": "…", "expires_at": "…",
  "summary": { "total": 12, "changed": 4, "unchanged": 6, "unavailable": 1, "deleted": 1 },
  "items": [
    { "item_id": "…", "item_version": 3, "status": "changed",
      "changes": [ { "field": "title", "before": "…", "after": "…" },
                   { "field": "secondary[0]", "before": "…", "after": "…" } ] },
    { "item_id": "…", "item_version": 1, "status": "unavailable" }
  ]
}
```

- `changes` lists only fields whose value differs; unchanged fields are absent. Fields are the snapshot fields; list rows (`items`) are compared per row.
- `unavailable` = the source failed or is unreachable; `deleted` = the plugin raised its not-found error. Both keep their snapshot and carry no `changes`.
- `manual` lines are always `unchanged` (no source).

`GET /api/v1/inbox/refresh/{refresh_id}/items/{item_id}/render?side=before|after&printer=<key>` — `read`. A PNG of the stored (`before`) or candidate (`after`) data, rendered like `POST /api/v1/render/preview` for the given tape printer; for a page printer, rendered as one cell of the sheet type the cart has selected (builder's call: one route for both sides, so the client never handles candidate data itself).

`POST /api/v1/inbox/refresh/{refresh_id}/accept` — `print`. Body `{ "items": [{ "item_id": "…", "item_version": 3 }] }` or `{ "all": true }`.

- Writes the candidate data of each named `changed` item as its new snapshot, sets `snapshot_at`, bumps `version`.
- `all: true` accepts exactly the `changed` items of this refresh; `unavailable`, `deleted` and `unchanged` items are untouched.
- "Keep" and "Keep all" are client-only: nothing is written, the refresh row expires.
- Errors: `409 inbox_item_changed` when a line's `version` differs from the `item_version` the refresh recorded (the line was edited, merged or accepted elsewhere in between) — **nothing** of the request is written, `error_detail` lists the stale ids; `409 refresh_expired` after `expires_at`; `404 refresh_not_found`; `422 not_changed` when a named item is not `changed` in this refresh.

### 6.5 Printing from the inbox

The client sends line ids, the server builds the print. (builder's call: the server, not the client, resolves the data per the freshness setting, flags fallbacks and removes printed lines in the same transaction that accepts the print; a client-side build could not do the last two reliably.)

**Tape:** `POST /api/v1/inbox/print/{printer_key}` — `print`, printer ACL.

```json
{ "items": [ { "id": "…", "version": 3 } ], "half_cut_override": null }
```

Resolves each line (section 9), submits **one batch** through the same path as `POST /api/v1/print/{printer}/batch` (`dispatch_batch`), keeps `source_app` and `item_ref` in the job payload instead of `"manual"`, and in the same transaction removes the printed lines. Response = the batch response plus per item `{ "id", "data_source": "fresh" | "snapshot" | "snapshot_fallback" }`. All errors of the batch route apply; additionally `409 inbox_item_changed` (stale version, nothing printed), `409 media_kind_mismatch` for an IPP printer, and `422 selection_too_large` when the selected lines expand to more than 500 labels (the existing `MAX_ITEMS`; `error_detail: {labels, max}`). (controller's call: refused with a named code; the UI disables the print button and says why, section 11.2.)

**Sheet:** `POST /api/v1/inbox/sheet/preview/{printer_key}` — `read`; `POST /api/v1/inbox/sheet/print/{printer_key}` — `print`.

```json
{
  "items": [ { "id": "…", "version": 3 } ],
  "placements": [ { "sheet": "L4736-0012", "cells": "first_free", "skip": [] } ],
  "tray": null,
  "overflow": "next_sheet",
  "expected_cells": null
}
```

- Lines are expanded into one sheet item per copy, in the order sent, mapped to `SheetItem` with raw `data`, `source = source_app`, `ref = item_ref`, `purpose = title` (so the sheet records the same purpose and reference a lookup item gets today).
- `overflow: "next_sheet"` (default for this route): when the placements cannot take every label, the preview fills what fits and returns the rest instead of `409 insufficient_cells`. `overflow: "refuse"` keeps today's behaviour. **`next_sheet` is only a leftover list:** the route never adds a second placement or a new sheet for the overflow within the same print; the leftover lines stay in the inbox until the next sheet is scanned (controller's call).
- **Content type against sheet type** is checked here, at preview and print time, never when an item is added (controller's call). A line whose content type the chosen sheet type cannot render (today the planner's `content_type_data_mismatch` per `item_index`) is not a reason to refuse the whole request: it is listed under `not_printable` with the reason and excluded from the plan and the print; the remaining lines are placed.
- More than 500 expanded labels → `422 selection_too_large`, as for tape.
- The preview response is the existing `SheetPreview` plus:
  - `item_map`: per expanded item index `{ "inbox_item_id", "copy": 1..n, "source_app", "title" }`;
  - `next_sheet`: the expanded items that are not placed, same shape;
  - `not_printable`: per line `{ "inbox_item_id", "reason": "content_type_not_supported" | "unavailable" }`;
  - `data_sources`: per line, as above.
- The print takes `expected_cells` from the preview as today (`409 plan_changed`), prints only the placed labels, removes them from the inbox, and leaves the `next_sheet` and `not_printable` lines in it. A partial print (`502 print_interrupted`) removes only the copies whose pages were queued, as `SheetSection` does today (`SheetSection.tsx:262-282`), now on the server.
- Removal happens when the hub **accepts** the print (`202`), not when the printer reports it done — today's behaviour. A job that fails later is retried from the job history, not from the inbox. (builder's call: unchanged semantics; a failed sheet job leaves its cells `unconfirmed` per D15 anyway.)

## 7. Routing rule

Decides what a webhook or a routed API call does: print now or park. Stored as settings per integration (builder's call: the settings store already has per-integration keys, an admin UI and env locks; a table is not needed for four integrations):

| Key | Kind | Default | Meaning |
|---|---|---|---|
| `inbox.route.<app>.action` | enum `park`, `print` | `park` | What a webhook from `<app>` does |
| `inbox.route.<app>.printer` | str (printer slug), empty = none | empty | The target printer |
| `inbox.route.<app>.content_type` | enum `ContentType` | per app, the content type the integration page offers first (builder's call) | Webhooks carry no content type (`schemas/webhook.py`) |

`<app>` ∈ `grocy`, `spoolman`, later `kept`. The Grocy label webhook can override the rule per call with `printer` and `mode` parameters (section 8.1.4).

The default `park` is acceptable although it changes what a webhook does: because of #188 nothing prints through a webhook today, and #188 ships in the same release or earlier (controller's call).

Evaluation, in this order:

1. The target printer is a **page printer** (`backend == "ipp"`) → **park**, whatever `action` says (decision 2). `intended_printer_id` is set to it.
2. `action = park` → park; `intended_printer_id` = the printer if one is set.
3. `action = print` and a tape printer is set, enabled and reachable → print now through the path #188 repairs; the response names the job.
4. `action = print` and no printer is set → the first enabled tape printer, as today (`webhooks.py:66-82`).
5. `action = print` and the printer is disabled, missing or offline → **park** and log a warning (builder's call: a label that waits is better than one that is lost); the webhook response says `parked` and why (`reason: "printer_unavailable"`).

The settings page validates that a `print` route does not name an IPP printer and says that such a route parks. The rule applies per integration and names a printer, which covers "per printer/integration": the printer's kind decides rule 1, the integration selects the rule.

`POST /api/v1/inbox/items` (section 6.2) always parks; it never consults the rule (an enqueue-only key cannot print).

## 8. Webhook changes

### 8.1 Grocy label webhook (new, in Grocy's own format)

**What Grocy actually sends** (verified against Grocy's `docs/label-printing.md` and `helpers/WebhookRunner.php`, 2026-11-09):

- Configured through `LABEL_PRINTER_WEBHOOK` (URL), `LABEL_PRINTER_RUN_SERVER` (server or browser sends it), `LABEL_PRINTER_PARAMS` (fixed extra fields) and `LABEL_PRINTER_HOOK_JSON` (JSON instead of form encoding).
- A POST with the fields `product`, `grocycode`, `due_date` and others; since Grocy 4.5.0 also `details` (the full object); for a stock-entry label `stock_entry`. **Form-encoded by default**, JSON only with `LABEL_PRINTER_HOOK_JSON`. The grocycode is printed as a 1D (Code128) or 2D (DataMatrix) code; its content is the grocycode string.
- The server-side runner uses a Guzzle client with a **2.0 s timeout**, sends **no custom headers** (only `form_params` or `json`), catches every failure and only logs it to stderr — **no retry** — and logs the full request arguments, `LABEL_PRINTER_PARAMS` included, to stderr.
- With `LABEL_PRINTER_RUN_SERVER=false` the browser sends the call, and the configuration values, params included, are delivered to every Grocy client.
- Grocy also prints on its own: on an automatic due-date change and when a recipe "produces" a product (server-side webhook only).

The existing `/api/webhook/grocy` matches none of this (section 3). The design adds a receiver that takes Grocy's format as it is.

#### 8.1.1 Endpoint

`POST /api/v1/webhook/grocy/label`, accepting `application/x-www-form-urlencoded` **and** `application/json` with the same fields. Unknown fields are ignored (Grocy adds fields between versions); the body is capped at 64 KiB (builder's call: `details` is a full product object, still small).

#### 8.1.2 Mapping into the snapshot

| Grocy field | Snapshot |
|---|---|
| `product` (name) | `title` |
| `grocycode` | `qr_payload` (the code's content) and `primary_id`; also `item_ref` |
| `due_date` | first `secondary` line, formatted per `general.language` ("Best before …"); omitted when empty or Grocy's "never" date |
| `stock_entry` (amount, unit, location when present) | further `secondary` lines |
| `details` | read for name, unit and default location when the flat fields are missing; never stored as a whole |

`source_app = grocy`. The content type comes from the routing rule (`inbox.route.grocy.content_type`). The grocycode is the line identity, so a product label and a stock-entry label are different lines, and two stock entries are two lines. Every value is bounded like `SheetRawLabelData` and treated as untrusted text (section 12.4).

#### 8.1.3 Answer within Grocy's 2-second budget

- The receiver parks or submits **from the payload alone**, synchronously, and answers well inside 2 s. It does **not** call Grocy's API in the request. Because Grocy never retries, a slow or failed request loses the label — persisting from the payload is mandatory.
- An enrichment lookup (the Grocy plugin, when configured) may run afterwards as a background task and replaces the snapshot only while the line is unchanged (`version` check); until it succeeds the line is `snapshot_complete: false`. If the plugin is not configured or Grocy's API is down, the line stays as parked from the payload and is printable (this answers open question Q3 for Grocy; it stays open for the generic route, section 6.2). (builder's call: enrichment is optional and never blocks.)
- "Print now" (section 8.1.4) submits through the #188 path with the payload data; it waits for the queue's acceptance, not for the printer.

#### 8.1.4 Auth, target and mode — without headers

Grocy cannot send headers, so the credential travels in the URL or the body:

- `token=<key>` as a query parameter in `LABEL_PRINTER_WEBHOOK` or as a field in `LABEL_PRINTER_PARAMS`. It is a normal hub API key (`lh_…`) and **must be a dedicated low-privilege key**: `inbox` scope, or `print` limited to one printer through `allowed_printer_ids`. The token ends up in Grocy's stderr log and, in browser mode, in every Grocy client; the key form says so when the key is created for Grocy, and the docs recommend server mode. An `admin` key is refused on this route (`403 token_scope_too_broad`, builder's call).
- `printer=<slug or id>` and `mode=print|collect` (`collect` = park in the inbox), as query or body parameters; both default to the routing rule. Rule 1 of section 7 still applies: a page printer always parks. `mode=print` needs a key with `print` on that printer; an `inbox`-only key with `mode=print` parks and answers `reason: "key_cannot_print"` (builder's call: the label is not lost).
- **Browser mode** needs CORS for the Grocy origin: a setting `integrations.grocy.webhook_cors_origin` (empty = no CORS); only this route answers the preflight, with that single origin, `POST` only, no credentials (builder's call).
- **Our side never logs the token**: the access log entry of this route has the query string removed, error bodies never echo it, and the token is not stored in the idempotency record (only the key id).

#### 8.1.5 Duplicates, responses, the old endpoint

- Grocy sends no event id and never retries; the only duplicates are double clicks or two open tabs. Dedupe by `(key id, request hash)` within 10 seconds (builder's call: shorter than the generic 60 s, because printing the same label twice on purpose a minute later is normal in Grocy).
- Response `200` `{ "outcome": "parked" | "printed" | "duplicate", "item_id"?, "job_id"?, "reason"? }`. Grocy ignores the body; it is for logs and tests. Errors keep the envelope; an unknown token is `401` with a fixed message.
- Automatic prints Grocy sends (due-date change, recipe "produces") arrive the same way and follow the same rule; with the default `park` they collect in the inbox instead of printing unasked.
- **The old `POST /api/v1/webhook/grocy`** (JSON `{product_id, type, quantity}`, `X-API-Key`) is **removed** (builder's call: nothing working uses it — every real Grocy call fails there — and 1.x carries no compatibility promise for it). The release notes point to `/grocy/label`. A caller with its own JSON events uses `POST /api/v1/inbox/items`.

#### 8.1.6 Future, outside this design

Possible feature requests to grocy/grocy, **only after a positive reaction from the Grocy maintainer**: custom headers for the label-printer webhook (so the token can leave the URL); a per-print choice of printer and print/collect in Grocy's UI; printing several products in one webhook call.

### 8.1a Spoolman

`POST /api/v1/webhook/spoolman` keeps its payload and its shared-secret header `X-API-Key` (`access.webhook_api_key`) and additionally accepts `X-Label-Hub-Key` with `inbox` scope or higher (builder's call: a per-app key that can be revoked on its own). (Whether this payload matches what Spoolman sends was not checked for this design; it should be, the same way Grocy was.)

- Look the item up (snapshot), apply the routing rule (section 7), then park or print.
- Idempotency: an `Idempotency-Key` header if the caller sends one; otherwise the 60-second duplicate window of section 6.2 over `(app, entity id, type)`.
- `quantity` is remaining grams and is **not** used as copies (`schemas/webhook.py`); copies are 1.
- Response `202` with `{ "outcome": "parked" | "printed", "item_id"?, "job_id"?, "reason"? }`. `job_id` keeps its name for existing callers.
- The docstrings and OpenAPI descriptions say what happens (#188 acceptance).

### 8.2 Generic callers

Any app or script uses `POST /api/v1/inbox/items` with an `inbox`-scoped key. This is the path for callers without a dedicated receiver.

### 8.3 Kept

**Finding (2026-11-09):** Kept can send outgoing webhooks — [Kept docs, "Webhooks"](https://github.com/keptinventory/kept/blob/main/apps/docs/src/content/docs/users/webhooks.md). Per location, signed POSTs for `thing.created`, `thing.updated`, `thing.moved`, `thing.trashed`, `thing.restored`, `thing.lifecycle_changed`, `reading.logged`, `reminder.due`. The body carries an event `id` (`evt_…`), the entity type and id and the names of changed fields, **never values**; the receiver fetches the thing through Kept's API. Signature header `Kept-Signature: t=<unix>,v1=<HMAC-SHA256 of "<t>.<body>">`, secret shown once in Kept. Up to 10 attempts over about 24 hours; redirects are not followed; Kept refuses private addresses unless an instance admin allows them.

Design:

- `POST /api/v1/webhook/kept`, authenticated **only** by the signature: constant-time compare, timestamp no older than 5 minutes, secret in a new secret setting `integrations.kept.webhook_secret` (D5, write-only). No API key header (Kept cannot send one).
- Kept's event `id` is the idempotency key, so Kept's retries never duplicate.
- Events that enqueue: `thing.created` (builder's call; which events should print is open question Q1). Other events answer `202 { "outcome": "ignored" }`; `ping` answers `200`.
- The receiver looks the thing up through the Kept plugin of #173 and applies the routing rule for `kept`. **Until #173 ships, the route does not exist.** Alternatively Kept (or a script around it) can call `POST /api/v1/inbox/items` with an `inbox` key and `data` it already has — that works from day one.
- Kept's docs mark thing names as user-written data; the hub treats them as untrusted text (section 12.4).

## 9. Data freshness

Hub setting `inbox.freshness`, enum `snapshot` | `fresh` | `fresh_with_fallback`, default `fresh_with_fallback` (decision 6). Shown on the settings page under "Print inbox", with one sentence per option.

| Setting | At print and preview time |
|---|---|
| `snapshot` | No lookup. The stored snapshot is printed. The integration client is not called |
| `fresh` | Lookup; on failure or not-found the print is refused with the integration's error, as the batch route does today |
| `fresh_with_fallback` | Lookup; on `integration_lookup_failed`, `integration_not_configured` or not-found the snapshot is printed and the line is flagged `snapshot_fallback` |

- A fresh lookup at print time does **not** overwrite the snapshot. Only an accept (section 6.4) or a re-add (section 5.1) does.
- The flag reaches three places: the print response (`data_sources`), the job row (a new nullable column `data_source` with `fresh`, `snapshot` or `snapshot_fallback`, added by an additive Alembic migration (controller's call); exposed on the job APIs as `printed_from_snapshot: bool` plus the reason) and the job list in the UI ("Printed from snapshot" badge).
- **Preview under `fresh`:** a line whose lookup fails is marked `unavailable` in the preview (`not_printable`, reason `unavailable`) and the rest renders; the print then follows the setting's rule for that line (refused under `fresh`, snapshot under `fresh_with_fallback`) (controller's call).
- A `snapshot_complete: false` line (section 13) prints its name only under `snapshot` or on fallback; the UI warns on the line.
- The preview resolves data the same way as the print. Lookups made for a preview are cached per `(app, ref)` for 60 seconds so the debounced re-previews do not hammer the source; **failures are cached like successes** for the same window (controller's call); the print always looks up again (builder's call).
- A per-integration override would be `inbox.freshness.<app>` with the hub setting as fallback; not built now.

## 10. Events and notification

- New SSE channel `inbox`, subscribed for every `read` caller in `events_v1.py` (no printer restriction, like `sheets`).
- Event `inbox.changed`: `{ "revision": 43, "reason": "added" | "updated" | "removed" | "printed" | "expired" | "accepted", "item_ids": [...], "count": 12, "labels": 19, "waiting_for_sheet": 9 }`. No titles or data (builder's call: clients refetch `GET /api/v1/inbox`; keeps upstream text out of the event log and the metrics).
- The SSE snapshot on connect includes the current `inbox` counts, so a reconnect resyncs.
- The cart page refetches on `inbox.changed` when `revision` is newer than its own; a second device sees an add within one event.
- **Notification (#255):** while `waiting_for_sheet > 0`, the notification centre shows one entry "N labels wait for sheet printing", severity info, updated in place by `inbox.changed`, opening `/cart` with the intended page printer preselected. `waiting_for_sheet` = sum of copies of lines whose `intended_printer_id` is a page printer (builder's call: lines added in the UI have no intended printer and do not count). If #255 is not built when this ships, the cart link in the top bar shows the count instead and the entry is added with #255.

## 11. UI

Design skills for the build: `taste-skill:design-taste-frontend` and `emil-design-eng` for the cart and the diff view, `break-ui` for long names and many lines, `mobile-native` for the phone flow, `impeccable:impeccable` for acceptance.

### 11.1 Cart page

`CartPage.tsx` keeps its structure; the data now comes from `GET /api/v1/inbox` through TanStack Query, kept current by `inbox.changed`. `useCart()` keeps its shape where it can (items, add, remove, setCopies, clear, print) so the item view's "Add to cart" (`ItemView.tsx`) only swaps its implementation.

Per line: checkbox, name (link to the item view), app and id, origin badge for `webhook`/`api` ("from Grocy"), copies, Remove, and the badges of section 11.5. Copies changes are sent debounced with the line's `version`; a `409` refetches and keeps the user's value in the field with a note (builder's call).

Read-only sessions see the inbox but no checkboxes, copies fields or buttons; the page says that printing needs a print key.

The grouping/confirmation step and the global cart icon of #27 (1.6.1) build on this page: both read the server inbox; the badge counts `labels`.

### 11.2 Selection

- Checkbox per line; header checkbox tri-state (none / some / all). When all are selected the header box clears the selection; otherwise it selects all.
- "Clear selection" is a visible button while at least one line is selected.
- The whole row toggles (not the name link, the copies field or Remove). Touch targets at least 44 px. A focused row toggles with Space; the list is one tab stop with arrow keys between rows (builder's call: roving focus, so a long inbox is not 60 tab stops).
- The print button names count and total in labels, copies included: "Print 7 of 12 labels"; with everything selected "Print 12 labels"; disabled with nothing selected, and disabled with the reason shown ("At most 500 labels per print") when the selection exceeds 500 labels (controller's call).
- The sheet capacity check counts selected labels × copies against the target's free cells.
- Only printed lines leave the inbox; unselected lines and `next_sheet` labels stay.
- **Where it lives:** `localStorage` key `lph.inbox.selection` (builder's call: per device, survives a reload, as the decision requires "per device"), a set of line ids, pruned to ids that still exist on every inbox fetch. It is never sent except as the list of lines to print or preview.
- **Defaults** (builder's call): with no stored selection, all lines are selected (today the whole cart prints). Lines that arrive later through SSE are **not** selected, so a webhook during the preview cannot add a label to a print the user already looked at; the header box then shows "some".

### 11.3 Sheet preview

`SheetSection` takes the selected lines and calls the inbox preview (section 6.5) instead of the raw sheet preview.

- Rebuilds, debounced like today (`useDebounced`, `PREVIEW_DEBOUNCE_MS`), whenever the selection, a line's copies or an accepted snapshot changes.
- The page image shows the cell number on each new cell; the list beside it reads "Cell 14 → Grocy · Oat milk" (`item_map`), copies numbered when a line has more than one ("Oat milk (2/3)").
- Two-way highlight: hovering or focusing a list entry highlights its cell; hovering or tapping a cell highlights and scrolls to its entry. On touch, tap toggles the highlight.
- `next_sheet` labels are listed under "Next sheet" with their names and count, not dropped and not an error. They are not placed onto a second sheet in this print; they stay in the inbox (and stay selected, builder's call) until the next sheet is scanned. The print button counts only placed labels ("Print 9 of 12 labels onto L4736-0012").
- `not_printable` lines are listed under "Not printable on this sheet type" (or "Source unreachable" under `fresh`) with the reason, excluded from the print, and stay in the inbox.
- The existing distinction stays: used cells, reserved/unconfirmed, the new labels, the sheet ID and the feed mark. Cell numbers use the token from #249 and the legend "1 = cell number (not printed)".
- `data_sources` shows a small "snapshot" marker on lines that would print from the snapshot under `fresh_with_fallback` (the preview already knows).

### 11.4 Scan → sheet at the laser

- The sheet scan resolver (`features/sheets/resolver.ts`) resolves a sheet code to `/cart?sheet=<code>` **when the inbox has at least one line**, otherwise to the sheet page as today (builder's call).
- On `/cart?sheet=<code>` the printer picker preselects the page printer that last printed onto this sheet, else the line's `intended_printer_id`, else the only usable page printer; if none fits, the user picks (builder's call).
- The scan offers **all** inbox lines, whatever their `intended_printer_id` (controller's call); the selection applies as usual. Lines the sheet type cannot render are shown as "not printable on this sheet type" (section 6.5), not refused wholesale.
- The preview shows the current selection on that sheet immediately. One more tap prints.
- A discarded, full or unknown sheet keeps today's notes (`SheetSection.tsx:120-128`).

### 11.5 Refresh and diff

- "Refresh data" button on the cart page (print scope). While it runs, lines show a spinner; afterwards a summary: "4 of 12 changed · 1 unreachable · 1 deleted at the source".
- Badges on lines: "Changed", "Source unreachable", "Deleted at source". The last two keep their snapshot and say so.
- Opening a changed line shows **before and after as rendered labels side by side** (stacked on phones), from the render route of section 6.4, and below it a field diff with only the changed fields, old value struck through, new value highlighted. Field labels are human names ("Name", "Best before", "Location", "Code"), mapped from the snapshot fields per integration (builder's call: a fixed mapping per app; unknown fields show their key).
- Per line: "Accept" / "Keep". At the top: "Accept all changes" (no per-item confirmation) and "Keep all".
- After an accept the preview rebuilds. A `409 inbox_item_changed` says "This item changed since the refresh. Refresh again." and offers the button; nothing was written.
- With `inbox.freshness = snapshot` the page explains that refreshing is the only way data changes; with the fresh modes it says the print uses current data anyway and the refresh lets you see it first.
- Values in the diff are text. Long values wrap (`overflow-wrap:anywhere`), as the preview list does.

### 11.6 Mobile

At 390 px the cart is a single column: lines with the checkbox at the leading edge, a sticky bottom bar with the selection count, "Clear selection" and the print button; the sheet preview under the list, the cell list collapsible like today's "Show the N cells". The diff view is a full-height sheet with before above after. Safe-area insets on the sticky bar; no zoom on the copies input (16 px font).

### 11.7 Strings

English and German for every new string (D8). Counts through `plural`.

## 12. Security

### 12.1 Scope `inbox`

- **Scopes become a set, not only a chain** (controller's call). The chain `read` ⊂ `print` ⊂ `admin` stays; `inbox` is **additive**: a key's `scopes` list may hold `inbox` alone or together with others (for example `inbox` + `read`), and the effective permission is the **union** of what each listed scope grants. `print` and `admin` grant `inbox`; `inbox` grants neither `read` nor `print`.
- An `inbox`-only key can call `POST /api/v1/inbox/items` and the webhook routes, and nothing else — not `GET /api/v1/inbox`, not the event stream, not any print route.
- `auth/dependencies.py` today reduces `scopes` to one effective scope from `["admin", "print", "read"]` and answers `401 key_no_scopes` for any other list (`dependencies.py:244-262`); `AuthContext.scope` is a single `Literal`. This changes to a set of granted capabilities on `AuthContext`; `require_scope(x)` checks membership; `require_inbox` joins `scope_deps.py`. The existing single `scope` field stays for logging and for routes that read it (the highest chain scope, or `inbox`). The admin key form offers `inbox` as a checkbox next to the chain with the text "Can add items to the print inbox".
- **Browser sessions** carry the capabilities of the key they were minted from, `inbox` included; the session row's scope becomes the same set (builder's call: stored as the key's scope list, re-read from the key on every use as `load_valid` already does for `allowed_printer_ids`).
- The enqueue response never returns stored data (section 6.2), so the key cannot be used to read the inventory back through lookups.
- `allowed_printer_ids` does not restrict enqueue (nothing prints). It restricts the inbox print routes as everywhere.
- The Basic bypass and SSO header paths resolve to the required scope today; for `inbox` they behave the same as for `print` (builder's call; with `pangolin_bypass_scope_downgrade` the bypass cannot enqueue).

### 12.2 Limits

| Setting | Default | Effect |
|---|---|---|
| `inbox.max_items` | 500 (the batch and sheet item cap) | Counts **labels**, copies included (controller's call); more → `409 inbox_full` |
| `inbox.expiry_days` | 30 | Lines older than this are removed by the existing cleanup task (`services/cleanup_task.py`) with `inbox.changed reason=expired`, and hidden from reads once past `expires_at` even before the sweep |
| `inbox.idempotency_days` | 7 | Retention of idempotency records |

A print selection above the existing `MAX_ITEMS` (500 labels) is refused with `422 selection_too_large` (section 6.5).

Per request: ≤ 50 items, body ≤ 256 KiB (builder's call; 64 KiB on the Grocy label route), raw text bounded as `SheetRawLabelData`, `idempotency_key` ≤ 128. The per-key rate limit applies; the shared webhook secret gets a fixed limit of 60 requests per minute (builder's call). Refresh: one running refresh per hub at a time (`409 refresh_running`, builder's call).

### 12.3 No echo, no client-supplied snapshots

- Error bodies never contain the request body, an idempotency key, a header value, the webhook secret or an upstream URL; integration failures keep the fixed messages of `batch.py` (CWE-209).
- Logs name line ids and app names, never titles or keys (`log_value`).
- A snapshot is only ever written from a lookup the server made, from `data` the caller added as `manual`, or from a refresh candidate the server stored. Accept takes ids, never data.
- The Kept receiver compares signatures in constant time and refuses stale timestamps; the secret is write-only (D5).
- The Grocy label route takes its token from the URL or body (section 8.1.4): the query string is stripped from the access log for this route, the token is never logged, stored or echoed, and an `admin` key is refused there.

### 12.4 Upstream text is untrusted (taint)

Titles, secondary lines, list rows and QR payloads come from Grocy (including the label webhook's form fields, which in browser mode any Grocy client can forge), Snipe-IT, Spoolman, Kept or an API caller. They reach the cart list, the cell list, the diff view, the notification, the job history and the rendered labels.

- Rendered as text nodes only (React escaping); no `dangerouslySetInnerHTML`, no `title`/`aria-label` built from them beyond plain interpolation.
- Never used as a link target. The line's link goes to the hub's own item view by `(app, item_ref)`, encoded; a QR payload is never an `href`.
- Bounded on the way in (section 12.2); the renderer shortens what does not fit, as today.
- Not put into SSE events (section 10) or metric labels.

## 13. Migration from `localStorage`

- On the first load of the cart page or of any page that uses `useCart()`, if `lph.cart` holds lines and the key `lph.cart.migrated` is absent, the client sends them to `POST /api/v1/inbox/import` (`print` scope, builder's call: same as other inbox writes; `inbox` would let an enqueue key bypass the add path's rules).
- `import` takes the old line shape `{app, id, name, content_type, copies}` (≤ 500 lines), looks each item up for a snapshot, and on lookup failure stores a snapshot with only `title = name` and `snapshot_complete: false` instead of refusing (builder's call: the user's cart must not be lost because a source is down). Lines merge into existing ones by the rule of section 5.1. `origin = ui`.
- Idempotency: the client generates a random device id once (`lph.device`), and each line's key is `<device id>:<app>:<id>`, so two tabs migrating at the same time, or a retry after a lost response, import once.
- After a `2xx` the client writes `lph.cart.migrated` and removes `lph.cart`. On any error it keeps `lph.cart` and tries again on the next load; the page shows the server inbox plus a note "N items from this browser could not be moved yet".
- A read-only session does not migrate; it keeps `lph.cart` untouched and says that a print key is needed to move it.
- The `storage`-event sync between tabs (`cart.ts:84-95`) is removed; SSE replaces it.
- After two releases the migration code can go (builder's call).

## 14. Testing

Every test that guards a rule has a counter-test against the code without the rule (`test-coverage-pflicht`): remove the guard, the test must turn red **for the right reason**.

**Backend (pytest)**

- Enqueue: lookup item → snapshot stored; `data` item → `manual`; same key twice → one line, second `duplicate: true`; same key with another body → `409 idempotency_conflict`; key reused after the line was printed → still no new line (counter-test: delete the record on print → the test sees a second line); 60-second window without key.
- Limits: an add that brings the inbox to 501 **labels** (e.g. 499 labels + one line with 2 copies) → `409 inbox_full` and nothing of the request stored (counter-test: count lines instead of labels → the test turns red); expired lines hidden before the sweep and removed by it; a print selection of 501 labels → `422 selection_too_large`, nothing queued.
- Scope set: a key with `["inbox", "read"]` can enqueue **and** read; `["inbox"]` only enqueue; a session minted from an `inbox`+`read` key can enqueue. Counter-test: keep the old "highest of three" reduction → the `["inbox", "read"]` key loses one of the two and a test turns red.
- Scope: an `inbox` key can enqueue; it gets `403` on `GET /api/v1/inbox`, the event stream, every print route, PATCH/DELETE; a `read` key gets `403` on enqueue; `print` and `admin` can enqueue. Counter-test: make `inbox` imply `read` → the read test turns red. The enqueue response contains no snapshot field (assert on the raw JSON, not the parsed model).
- Routing: IPP target with `action=print` → parked (counter-test: drop rule 1 → printed); `park` → parked with `intended_printer_id`; `print` with an offline tape printer → parked with reason; `print` → job reaches the queue and a recording backend prints it (depends on #188).
- Freshness: `snapshot` → the integration client receives **no** call (assert on the client mock's call count, not on the output); `fresh_with_fallback` with the source down → snapshot printed, job row `data_source = snapshot_fallback`; with the item deleted → same; `fresh` with the source down → `502`, nothing printed, lines unchanged. The fallback test must distinguish "snapshot because fallback" from "snapshot because the lookup was skipped": assert the client **was** called.
- Print: stale version → `409`, nothing queued, nothing removed; success → exactly the sent lines removed in the same transaction; partial sheet print → only queued copies removed; `next_sheet` labels stay; job payload keeps `source_app` (not `manual`).
- Refresh: never writes a snapshot (compare rows before/after); diff lists only changed fields (a fixture with one changed field yields exactly one entry); accept-all writes exactly the `changed` lines and leaves `unavailable`, `deleted`, `unchanged` alone; accept after a copies edit in between → `409`, nothing written (counter-test: skip the version check → the snapshot is overwritten); expired refresh → `409 refresh_expired`.
- Grocy label route, against recorded Grocy requests (form-encoded and JSON, with and without `details`, a product and a stock-entry print): fields mapped as in section 8.1.2; token in the query and in the body both work; no header needed; the request does **not** call the Grocy plugin (assert zero calls on the plugin mock) and answers within a fixed budget with the plugin mock hanging (counter-test: a synchronous lookup makes the test fail on time); Grocy API down → line parked from the payload, `snapshot_complete: false`; two identical requests within 10 s → one line, second `duplicate`; an `admin` token → `403`; `mode=print` with an `inbox`-only key → parked with `key_cannot_print`; `mode=print` with a page printer → parked; the token never appears in captured logs (`caplog`) or response bodies; CORS preflight answered only for the configured origin. The old `/api/v1/webhook/grocy` path answers `404`.
- Content type vs sheet type: a selection with one line whose content type the sheet type cannot render → preview and print succeed for the others, that line is in `not_printable` and stays in the inbox; adding that line to the inbox is never refused for this reason. `next_sheet` never produces a second placement in the print request built by the server.
- Preview under `fresh` with one source down → that line `unavailable`, the others rendered; a second preview within 60 s makes no new lookup for it (failure cached).
- Kept receiver (with #173): valid signature → parked; wrong signature, stale `t`, missing header → `401` with a fixed message; same event id twice → one line.
- Errors: no error body contains the posted title, the idempotency key or a secret (assert on raw bodies).
- Events: every write publishes `inbox.changed` with an increasing `revision`; the event carries no title.

**Frontend (Vitest + jsdom)**

- Selection: select all, untick two → the print request carries exactly the remaining ids; header box states none/some/all; header click when all selected clears; "Clear selection" visible only with a selection; Space toggles a focused row; a row click toggles, a click on Remove does not.
- Selection storage: survives a reload; ids no longer in the inbox are pruned; a line arriving through SSE is unselected; nothing about the selection is sent in any request except the print/preview id list.
- Preview: a selection change sends a new preview request with exactly the selected ids (debounced: three quick changes → one request); `next_sheet` labels listed; list entry and cell agree on the cell for each item; hover on the entry highlights the cell and the reverse.
- Refresh: summary counts; diff shows only changed fields; accept-all sends `all: true`; `409` shows the refresh-again note; the preview rebuilds after accept.
- Migration: lines sent once with the derived keys; `lph.cart` removed only after `2xx`; kept on error; a read-only session does not send.
- Taint: a title `<img src=x onerror=…>` renders as text in the list, the cell list and the diff.

**End-to-end (Playwright, fake printers and fake upstreams)**

- Two browser contexts: add on one, appears on the other without reload.
- Grocy webhook routed to the IPP printer → line in the inbox, notification count 1; scan the sheet code → `/cart?sheet=…` with the preview; print → line gone, cells used.
- Partial print → unselected lines still present after a reload.
- Light and dark screenshots at 1280 px and 390 px for the cart, the preview and the diff.

## 15. Dependencies and order

1. **#188** — webhook jobs reach the queue with a re-renderable payload. The "print now" route and the inbox tape print share that path. Blocks everything below that prints. Ships in the same release as the inbox or earlier (controller's call).
2. **1.5.0 (#226)** — paths under `/api/v1`. This design assumes it.
3. **Backend inbox:** table, migration, scope `inbox`, enqueue/read/change routes, idempotency, limits, events.
4. **Freshness + inbox print** (tape and sheet routes, job flag).
5. **Routing rule + webhook changes:** the new Grocy label route (section 8.1), removal of the old `/grocy` route, Spoolman.
6. **UI:** server cart, selection, migration, then the sheet preview changes (with #249 for the colour token), then scan → sheet.
7. **Refresh and diff** (backend + UI).
8. **Notification** — with #255, or the top-bar count as interim (section 10).
9. **Kept receiver** — after #173.

The 1.6.1 items of #27 (cart icon with badge, grouping and confirmation) can follow step 6.

**Decision register:** proposes new rows (numbers to be assigned when merged):
- "The cart is a server-side print inbox; selection stays per device";
- "Parked items always store a snapshot; `inbox.freshness` decides which source prints";
- "Scope `inbox` may only enqueue";
- "Page printers always park".

## 16. Rollout

- Release notes: the cart moves to the server on first visit; read-only sessions see but cannot change it (unless Q5 decides otherwise); webhook responses gain `outcome`; a webhook routed to a page printer now parks instead of failing silently.
- Grocy: the old `/api/v1/webhook/grocy` is gone; the notes show how to set `LABEL_PRINTER_WEBHOOK` to `/api/v1/webhook/grocy/label?token=…`, recommend `LABEL_PRINTER_RUN_SERVER=true`, and say why the token must be a dedicated `inbox` key (it appears in Grocy's logs and, in browser mode, in every client).
- The migration needs no operator action. `inbox.*` settings have defaults; routes default to `park`. Nothing printed through a webhook before (#188, and the Grocy format mismatch), so no working setup changes behaviour; the notes name the one setting for "print now".

## 17. Builder's calls (collected)

| # | Call | Section |
|---|---|---|
| B1 | Own table `inbox_items`, not settings/JSON blob | 5.1 |
| B2 | `paperless` not in the inbox app enum yet; `manual` for raw data | 5.1 |
| B3 | A merge does not extend `expires_at` | 5.1 |
| B4 | Re-adding an item merges into its line, adds copies, replaces the snapshot | 5.1 |
| B5 | Idempotency records kept 7 days after print/removal | 5.3 |
| B6 | Refresh candidates stored server-side, 15 minutes | 5.4 |
| B7 | ≤ 50 items per enqueue request; `200` not `202` | 6.2 |
| B8 | 60-second duplicate window for callers without a key | 6.2, 8.1 |
| B9 | Lookup failure at enqueue refuses with `502` on the generic route (Grocy label route parks from payload) | 6.2 |
| B10 | Changing, removing, refreshing, accepting and importing need `print` | 6.3, 13 |
| B11 | ≤ 4 concurrent lookups per integration during refresh; one refresh at a time | 6.4, 12.2 |
| B12 | One render route for before/after; sheet items rendered as one cell | 6.4 |
| B13 | Server builds the print from line ids, flags fallbacks, removes lines in the same transaction | 6.5 |
| B14 | Removal on acceptance (`202`), not on printer completion — unchanged | 6.5 |
| B15 | Routing rules as settings per integration; default `park`; content type default per app | 7 |
| B16 | `print` route with unavailable printer parks with a reason | 7 |
| B17 | Spoolman webhook also accepts an `inbox`-scoped `X-Label-Hub-Key` | 8.1a |
| B18 | Webhook `quantity` is not copies; copies = 1 | 8.1a |
| B19 | Kept: only `thing.created` enqueues until Q1 is answered (recommendation: also `thing.moved`) | 8.3 |
| B20 | Print always looks up again (the preview cache does not apply to it) | 9 |
| B21 | `inbox.changed` carries counts and ids, no text | 10 |
| B22 | `waiting_for_sheet` counts only lines with an intended page printer; top-bar count until #255 | 10 |
| B23 | Copies edit `409` keeps the user's value with a note | 11.1 |
| B24 | Roving focus in the list | 11.2 |
| B25 | Selection in `localStorage` `lph.inbox.selection`; default all; SSE arrivals unselected | 11.2 |
| B26 | Sheet scan → cart only when the inbox is not empty; printer preselect order | 11.4 |
| B27 | Fixed field-name mapping per app in the diff | 11.5 |
| B28 | SSO/bypass treat `inbox` like `print` | 12.1 |
| B29 | Body ≤ 256 KiB; shared webhook secret 60/min | 12.2 |
| B30 | Migration: lookup failure stores a name-only snapshot; device-derived idempotency keys; code removed after two releases | 13 |
| B31 | Grocy label route body cap 64 KiB; unknown fields ignored | 8.1.1 |
| B32 | Grocy enrichment lookup optional, in the background, version-guarded | 8.1.3 |
| B33 | Grocy route refuses `admin` tokens; `mode=print` with an `inbox`-only key parks with a reason | 8.1.4 |
| B34 | Browser-mode CORS: one configured origin, `POST` only, no credentials | 8.1.4 |
| B35 | Grocy duplicate window 10 s over `(key id, request hash)` | 8.1.5 |
| B36 | Old `/api/v1/webhook/grocy` removed, not kept as a generic JSON endpoint | 8.1.5 |
| B37 | Sessions store the key's scope list, re-read on use | 12.1 |
| B38 | `next_sheet` labels stay selected after the print | 11.3 |

**Controller's calls** (decided at the builder check, 2026-11-09):

| # | Ruling | Section |
|---|---|---|
| C1 | `next_sheet` is only a leftover list: no second placement in the same print; leftovers stay until the next sheet is scanned | 6.5, 11.3 |
| C2 | A sheet scan offers all inbox lines regardless of intended printer; content type is checked against sheet type at preview/print time, unrenderable lines listed as "not printable on this sheet type" and excluded, not refused wholesale | 6.5, 11.4 |
| C3 | `inbox.max_items` counts labels (copies included), 500; a print selection above `MAX_ITEMS` 500 → `422 selection_too_large`, button disabled with the reason | 6.2, 6.5, 11.2, 12.2 |
| C4 | Scopes become a set: `inbox` is additive, effective permission is the union; sessions carry the minting key's capabilities | 12.1 |
| C5 | Idempotency scope = API key id; sessions: minting key id; SSO sessions: SSO user; migration: device id | 5.3 |
| C6 | `revision` persisted in the DB; single-process assumption stated with what breaks under several workers | 5.1, 6.1 |
| C7 | Under `fresh` the preview marks failing lines unavailable and renders the rest; print follows the fallback rule; failures cached like successes for 60 s | 9 |
| C8 | `data_source` on the job row as an additive Alembic column | 9 |
| C9 | Webhook default `park` is acceptable; #188 ships in the same release or earlier | 7, 15 |

## 18. Open questions for the maintainer

Each question carries the recommendation of the builder check; none of them is decided.

- **Q1 — Kept events.** Which Kept events should put a thing into the inbox? *Recommendation:* `thing.created` and `thing.moved` (a moved thing needs a new location label). B19 implements only `thing.created` until this is answered.
- **Q2 — Same item twice.** When the same item is added again (Grocy: two purchases), one line with more copies or a second line? *Recommendation:* two lines when a print-relevant field (for example the best-before date) differs, otherwise merge and add copies. B4 merges always until this is answered.
- **Q3 — Source down when a caller enqueues (generic route).** For the Grocy label route this is settled (park from the payload, section 8.1.3). For `POST /api/v1/inbox/items`: refuse with `502` so the caller retries (B9), or park with what the caller sent and mark it incomplete?
- **Q4 — Limits.** 500 labels and 30 days expiry? *Recommendation:* yes, plus a notification 3 days before a line expires unprinted.
- **Q5 — Read-only users.** Today anyone who can open the hub fills the local cart. *Recommendation:* `read` sessions may add to the inbox and select, but not print; that would grant `read` sessions the `inbox` capability for UI adds (B10 currently requires `print` for every inbox write).
