# Milestone 1.7.0 — Design

**Date:** 2026-11-14
**Status:** Draft, written autonomously overnight; the maintainer reviews it together with the plan.
**Milestone:** 1.7.0 (minor: `feat` commits allowed, no `!`, no `BREAKING CHANGE:` footer)
**Branch:** `milestone/1.7.0`, created from `milestone/1.6.0` so the work starts with the Labelyard names
**Issues:** #296, #285, #284, #283, #282, #281, #255 (read with `gh api repos/strausmann/Label-Printer-Hub/issues/<n>`
and `/comments`; `gh issue view` fails on this repo because of the Projects (classic) sunset)
**Plan:** `docs/superpowers/plans/2026-11-14-milestone-1-7-0.md`

The maintainer was not available while this was written. Every decision that the issues and the code did not settle is
recorded as a **ruling** (R-numbers below). Everything only the maintainer can decide is in
[Questions for the maintainer](#questions-for-the-maintainer), each with a recommendation.

## 1. Intent

1.7.0 collects the features that the 1.5.x triage moved out of a patch release, plus the Grocy label printer webhook
that #27 split off. The common thread: the operator should see and finish more from the web UI, without scripts or
the admin API.

- An operator who sets up a tape printer only in the web UI gets its status (#296).
- A cart catches a label that will not print before it is sent (#285).
- Webhook labels show the quantity the event carries (#284), and Grocy can print its own labels on the hub (#281).
- A sheet with many unconfirmed cells is settled in one step (#282).
- Failures and printer problems surface where the operator looks first (#255).
- The rule for admin keys and printer restrictions gets decided (#283).

### Non-goals

- The print inbox (#27). The Grocy label endpoint prints directly; #27 later routes it through the inbox.
- Per-user server-side notification state. Read and cleared state stays per browser (#255, decided in the issue).
- A Grocycode reader in the hub's scan page. Grocy labels carry a Grocycode for Grocy's own scanner (R-281-6).
- Any change to the API key model beyond what #281 needs. #283 is a decision, not an implementation task here.

### Anti-goals (a failure even if it technically works)

- A token that ends up in the hub's own logs, error bodies or events (#281).
- A webhook or bulk call that lets a key do more than its scope and printer list allow.
- A notification centre that hides an error behind colour alone, or whose panel the on-screen keyboard can cover.
- A release with an open issue in the milestone (repo rule; #283 needs the maintainer's ruling first).

## 2. Constraints that bind every part

- **Names:** Labelyard in prose. Settings are `LABELYARD_*`; the `PRINTER_HUB_*` fallback from `app/config_legacy.py`
  keeps working. Browser storage keys keep the existing `lph.` prefix (`lph.cart`, `lph.theme`): renaming storage keys
  is 1.6.0's business, not this milestone's (R-0-1).
- **Hard repo rules** (`CLAUDE.md`, `CONTRIBUTING.md`): TDD, Conventional Commits with the scopes in
  `commitlint.config.cjs`, the print queue is mandatory (ADR 0005), mypy strict, website pages in English and German in
  the same PR, glossary terms, generated screenshots for UI changes, `e2e/short-viewport.spec.ts` for new dialogs,
  popovers and fields that must stay in sight with the on-screen keyboard.
- **New API endpoints** come with their OpenAPI schema (ADR 0011) and `frontend/src/api/schema.gen.ts` regenerated
  with `pnpm gen:api`.
- **Every new route** carries a recognised auth marker; `backend/tests/unit/api/test_route_auth_coverage_guardrail.py`
  must stay green (a new marker is added to `_RECOGNISED_AUTH_MARKERS` there, with its reason).
- **Privacy:** no private addresses, host names or tokens in the repo; examples use `example.invalid`.

### The attacker model from the 1.5.x hardening (applies to #281, #282, #284, #285)

| Actor | What it holds | What it may do |
|---|---|---|
| Anonymous caller on the network | nothing | reach unauthenticated routes only; webhook routes answer 401/503 |
| Webhook caller | the shared webhook key (`LABELYARD_WEBHOOK_API_KEY`, ≥ 32 chars, `X-API-Key`) | print through `/api/v1/webhook/{spoolman,grocy}`, 120 calls/min per key (`LABELYARD_WEBHOOK_LIMIT_PER_MINUTE`) |
| API key `read` | key header `X-Label-Hub-Key` | read; sees only its own jobs (#294) |
| API key `print` | as above | read and print; marks and resolves sheet cells (#264); restricted to `allowed_printer_ids` when set |
| API key `admin` | as above | everything; printer restriction not enforced on admin printer routes (#283, open) |
| Browser session | a session derived from a key | the key's scope, printer list and rate limit |

Every key has its own per-minute bucket (`enforce_key_rate_limit`, applied after bcrypt verification). Error bodies
never carry `str(exc)` of an upstream or integration error (CWE-209). A job records `api_key_id` and `source_ip`.

## 3. #296 — SNMP status discovery in the printer form

### Findings in the code

- `SNMPConfig` (`backend/app/schemas/printer_admin.py:32`) has `discover: bool = False` and
  `community: str | None = "public"` (≤ 64 chars); the model validator requires a community when `discover` is true.
- `PUT /api/v1/admin/printers/{slug}` replaces `connection` as a whole (`docs/getting-started.md`, section "Turn on
  status discovery"). The form already spreads the stored connection into what it sends
  (`frontend/src/features/settings/PrinterForm.tsx`, `submit()`), so today a save keeps the stored `snmp` object.
- **Is the community a secret?** Partly. The audit trail redacts it (`backend/app/services/audit_redaction.py`,
  `SECRET_PATHS`), but the admin read routes return it unredacted (`_row_to_read` in
  `backend/app/api/routes/admin_printers_api.py` returns `printer.connection` as stored), to admin callers only.
- Both tape drivers use it (`ptouch_backend.py`, `brother_ql_backend.py`); IPP printers have no SNMP block.

### Design

- **R-296-1:** The form shows a **Status discovery** switch and an **SNMP community** field for the drivers `ptouch`
  and `brother_ql`, never for `ipp`.
- **R-296-2 (write-only in the UI):** the community field is a password-type input that is never filled from the
  stored value. Empty means "keep the stored community". When a community is stored, the field description says so
  ("A community is stored. Leave the field empty to keep it."). The API contract stays as it is in 1.7.0; whether the
  admin read routes should stop returning the community is question Q2.
- **R-296-3 (client validation, mirrors the backend):** discovery on with an empty field and no stored community is
  refused before sending ("Enter the SNMP community, or turn status discovery off."). Over 64 characters is refused.
- **R-296-4:** the snmp object that the form sends is computed by one pure function
  (`snmpPayload(stored, draft)`); on create with discovery off it sends `{discover: false, community: "public"}` like
  the schema default.
- No backend change. The backend already validates and re-wires on a connection change (`wiring_key`).
- Docs: `docs/getting-started.md` section 2 ("Turn on status discovery") is rewritten to use the form; the
  `curl` example moves to "from a script". The website page `install/printers.md` (en + de) gets the switch.

## 4. #285 — Preview every distinct content type in the cart

### Findings

- `CartPage.tsx` previews `cart.items[0]` only (`CartPreview`), via a client lookup plus `POST /api/v1/render/preview`.
- Whether a QR payload fits is not a fixed byte count: the fixed QR box depends on tape, orientation and preset
  (`build_box_qr` in `backend/app/services/ql_layout.py` raises `QrPayloadTooLongError(length, max_bytes)`), and the
  QR payload of a cart item comes from the integration lookup. **A client-side size check cannot be exact**, so the
  issue's alternative ("check each item's size client-side") is not taken.

### Design

- **R-285-1 (previews):** one preview per distinct `content_type` in the cart, in cart order, using the first item of
  that type; at most `MAX_CART_PREVIEWS = 4`. Above that, a line "N more layouts are not shown." Each preview names
  its item ("Shows Cable 7 for the QR + 2 lines layout.").
- **R-285-2 (check every item):** a new read endpoint `POST /api/v1/render/check` validates items the way a print
  would render them, without a printer, queue or database:
  - Body: `{tape_mm, orientation?, layout_preset?, items: [{content_type, lookup: {app, identifier}}]}`, 1 to
    `MAX_RENDER_CHECK_ITEMS = 50` items.
  - Answer 200: `{results: [{index, ok, error_code, error_detail}]}`, one per item, same order.
  - Per-item codes: `qr_payload_too_long` (with `length`, `max_bytes`), `content_type_data_mismatch` (with
    `missing_fields`), `app-lookup-not-found`, `integration_lookup_failed`, `integration_not_configured`,
    `integration_unknown_app`. Request-level codes: 409 `unsupported_tape` (as the preview), 422 for a bad body.
  - Lookups run through `AppLookupService` with at most `MAX_BATCH_LOOKUPS` (8) at once; identical
    `(app, identifier, content_type)` items are looked up and rendered once. Renders run in `asyncio.to_thread`.
  - Scope `read` (the preview and the lookup route are `read` too). No `str(exc)` in any result.
- **R-285-3 (cart UI):** the cart sends its items in chunks of 50 when a tape printer is selected and the tape is known;
  an item with a failed check gets an inline flag in its row ("The QR code does not fit this tape: 812 of at most 122
  bytes."), and the print button stays enabled but the print section shows "N labels will not print. Remove them or
  change the layout." The server stays the authority: a batch with such an item is still refused as before.
  - Rationale for not disabling the button: the check uses the current lookup data, which can change; the batch
    answer is binding. The flag is advice that appears before printing.
- Attacker model: `read` keys could already render previews; the check caps work per call (50 items, 8 lookups at
  once, deduplication) and is counted by the key's rate limit like any call.

## 5. #284 — The webhook quantity on the label

### Findings

- `SpoolmanWebhookPayload.quantity` and `GrocyWebhookPayload.quantity` are accepted and ignored
  (`backend/app/schemas/webhook.py`); webhook labels print as `qr_two_lines`, which shows `primary_id` and `title` only.
- The Spoolman lookup already builds a `"{grams}g remaining"` line with half-up rounding
  (`integrations/spoolman/plugin.py`), which `qr_two_lines` never shows.
- `qr_three_lines` shows `secondary[0]` (`layout_engine.py`, `ContentType.QR_THREE_LINES`).
- The website already promises the quantity ("with the quantity when the event carries one",
  `website/src/content/docs/integrations/grocy.md`).

### Design

- **R-284-1 (content type):** with a quantity the label prints as `qr_three_lines` and the quantity line is
  `secondary[0]`; without one it prints as `qr_two_lines` exactly as today (acceptance: unchanged when absent).
- **R-284-2 (Spoolman):** `"{grams}g remaining"`, grams rounded half up to a whole number (same rule and text as the
  plugin). The webhook value wins over the lookup's remaining weight: it describes the event that triggered the print.
- **R-284-3 (Grocy):** `"Stock change: {signed}"`, the delta with an explicit sign (`+2`, `-1.5`, `0`), rounded half up
  to at most two decimals, trailing zeros removed, ASCII minus. Grocy's webhook carries no quantity unit, so none is
  printed.
- **R-284-4 (bounds, no new refusals):** a quantity outside `[0, 1 000 000]` (Spoolman) or `[-1 000 000, 1 000 000]`
  (Grocy) is treated as absent and logged at INFO without the value. 1.7.0 adds no new 422 for a payload that 1.5.x
  accepted.
- **R-284-5 (label text language):** English, like the existing Spoolman line. Localised label text is question Q4.
- The stored job payload carries the label data with the quantity line, so a restart re-renders the same label.
- Mechanism: `PrintService.submit_print_job` gets an optional `label_transform` that runs on the resolved
  `LabelData` before render and persist; the webhook passes a transform that sets the quantity line.
- Schema descriptions of `quantity` say what is printed.

## 6. #281 — Grocy's label printer webhook

### What Grocy sends (from Grocy's source, commit `146f73af47fe65f806b6eea0ac5f3bee7cb62cb5`)

- `controllers/Api/{Stock,Chores,Batteries,Recipes}ApiController.php` build `$webhookData` and call
  `helpers/WebhookRunner.php`, which POSTs it with a **2.0 s timeout**, as JSON when `LABEL_PRINTER_HOOK_JSON` is true
  (the default in `config-dist.php`), else form fields. Grocy writes every webhook URL **and body** to its stderr.
- Fields per label type (then `array_merge` with `LABEL_PRINTER_PARAMS`, which can override any key):

| Label | Name field | `grocycode` | Extra |
|---|---|---|---|
| product | `product` | `grcy:p:<product_id>` | `details` |
| stock entry | `product` | `grcy:p:<product_id>:<stock_id>` | `details`, `stock_entry`, `due_date` = `"<localised DD>: <date>"` when best-before tracking is on |
| chore | `chore` | `grcy:c:<chore_id>` | `details` |
| battery | `battery` | `grcy:b:<battery_id>` | `details` |
| recipe | `recipe` | `grcy:r:<recipe_id>` | `details` |

- The magic prefix is `grcy` (`Grocycode::MAGIC` in `helpers/Grocycode.php`), not `grocy` as Grocy's own
  `docs/label-printing.md` example shows.

### Design

- **Endpoint:** `POST /api/v1/webhook/grocy/label`, 202 `WebhookAcceptedResponse` (the existing schema).
- **R-281-1 (authentication):** an **API key** (the `lh_…` keys of `api_keys`), not the shared webhook key: the issue
  asks for a dedicated key that can be printer-restricted, which only API keys can be.
  - The key comes from the query parameter `token`; the `X-Label-Hub-Key` header is accepted too, for callers that can
    send headers (header wins when both are present).
  - The key must have the effective scope **`print`**. A `read` key answers 403 `insufficient_scope`; an **`admin` key
    answers 403 `token_scope_too_wide`**: a URL token is stored in Grocy's config and written to Grocy's stderr, so it
    must never be an admin key.
  - Every failure of the token itself (missing, malformed, unknown, disabled, expired, wrong) answers the same
    **401 `invalid_token`** with one fixed message. The 1.5.x API key path distinguishes `key_disabled`, `key_expired`
    and so on; a URL token does not get that detail.
  - The key's own rate limit applies (`enforce_key_rate_limit`, after bcrypt), 429 with `Retry-After` above it.
  - The token is read from `request.query_params` inside the dependency, not declared as a FastAPI `Query` parameter:
    a declared parameter with a constraint would echo the value in a 422 body.
- **R-281-2 (the hub's logs):** a logging filter on the `uvicorn.access` and `uvicorn.error` loggers replaces the
  value of every `token` query parameter with `***` before the record is formatted. The filter is installed at app
  start. The job records `api_key_id` and `source_ip`, never the token.
- **R-281-3 (body):** JSON only (`application/json`), else 415 `json_required` with a hint to set
  `LABEL_PRINTER_HOOK_JSON=true`. At most 64 KiB (`MAX_GROCY_LABEL_BODY = 65_536`), else 413. Unknown fields are
  ignored (`details` and `stock_entry` are not read, R-281-5).
- **R-281-4 (label type):** taken from `grocycode`, validated against
  `^grcy:(p|c|b|r):[0-9]{1,10}(:[A-Za-z0-9_-]{1,64}){0,3}$`: `p` with an extra part is a stock entry, `p` without is a
  product, `c` chore, `b` battery, `r` recipe. The name field must match the type (`product` for `p`, and so on),
  else 422 `grocy_label_mismatch`.
- **R-281-5 (label data, no call back to Grocy):** everything comes from the body. Grocy waits 2 s at most, and a
  lookup round trip is not needed:
  - `title` = the name, `primary_id` = the object id from the Grocycode, `qr_payload` = the Grocycode (Grocy's own
    scanner understands it), `secondary` = `(due_date,)` for a stock entry that carries one, else empty;
    `source_app = "grocy"`.
  - Every text is cleaned with `sanitise_text` and capped at `RAW_TEXT_MAX` (512).
- **R-281-6:** the hub's scan page does not learn Grocycodes in 1.7.0 (question Q5).
- **R-281-7 (mapping on the Grocy settings page):** new runtime settings, editable under
  **Settings > Integrations > Grocy**:

| Key | Kind | Default |
|---|---|---|
| `integrations.grocy.label.enabled` | bool | `false` |
| `integrations.grocy.label.product.content_type` | enum | `qr_two_lines` |
| `integrations.grocy.label.stock_entry.content_type` | enum | `qr_three_lines` |
| `integrations.grocy.label.chore.content_type` | enum | `qr_two_lines` |
| `integrations.grocy.label.battery.content_type` | enum | `qr_two_lines` |
| `integrations.grocy.label.recipe.content_type` | enum | `qr_two_lines` |
| `integrations.grocy.label.<type>.printer` | str (printer slug) | `""` = the first enabled tape printer, as the other webhooks |

  Enum choices: `qr_only`, `qr_one_line`, `qr_two_lines`, `qr_three_lines`. A `qr_three_lines` label without a
  secondary line prints the third line empty (the engine's existing behaviour). No environment variable locks these.
- **R-281-8 (order of checks):** token → rate limit → `label.enabled` (503 `grocy_label_disabled`) → body → printer
  resolution (configured slug unknown, disabled or a page printer: 503 `grocy_label_printer_unavailable`; none
  enabled: the existing 503) → `check_printer_access` (403 `printer_not_allowed`; `default_printer=True` when the
  mapping names no printer, so the id is not revealed) → `PrintService.submit_print_job` with raw label data and
  `source_app="grocy"` → 202. Print errors are answered by `print_error_response` like the other webhooks.
- **R-281-9 (config block):** the settings page shows a ready-to-copy block for Grocy's `config.php`:

```php
Setting('FEATURE_FLAG_LABEL_PRINTER', true);
Setting('LABEL_PRINTER_WEBHOOK', '<public-url>/api/v1/webhook/grocy/label?token=<print-key>');
Setting('LABEL_PRINTER_RUN_SERVER', true);
Setting('LABEL_PRINTER_HOOK_JSON', true);
```

  `<public-url>` is filled from `general.public_url`; `<print-key>` stays a placeholder, with a link to
  **Settings > Access keys** and the advice "a key with the print scope, restricted to the label printer".
  `LABEL_PRINTER_RUN_SERVER=true` is recommended: run client-side, Grocy hands the URL and token to every browser.
- **R-281-10 (ADR):** URL-token authentication for one route is a security decision: a new ADR (next free number after
  1.6.0's) records it, `Proposed` in the first task, `Accepted` when the feature ships, with the register row.
- Docs: `website/src/content/docs/integrations/grocy.md` and `webhooks.md` (en + de), `admin/api-keys.md` (en + de):
  the token form, its exposure in Grocy's own log, and the advice to restrict the key.

## 7. #282 — Resolve all unconfirmed cells of a sheet

### Findings

- `resolve_cells` in `backend/app/sheets/sheet_service.py` settles a list of cells in one `write_transaction`,
  publishes one `sheet.updated` and logs the count. The route `POST /api/v1/sheets/{code}/cells/resolve`
  (`backend/app/api/routes/sheets.py`) uses `PrintDep` and does not check printer access; #264 decided that a
  printer-restricted `print` key may resolve cells.

### Design

- **Endpoint:** `POST /api/v1/sheets/{code}/cells/resolve-all`, scope `print`, response `SheetRead`.
- **Body:** `{outcome: "printed" | "not_printed", expected_count?: int ≥ 1}`.
- **R-282-1 (the count the user confirmed):** when `expected_count` is sent and the number of unconfirmed cells at the
  server differs, the call answers **409 `unconfirmed_count_changed`** with `error_detail.unconfirmed` and changes
  nothing. The UI always sends it, so a cell that turned unconfirmed after the dialog opened is never resolved
  unseen.
- **R-282-2:** nothing unconfirmed answers **409 `no_unconfirmed_cells`** (issue acceptance).
- **R-282-3 (one code path):** the per-cell settle logic moves into one private helper used by `resolve_cells` and
  `resolve_all_cells`, so `printed` keeps setting `id_printed` and `feed_mark_printed` exactly as today.
- One transaction; a failure part-way changes no cell. One `sheet.updated` event with all changed cell numbers.
  A discarded sheet answers the existing 409 `sheet_discarded`.
- **UI:** in the "Unconfirmed cells" panel of `SheetDetail.tsx`, two buttons "Resolve all as printed" and
  "Resolve all as not printed", shown when at least two cells are unconfirmed. Each opens a confirmation in
  `ModalDialog` naming the count ("Resolve 3 cells as printed?"); on 409 `unconfirmed_count_changed` the sheet reloads
  and the dialog says "The number of unconfirmed cells changed. Check the list and try again." Added to
  `e2e/short-viewport.spec.ts` like the discard confirmation.

## 8. #283 — Do printer restrictions bind admin keys? (decision, no task)

### Current state

- The admin printer routes (`backend/app/api/routes/admin_printers_api.py`) call `check_printer_access` only in
  `resolve_identity` (line 565). A restricted admin key can create printers and update, disable and enable any
  printer.
- `create_api_key` (`backend/app/api/routes/admin_api_keys.py:158`) lets any admin key create any key, including an
  unrestricted admin key; `update_api_key` lets it widen `allowed_printer_ids` of any key.
- Not exploitable beyond the admin scope itself: a restricted admin key can always mint an unrestricted one.

### Options

| | 1. Admin ignores printer restrictions | 2. Enforce restrictions for admin keys |
|---|---|---|
| Rule | `admin` means the whole hub. `allowed_printer_ids` is refused (422) when a key with `admin` is created or updated | A restricted admin key acts only on its printers and cannot create or widen a key beyond its own access |
| Work | small: validation in two routes, docs, a migration note for existing restricted admin keys (they keep working, the list is ignored and shown as ignored) | larger: every admin printer route checks access; `create_printer` is refused for a restricted admin (a new printer is outside its list); key create/update check that the new scopes and printer list are a subset of the caller's; `list_printers` filtered |
| Hub-wide routes | unchanged | still open to a restricted admin: settings, integrations, webhook key, sheet types. A restricted admin is a "printer admin", not a hub admin, unless those are closed too (more work) |
| Existing installs | restricted admin keys stop pretending to be restricted (visible in the UI) | restricted admin keys lose access they have today; that can break automation |
| Release impact | clean minor | closing access existing keys have is close to breaking; needs an upgrade note |

### Recommendation

**Option 1.** The restriction cannot be a real boundary for admin unless every hub-wide route (settings, keys,
integrations, sheet types) is closed as well, and that is a role model the hub does not have. Option 1 makes the
documented rule match the code, costs little, and leaves a "printer operator" role (print scope plus printer admin
actions) as a clean future feature if it is wanted. The issue's acceptance (rule documented, tests with a counter-test
for every admin printer route and key creation) applies to whichever option is chosen; the plan adds that task once
the ruling is in (Q1).

## 9. #255 — Notification centre in the top bar

> **The UI design below needs the maintainer's approval before implementation.** The plan task is marked so.

### Decided in the issue (binding)

Button with a severity dot and an unread count next to the scan button; panel newest first; click opens the job or
printer page; every print job with its live state; printer problems while they last; "Mark all as read" keeps
entries, "Clear all" hides them up to the newest one present when clearing; full-height sheet on a phone; focus trap
and Escape; entries come from the server and stay live over SSE; read and cleared state per browser in local storage;
the overview card "Needs attention" uses the same source, and a failed job that was retried successfully or dismissed
leaves it.

### Source of entries

- **R-255-1 (no new endpoint):** entries are derived in the browser by one pure function
  `deriveNotifications({jobs, printers, statuses, sheets, now})` from data the server already serves and keeps live:
  `GET /api/v1/jobs?since=<now − 24 h>&limit=200`, the printer list and statuses, and `GET /api/v1/sheets`. These
  queries are invalidated by the existing SSE events (`job.state_changed`, `printer.status`, `printer.tape_changed`,
  `printer.identity_mismatch`, `sheet.updated`) and re-read after a reconnect. A second endpoint would duplicate the
  printer-state rules that `describePrinter` (`frontend/src/features/printers/model.ts`) already owns.
  A read key sees only its own jobs (#294); its centre shows what it may see.
- **R-255-2 (retried jobs):** the retry route stores `retry_of: "<original job id>"` in the new job's payload
  (`backend/app/api/routes/jobs.py`, `retry_job` and `_retry_page_job`). A failed job with a later `done` job whose
  `payload.retry_of` names it counts as resolved: it stays in the centre as information and leaves "Needs attention".
  Only retries made from 1.7.0 on carry the link.

### What counts as an entry, and its severity

| Source | Entry | Severity | Target |
|---|---|---|---|
| Job `queued`, `printing` | "Cable 7 is printing on PT-P750W" | info | job page |
| Job `done` | "Cable 7 printed" | success | job page |
| Job `cancelled` | "Cable 7 was cancelled" | info | job page |
| Job `failed`, `failed_restart` (not resolved by a retry) | "Cable 7 failed: <error text as on the job page>" | **error** | job page |
| Job failed, resolved by a retry | "Cable 7 failed, printed on retry" | info | job page |
| Printer offline, error, stopped with a blocking or error reason | `describePrinter` kind and detail | **error** | printer page |
| Printer answered as another device (#231) | "Different device at the address of …" | **error** (issue) | printer page |
| Printer paused, stopped without a serious reason | kind label | warning | printer page |
| Printer status stale or not polled (#227) | "Status unknown" / "Not monitored" | warning | printer page |
| Tape or label roll empty, toner or ink low or empty | the status's own words | warning | printer page |
| Sheet with unconfirmed cells | "3 unconfirmed cells on sheet AB-12" | warning | sheet page |

- Entry ids: `job:<id>:<state>` (a state change is a new, unread entry), `printer:<id>:<kind>`,
  `sheet:<code>:unconfirmed`. Printer and sheet entries exist while the condition lasts; their time is the moment
  this browser first saw the condition (kept in storage), so "Clear all" can hide them.
- At most 100 entries, newest first.

### Button and badge

- An icon button (bell) in `TopBar.tsx`, between the search and the about link; on a phone in the top bar too (the
  tab bar keeps Scan).
- The dot shows the highest **unread** severity: red dot for error, yellow **diamond** for warning (the shape rule of
  `StatusBadge`: colour is never the only signal), green dot for success/info only, nothing when all is read. Next to
  it the unread count, `99+` above 99.
- Accessible name: "Notifications, 3 unread, the most severe is an error" (de: "Benachrichtigungen, 3 ungelesen, die
  schwerste ist ein Fehler").

### Panel

- Desktop: a popover under the button, 24 rem wide, at most `min(70vh, var(--vvh) − 5rem)` high, scrolls inside.
- Phone (< 640 px): a full-height sheet sized with `var(--vvh)` and `var(--vv-top)` (CONTRIBUTING, on-screen
  keyboard), with a close button in its header.
- Header: title, "Mark all as read", "Clear all". Each entry: severity shape and word, one-line text (two lines on a
  phone), relative time ("2 min ago", absolute time in the title attribute), printer or source; unread entries carry
  a bold text and a small "new" marker. The whole entry is a link to its target and closes the panel.
- States: loading ("Loading notifications…"), empty ("Nothing new."), every source failed ("Notifications could not be
  loaded." with a retry button), live stream down (one line "Live updates paused; the list may be out of date.", from
  the stream state `LiveStatus` already shows).
- Keyboard: the button opens the panel with focus on its first action; Tab stays inside; Escape and the close button
  return focus to the bell. Built on react-aria `DialogTrigger` + `Popover`/`Modal`, like the other dialogs.
- Motion: a 150 ms fade and lift on open; none with `prefers-reduced-motion`.
- **On-screen keyboard rule:** the panel holds no text field, but it can be opened while the global search has the
  keyboard up. In `e2e/short-viewport.spec.ts`, at 1280x500 and 390x400 with a visual-viewport keyboard, the header
  actions and the first entry must lie in the visible area.

### Read, clear, dismiss, persistence

- Storage key `lph.notifications`, value `{v: 1, read: string[], clearedAt: string | null, dismissed: string[],
  firstSeen: Record<string, string>}`; `read` and `dismissed` keep the newest 500 ids each.
- "Mark all as read": every visible id goes into `read`; the dot disappears; entries stay.
- "Clear all": `clearedAt` = the newest entry time present; entries at or before it are hidden.
- "Dismiss" (overview card only): adds the entry id to `dismissed`; it leaves the card and the centre.
- A missing or broken storage (private mode, quota, invalid JSON) falls back to an in-memory state for the tab; nothing
  throws.
- **"Needs attention"** on the overview shows the unresolved error and warning entries of the same derivation that are
  neither cleared nor dismissed, each with a "Dismiss" button.

### Design skills for implementation

`taste-skill:design-taste-frontend` and `emil-design-eng` for the panel and the badge, `mobile-native` for the sheet,
`impeccable:impeccable` for acceptance. Screenshots light and dark at 1280 px and 390 px (`pnpm screenshots`).

## 10. Rulings index

| ID | Ruling |
|---|---|
| R-0-1 | Browser storage keys keep the `lph.` prefix |
| R-296-1…4 | Discovery switch for tape drivers; community write-only in the UI; client validation; one payload function |
| R-285-1…3 | Up to 4 previews, one per content type; `POST /api/v1/render/check`; inline flags, button stays enabled |
| R-284-1…5 | `qr_three_lines` with a quantity line; Spoolman grams; Grocy signed delta; out-of-range treated as absent; English |
| R-281-1…10 | Print-scope API key as URL token, admin refused; log filter; JSON only, 64 KiB; type from Grocycode; data from the body; no Grocycode scanning; mapping settings; check order; config block; ADR |
| R-282-1…3 | `expected_count` guard; 409 when nothing is unconfirmed; one settle helper |
| R-255-1…2 | Entries derived client-side from existing live queries; `retry_of` in the retried job's payload |

## Questions for the maintainer

| # | Question | Recommendation |
|---|---|---|
| Q1 | **#283:** do printer restrictions bind admin keys? | Option 1 (admin ignores them; refuse `allowed_printer_ids` on admin keys). The release waits for this ruling; the plan then gets its task. |
| Q2 | **#296:** should the admin printer routes stop returning the SNMP community (return `community_set: true` instead)? It changes a response field. | Yes, but in the next major, or in 1.7.0 only as an additional `community_set` field with the value kept. 1.7.0 keeps the contract (UI is write-only). |
| Q3 | **#255:** approve the UI design in section 9 (button, badge shapes, panel, sheet, states, dismiss on the overview card). | Approve as written; implementation starts after the approval. |
| Q4 | **#284:** label text in English only, or in the hub's language (`general.language`)? | English for 1.7.0, matching the existing Spoolman line; localised label text as its own issue. |
| Q5 | **#281:** Grocy labels carry the Grocycode as QR. Should the hub's scan page learn to read Grocycodes later? | Yes, as a separate issue for a later minor; not in 1.7.0. |
| Q6 | **#281:** refuse admin keys as URL tokens (403 `token_scope_too_wide`) — agreed? | Yes; a URL token sits in Grocy's config and stderr. |
