# Print inbox: a server-side cart that other apps can fill

- **Date:** 2026-11-09
- **Status:** Draft, awaiting maintainer review.
- **Issue:** #27 (the comments of 2026-11-09 hold the maintainer's decisions verbatim). Blocked by #188. Related: #173 (Kept lookup), #255 (notification centre), #249 (cell-number colour), #242 (free-text search), #244 (item details), ADR [0013](../../decisions/0013-browse-cart-bulk-print-ui-pattern.md) (cart pattern; this document adopts its "Option D").
- **Builds on:** [`2026-06-04-multi-label-batch-design.md`](2026-06-04-multi-label-batch-design.md) (batch print), [`2026-11-05-sheet-archive-design.md`](2026-11-05-sheet-archive-design.md) (sheets, sheet preview and print), [`2026-05-16-phase6b-sse-eventbus-design.md`](2026-05-16-phase6b-sse-eventbus-design.md) (event bus), [`2026-05-17-phase-7c-api-auth-design.md`](2026-05-17-phase-7c-api-auth-design.md) (scopes).
- **API paths:** every path is written as it will be after 1.5.0 (#226, branch `feat/api-v1-status-manifest`), which moves all routes under `/api/v1`. Where this document cites today's code it names today's path.
- **Also related:** #11 (Grocy labels use case).
- **How decisions are marked:** the maintainer's decisions are listed in section 4 and followed as written (1–10 from #27, 11–16 the answers of 2026-11-09 to this document's open questions). Rulings of the controller from the builder check (2026-11-09) are marked **(controller's call: …)** and are decided. A smaller decision this document makes on its own is marked inline as **(builder's call: …)**; all of them are collected in section 17. Questions only the maintainer can answer are in section 18.

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
- A daily e-mail/JMAP report. It is a separate issue (being filed); it will consume the "expires in N days" data this design exposes (section 10), nothing more.
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
2. **Other apps park instead of printing.** Grocy (after a shopping scan), later Kept, put items into the inbox via API or webhook. A **routing rule per printer/integration** (realised as the event rules of decision 11) decides "print now" vs "park in inbox"; **page (sheet) printers always park**, because a sheet must be loaded first. → sections 7, 8.
3. **Flow at the laser:** load sheet → scan the sheet's QR → the inbox selection is applied onto that sheet. → section 11.4.
4. **Selection in the cart UI:** checkbox per line; header "select all" tri-state; typical flow select all then untick some; deselect all in one click (header box when all are selected, plus an always-visible "Clear selection" while anything is selected); the print button names the count ("Print 7 of 12 labels"); only printed lines leave the cart, the rest stays; the sheet capacity check counts selected labels × copies; selection is per device, not part of cart data; the whole row toggles, 44 px targets, Space toggles. → section 11.2.
5. **Sheet preview shows the selected items placed on the sheet:** rebuilt (debounced) on selection or copies change; cell number in the image plus a list "cell → item (app, name)" with two-way highlight; labels that do not fit shown as "next sheet"; used cells, new labels and the sheet ID stay distinct; cell numbers in their own colour (#249). → section 11.3.
6. **Data freshness is a hub setting:** `snapshot` | `fresh` | `fresh_with_fallback` (default). Every item always stores a snapshot; on fallback the print result and the job history flag "printed from snapshot". Per-integration override optional/later. → section 9.
7. **Manual "Refresh data":** re-looks up all items without changing snapshots; marks changed items ("4 of 12 changed"), flags unreachable/deleted separately; per item before/after rendered label side by side plus a field diff with only the changed fields; Accept / Keep per item; "Accept all changes" without per-item confirmation and "Keep all"; the preview rebuilds after accepting; with `snapshot` this is the only way data changes. Accept is guarded by a version token from the refresh → `409` if data changed in between. → sections 6.4, 11.5.
8. **Idempotency key per enqueued item** so retried webhooks never duplicate; inbox limits (max entries, expiry); an API key scope that may only enqueue, not print. → sections 5.3, 5.4, 12.
9. **Notification** "N labels wait for sheet printing" via #255. → section 10.
10. **#188 is fixed first.** → section 15.
11. **Event → action rules are user-defined, per integration.** For every integration that emits events (the Grocy label webhook now; Kept once its integration exists, e.g. `thing.created`, `thing.moved`, `thing.updated`; others later) the user configures per event type: action `none` | park in inbox | print now; target printer (or the integration's default); template/format (today a content type, later a Label-Designer layout id from #178, without a schema break). A newly connected integration parks every known event; no event prints automatically. Presets ship but are editable (Kept: created + moved park, updated none). → section 7.
12. **Grocy integration settings** configure the Grocy label endpoint: target (inbox or a specific printer) and template/format; the `printer=`/`mode=` URL parameters are an optional per-call override. → sections 7, 8.1.4.
13. **Separate lines when the code or a print-relevant field differs;** merge into copies only for an identical label. Grocy: every stock entry has its own grocycode, so stock-entry labels are always separate lines; "label per unit" sends one call per unit with its own `stock_id`. → section 5.1.
14. **Limits:** 500 labels (copies included) and 30-day expiry; a notification 3 days before expiry, never silent removal. → sections 10, 12.2.
15. **Read-only access may add to and select in the inbox, but not print.** → sections 6.3, 12.1, 13.
16. **Webhook default = park in inbox**, switchable per integration and event (through the rules of 11). → section 7.
17. **Webhook call log in the hub** (maintainer, 2026-11-09): every call to a hub webhook is recorded and viewable in the hub: when, from where, the payload, what happened to it, and the final status of the job or inbox line it produced. → section 8.4.

## 5. Data model

### 5.1 `inbox_items`

One row per inbox line. (builder's call: a new SQLModel table with an Alembic migration, like the sheet tables; not the settings store and not a JSON blob, because lines are changed one at a time from several devices.)

| Field | Type | Meaning |
|---|---|---|
| `id` | UUID | Line id; the client's selection refers to it |
| `source_app` | enum `snipeit`, `grocy`, `spoolman`, `kept`, `manual` | Where the item lives. `kept` only once #173 ships a plugin; `manual` for raw data from the API (builder's call: `paperless` is left out until the cart can add Paperless items; the enum is the lookup route's `AppLiteral` plus `kept` and `manual`) |
| `item_ref` | str ≤ 120 | The identifier the plugin's `lookup` takes (same cap as `SheetItem.lookup.identifier`); null for `manual`. For Grocy lines the **product id** (controller's call C11) |
| `item_meta` | JSON, nullable | Integration data that is not label content but identifies the label. Grocy: `grocycode` and, for stock-entry labels, `stock_id` (C11) |
| `format` | JSON `{"kind": "content_type", "content_type": …}`; later `{"kind": "designer_layout", "layout_id": …}` (#178) | How the label is laid out. Only `content_type` is accepted until #178 ships; the tagged shape lets a designer layout be added without a schema change (decision 11). The API also accepts a plain `content_type` field as shorthand |
| `snapshot_hash` | str | SHA-256 of the normalised snapshot. The merge key is `(source_app, item_ref, format, item_meta.grocycode, item_meta.stock_id, snapshot_hash)` |
| `copies` | int 1–10 | Same bounds as `MAX_COPIES` and `PrintOptions.copies` |
| `snapshot` | JSON, the `SheetRawLabelData` shape (title, primary_id, qr_payload, secondary, items) with its bounds | The label data captured when the item was added or last accepted. **Always present** (decision 6) |
| `snapshot_at` | datetime | When the snapshot was captured |
| `snapshot_complete` | bool | False when the snapshot holds less than a lookup would give: items migrated from `localStorage` whose lookup failed (section 13, name only), and Grocy label webhooks parked from the payload alone while enrichment is pending or failed (section 8.1.3) |
| `version` | int, starts at 1 | Bumped by every write to the row (copies, snapshot accept, merge). Guards print and accept against concurrent changes |
| `origin` | enum `ui`, `webhook`, `api` | Who added it |
| `origin_detail` | str ≤ 64, nullable | Webhook source (`grocy`, `kept`, …) or the API key's name; never the key itself |
| `origin_event` | str ≤ 64, nullable | The integration's event type that parked it (`grocy.stock_entry`, `kept.thing.created`, …) |
| `intended_printer_id` | UUID, nullable | The printer the event rule named when it parked the item (section 7); null for UI adds. Used for the notification and the default printer choice, never as a restriction |
| `created_at`, `updated_at` | datetime | |
| `expires_at` | datetime | `created_at` + `inbox.expiry_days` (30); a merge does not extend it (builder's call: so a webhook firing daily cannot keep an item forever) |
| `expiry_warned_at` | datetime, nullable | When the 3-day warning for this line was raised (section 10) |

**Line identity** (decision 13). An add merges into an existing line **only for an identical label**: same `source_app`, same `item_ref` (the code; for a Grocy stock entry also the same `stock_id`), same `format`, and a snapshot that is equal field by field (compared as a hash of the normalised snapshot, `snapshot_hash`). Then the copies are added (clamped to 10) and `version` is bumped; the snapshot is unchanged because it is the same. If the code or any print-relevant field differs — a new best-before date, another amount, another name — the add creates a **separate line**. `manual` lines merge by the same rule (builder's call: identical raw data is an identical label). Grocy: every stock entry has its own grocycode (`item_ref`), so stock-entry labels are always separate lines; Grocy's "label per unit" sends one call per unit with its own `stock_id` and becomes one line per unit. A refresh accept (section 6.4) can make two lines identical; they are **not** merged afterwards (builder's call: a merge the user did not ask for would surprise the selection).

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

`POST /api/v1/inbox/items` — `inbox` capability, which `read`, `print` and `admin` also grant (section 12.1, decision 15).

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
- Each item has `lookup`, `data`, or both. `data` alone is stored as given, bounded like `SheetRawLabelData`, with `source_app = "manual"`. For `lookup` the server looks the item up **now** and stores the result as the snapshot; `data` sent **together with** `lookup` is display data (name, fields) that the server uses only when the source cannot be reached.
- **Source down at enqueue** (controller's call): if the item carries display data, it is **parked** from that data with `snapshot_complete: false` (shown as incomplete) and the gaps are filled later by a background lookup, as on the Grocy route (section 8.1.3). If the item carries only a reference and nothing to show, the request is **refused with a retryable `503`** and a `Retry-After` header, so the caller retries — an API caller can retry, unlike Grocy. Under one request, either every item is stored or none (a single reference-only item that cannot be resolved refuses the whole request).
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
| 503 | `integration_unavailable` | The source failed or is unreachable **and** a reference-only item carried no display data; `Retry-After` set (builder's call: 30 s); nothing stored, safe to retry with the same keys. Items with display data are parked incomplete instead (controller's call) |
| 503 | `integration_not_configured` | |
| 429 | existing rate-limit error | Per-key `rate_limit_per_minute` |

### 6.3 Changing and removing

All `print` scope. Read-only access may add and select (decision 15) but not change or remove lines (builder's call: an add is harmless, a removal can take away what someone else parked; the decision names adding and selecting only).

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

`GET /api/v1/inbox/refresh/{refresh_id}/items/{item_id}/render?side=before|after&printer=<key>&sheet_type=<key>` — `read`. `sheet_type` is required for a page printer, because the server does not know the cart's selected sheet type. A PNG of the stored (`before`) or candidate (`after`) data, rendered like `POST /api/v1/render/preview` for the given tape printer; for a page printer, rendered as one cell of the sheet type the cart has selected (builder's call: one route for both sides, so the client never handles candidate data itself).

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
- **Locking (controller's call C12).** No network lookup and no render runs while the hub-wide inbox lock is held. Under the lock the server checks the sent versions (a stale version gives `409 inbox_item_changed`, nothing queued), **claims** the line ids for this print and copies the lines. A line already claimed by another print answers `409 inbox_item_printing`, nothing queued, so two devices printing the same lines print them once. The claim is released on every exit path (success, failure, cancellation) and expires after 5 minutes, which covers a crash. Copies edits and removals of a claimed line still proceed; the print then reports the line under `kept_changed`. Then it releases the lock, resolves and renders, and submits. After the queue accepted, it takes the lock again only briefly, to remove the printed lines guarded by their version. A line changed meanwhile stays and is listed in the response under `kept_changed`. Adds never wait on a print. JobStore writes jobs in its own sessions, so the removal is not in the same DB transaction as the job rows. A crash in between leaves a printed line in the inbox, and never loses an unprinted one.
- Removal happens when the hub **accepts** the print (`202`), not when the printer reports it done — today's behaviour. A job that fails later is retried from the job history, not from the inbox. (builder's call: unchanged semantics; a failed sheet job leaves its cells `unconfirmed` per D15 anyway.)

## 7. Event → action rules

Decides what an incoming event does: nothing, park in the inbox, or print now (decisions 2, 11, 12, 16). The rules are **user-defined in the hub, per integration and per event type**.

### 7.1 Model

Two tables (builder's call: rules are a list per integration with event types that differ by integration, which the flat settings store does not express well; the settings page edits them through their own admin API):

**`integration_event_defaults`** — one row per event-emitting integration:

| Field | Meaning |
|---|---|
| `integration` | `grocy`, `spoolman`, later `kept`, … |
| `action` | `none` \| `park` \| `print` — default `park` (decision 16) |
| `printer_id` | nullable; the default target ("routing default" for the event rows) |
| `format` | the tagged format of section 5.1; default per integration, the content type the integration page offers first (builder's call) |

**`integration_event_rules`** — one row per `(integration, event_type)`:

| Field | Meaning |
|---|---|
| `event_type` | from the integration's list of known event types (section 7.2) |
| `action` | `none` \| `park` \| `print` \| `default` (inherit) |
| `printer_id` | nullable = the integration default |
| `format` | nullable = the integration default; the same tagged shape, so a Label-Designer layout id (#178) can be stored later without a schema break |

Every integration declares its known event types and a preset in code. When an integration is connected (or a hub without rows starts), the rows are created from the preset; the user can change every row. **Presets never print:** every known event is `park` or `none` (decision 11).

| Integration | Event types | Preset |
|---|---|---|
| Grocy (label webhook) | `grocy.product` (a product label: no `stock_entry` in the payload), `grocy.stock_entry` (a stock-entry label: `stock_entry` present — a purchase with "one label" or "label per unit", a manual stock-entry print, and Grocy's automatic re-print on due-date change all arrive as this) | both `park` |
| Spoolman | the `type` of its payload (`created`, `updated`, …) | all `park` |
| Kept (after #173) | `thing.created`, `thing.moved`, `thing.updated`, others Kept documents | `thing.created` park, `thing.moved` park, `thing.updated` none, all others none |

(builder's call: Grocy's payload does not say whether a stock-entry call came from a purchase, a manual print or an automatic re-print, so the hub can only tell the two kinds above apart; finer types would need a change in Grocy, section 8.1.6.) An event type the integration does not know yet (a new Kept event) is treated as `none` and logged once, until the user adds a rule.

### 7.2 Evaluation

For an incoming event: take its rule row, fill `default` fields from the integration default, apply the per-call override of the Grocy route (section 8.1.4), then:

1. `action = none` → nothing is stored or printed; the response says `ignored`.
2. The target printer is a **page printer** (`backend == "ipp"`) → **park**, whatever the action (decision 2). `intended_printer_id` is set to it.
3. `action = park` → park; `intended_printer_id` = the target printer if one is set.
4. `action = print` and a tape printer is set, enabled and reachable → print now through the path #188 repairs; the response names the job.
5. `action = print` and no printer is set → the first enabled tape printer, as today (`webhooks.py:66-82`).
6. `action = print` and the printer is disabled, missing or offline → **park** and log a warning (builder's call: a label that waits is better than one that is lost); the response says `parked` with `reason: "printer_unavailable"`.

The default `park` changes what a webhook did on paper, which is acceptable: because of #188 nothing prints through a webhook today, and #188 ships in the same release or earlier (controller's call).

### 7.3 Settings UI and API

- Each integration's settings page gets a section "Incoming events": the integration default (target: "Collect in the print inbox" or a printer; format) and one row per known event type (action, printer or "integration default", format or "integration default"). For Grocy this is where the label endpoint is configured (decision 12), next to the generated webhook URL and the token hint of section 8.1.4.
- The page says that a page printer always collects, and refuses saving `print` with an IPP printer as target (it would park).
- API: `GET/PUT /api/v1/integrations/{name}/event-rules` — `admin`. The format field validates against the known content types now; `designer_layout` is refused with `422 format_not_supported` until #178.

`POST /api/v1/inbox/items` (section 6.2) always parks; it never consults the rules (an enqueue-only key cannot print).

## 8. Webhook changes

### 8.1 Grocy label webhook (new, in Grocy's own format)

**What Grocy actually sends** (verified against Grocy's `docs/label-printing.md`, `helpers/WebhookRunner.php`, `controllers/StockApiController.php` and `services/StockService.php`, 2026-11-09):

- Configured through `LABEL_PRINTER_WEBHOOK` (URL), `LABEL_PRINTER_RUN_SERVER` (server or browser sends it), `LABEL_PRINTER_PARAMS` (fixed extra fields) and `LABEL_PRINTER_HOOK_JSON` (JSON instead of form encoding).
- A POST with these fields. **Form-encoded by default**, JSON only with `LABEL_PRINTER_HOOK_JSON`:
  - `product` — the product name;
  - `grocycode` — the code's content; Grocy prints it as 1D (Code128) or 2D (DataMatrix);
  - `due_date` — a **localized display string** ("DD: …"), not a date;
  - `details` (since 4.5.0) — the result of `GetProductDetails`: the product row, `product_barcodes`, `location` (the product's **default** location object), the quantity units, stock amounts, prices, `next_due_date`, `average_shelf_life_days` and more;
  - `stock_entry` — on purchase and stock-entry prints only: `amount`, `best_before_date`, `purchased_date`, `location_id`, `price`, `open`, `note`, `stock_id`.
- Not in the payload: the stock entry's location **name** (only `location_id`), the product group and the shopping location (ids only), userfields, the product picture (only its file name).
- The server-side runner uses a Guzzle client with a **2.0 s timeout**, sends **no custom headers** (only `form_params` or `json`), catches every failure and only logs it to stderr — **no retry** — and logs the full request arguments, `LABEL_PRINTER_PARAMS` included, to stderr.
- With `LABEL_PRINTER_RUN_SERVER=false` the browser sends the call, and the configuration values, params included, are delivered to every Grocy client.
- Automatic triggers, **all only with `LABEL_PRINTER_RUN_SERVER=true`**: a purchase with `stock_label_type` 1 (one label) or 2 (one call per unit, each with its own `stock_id`), and the automatic re-print on a due-date change (`product.auto_reprint_stock_label`). Recipes that "produce" a product print the same way.

The existing `/api/webhook/grocy` matches none of this (section 3). The design adds a receiver that takes Grocy's format as it is.

#### 8.1.1 Endpoint

`POST /api/v1/webhook/grocy/label`, accepting `application/x-www-form-urlencoded` **and** `application/json` with the same fields. The form body uses PHP bracket notation, because Guzzle's `form_params` encodes nested arrays that way (`stock_entry[best_before_date]=…`, `details[product][name]=…`). The receiver decodes it into nested objects: `[]` makes a list, and for a repeated scalar the last value wins (controller's call C16). Unknown fields are ignored (Grocy adds fields between versions); the body is capped at 64 KiB (builder's call: `details` is a full product object, still small).

#### 8.1.2 Mapping into the snapshot

| Snapshot field | Taken from |
|---|---|
| `title` | `product` (fallback `details.product.name`) |
| `primary_id`, `qr_payload` | `grocycode` (the code's content), kept in `item_meta.grocycode`. `item_ref` is the product id: `details.product.id`, else the second field of the grocycode (`grcy:p:<product id>[:<stock id>]`); with neither, `item_ref` is null and the line always prints its snapshot (controller's call C11) |
| best-before line | `stock_entry.best_before_date` (an ISO date), formatted per `general.language` ("Best before …"); omitted for Grocy's "never" date. Without `stock_entry`, `details.next_due_date`. **`due_date` is not parsed** — it is a localized display string |
| amount line | `stock_entry.amount` with the quantity unit from `details` (singular/plural by amount) |
| location line | the product's default location from `details.location.name` at first; the stock entry's own location name replaces it after enrichment (only `location_id` is sent) |
| further lines | `stock_entry.note` when set (builder's call: notes are often what the label is for) |

`source_app = grocy`; `origin_event` is `grocy.stock_entry` when `stock_entry` is present, else `grocy.product`. `stock_entry.stock_id` is kept in `item_meta.stock_id` so "label per unit" calls stay distinguishable even with equal data. `price`, `open`, `purchased_date` and the stock amounts are not printed (builder's call: not label content today; the format can pick them up later). `details` is read, never stored as a whole. Every value is bounded like `SheetRawLabelData` and treated as untrusted text (section 12.4). The format comes from the event rule (section 7).

#### 8.1.3 Answer within Grocy's 2-second budget

- The receiver parks or submits **from the payload alone**, synchronously, and answers well inside 2 s. It does **not** call Grocy's API in the request. Because Grocy never retries, a slow or failed request loses the label — persisting from the payload is mandatory.
- An enrichment lookup through the Grocy API (the Grocy plugin, when configured) runs afterwards as a background task and fills what the payload lacks: the stock entry's location name (from `location_id`), the product group and shopping location names, userfields, and the product picture (by its file name). It replaces the snapshot only while the line is unchanged (`version` check); until it succeeds the line is `snapshot_complete: false`. (builder's call: userfields and the picture are fetched but only used once a format shows them.) If the plugin is not configured or Grocy's API is down, the line stays as parked from the payload and is printable (so Grocy never loses a label to a slow or absent API). (builder's call: enrichment is optional and never blocks.)
- "Print now" (section 8.1.4) submits through the #188 path with the payload data; it waits for the queue's acceptance, not for the printer.

#### 8.1.4 Auth, target and mode — without headers

Grocy cannot send headers, so the credential travels in the URL or the body:

- `token=<key>` as a query parameter in `LABEL_PRINTER_WEBHOOK` or as a field in `LABEL_PRINTER_PARAMS`. It is a normal hub API key (`lh_…`) and **must be a dedicated low-privilege key**: `inbox` scope, or `print` limited to one printer through `allowed_printer_ids`. The token ends up in Grocy's stderr log and, in browser mode, in every Grocy client; the key form says so when the key is created for Grocy, and the docs recommend server mode. An `admin` key is refused on this route (`403 token_scope_too_broad`, builder's call).
- The behaviour comes from the **Grocy integration settings** (decision 12, section 7.3): target (inbox or a printer) and format, per event type. `printer=<slug or id>` and `mode=print|collect` (`collect` = park in the inbox), as query or body parameters, are an **optional per-call override**. (builder's call: they may override target and mode, but only within bounds — they never enable an event whose rule is `none`, `mode=print` needs a key with `print` on that printer, and rule 2 of section 7.2 still applies: a page printer always parks.) An `inbox`-only key with `mode=print` parks and answers `reason: "key_cannot_print"`, so the label is not lost.
- **Browser mode** needs CORS for the Grocy origin: a setting `integrations.grocy.webhook_cors_origin` (empty = no CORS); only this route answers the preflight, with that single origin, `POST` only, no credentials (builder's call).
- **Our side never logs the token**: the app installs a filter on the `uvicorn.access` logger that removes the query string for `/api/v1/webhook/` paths. A test runs real uvicorn with the container's command and checks the log output (controller's call C13). The reverse proxy logs query strings too, so the docs and the setup panel recommend sending the token as a body field (`LABEL_PRINTER_PARAMS`) over `?token=`. Also, error bodies never echo it, and the token is not stored in the idempotency record (only the key id).

#### 8.1.4a Setup in the Grocy integration page (maintainer decision 2026-11-09)

The hub's Grocy integration settings page shows everything an operator needs to point Grocy at the hub. Nobody has to assemble the URL by hand.

- **A "Grocy label webhook" panel.**
  - It shows the full webhook URL built from `PRINTER_HUB_PUBLIC_URL`: `<public url>/api/v1/webhook/grocy/label`, with a **Copy** button.
  - The token is not part of the URL until the operator creates or chooses a dedicated key in the panel. The panel offers "Create a Grocy key", which creates an `inbox` key with the name `grocy`, shows the value **once**, and builds the copyable URL with `?token=` from it. An existing key is never shown again, because keys are write-only. Reusing one means pasting it in. Next to the URL it shows the `LABEL_PRINTER_PARAMS` form with the token as a body field, and recommends that form, because proxies log query strings (C13).
- **A ready-to-paste Grocy configuration block.** It covers `config.php`, or the matching environment variables for the Docker image: `LABEL_PRINTER_WEBHOOK`, `LABEL_PRINTER_RUN_SERVER=true`, `LABEL_PRINTER_HOOK_JSON=true` and `FEATURE_FLAG_LABEL_PRINTER=true`. A note recommends server mode and explains why: in browser mode the token reaches every Grocy client.
- **"Send test label".** It runs the same code path with a fixed sample payload, honours the configured target (inbox or printer), and reports the outcome.
- **"Last call received".** It shows the time, outcome and event type of the last real call from Grocy (no payload), so the operator can check after configuring Grocy that calls arrive.

Tests: the panel URL uses the public URL, not the request host. The key value appears only in the create response. A test label lands in the inbox with the default rule.

#### 8.1.5 Duplicates, responses, the old endpoint

- Grocy sends no event id and never retries; the only duplicates are double clicks or two open tabs. Dedupe by `(key id, request hash)` within 10 seconds (builder's call: shorter than the generic 60 s, because printing the same label twice on purpose a minute later is normal in Grocy).
- Response `200` `{ "outcome": "parked" | "printed" | "duplicate", "item_id"?, "job_id"?, "reason"? }`. Grocy ignores the body; it is for logs and tests. Errors keep the envelope; an unknown token is `401` with a fixed message.
- Automatic prints Grocy sends (purchase, due-date re-print, recipe "produces") arrive as `grocy.stock_entry` and follow its rule; with the default `park` they collect in the inbox instead of printing unasked.
- **The old `POST /api/v1/webhook/grocy`** (JSON `{product_id, type, quantity}`, `X-API-Key`) is **removed** (builder's call: nothing working uses it — every real Grocy call fails there — and 1.x carries no compatibility promise for it). The release notes point to `/grocy/label`. A caller with its own JSON events uses `POST /api/v1/inbox/items`.

#### 8.1.6 Future, outside this design

Possible feature requests to grocy/grocy, **only after a positive reaction from the Grocy maintainer**: custom headers for the label-printer webhook (so the token can leave the URL); a per-print choice of printer and print/collect in Grocy's UI; printing several products in one webhook call.

### 8.1a Spoolman

`POST /api/v1/webhook/spoolman` keeps its payload and its shared-secret header `X-API-Key` (`access.webhook_api_key`) and additionally accepts `X-Label-Hub-Key` with `inbox` scope or higher (builder's call: a per-app key that can be revoked on its own). **Spoolman itself sends no webhooks** (checked against Donkie/Spoolman: no outgoing HTTP hooks; it only publishes change events over a WebSocket, `spoolman/ws.py`, events like `added`/`updated`/`deleted` per spool, filament or vendor). This route therefore serves third-party callers (an automation tool, a script, a printer host plugin), not Spoolman directly; its payload is ours to define and stays as it is. A hub-side WebSocket subscriber that parks a label when a spool is added is possible later and is a non-goal of this design.

- Look the item up (snapshot), apply the event rule for the payload's `type` (section 7), then park, print or ignore.
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
- Which events do what is the user's event rule per Kept event type (decision 11, section 7). An event whose rule is `none`, or an unknown event type, answers `202 { "outcome": "ignored" }`; `ping` answers `200`.
- The receiver looks the thing up through the Kept plugin of #173 and applies the event rules for `kept` (section 7; preset: `thing.created` and `thing.moved` park, `thing.updated` none). **Until #173 ships, the route does not exist.** Alternatively Kept (or a script around it) can call `POST /api/v1/inbox/items` with an `inbox` key and `data` it already has — that works from day one.
- Kept's docs mark thing names as user-written data; the hub treats them as untrusted text (section 12.4).

### 8.4 Webhook call log (decision 17)

Every request to a hub webhook route (`/api/v1/webhook/grocy/label`, `/spoolman`, `/kept`, and calls to `POST /api/v1/inbox/items` made with an API key) gets **one log record**. That includes rejected requests (401, 403, 413, 422). It answers: when, from where, with what, what the hub did, and how it ended.

**Record (`webhook_calls` table):**

| Field | Content |
|---|---|
| `received_at` | server time, ms precision |
| `route`, `integration`, `event_type` | for example `grocy/label`, `grocy`, `grocy.stock_entry` |
| `source_ip` | the client address after the trusted-proxy resolution the hub already uses (`FORWARDED_ALLOW_IPS`), plus `user_agent` (cut to 200 chars) |
| `key_id`, `key_name` | which key authenticated (never the key or the token itself); `null` for rejected calls |
| `content_type`, `body_bytes` | the request format and size |
| `payload` | the parsed body as JSON, **redacted** (see below), capped at 32 KiB, with `payload_truncated: true` when cut |
| `http_status`, `outcome`, `reason` | what the hub answered: `parked`, `printed`, `duplicate`, `ignored`, `rejected`, plus the error code |
| `duration_ms` | time to answer. Useful against Grocy's 2-second budget |
| `inbox_item_id`, `job_id` | what the call produced; links to the inbox line or the job |
| `response_body`, `redacted_paths` | the hub's own answer (≤ 2 KiB), shown in the detail view; the paths the redaction replaced, so a replay is refused when a non-auth field was redacted (plan review) |

The **final status** is not copied. The log view joins it live from the inbox line or the job: still parked, printed on sheet X, failed with reason Y, expired, or removed. So the record never goes stale.

**Redaction.** The redaction is built in, not a filter applied afterwards:
- `token`, `key`, `secret`, `signature`, `password` and every field whose name ends in one of those are replaced with `"[redacted]"` before the record is written.
- The query string is stored without `token`.
- Kept's signature header is stored as "valid/invalid" only.

The rest of the payload is kept, because the operator explicitly wants to see it. It is product or item data from the operator's own systems.

**Retention.** 14 days or 2,000 records, whichever is reached first (builder's call). Both caps hold **at write time** (controller's call C14): a write that brings the table above 2,000 rows deletes the oldest ones in the same session; records without a key id have their own cap of 500, so an unauthenticated flood never evicts the authenticated history; and a payload of a rejected call from an unknown source is cut to 2 KiB before it is stored. The daily retention job removes records older than 14 days. So an unauthenticated flood cannot fill the table.

**Access.** Admin only: payloads can contain item data and source addresses. Read-only and inbox keys do not see the log.

**UI.**
- An **"Webhook log"** page under Settings, and a filtered view on each integration page. The Grocy panel's "Last call received" (section 8.1.4a) is the newest record of this log, not a separate field.
- The table lists time, integration, event, source, outcome, final status and duration. Rejected calls are highlighted.
- A detail view shows the formatted payload (rendered as text, never as HTML), the response sent, and links to the produced inbox line or job.
- Filters: integration, outcome, time range.
- A **"Replay"** action for a record whose outcome was `rejected` because of the hub's own configuration (for example, no target printer): it re-runs the stored payload through the current rules, and the new record is linked to the old one. No replay for authentication failures (builder's call).

**API.** `GET /api/v1/admin/webhook-calls` (filter, paginate) and `GET /api/v1/admin/webhook-calls/{id}`, `POST …/{id}/replay`. All admin-scoped.

**Tests.**
- A token in the query string or the body never appears in the stored record. Counter-test: with redaction removed, the test turns red.
- A rejected call (401) is logged without a key id.
- The final status follows a parked line through to "printed".
- Pruning respects both limits.
- An unauthenticated call stores no more than 2 KiB of payload.

## 9. Data freshness

Hub setting `inbox.freshness`, enum `snapshot` | `fresh` | `fresh_with_fallback`, default `fresh_with_fallback` (decision 6). Shown on the settings page under "Print inbox", with one sentence per option.

| Setting | At print and preview time |
|---|---|
| `snapshot` | No lookup. The stored snapshot is printed. The integration client is not called |
| `fresh` | Lookup; on failure or not-found the print is refused with the integration's error, as the batch route does today |
| `fresh_with_fallback` | Lookup; on `integration_lookup_failed`, `integration_not_configured` or not-found the snapshot is printed and the line is flagged `snapshot_fallback` |

- **Grocy lines (controller's call C11).** A Grocy line is looked up by its product id (`item_ref`). A stock-entry line also reads its stock entry, by `stock_id` from Grocy's `GET /api/stock/products/{productId}/entries` (`GET /api/stock/entry/{entryId}` needs the numeric row id, which the label webhook does not document). The fresh label keeps the grocycode as its code content, and the best-before date, amount and location come from the stock entry, not from the product's plain label. A stock entry that no longer exists counts as not found ("deleted at source").
- A fresh lookup at print time does **not** overwrite the snapshot. Only an accept (section 6.4) or a re-add (section 5.1) does.
- The flag reaches three places: the print response (`data_sources`), the job row (a new nullable column `data_source` with `fresh`, `snapshot` or `snapshot_fallback`, added by an additive Alembic migration (controller's call); exposed on the job APIs as `printed_from_snapshot: bool` plus the reason; a sheet page job, which holds several lines, stores the worst value of its cells (`snapshot_fallback` > `snapshot` > `fresh`) on the row and the value per cell in its payload) and the job list in the UI ("Printed from snapshot" badge).
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
- **Expiry warning (decision 14):** a line is never removed silently. Once a day the cleanup task marks lines whose `expires_at` is at most 3 days away (`expiry_warned_at`) and publishes `inbox.expiring` with `{ "count", "labels", "earliest_expires_at" }`. The notification centre shows "N labels expire in 3 days or less" (severity warning) opening `/cart`, where those lines carry an "Expires in N days" badge. At expiry the lines are removed and a notification "N labels expired and were removed" (warning) stays until read; `inbox.changed reason=expired` carries the ids. Without #255 the cart page shows both as a banner. (builder's call: warning entries are aggregated, not one per line.)
- `GET /api/v1/inbox` returns `expires_in_days` per line and a summary `expiring_soon: {count, labels}`; this is the data the separate daily e-mail/JMAP report issue will consume.

## 11. UI

Design skills for the build: `taste-skill:design-taste-frontend` and `emil-design-eng` for the cart and the diff view, `break-ui` for long names and many lines, `mobile-native` for the phone flow, `impeccable:impeccable` for acceptance.

### 11.1 Cart page

`CartPage.tsx` keeps its structure; the data now comes from `GET /api/v1/inbox` through TanStack Query, kept current by `inbox.changed`. `useCart()` keeps its shape where it can (items, add, remove, setCopies, clear, print) so the item view's "Add to cart" (`ItemView.tsx`) only swaps its implementation.

Per line: checkbox, name (link to the item view), app and id, origin badge for `webhook`/`api` ("from Grocy"), copies, Remove, and the badges of section 11.5. Copies changes are sent debounced with the line's `version`; a `409` refetches and keeps the user's value in the field with a note (builder's call).

Read-only sessions (decision 15) see the inbox, can add items from the item views and select lines, but get no print button, copies fields or Remove; the page says that printing needs a print key.

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

- The sheet scan resolver (`features/sheets/resolver.ts`) resolves a sheet code to `/cart?sheet=<code>`. The cart replaces the route with the sheet page when the inbox turns out empty (builder's call; the resolver is synchronous and cannot read the inbox count).
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

- **Scopes become a set, not only a chain** (controller's call). The chain `read` ⊂ `print` ⊂ `admin` stays; `inbox` is **additive**: a key's `scopes` list may hold `inbox` alone or together with others, and the effective permission is the **union** of what each listed scope grants. `read`, `print` and `admin` grant `inbox` (for `read`: decision 15, read-only access may add); `inbox` grants neither `read` nor `print`. So the enqueue-only key of decision 8 is a key whose list is exactly `["inbox"]`.
- An `inbox`-only key can call `POST /api/v1/inbox/items` and the webhook routes, and nothing else — not `GET /api/v1/inbox`, not the event stream, not any print route.
- `auth/dependencies.py` today reduces `scopes` to one effective scope from `["admin", "print", "read"]` and answers `401 key_no_scopes` for any other list (`dependencies.py:244-262`); `AuthContext.scope` is a single `Literal`. This changes to a set of granted capabilities on `AuthContext`; `require_scope(x)` checks membership; `require_inbox` joins `scope_deps.py`. The existing single `scope` field stays for logging and for routes that read it (the highest chain scope, or `inbox`). The admin key form offers `inbox` as a checkbox next to the chain with the text "Can add items to the print inbox".
- **Browser sessions** carry the capabilities of the key they were minted from, `inbox` included; the session row keeps its single scope label, and the capabilities are re-read from the key's scope list on every use, as `load_valid` already does for `allowed_printer_ids` (builder's call).
- **Read keys still cannot sign in to the browser** (controller's call C15). The security posture stays as it is. Decision 15 is implemented at the API and scope level: a `read` key may add to the inbox and see it. The UI hides printing, copies and removal for any session without `print`. Allowing read-key sign-in is a follow-up, not part of this release.
- The enqueue response never returns stored data (section 6.2), so the key cannot be used to read the inventory back through lookups.
- `allowed_printer_ids` does not restrict enqueue (nothing prints). It restricts the inbox print routes as everywhere.
- The Basic bypass and SSO header paths resolve to the required scope today; since `read` grants `inbox`, the bypass can add to the inbox even with `pangolin_bypass_scope_downgrade` (consequence of decision 15; it still cannot print or remove).

### 12.2 Limits

| Setting | Default | Effect |
|---|---|---|
| `inbox.max_items` | 500 (the batch and sheet item cap) | Counts **labels**, copies included (controller's call); more → `409 inbox_full` |
| `inbox.expiry_days` | 30 | Lines older than this are removed by the existing cleanup task (`services/cleanup_task.py`) — never silently: a warning 3 days before and a notification on removal (section 10) |
| `inbox.expiry_warning_days` | 3 | When the expiry warning is raised |
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

- On the first load of the cart page or of any page that uses `useCart()`, if `lph.cart` holds lines and the key `lph.cart.migrated` is absent, the client sends them to `POST /api/v1/inbox/import` (`read` scope, builder's call: read-only access may add (decision 15); an `inbox`-only key cannot use it, so the import's softer lookup rule is not open to other apps).
- `import` takes the old line shape `{app, id, name, content_type, copies}` (≤ 500 lines), looks each item up for a snapshot, and on lookup failure stores a snapshot with only `title = name` and `snapshot_complete: false` instead of refusing (builder's call: the user's cart must not be lost because a source is down). Lines merge into existing ones by the rule of section 5.1. `origin = ui`.
- Idempotency: the client generates a random device id once (`lph.device`), and each line's key is `<device id>:<app>:<id>`, so two tabs migrating at the same time, or a retry after a lost response, import once.
- After a `2xx` the client writes `lph.cart.migrated` and removes `lph.cart`. On any error it keeps `lph.cart` and tries again on the next load; the page shows the server inbox plus a note "N items from this browser could not be moved yet".
- The `storage`-event sync between tabs (`cart.ts:84-95`) is removed; SSE replaces it.
- After two releases the migration code can go (builder's call).

## 14. Testing

Every test that guards a rule has a counter-test against the code without the rule (`test-coverage-pflicht`): remove the guard, the test must turn red **for the right reason**.

**Backend (pytest)**

- Enqueue: lookup item → snapshot stored; source down with display data → parked, `snapshot_complete: false`, filled by the background lookup once the source is back; source down, reference only → `503` with `Retry-After`, nothing stored (counter-test: park reference-only items → the test sees a line without anything to show); `data` item → `manual`; same key twice → one line, second `duplicate: true`; same key with another body → `409 idempotency_conflict`; key reused after the line was printed → still no new line (counter-test: delete the record on print → the test sees a second line); 60-second window without key.
- Line identity: the same Grocy product twice with equal data → one line, copies 2; with another best-before date → two lines; two stock entries (different grocycodes) → two lines; two "label per unit" calls (same data, different `stock_id`) → two lines. Counter-test: merge on `(app, ref, format)` only → the best-before test turns red.
- Event rules: a fresh integration has its preset rows, none with `print`; `none` → nothing stored, response `ignored`; per-event printer and format override the integration default; `print` onto an IPP printer parks; an unknown Kept event type → ignored; a `designer_layout` format → `422 format_not_supported` until #178. Grocy URL params never enable a `none` event (counter-test: let `mode=print` win over `none` → red).
- Expiry: a line 3 days before `expires_at` raises `inbox.expiring` once (not daily again for the same line); at expiry the line is removed and the removal notification exists; no line ever disappears without one of the two (assert both events in a time-travel test).
- Limits: an add that brings the inbox to 501 **labels** (e.g. 499 labels + one line with 2 copies) → `409 inbox_full` and nothing of the request stored (counter-test: count lines instead of labels → the test turns red); expired lines hidden before the sweep and removed by it; a print selection of 501 labels → `422 selection_too_large`, nothing queued.
- Scope set: `["inbox"]` only enqueues; `["read"]` enqueues and reads but gets `403` on PATCH/DELETE/remove/refresh/print; a session minted from a `["inbox", "print"]` key can enqueue and print. Counter-test: keep the old "highest of three" reduction → an `["inbox"]` key gets `401 key_no_scopes` and the test turns red.
- Scope: an `inbox` key can enqueue; it gets `403` on `GET /api/v1/inbox`, the event stream, every print route, PATCH/DELETE; `read`, `print` and `admin` can enqueue. Counter-test: make `inbox` imply `read` → the read test turns red. The enqueue response contains no snapshot field (assert on the raw JSON, not the parsed model).
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
- Migration: lines sent once with the derived keys; `lph.cart` removed only after `2xx`; kept on error; a read-only session migrates too.
- Read-only session: "Add to cart" works, checkboxes work, no print button, no Remove, no copies field.
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
5. **Event rules + webhook changes:** the rule tables with presets and their settings UI (section 7), the new Grocy label route (section 8.1) with background enrichment, removal of the old `/grocy` route, Spoolman.
6. **UI:** server cart, selection, migration, then the sheet preview changes (with #249 for the colour token), then scan → sheet.
7. **Refresh and diff** (backend + UI).
8. **Notifications** (waiting for sheet, expiry warning, expired) — with #255, or the top-bar count and cart banner as interim (section 10).
9. **Kept receiver** — after #173.

The 1.6.1 items of #27 (cart icon with badge, grouping and confirmation) can follow step 6.

**Decision register:** proposes new rows (numbers to be assigned when merged):
- "The cart is a server-side print inbox; selection stays per device";
- "Parked items always store a snapshot; `inbox.freshness` decides which source prints";
- "Scope `inbox` may only enqueue";
- "Page printers always park".

## 16. Rollout

- The inbox is built on `milestone/<version>` and ships when that branch is merged into `main` with a merge commit; releases run from `main` only.
- Release notes: the cart moves to the server on first visit; read-only sessions can add and select but not print or remove; webhook responses gain `outcome`; a webhook routed to a page printer now parks instead of failing silently.
- Grocy: the old `/api/v1/webhook/grocy` is gone; the notes show how to set `LABEL_PRINTER_WEBHOOK` to `/api/v1/webhook/grocy/label?token=…`, recommend `LABEL_PRINTER_RUN_SERVER=true`, and say why the token must be a dedicated `inbox` key (it appears in Grocy's logs and, in browser mode, in every client).
- The migration needs no operator action. `inbox.*` settings have defaults; routes default to `park`. Nothing printed through a webhook before (#188, and the Grocy format mismatch), so no working setup changes behaviour; the notes name the one setting for "print now".

## 17. Builder's calls (collected)

| # | Call | Section |
|---|---|---|
| B1 | Own table `inbox_items`, not settings/JSON blob | 5.1 |
| B2 | `paperless` not in the inbox app enum yet; `manual` for raw data | 5.1 |
| B3 | A merge does not extend `expires_at` | 5.1 |
| B4 | Identical raw `manual` data merges like any label; lines that become identical after an accept are not merged | 5.1 |
| B5 | Idempotency records kept 7 days after print/removal | 5.3 |
| B6 | Refresh candidates stored server-side, 15 minutes | 5.4 |
| B7 | ≤ 50 items per enqueue request; `200` not `202` | 6.2 |
| B8 | 60-second duplicate window for callers without a key | 6.2, 8.1 |
| B9 | `Retry-After: 30` on the generic route's `503`; all-or-nothing per request | 6.2 |
| B10 | Changing, removing, refreshing and accepting need `print`; read-only access only adds and selects; import needs `read` | 6.3, 13 |
| B11 | ≤ 4 concurrent lookups per integration during refresh; one refresh at a time | 6.4, 12.2 |
| B12 | One render route for before/after; sheet items rendered as one cell | 6.4 |
| B13 | Server builds the print from line ids, flags fallbacks, removes lines in the same transaction | 6.5 |
| B14 | Removal on acceptance (`202`), not on printer completion — unchanged | 6.5 |
| B15 | Event rules in two tables (integration default + per event type), own admin API; default format per app | 7.1, 7.3 |
| B16 | `print` route with unavailable printer parks with a reason | 7 |
| B17 | Spoolman webhook also accepts an `inbox`-scoped `X-Label-Hub-Key` | 8.1a |
| B18 | Webhook `quantity` is not copies; copies = 1 | 8.1a |
| B19 | Grocy event types limited to `grocy.product` / `grocy.stock_entry` (the payload cannot tell purchase, manual print and auto re-print apart); unknown event types of any integration are ignored | 7.1 |
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
| B33 | Grocy route refuses `admin` tokens; URL params override target/mode only within bounds (never enable `none`, need print rights, page printer parks); `mode=print` with an `inbox`-only key parks with a reason | 8.1.4 |
| B34 | Browser-mode CORS: one configured origin, `POST` only, no credentials | 8.1.4 |
| B35 | Grocy duplicate window 10 s over `(key id, request hash)` | 8.1.5 |
| B36 | Old `/api/v1/webhook/grocy` removed, not kept as a generic JSON endpoint | 8.1.5 |
| B37 | Sessions store the key's scope list, re-read on use | 12.1 |
| B38 | `next_sheet` labels stay selected after the print | 11.3 |
| B39 | Grocy mapping: best-before from `stock_entry.best_before_date` (else `details.next_due_date`), `due_date` never parsed; note printed; price/open/purchase date not printed; `stock_id` kept as metadata | 8.1.2 |
| B40 | Enrichment fetches stock-entry location, product group, shopping location, userfields, picture; userfields and picture used only once a format shows them | 8.1.3 |
| B41 | Expiry warnings aggregated into one entry; banner on the cart page until #255 | 10 |

**Controller's calls** (decided at the builder check, 2026-11-09; C11–C16 after the plan review, 2026-11-09):

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
| C10 | Generic enqueue with the source down: display data sent → park incomplete, fill later; reference only → `503` + `Retry-After` | 6.2 |
| C11 | Grocy lines store the product id as `item_ref`; `grocycode` and `stock_id` in `item_meta`; fresh and refresh read product + stock entry, the code stays the grocycode | 5.1, 8.1.2, 9 |
| C12 | No lookup or render under the inbox lock; versions checked, lines claimed (`409 inbox_item_printing` for a claimed line) and copied under it, printed lines removed under a brief second lock by version; changed lines stay and are reported; claims released on every exit path, expiring after 5 minutes | 6.5 |
| C13 | Token stripped from uvicorn's access log by an app-installed filter, tested against real uvicorn with the container command | 8.1.4 |
| C14 | Call-log caps (2,000 rows overall, 500 rows and 2 KiB for unauthenticated) enforced at write time | 8.4 |
| C15 | Browser sign-in with read keys stays refused; decision 15 holds at API/scope level and in the UI for sessions with inbox capability; read-key sign-in is a follow-up | 12.1 |
| C16 | Grocy form bodies are decoded with PHP bracket notation | 8.1.1 |

## 18. Open questions for the maintainer

None. The maintainer's answers of 2026-11-09 are decisions 11–16 (section 4); the last open point (generic enqueue with the source down) is decided as controller's call C10 (section 6.2).
