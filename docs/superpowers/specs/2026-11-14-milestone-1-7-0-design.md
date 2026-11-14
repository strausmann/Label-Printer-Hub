# Milestone 1.7.0 — Design

**Date:** 2026-11-14
**Status:** Draft; the maintainer ruled on Q1–Q6 on 2026-11-14 (issue comments 00:16–00:17Z), the rulings are applied
below. #316 joined the milestone at 00:18Z. Revised after the plan review of `c988990` (NEEDS_FIXES, corrections
C0–C18) and the controller's rulings on its open points.
**Milestone:** 1.7.0 (minor: `feat` commits allowed, no `!`, no `BREAKING CHANGE:` footer; two maintainer-ruled
exceptions, section 2)
**Branch:** `milestone/1.7.0`, created from `milestone/1.6.0` so the work starts with the Labelyard names
**Issues:** #296, #285, #284, #283, #282, #281, #255, #316 (read with `gh api repos/strausmann/Label-Printer-Hub/issues/<n>`
and `/comments`; `gh issue view` fails on this repo because of the Projects (classic) sunset)
**Plan:** `docs/superpowers/plans/2026-11-14-milestone-1-7-0.md`

Decisions that the issues, the code and the maintainer did not settle are recorded as **rulings** (R-numbers). The
maintainer's own decisions are marked "maintainer, 2026-11-14". Open points are in
[Questions for the maintainer](#questions-for-the-maintainer).

## 1. Intent

1.7.0 collects the features that the 1.5.x triage moved out of a patch release, plus the Grocy label printer webhook
that #27 split off. The common thread: the operator should see and finish more from the web UI, without scripts or
the admin API.

- An operator who sets up a tape printer only in the web UI gets its status, and the SNMP community is never shown
  back (#296).
- A cart catches a label that will not print before it is sent (#285), and the cart is always one tap away (#316).
- Webhook labels show the event's quantity in the hub's language (#284); Grocy prints its own labels on the hub and
  its codes can be scanned (#281).
- A sheet with many unconfirmed cells is settled in one step (#282).
- Failures and printer problems surface where the operator looks first (#255).
- Admin keys have one clear rule for printer restrictions (#283).

### Non-goals

- The print inbox (#27). The Grocy label endpoint prints directly; #27 later routes it through the inbox.
- Per-user server-side notification state. Read and cleared state stays per browser (#255, decided in the issue).
- A role between `print` and `admin` ("printer admin"). #283 makes `admin` mean the whole hub.
- Fixing Grocy. Grocy's own handling of webhook errors is upstream's (section 6, Q7).

### Anti-goals (a failure even if it technically works)

- A token that ends up in the hub's own logs, error bodies or events (#281).
- A webhook or bulk call that lets a key do more than its scope and printer list allow.
- An SNMP community readable through any API response (#296).
- A notification centre that hides an error behind colour alone, or whose panel the on-screen keyboard can cover.
- A release with an open issue in the milestone.

## 2. Constraints that bind every part

- **Names:** Labelyard in prose. Settings are `LABELYARD_*`; the `PRINTER_HUB_*` fallback from `app/config_legacy.py`
  keeps working. Browser storage keys keep the existing `lph.` prefix (`lph.cart`, `lph.theme`): renaming storage keys
  is 1.6.0's business (R-0-1).
- **Minor rule:** no removed or renamed response field, **except** the two maintainer rulings of 2026-11-14:
  `connection.snmp.community` is no longer returned (replaced by `connection.snmp.community_set`, #296), and
  `allowed_printer_ids` on a key with the admin scope is refused with 422 (#283). Both get an upgrade note in the
  release notes; neither carries `!` or a BREAKING footer.
- **Hard repo rules** (`CLAUDE.md`, `CONTRIBUTING.md`): TDD, Conventional Commits with the scopes in
  `commitlint.config.cjs`, the print queue is mandatory (ADR 0005), mypy strict, website pages in English and German in
  the same PR, glossary terms, generated screenshots for UI changes, `e2e/short-viewport.spec.ts` for new dialogs,
  popovers and fields that must stay in sight with the on-screen keyboard.
- **New API endpoints** come with their OpenAPI schema (ADR 0011) and `frontend/src/api/schema.gen.ts` regenerated
  with `pnpm gen:api`. `test_endpoint_count_in_range` (`backend/tests/api/test_openapi_completeness.py:139-161`,
  upper bound 88, 84 operations today) is raised to fit 1.7.0's routes.
- **Every new route** carries a recognised auth marker; `backend/tests/unit/api/test_route_auth_coverage_guardrail.py`
  must stay green.
- **Request bodies read raw** use the bounded read (`_read_bounded` in `backend/app/api/routes/sheet_types.py:161`,
  moved to `app/api/bounded_body.py`), never `await request.body()`.
- **Privacy:** no private addresses, host names or tokens in the repo; examples use `example.invalid`.

### The attacker model from the 1.5.x hardening (applies to #281, #282, #283, #284, #285, #296)

| Actor | What it holds | What it may do |
|---|---|---|
| Anonymous caller on the network | nothing | reach unauthenticated routes only; webhook routes answer 401/503 |
| Webhook caller | the shared webhook key (`LABELYARD_WEBHOOK_API_KEY`, ≥ 32 chars, `X-API-Key`) | print through `/api/v1/webhook/{spoolman,grocy}`, 120 calls/min per key (`LABELYARD_WEBHOOK_LIMIT_PER_MINUTE`) |
| API key `read` | key header `X-Label-Hub-Key` | read; sees only its own jobs (#294) |
| API key `print` | as above | read and print; marks and resolves sheet cells (#264); restricted to `allowed_printer_ids` when set |
| API key `admin` | as above | everything, on every printer: from 1.7.0 an admin key carries no printer restriction (#283) |
| Browser session | a session derived from a key | the key's scope, printer list and rate limit |
| Grocy user | can press "print label" in Grocy | when the hub answers with an error or Grocy times out after 2 s, Grocy's API answer carries the Guzzle message with the full webhook URL, **token included** (`WebhookRunner.php` catches an unimported `RequestException`; the controller returns `$ex->getMessage()`) |

Every key has its own per-minute bucket (`enforce_key_rate_limit`, applied after bcrypt verification). Error bodies
never carry `str(exc)` of an upstream or integration error (CWE-209). A job records `api_key_id` and `source_ip`.

## 3. #296 — SNMP status discovery in the printer form

### Findings in the code

- `SNMPConfig` (`backend/app/schemas/printer_admin.py:32-42`) has `discover: bool = False` and
  `community: str | None = "public"` (≤ 64 chars); the model validator requires a community when `discover` is true.
- `PUT /api/v1/admin/printers/{slug}` replaces `connection` as a whole (`printer_admin_service.py:294-300`). The form
  spreads the stored connection into what it sends (`PrinterForm.tsx:91`).
- The community is returned in plain text by the admin routes (`_row_to_read`, `admin_printers_api.py:210`) **and to
  every read caller** by `GET /api/v1/printers[/{id}]` (`_connection_view`, `printers.py:75-84`). Only the audit trail
  redacts it (`audit_redaction.py:15-19`).
- The print preflight ignores the stored community: `PrintService` calls `preflight_check()` without one and the
  backends are built without it (`backend_router.py:143-145`; `preflight_check` defaults to `"public"`), so a
  non-`public` community breaks printing. Only the status producer and the PJL query use `cfg.snmp.community`.
- Both tape drivers use SNMP; IPP printers have no SNMP block.

### Design

- **R-296-1:** the form shows a **Status discovery** switch and an **SNMP community** field for the drivers `ptouch`
  and `brother_ql`, never for `ipp`.
- **R-296-2 (write-only, maintainer 2026-11-14):** the community field is a password-type input with
  `autoComplete="off"`, never filled. Empty means "keep the stored community". With `community_set: true` the field
  description says "A community is stored. Leave the field empty to keep it."
- **R-296-3 (client validation):** discovery on, `community_set` false and an empty field is refused before sending
  ("Enter the SNMP community, or turn status discovery off."); over 64 characters is refused.
- **R-296-4:** the snmp object the form sends is computed by one pure function `snmpPayload(storedSet, draft)`; it
  omits `community` when the field is empty.
- **R-296-5 (backend, maintainer 2026-11-14):** every printer response (admin and read routes) replaces
  `connection.snmp.community` by `connection.snmp.community_set: bool`. On create and update, a `snmp` object
  **without** a `community` key (or with `null`) keeps the stored community (`"public"` on create); a non-empty string
  replaces it. The rest of `connection` is still replaced as a whole.
- **R-296-6 (backend, review F3):** the tape backends receive the stored community and use it for the preflight, so
  printing and discovery use the same community.
- Docs: `docs/getting-started.md` section 2 ("Turn on status discovery") uses the form; the `curl` example moves to
  "From a script" and no longer reads the community back. Website `install/printers.md` (en + de) gets the switch;
  `admin/upgrades` gets the upgrade note for `community_set`.

## 4. #285 — Preview every distinct content type in the cart

### Findings

- `CartPage.tsx` previews `cart.items[0]` only (`CartPreview`), via a client lookup plus `POST /api/v1/render/preview`.
- Whether a QR payload fits is not a fixed byte count: the fixed QR box depends on tape, orientation and preset
  (`build_box_qr` in `ql_layout.py:225-236` raises `QrPayloadTooLongError(length, max_bytes)`), and the QR payload of a
  cart item comes from the integration lookup. A client-side size check cannot be exact.
- Cart items are unique per `(app, id)` (`cart.ts:30`).

### Design

- **R-285-1 (previews):** one preview per distinct `content_type` in the cart, in cart order, using the first item of
  that type; at most `MAX_CART_PREVIEWS = 4`. Above that, a line "N more layouts are not shown." Each preview names
  its item ("Shows Cable 7 for the QR + 2 lines layout.").
- **R-285-2 (check every item):** a new read endpoint `POST /api/v1/render/check` validates items the way a print
  would render them, without a printer, queue or database:
  - Body: `{tape_mm, orientation?, layout_preset?, items: [{content_type, lookup: {app, identifier}}]}`, 1 to
    `MAX_RENDER_CHECK_ITEMS = 50` items; `lookup` is a `RenderCheckLookup` with `app ≤ 32` and
    `1 ≤ identifier ≤ 256` characters, `extra="forbid"`.
  - Answer 200: `{results: [{index, ok, error_code, error_detail}]}`, one per item, same order.
  - Per-item codes: `qr_payload_too_long` (with `length`, `max_bytes`), `content_type_data_mismatch` (with
    `missing_fields`), `app-lookup-not-found`, `integration_unknown_app` (caught before `LookupFailedError`, it is a
    subclass), `integration_not_configured`, `integration_lookup_failed`.
  - The request-level 409 `unsupported_tape` is decided **before** any lookup (tape geometry and orientation first).
  - Lookups run through `AppLookupService` with at most `MAX_BATCH_LOOKUPS` (8) at once; identical
    `(app, identifier, content_type)` items are looked up and rendered once (API callers can send duplicates; the cart
    cannot). Renders run in `asyncio.to_thread`. No `str(exc)` in any result. Scope `read`.
- **R-285-3 (cart UI):** the cart sends its items in chunks of 50 when a tape printer is selected and the tape is known;
  an item with a failed check gets an inline flag in its row ("The QR code does not fit this tape: 812 of at most 122
  bytes."), and the print section shows "N labels will not print. Remove them or change the layout." The print button
  stays enabled: the batch answer is binding, the flag is advice.

## 5. #284 — The webhook quantity on the label

### Findings

- `SpoolmanWebhookPayload.quantity` and `GrocyWebhookPayload.quantity` are accepted and ignored
  (`backend/app/schemas/webhook.py`); webhook labels print as `qr_two_lines`.
- The Spoolman lookup builds `"{grams}g remaining"` with half-up rounding (`spoolman/plugin.py:77-82`), which
  `qr_two_lines` never shows. `qr_three_lines` requires and shows `secondary[0]` (`layout_engine.py:35-43`).
- **Backend language source:** `general.language` (`en`/`de`, `backend/app/settings_store/registry.py:32`) read through
  `request.app.state.settings_store.get("general.language")`; label text is translated with a per-language dict and an
  `en` fallback, the pattern of `FEED_MARK_TEXTS` (`backend/app/sheets/planner.py:83-86`, used at `:243`). There is no
  gettext catalogue in the backend.

### Design

- **R-284-1:** with a quantity the label prints as `qr_three_lines` and the quantity line is `secondary[0]`; without
  one it prints as `qr_two_lines` exactly as today.
- **R-284-2 (Spoolman):** whole grams rounded half up. The webhook value wins over the lookup's remaining weight.
- **R-284-3 (Grocy):** the delta with an explicit sign, rounded half up to at most two decimals, trailing zeros
  removed, ASCII minus; an exact zero has no sign, `-0.001` prints `0`. Grocy's webhook carries no unit.
- **R-284-4 (bounds, no new refusals):** a quantity outside `[0, 1 000 000]` (Spoolman) or `[-1 000 000, 1 000 000]`
  (Grocy) is treated as absent and logged at INFO without the value.
- **R-284-5 (language, maintainer 2026-11-14):** the line follows `general.language`.

| | en | de |
|---|---|---|
| Spoolman | `851g remaining` | `851 g übrig` |
| Grocy | `Stock change: +2`, `Stock change: -1.5` | `Bestandsänderung: +2`, `Bestandsänderung: -1,5` |

  The strings live in `QUANTITY_TEXTS: Final[dict[str, dict[str, str]]]` in `backend/app/services/webhook_quantity.py`;
  an unknown language falls back to `en`.
- The stored job payload carries the label data with the quantity line, so a restart re-renders the same label.
- Mechanism: `PrintService.submit_print_job` gets an optional `label_transform` that runs on the resolved `LabelData`
  before render and persist.

## 6. #281 — Grocy's label printer webhook and Grocycode scanning

### What Grocy sends (from Grocy's source, commit `146f73af47fe65f806b6eea0ac5f3bee7cb62cb5`)

- `controllers/Api/{Stock,Chores,Batteries,Recipes}ApiController.php` build `$webhookData` and call
  `helpers/WebhookRunner.php`, which POSTs it with a **2.0 s timeout**, as JSON when `LABEL_PRINTER_HOOK_JSON` is true
  (default), else form fields. Grocy writes every webhook URL **and body** to its stderr, and returns the URL with the
  token to its user on an error answer or a timeout (attacker model, section 2).
- Fields per label type (then `array_merge` with `LABEL_PRINTER_PARAMS`, which can override any key):

| Label | Name field | `grocycode` | Extra |
|---|---|---|---|
| product | `product` | `grcy:p:<product_id>` | `details` |
| stock entry | `product` | `grcy:p:<product_id>:<stock_id>` | `details`, `stock_entry`, `due_date` = `"<localised DD>: <date>"` only with best-before tracking |
| chore | `chore` | `grcy:c:<chore_id>` | `details` |
| battery | `battery` | `grcy:b:<battery_id>` | `details` |
| recipe | `recipe` | `grcy:r:<recipe_id>` | `details` |

- **Grocycode:** `grcy` is Grocy's official magic. Grocy's `docs/grocycode.md` defines
  `grcy:<entity>:<id>[:<extra>…]` with the entities `p` (product), `b` (battery) and `c` (chore); for `p` an optional
  stock id follows. Grocy's code also has `r` for recipes (`helpers/Grocycode.php:23`) and prints recipe labels with it;
  the documented grammar does not list it.
- `details` carries the full product or recipe row; its description can hold pasted images as data URIs.

### Design: endpoint

- **Endpoint:** `POST /api/v1/webhook/grocy/label`, 202 `WebhookAcceptedResponse` (the existing schema). Request body
  documented with `openapi_extra`, like `import_sheet_type`.
- **R-281-1 (authentication, maintainer 2026-11-14):** an **API key** with the effective scope **`print`**; a `read`
  key answers 403 `insufficient_scope`, an `admin` key 403 `token_scope_too_wide`.
  - The key comes from the query parameter `token`, taken only from a literal `token=` parameter of the raw query
    string (`request.scope["query_string"]`), the same shape the log filter redacts; a percent-encoded parameter name
    is not a token. The `X-Label-Hub-Key` header is accepted too (header wins).
  - Every failure of the token itself (missing, malformed, longer than 128 characters, unknown, disabled, expired,
    wrong) answers the same **401 `invalid_token`** with one fixed message. A token over 128 characters is refused
    without a database lookup (bcrypt ≥ 5 raises on > 72 bytes).
  - The key's own rate limit applies (429 with `Retry-After`).
- **R-281-2 (the hub's logs):** a logging filter on `uvicorn.access` and `uvicorn.error` replaces the value of every
  literal `token=` query parameter with `***` in the record's args and message; the app installs it at start. The
  debug log line of an unknown key prefix (`dependencies.py:212`, 16 characters, not secret for `lh_` keys) stays; the
  ADR names it.
- **R-281-3 (body):** JSON only (`application/json`, parameters allowed), else 415 `json_required` with a hint to set
  `LABEL_PRINTER_HOOK_JSON=true`. At most **1 MiB** (`MAX_GROCY_LABEL_BODY = 1_048_576`), read with the bounded read:
  a declared `Content-Length` above the limit is refused before a byte is read, otherwise `request.stream()` stops at
  limit + 1; 413 `body_too_large`. Unknown fields are ignored; `details` and `stock_entry` are not read or declared.
- **R-281-4 (label type):** taken from `grocycode`, validated against
  `GROCYCODE_PATTERN = ^grcy:(p|b|c|r):[0-9]{1,10}(:[^:\s]{1,64}){0,3}$`: `p` with an extra part is a stock entry,
  `p` without is a product, `b` battery, `c` chore, `r` recipe (recipe accepted because Grocy's code sends it). The
  name field must match the type, else the content error `grocy_label_mismatch` (R-281-8).
- **R-281-5 (label data, no call back to Grocy):** `title` = the name, `primary_id` = the object id, `qr_payload` = the
  Grocycode, `secondary` = `(due_date,)` for a stock entry that carries one, else empty; `source_app = "grocy"`.
  Every text cleaned with `sanitise_text` and capped at `RAW_TEXT_MAX` (512).
- **R-281-7 (mapping on the Grocy settings page):** new runtime settings under **Settings > Integrations > Grocy**:

| Key | Kind | Default |
|---|---|---|
| `integrations.grocy.label.enabled` | bool | `false` |
| `integrations.grocy.label.product.content_type` | enum | `qr_two_lines` |
| `integrations.grocy.label.stock_entry.content_type` | enum | `qr_three_lines` |
| `integrations.grocy.label.chore.content_type` | enum | `qr_two_lines` |
| `integrations.grocy.label.battery.content_type` | enum | `qr_two_lines` |
| `integrations.grocy.label.recipe.content_type` | enum | `qr_two_lines` |
| `integrations.grocy.label.<type>.printer` | str (printer slug) | `""` = the first enabled tape printer |

  Enum choices: `qr_only`, `qr_one_line`, `qr_two_lines`, `qr_three_lines`. `qr_three_lines` requires a secondary line
  (`REQUIRED_FIELDS`, `layout_engine.py:39`): a label mapped to `qr_three_lines` without one (every type but a stock
  entry with `due_date`) is printed as `qr_two_lines`; the stored job records the content type actually printed.
- **R-281-8 (order and outcome, controller ruling on the time budget):**
  1. token → rate limit → `label.enabled` (503 `grocy_label_disabled`) → content type (415) → bounded read (413);
  2. the target printer: from the mapping of the code's type (the `product` mapping when the code is unreadable),
     resolved to an id (unknown slug: 503 `grocy_label_printer_unavailable`; no enabled tape printer: the existing
     503) → `check_printer_access(auth, id, default_printer=True)` (403 `printer_not_allowed` with the fixed message,
     mapped or not: Grocy forwards the message to its user) → disabled or page printer: 503
     `grocy_label_printer_unavailable`;
  3. **content errors** (unparseable JSON, a schema failure, a code outside `GROCYCODE_PATTERN`, a text over 512:
     `grocy_label_invalid`; a name field that does not match the type: `grocy_label_mismatch`) answer **202
     with a job in state `failed`** on the target printer, with the error code as the job error: the request was
     accepted, the label could not be built, and the failure belongs where the operator looks (job page, #255);
  4. otherwise a job is accepted for deferred printing and the route answers 202.
- **R-281-11 (time budget, controller ruling):** the route answers within **1.5 s**. It validates, records the job and
  returns 202; the preflight (SNMP, up to 3 s per try on PT/QL), render and queue hand-off run after the response.
  A later failure (offline, no tape, unsupported tape, QR too long) sets the job to `failed` with the same error code
  `POST /api/v1/print` would answer, and is visible on the job page and in the notification centre. Grocy therefore
  never waits for the printer, and a Grocy timeout no longer means "printed anyway".
  - Mechanism: `PrintService.accept_deferred_job(raw: RawLabelData, *, content_type, source_app, api_key_id,
    source_ip) -> UUID` stores a `queued` job with the label data and `payload.deferred = true` (no tape fields yet),
    then completes it in a tracked background task: preflight → tape → render (with the `qr_three_lines` fallback) →
    payload completed → `submit_with_id`. A deferred job still without tape fields at a restart ends as
    `failed_restart` and never prints twice.
- **R-281-9 (config block):** the settings page shows a ready-to-copy block for Grocy's `config.php`:

```php
Setting('FEATURE_FLAG_LABEL_PRINTER', true);
Setting('LABEL_PRINTER_WEBHOOK', '<public-url>/api/v1/webhook/grocy/label?token=<print-key>');
Setting('LABEL_PRINTER_RUN_SERVER', true);
Setting('LABEL_PRINTER_HOOK_JSON', true);
```

  `<public-url>` is filled from `general.public_url`; `<print-key>` stays a placeholder, with a link to
  **Settings > Access keys** and the warning: "Use a key with the print scope, restricted to the label printer. Grocy
  writes the address with the key to its own log, and shows it to the Grocy user when the hub refuses a label or does
  not answer within 2 seconds."
- **R-281-10 (ADR):** URL-token authentication for one route: a new ADR (next free number after 1.6.0's), `Proposed`
  in the first task, `Accepted` when the feature ships. Consequences include the Grocy user exposure, the reduction on
  our side (print-scope-only tokens, answer inside the budget, content errors as 202 with a failed job) and that a
  reverse proxy's access log is outside the hub.

### Design: Grocycode on the scan page (maintainer 2026-11-14)

- **R-281-12:** a scan resolver `grocycode` parses exactly the documented grammar
  `GROCYCODE_SCAN = ^grcy:(p|b|c):([0-9]+)(?::([^:]+))*$` (Grocy `docs/grocycode.md`), on the trimmed text; the scanner
  already reads QR, DataMatrix and Code 128 (`decoder.ts:16`).
  - `p` (with or without a stock id) opens the Grocy product in the hub's Grocy integration: route `/product/<id>`
    (`ProductPage`, lookup `grocy`).
  - `b` and `c` have no item in the hub's Grocy integration. They open a new route `/grocycode/$entity/$id` that says
    "Grocy battery 4" / "Grocy chore 4" and links to Grocy's own page (`<grocy url>/battery/<id>`,
    `<grocy url>/chore/<id>`, Grocy `routes.php:119,128` at `146f73af`) when the Grocy address is known, else names
    the code only.
  - Anything else (`grcy:r:…`, an unknown entity, a non-numeric id) is not claimed by this resolver.

## 7. #282 — Resolve all unconfirmed cells of a sheet

### Findings

- `resolve_cells` in `backend/app/sheets/sheet_service.py:464-515` settles a list of cells in one `write_transaction`,
  publishes one `sheet.updated` and logs the count. The route `POST /api/v1/sheets/{code}/cells/resolve` uses
  `PrintDep` and does not check printer access; #264 decided that a printer-restricted `print` key may resolve cells.

### Design

- **Endpoint:** `POST /api/v1/sheets/{code}/cells/resolve-all`, scope `print`, response `SheetRead`.
- **Body:** `{outcome: "printed" | "not_printed", expected_count?: int ≥ 1}`.
- **R-282-1:** when `expected_count` is sent and the number of unconfirmed cells at the server differs, the call
  answers **409 `unconfirmed_count_changed`** with `error_detail.unconfirmed` and changes nothing. The UI always sends
  it.
- **R-282-2:** nothing unconfirmed answers **409 `no_unconfirmed_cells`**.
- **R-282-3:** the per-cell settle logic moves into one private helper used by `resolve_cells` and
  `resolve_all_cells`, so `printed` keeps setting `id_printed` and `feed_mark_printed` exactly as today.
- One transaction; a failure part-way changes no cell. One `sheet.updated` event with all changed cell numbers.
- **UI:** in the "Unconfirmed cells" panel of `SheetDetail.tsx`, "Resolve all as printed" and "Resolve all as not
  printed", shown from two unconfirmed cells; each opens a `ModalDialog` naming the count ("Resolve 3 cells as
  printed?"); on 409 `unconfirmed_count_changed` the sheet reloads and the dialog says "The number of unconfirmed cells
  changed. Check the list and try again."

## 8. #283 — Admin keys and printer restrictions (maintainer 2026-11-14: option 1)

### Current state

- The admin printer routes call `check_printer_access` only in `resolve_identity` (`admin_printers_api.py:565`), but a
  restricted admin key **is** restricted on the print, batch, job-list and identity routes, because
  `_validate_api_key` and `_session_context` pass the stored `allowed_printer_ids` on (`dependencies.py:298-307`,
  `:358`).
- `create_api_key` (`admin_api_keys.py:158`) accepts `allowed_printer_ids` with any scope; `update_api_key` changes it
  (`:238`), but not the scopes (`:213`).

### Decision and design

- **R-283-1:** admin keys ignore printer restrictions. `create_api_key` with the admin scope and a non-empty
  `allowed_printer_ids`, and `update_api_key` setting a non-empty list on an admin key, answer **422
  `admin_key_not_restrictable`**.
- **R-283-2:** `_validate_api_key` and `_session_context` give an admin-scope key `allowed_printer_ids=[]`. An existing
  restricted admin key keeps working, unrestricted; the key list shows its stored list as "ignored for admin keys".
- Docs: `website/src/content/docs/admin/api-keys.md` (en + de) states the rule; the release notes carry the upgrade
  note (existing restricted admin keys lose their restriction; a new restricted admin key is refused).

## 9. #255 — Notification centre in the top bar (design approved by the maintainer, 2026-11-14)

### Decided in the issue (binding)

Button with a severity dot and an unread count next to the scan button; panel newest first; click opens the job or
printer page; every print job with its live state; printer problems while they last; "Mark all as read" keeps
entries, "Clear all" hides them up to the newest one present when clearing; full-height sheet on a phone; focus trap
and Escape; entries come from the server and stay live over SSE; read and cleared state per browser in local storage;
the overview card "Needs attention" uses the same source, and a failed job that was retried successfully or dismissed
leaves it.

### Source of entries

- **R-255-1 (no new endpoint):** entries are derived in the browser by one pure function
  `deriveNotifications({jobs, printers, statuses, sheets, firstSeen, now})` from data the server already serves and
  keeps live: `GET /api/v1/jobs?since=<now − 24 h>&limit=200&order=newest` — a new optional query parameter
  `order: Literal["oldest", "newest"] = "oldest"` (default unchanged), because the list is sorted oldest first
  (`repositories/jobs.py:50`) and would otherwise drop the newest jobs above 200 — the printer list and statuses, and
  `GET /api/v1/sheets`. These queries are invalidated by the existing SSE events and re-read after a reconnect
  (`events.ts:98-140`, `:217-223`). A read key sees only its own jobs (#294).
- **R-255-2 (retried jobs):** every retry stores `retry_of: "<id of the job being retried>"` in the new job's payload,
  overwriting a copied one: the tape path (`retry_job`), the page path (`_retry_page_job`, `PagePayload.retry_of`) and
  the sheet page path (`retry_sheet_page` in `backend/app/sheets/print_service.py`). A failed job with a later `done`
  job in its retry chain counts as resolved: it stays in the centre as information and leaves "Needs attention".

### What counts as an entry, and its severity

| Source | Entry | Severity | Target |
|---|---|---|---|
| Job `queued`, `printing` | "Cable 7 is printing on PT-P750W" | info | job page |
| Job `done` | "Cable 7 printed" | success | job page |
| Job `cancelled` | "Cable 7 was cancelled" | info | job page |
| Job `failed`, `failed_restart` (not resolved by a retry) | "Cable 7 failed: <error text as on the job page>" | **error** | job page |
| Job failed, resolved by a retry | "Cable 7 failed, printed on retry" | info | job page |
| Printer offline, error, stopped with a blocking or error reason | `describePrinter` kind and detail | **error** | printer page |
| Printer answered as another device (#231) | "Different device at the address of …" | **error** | printer page |
| Printer paused, stopped without a serious reason | kind label | warning | printer page |
| Printer status stale or not polled (#227) | "Status unknown" / "Not monitored" | warning | printer page |
| Tape or label roll empty, toner or ink low or empty | the status's own words | warning | printer page |
| Sheet with unconfirmed cells | "3 unconfirmed cells on sheet AB-12" | warning | sheet page |

- Entry ids: `job:<id>:<state>`, `printer:<id>:<kind>`, `sheet:<code>:unconfirmed`. Printer and sheet entries exist
  while the condition lasts; their time is the moment this browser first saw the condition (kept in storage).
- At most 100 entries, newest first.

### Button and badge

- An icon button (bell) in `TopBar.tsx`, between the search and the cart icon (#316); on a phone in the top bar too.
- The dot shows the highest **unread** severity: red dot for error, yellow **diamond** for warning (the shape rule of
  `StatusBadge`), green dot for success/info only, nothing when all is read. Next to it the unread count, `99+` above
  99.
- Accessible name: "Notifications, 3 unread, the most severe is an error" (de: "Benachrichtigungen, 3 ungelesen, die
  schwerste ist ein Fehler").

### Panel

- Desktop: a popover under the button, 24 rem wide, at most `min(70vh, var(--vvh) − 5rem)` high, scrolls inside.
- Phone (< 640 px): a full-height sheet sized with `var(--vvh)` and `var(--vv-top)`, with a close button in its header.
- Header: title, "Mark all as read", "Clear all". Each entry: severity shape and word, one-line text (two lines on a
  phone), relative time (absolute in the title attribute), printer or source; unread entries in bold with a "new"
  marker. The entry is a link to its target and closes the panel.
- States: loading ("Loading notifications…"), empty ("Nothing new."), every source failed ("Notifications could not be
  loaded." with a retry button), live stream down ("Live updates paused; the list may be out of date.").
- Keyboard: opening focuses the first action; Tab stays inside; Escape and the close button return focus to the bell.
  react-aria `DialogTrigger` + `Popover`/`Modal`.
- Motion: a 150 ms fade and lift on open; none with `prefers-reduced-motion`.
- On-screen keyboard rule: in `e2e/short-viewport.spec.ts`, at 1280x500 and 390x400 with a visual-viewport keyboard
  (search focused), the header actions and the first entry lie in the visible area.

### Read, clear, dismiss, persistence

- Storage key `lph.notifications`, value `{v: 1, read: string[], clearedAt: string | null, dismissed: string[],
  firstSeen: Record<string, string>}`; `read` and `dismissed` keep the newest 500 ids each.
- "Mark all as read": every visible id goes into `read`. "Clear all": `clearedAt` = the newest entry time present.
  "Dismiss" (overview card): adds the id to `dismissed`; it leaves the card and the centre.
- A missing or broken storage falls back to an in-memory state for the tab; nothing throws.
- "Needs attention" shows the unresolved error and warning entries that are neither cleared nor dismissed, each with a
  "Dismiss" button.

### Design skills

`taste-skill:design-taste-frontend` and `emil-design-eng`, `mobile-native` for the sheet, `impeccable:impeccable` for
acceptance. Screenshots light and dark at 1280 px and 390 px.

## 10. #316 — Permanent cart icon with a count in the top bar

- **R-316-1 (what the badge counts):** the number of **entries** in the cart (the rows on the cart page, the issue's
  "Cart, 3 items"), not the sum of copies; the cart page shows the copies sum on its print button ("Print 7 labels"),
  and the badge stays a measure of what the list shows.
- **R-316-2:** the icon is always in `TopBar.tsx`, on desktop and phones, after the bell and before the about link;
  empty cart: no badge, still a link to `/cart`. The existing in-page "Cart" links stay.
- The count comes from the cart state the cart page uses (`useCart()`, `lph.cart`), live within the tab and across
  tabs through the `storage` event. Accessible name "Cart, 3 items" / "Cart, empty"; badge `99+` above 99; the badge
  never overlaps a neighbouring control at 320 px width.
- Short-viewport case and the top bar screenshot. Same design skills as #255.

## 11. Rulings index

| ID | Ruling |
|---|---|
| R-0-1 | Browser storage keys keep the `lph.` prefix |
| R-296-1…6 | Discovery switch for tape drivers; write-only community; client validation; one payload function; `community_set` on every printer response with keep-on-omit; preflight uses the stored community |
| R-285-1…3 | Up to 4 previews; `POST /api/v1/render/check` with bounded identifiers and tape checked first; inline flags, button enabled |
| R-284-1…5 | `qr_three_lines` with a quantity line; Spoolman grams; Grocy signed delta; out-of-range treated as absent; de/en from `general.language` |
| R-281-1…12 | Print-scope key as literal `token=`; log filter; JSON, 1 MiB bounded read; type from Grocycode; data from the body; mapping with `qr_three_lines` fallback; check order, content errors as 202 + failed job; config block and warning; ADR; 1.5 s budget with deferred printing; Grocycode scan resolver |
| R-282-1…3 | `expected_count` guard; 409 when nothing is unconfirmed; one settle helper |
| R-283-1…2 | 422 for a restricted admin key; admin auth contexts carry no printer list |
| R-255-1…2 | Entries derived client-side, jobs newest first; `retry_of` on every retry path |
| R-316-1…2 | Badge counts entries; icon always in the top bar |

## Questions for the maintainer

| # | Question | Status / recommendation |
|---|---|---|
| Q1 | #283 rule for admin keys | **Ruled 2026-11-14:** option 1 (section 8) |
| Q2 | #296 stop returning the community | **Ruled 2026-11-14:** `community_set`, the value no longer returned |
| Q3 | #255 UI design | **Ruled 2026-11-14:** approved |
| Q4 | #284 label language | **Ruled 2026-11-14:** hub language (de/en) |
| Q5 | #281 Grocycode scanning | **Ruled 2026-11-14:** in 1.7.0 |
| Q6 | #281 admin keys as URL token | **Ruled 2026-11-14:** refused, 403 `token_scope_too_wide` |
| Q7 | Grocy returns the full webhook URL, token included, to its user on any non-2xx answer or timeout (`WebhookRunner.php` catches an unimported `RequestException`, the controller returns the exception message). Report it to Grocy? | A foreign security finding, your call. Recommendation: report it privately to the Grocy maintainers. Not a task in this milestone. |
| Q8 | `grcy:r:` (recipe) is in Grocy's code but not in `docs/grocycode.md`. The webhook accepts recipe labels; the scan resolver ignores `r`. Agreed? | Recommendation: agreed; scanning recipes needs a hub target first. |
| Q9 | Wording for scanned battery and chore codes ("Grocy battery 4" with a link to Grocy). | Recommendation: as written in R-281-12. |
