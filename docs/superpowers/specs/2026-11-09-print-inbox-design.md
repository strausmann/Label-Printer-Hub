# Print inbox: a server-side cart that other apps can fill

- **Date:** 2026-11-09
- **Status:** Draft, awaiting maintainer review.
- **Issue:** #27 (the comments of 2026-11-09 hold the maintainer's decisions verbatim). Blocked by #188. Related: #173 (Kept lookup), #255 (notification centre), #249 (cell-number colour), #242 (free-text search), #244 (item details), ADR [0013](../../decisions/0013-browse-cart-bulk-print-ui-pattern.md) (cart pattern; this document adopts its "Option D").
- **Builds on:** [`2026-06-04-multi-label-batch-design.md`](2026-06-04-multi-label-batch-design.md) (batch print), [`2026-11-05-sheet-archive-design.md`](2026-11-05-sheet-archive-design.md) (sheets, sheet preview and print), [`2026-05-16-phase6b-sse-eventbus-design.md`](2026-05-16-phase6b-sse-eventbus-design.md) (event bus), [`2026-05-17-phase-7c-api-auth-design.md`](2026-05-17-phase-7c-api-auth-design.md) (scopes).
- **API paths:** every path is written as it will be after 1.5.0 (#226, branch `feat/api-v1-status-manifest`), which moves all routes under `/api/v1`. Where this document cites today's code it names today's path.
- **How decisions are marked:** the maintainer's decisions are listed in section 4 and followed as written. A smaller decision this document makes on its own is marked inline as **(builder's call: …)**; all of them are collected in section 17. Questions only the maintainer can answer are in section 18.

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
| Webhooks | `POST /api/webhook/spoolman` and `/grocy`, shared secret `X-API-Key` = setting `access.webhook_api_key`; look the item up, take the first enabled non-IPP printer, write a `queued` row. **The row never reaches the print queue (#188)** and its payload cannot be re-rendered. No idempotency, no content type, `quantity` is a stock delta, not copies | `api/routes/webhooks.py`, `api/dependencies/webhook_auth.py`, `schemas/webhook.py` |
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
| `snapshot_complete` | bool | False only for items migrated from `localStorage` whose lookup failed (section 13): the snapshot then holds only the name |
| `version` | int, starts at 1 | Bumped by every write to the row (copies, snapshot accept, merge). Guards print and accept against concurrent changes |
| `origin` | enum `ui`, `webhook`, `api` | Who added it |
| `origin_detail` | str ≤ 64, nullable | Webhook source (`grocy`, `kept`, …) or the API key's name; never the key itself |
| `intended_printer_id` | UUID, nullable | The printer the routing rule named when it parked the item (section 7); null for UI adds. Used for the notification and the default printer choice, never as a restriction |
| `created_at`, `updated_at` | datetime | |
| `expires_at` | datetime | `created_at` + `inbox.expiry_days`; a merge does not extend it (builder's call: so a webhook firing daily cannot keep an item forever) |

**Line identity.** Like today's cart, a line is unique per `(source_app, item_ref, content_type)`; `manual` lines are never merged. Adding an item that already has a line adds the copies (clamped to 10), replaces the snapshot with the newly captured one and bumps `version`. (builder's call: the newer capture is the newer truth; see open question Q2 for the alternative of one line per add.)

### 5.2 Selection is not data

The selection lives only in the browser (decision 4). The server has no field for it, and no endpoint accepts or returns it. See section 11.2 for where the client keeps it.

### 5.3 `inbox_idempotency`

| Field | Type | Meaning |
|---|---|---|
| `scope_key` | str | `<origin_detail or key id>:<idempotency key>`, so two callers cannot collide |
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

`revision` is a hub-wide counter bumped by every inbox write; the SSE event carries it (section 10), so a client knows whether its list is current. Order: `created_at` ascending, like today's cart.

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
| 409 | `inbox_full` | The add would exceed `inbox.max_items` lines. Nothing of the request is stored (all or nothing) |
| 409 | `idempotency_conflict` | The key was used before with a different request body. `error_detail` names the item `index` only |
| 422 | `invalid_request` | Schema error (field paths only) |
| 422 | `integration_unknown_app` | Unknown or not installed integration |
| 404 | `app-lookup-not-found` | The integration has no such item; carries `item_index` |
| 502 | `integration_lookup_failed` | The source failed or is unreachable; nothing stored, safe to retry with the same keys (builder's call: refuse rather than park an item without a snapshot; see Q3) |
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

Resolves each line (section 9), submits **one batch** through the same path as `POST /api/v1/print/{printer}/batch` (`dispatch_batch`), keeps `source_app` and `item_ref` in the job payload instead of `"manual"`, and in the same transaction removes the printed lines. Response = the batch response plus per item `{ "id", "data_source": "fresh" | "snapshot" | "snapshot_fallback" }`. All errors of the batch route apply; additionally `409 inbox_item_changed` (stale version, nothing printed) and `409 media_kind_mismatch` for an IPP printer.

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
- `overflow: "next_sheet"` (default for this route): when the placements cannot take every label, the preview fills what fits and returns the rest instead of `409 insufficient_cells`. `overflow: "refuse"` keeps today's behaviour.
- The preview response is the existing `SheetPreview` plus:
  - `item_map`: per expanded item index `{ "inbox_item_id", "copy": 1..n, "source_app", "title" }`;
  - `next_sheet`: the expanded items that are not placed, same shape;
  - `data_sources`: per line, as above.
- The print takes `expected_cells` from the preview as today (`409 plan_changed`), prints only the placed labels, removes them from the inbox, and leaves the `next_sheet` labels in it. A partial print (`502 print_interrupted`) removes only the copies whose pages were queued, as `SheetSection` does today (`SheetSection.tsx:262-282`), now on the server.
- Removal happens when the hub **accepts** the print (`202`), not when the printer reports it done — today's behaviour. A job that fails later is retried from the job history, not from the inbox. (builder's call: unchanged semantics; a failed sheet job leaves its cells `unconfirmed` per D15 anyway.)

## 7. Routing rule

Decides what a webhook or a routed API call does: print now or park. Stored as settings per integration (builder's call: the settings store already has per-integration keys, an admin UI and env locks; a table is not needed for four integrations):

| Key | Kind | Default | Meaning |
|---|---|---|---|
| `inbox.route.<app>.action` | enum `park`, `print` | `park` | What a webhook from `<app>` does |
| `inbox.route.<app>.printer` | str (printer slug), empty = none | empty | The target printer |
| `inbox.route.<app>.content_type` | enum `ContentType` | per app, the content type the integration page offers first (builder's call) | Webhooks carry no content type (`schemas/webhook.py`) |

`<app>` ∈ `grocy`, `spoolman`, later `kept`.

Evaluation, in this order:

1. The target printer is a **page printer** (`backend == "ipp"`) → **park**, whatever `action` says (decision 2). `intended_printer_id` is set to it.
2. `action = park` → park; `intended_printer_id` = the printer if one is set.
3. `action = print` and a tape printer is set, enabled and reachable → print now through the path #188 repairs; the response names the job.
4. `action = print` and no printer is set → the first enabled tape printer, as today (`webhooks.py:66-82`).
5. `action = print` and the printer is disabled, missing or offline → **park** and log a warning (builder's call: a label that waits is better than one that is lost); the webhook response says `parked` and why (`reason: "printer_unavailable"`).

The settings page validates that a `print` route does not name an IPP printer and says that such a route parks. The rule applies per integration and names a printer, which covers "per printer/integration": the printer's kind decides rule 1, the integration selects the rule.

`POST /api/v1/inbox/items` (section 6.2) always parks; it never consults the rule (an enqueue-only key cannot print).

## 8. Webhook changes

### 8.1 Grocy and Spoolman

`POST /api/v1/webhook/grocy` and `/spoolman` keep their payloads and their shared-secret header `X-API-Key` (`access.webhook_api_key`). They additionally accept `X-Label-Hub-Key` with `inbox` scope or higher (builder's call: lets an operator replace the single shared secret with a per-app key that can be revoked on its own).

New behaviour:

- Look the item up (snapshot), apply the routing rule (section 7), then park or print.
- Idempotency: an `Idempotency-Key` header if the caller sends one; otherwise the 60-second duplicate window of section 6.2 over `(app, entity id, type)`.
- `quantity` stays a stock value and is **not** used as copies (it is a stock delta for Grocy and remaining grams for Spoolman, `schemas/webhook.py`); copies are 1.
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
- The flag reaches three places: the print response (`data_sources`), the job row (a payload field `data_source` with `fresh`, `snapshot` or `snapshot_fallback`; exposed on the job APIs as `printed_from_snapshot: bool` plus the reason) and the job list in the UI ("Printed from snapshot" badge).
- A `snapshot_complete: false` line (section 13) prints its name only under `snapshot` or on fallback; the UI warns on the line.
- The preview resolves data the same way as the print. (builder's call: lookups made for a preview are cached per `(app, ref)` for 60 seconds so the debounced re-previews do not hammer the source; the print always looks up again.)
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
- The print button names count and total in labels, copies included: "Print 7 of 12 labels"; with everything selected "Print 12 labels"; disabled with nothing selected.
- The sheet capacity check counts selected labels × copies against the target's free cells.
- Only printed lines leave the inbox; unselected lines and `next_sheet` labels stay.
- **Where it lives:** `localStorage` key `lph.inbox.selection` (builder's call: per device, survives a reload, as the decision requires "per device"), a set of line ids, pruned to ids that still exist on every inbox fetch. It is never sent except as the list of lines to print or preview.
- **Defaults** (builder's call): with no stored selection, all lines are selected (today the whole cart prints). Lines that arrive later through SSE are **not** selected, so a webhook during the preview cannot add a label to a print the user already looked at; the header box then shows "some".

### 11.3 Sheet preview

`SheetSection` takes the selected lines and calls the inbox preview (section 6.5) instead of the raw sheet preview.

- Rebuilds, debounced like today (`useDebounced`, `PREVIEW_DEBOUNCE_MS`), whenever the selection, a line's copies or an accepted snapshot changes.
- The page image shows the cell number on each new cell; the list beside it reads "Cell 14 → Grocy · Oat milk" (`item_map`), copies numbered when a line has more than one ("Oat milk (2/3)").
- Two-way highlight: hovering or focusing a list entry highlights its cell; hovering or tapping a cell highlights and scrolls to its entry. On touch, tap toggles the highlight.
- `next_sheet` labels are listed under "Next sheet" with their names and count, not dropped and not an error. The print button counts only placed labels ("Print 9 of 12 labels onto L4736-0012").
- The existing distinction stays: used cells, reserved/unconfirmed, the new labels, the sheet ID and the feed mark. Cell numbers use the token from #249 and the legend "1 = cell number (not printed)".
- `data_sources` shows a small "snapshot" marker on lines that would print from the snapshot under `fresh_with_fallback` (the preview already knows).

### 11.4 Scan → sheet at the laser

- The sheet scan resolver (`features/sheets/resolver.ts`) resolves a sheet code to `/cart?sheet=<code>` **when the inbox has at least one line**, otherwise to the sheet page as today (builder's call).
- On `/cart?sheet=<code>` the printer picker preselects the page printer that last printed onto this sheet, else the line's `intended_printer_id`, else the only usable page printer; if none fits, the user picks (builder's call).
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

- New scope value `inbox`. It is **not** part of the linear chain: `admin` ⊇ `print` ⊇ `inbox`, `print` ⊇ `read`, but `inbox` ⊉ `read`. An `inbox`-only key can call `POST /api/v1/inbox/items` and the webhook routes, and nothing else — not `GET /api/v1/inbox`, not the event stream, not any print route.
- `auth/dependencies.py` today picks the effective scope from `["admin", "print", "read"]` and answers `401 key_no_scopes` for any other list (`dependencies.py:244-262`); the selection and `_SCOPE_HIERARCHY` gain `inbox`, and `require_inbox` joins `scope_deps.py`. The admin key form offers it with the text "Can only add items to the print inbox".
- The enqueue response never returns stored data (section 6.2), so the key cannot be used to read the inventory back through lookups.
- `allowed_printer_ids` does not restrict enqueue (nothing prints). It restricts the inbox print routes as everywhere.
- The Basic bypass and SSO header paths resolve to the required scope today; for `inbox` they behave the same as for `print` (builder's call; with `pangolin_bypass_scope_downgrade` the bypass cannot enqueue).

### 12.2 Limits

| Setting | Default | Effect |
|---|---|---|
| `inbox.max_items` | 500 (the batch and sheet item cap) | More lines → `409 inbox_full` |
| `inbox.expiry_days` | 30 | Lines older than this are removed by the existing cleanup task (`services/cleanup_task.py`) with `inbox.changed reason=expired`, and hidden from reads once past `expires_at` even before the sweep |
| `inbox.idempotency_days` | 7 | Retention of idempotency records |

Per request: ≤ 50 items, body ≤ 256 KiB (builder's call), raw text bounded as `SheetRawLabelData`, `idempotency_key` ≤ 128. The per-key rate limit applies; the shared webhook secret gets a fixed limit of 60 requests per minute (builder's call). Refresh: one running refresh per hub at a time (`409 refresh_running`, builder's call).

### 12.3 No echo, no client-supplied snapshots

- Error bodies never contain the request body, an idempotency key, a header value, the webhook secret or an upstream URL; integration failures keep the fixed messages of `batch.py` (CWE-209).
- Logs name line ids and app names, never titles or keys (`log_value`).
- A snapshot is only ever written from a lookup the server made, from `data` the caller added as `manual`, or from a refresh candidate the server stored. Accept takes ids, never data.
- The Kept receiver compares signatures in constant time and refuses stale timestamps; the secret is write-only (D5).

### 12.4 Upstream text is untrusted (taint)

Titles, secondary lines, list rows and QR payloads come from Grocy, Snipe-IT, Spoolman, Kept or an API caller. They reach the cart list, the cell list, the diff view, the notification, the job history and the rendered labels.

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
- Limits: 501st line → `409 inbox_full` and nothing of the request stored; expired lines hidden before the sweep and removed by it.
- Scope: an `inbox` key can enqueue; it gets `403` on `GET /api/v1/inbox`, the event stream, every print route, PATCH/DELETE; a `read` key gets `403` on enqueue; `print` and `admin` can enqueue. Counter-test: make `inbox` imply `read` → the read test turns red. The enqueue response contains no snapshot field (assert on the raw JSON, not the parsed model).
- Routing: IPP target with `action=print` → parked (counter-test: drop rule 1 → printed); `park` → parked with `intended_printer_id`; `print` with an offline tape printer → parked with reason; `print` → job reaches the queue and a recording backend prints it (depends on #188).
- Freshness: `snapshot` → the integration client receives **no** call (assert on the client mock's call count, not on the output); `fresh_with_fallback` with the source down → snapshot printed, job row `data_source = snapshot_fallback`; with the item deleted → same; `fresh` with the source down → `502`, nothing printed, lines unchanged. The fallback test must distinguish "snapshot because fallback" from "snapshot because the lookup was skipped": assert the client **was** called.
- Print: stale version → `409`, nothing queued, nothing removed; success → exactly the sent lines removed in the same transaction; partial sheet print → only queued copies removed; `next_sheet` labels stay; job payload keeps `source_app` (not `manual`).
- Refresh: never writes a snapshot (compare rows before/after); diff lists only changed fields (a fixture with one changed field yields exactly one entry); accept-all writes exactly the `changed` lines and leaves `unavailable`, `deleted`, `unchanged` alone; accept after a copies edit in between → `409`, nothing written (counter-test: skip the version check → the snapshot is overwritten); expired refresh → `409 refresh_expired`.
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

1. **#188** — webhook jobs reach the queue with a re-renderable payload. The "print now" route and the inbox tape print share that path. Blocks everything below that prints.
2. **1.5.0 (#226)** — paths under `/api/v1`. This design assumes it.
3. **Backend inbox:** table, migration, scope `inbox`, enqueue/read/change routes, idempotency, limits, events.
4. **Freshness + inbox print** (tape and sheet routes, job flag).
5. **Routing rule + webhook changes** (Grocy, Spoolman).
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

- Release notes: the cart moves to the server on first visit; read-only sessions see but cannot change it; webhook responses gain `outcome`; a webhook routed to a page printer now parks instead of failing silently.
- The migration needs no operator action. `inbox.*` settings have defaults; routes default to `park`, which changes behaviour for Grocy and Spoolman webhooks that printed (or were meant to print) before — called out in the release notes, with the one setting to change back.

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
| B9 | Lookup failure at enqueue refuses with `502` (no snapshot-less items) | 6.2 |
| B10 | Changing, removing, refreshing, accepting and importing need `print` | 6.3, 13 |
| B11 | ≤ 4 concurrent lookups per integration during refresh; one refresh at a time | 6.4, 12.2 |
| B12 | One render route for before/after; sheet items rendered as one cell | 6.4 |
| B13 | Server builds the print from line ids, flags fallbacks, removes lines in the same transaction | 6.5 |
| B14 | Removal on acceptance (`202`), not on printer completion — unchanged | 6.5 |
| B15 | Routing rules as settings per integration; default `park`; content type default per app | 7 |
| B16 | `print` route with unavailable printer parks with a reason | 7 |
| B17 | Webhook routes also accept an `inbox`-scoped `X-Label-Hub-Key` | 8.1 |
| B18 | Webhook `quantity` is not copies; copies = 1 | 8.1 |
| B19 | Kept: only `thing.created` enqueues (see Q1) | 8.3 |
| B20 | Preview lookups cached 60 s; print always looks up | 9 |
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

## 18. Open questions for the maintainer

- **Q1 — Kept events.** Which Kept events should put a thing into the inbox: only `thing.created`, or also `thing.moved` (new location label) or `thing.updated`? (B19 assumes `thing.created`.)
- **Q2 — One line or one per add.** When Grocy adds the same product twice (two purchases, different best-before dates), should that be one line with 2 copies and the newer data (B4, like today's cart), or two lines with their own snapshots?
- **Q3 — Source down when an app enqueues.** Refuse with `502` so the caller retries (B9), or park the item with whatever the caller sent and mark it incomplete?
- **Q4 — Limits.** Are 500 lines and 30 days right, and should an item that expires unprinted raise a notification instead of disappearing quietly?
- **Q5 — Read-only users.** Today anyone who can open the hub can fill the local cart. With the inbox, adding and editing need a print-capable credential (B10). Is that wanted, or should `read` sessions be allowed to add to the inbox?
