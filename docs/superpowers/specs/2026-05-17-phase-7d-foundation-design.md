# Phase 7d Foundation Design — Generic Print API + QR Print Tab + Hangar Integration

**Date:** 2026-05-17
**Status:** Draft — awaiting user review
**Tracking:** strausmann/label-printer-hub#22 (master), `#NN` (Phase 7d issue, TBD)
**Dependencies:**
- Phase 7c API-Auth (#78) — MUST land before Phase 7d goes to production
- Hangar feature-request strausmann/hangar#63 — parallel work in Hangar repo for the cross-app integration

## 1. Executive Summary

Phase 7d delivers the **End-to-End MVP** for cross-application label-printing in the label-printer-hub project. After Phase 7b stabilised the foundation (lifespan, datetime, /readiness, status cache), Phase 7d turns the app outward by introducing two integration surfaces:

1. **Generic Print API** (`POST /api/preview` + `POST /api/print`) that any external app can call with a uniform item payload. Hangar will be the first consumer (see strausmann/hangar#63), but the API is plugin-agnostic — Grocy/Snipe-IT/Spoolman could also push from their own UIs if desired.

2. **QR Print Tab** (`/qr-print`) inside the label-printer-hub HTMX UI. Users can search across multiple external sources (Grocy, Snipe-IT, Spoolman, Hangar) through a single search field with a platform toggle, select an item, choose a template, see a live preview with tape-match indicator, and print.

The plugin system from Phase 3.5 (`IntegrationRegistry` with `lookup(identifier)`) is extended with `search(query)`, `get_item(item_id)`, and an optional `get_children(item_id)` for hierarchical sources like Hangar.

## 2. Item Datamodel — γ Hybrid

The single item shape that flows through every endpoint and every plugin:

```python
class PrintItem(BaseModel):
    name: str                                         # Required main line
    subtitle: str | None = None                       # Optional secondary line
    qr_url: str | None = None                         # QR-code payload (deep-link to source app)
    image_url: str | None = None                      # Optional thumbnail
    copies: int = Field(default=1, ge=1, le=99)       # NEW (Δ from initial design): per-item copies
    extras: dict[str, str | int | float | bool] = {}  # Template-specific fields (Jinja-accessible)


class PrintRequest(BaseModel):
    template_id: UUID
    printer_id: UUID
    items: list[PrintItem]                            # 1..N items
    force_tape_mismatch: bool = False                 # Optional override
```

Rationale for γ Hybrid (chosen over flat-α and template-aware-β):
- Templates have access to a fixed set of generic fields (`name`, `subtitle`, `qr_url`, `image_url`) that cover 80% of label layouts.
- `extras` dict carries plugin-specific or template-specific values (`fach_nr`, `regal_color`, `expiry_date`, etc.) without coupling the caller to specific template field-names.
- Templates use Jinja: `{{ name }}` or `{{ extras.fach_nr }}` — both work.
- Caller (Hangar, etc.) builds the `subtitle` string from its own hierarchy data: `"Vorratskeller > Kallax 02 > Fach C"`.

### Per-item copies

Total labels produced = `sum(item.copies for item in items)`. Each copy creates its own `Job` row for tracking. Example payload: 2 Samla-Boxes × 3 copies + 1 Regalfach × 1 copy = 7 print jobs.

## 3. Plugin Interface Extension

Building on the Phase 3.5 `IntegrationPlugin` Protocol:

```python
class IntegrationPlugin(Protocol):
    name: str                  # e.g. "grocy"
    display_name: str          # e.g. "Grocy"

    async def lookup(self, identifier: str) -> PluginItem | None:
        """Existing — barcode/identifier lookup."""
        ...

    async def search(self, query: str, limit: int = 20) -> list[PluginItemSummary]:
        """NEW Phase 7d — free-text search returning summary rows."""
        ...

    async def get_item(self, item_id: str) -> PluginItem | None:
        """NEW Phase 7d — full item data after user selection."""
        ...


class HasChildren(Protocol):
    """Optional capability — plugins with hierarchy implement this."""

    async def get_children(self, item_id: str) -> list[PluginItemSummary]:
        """Returns direct children of a container item (e.g. shelf -> compartments)."""
        ...


class PluginItemSummary(BaseModel):
    id: str                    # Plugin-internal identifier
    name: str
    subtitle: str | None = None
    image_url: str | None = None
    has_children: bool = False  # For UI: show '+ alle Kinder' toggle


class PluginItem(BaseModel):
    id: str
    name: str
    subtitle: str | None = None
    qr_url: str | None = None  # Plugin computes the deep-link
    image_url: str | None = None
    extras: dict[str, Any] = {}
    # NOTE: extras intentionally uses Any — plugin payloads are untrusted
    # and may carry arbitrary types (nested dicts, None, lists) before the
    # plugin maps them into a PrintItem.  The PrintItem.extras is the
    # tighter public boundary (dict[str, str | int | float | bool]).
```

### Plugins in MVP

| Plugin | search() | get_item() | get_children() | Notes |
|---|---|---|---|---|
| Grocy | ✅ new | ✅ new | — | Existing Phase-3.5 plugin; extend with the 2 new methods |
| Snipe-IT | ✅ new | ✅ new | — | Same |
| Spoolman | ✅ new | ✅ new | — | Same |
| **Hangar (NEW)** | ✅ | ✅ | ✅ | New plugin module `backend/app/integrations/hangar/` — see Section 8 |

`HasChildren` is only implemented by Hangar in MVP. Other plugins simply don't expose the protocol — UI hides the "+ alle Kinder" toggle when `summary.has_children == False`.

## 4. Backend Endpoints

### POST /api/preview

```
Body: PrintRequest (only items[0] is rendered as PNG; remaining items are counted but not drawn)
Response: PreviewResponse {
  image_data_url: str               # "data:image/png;base64,..." for inline embed
  items_count: int                  # Total items in the request
  items_rendered_count: int         # Always 1 (items[0] only)
  total_labels: int                 # sum(item.copies for item in items)
  template_name: str
  current_tape: {
    width_mm: int | None,
    color_name: str | None,
    hr_status: str | None
  }
  required_tape: { width_mm: int }
  tape_match: bool
  tape_match_reason: str | None     # If false: human-readable why
}
```

Preview renders only `items[0]` as PNG to keep the response payload small. UI shows "Vorschau Item 1 von N" caption.

Authorisation: `print` scope OR `read` scope sufficient (preview is read-only side-effect-free).

Idempotency: not required (read-only).

### POST /api/print

```
Body: PrintRequest
Header: Idempotency-Key (optional — prevents double-submit on retry)
Response: PrintResponse {
  job_ids: list[UUID]              # One per (item × copy) = sum of all copies
  accepted_count: int
  refused_count: int
  refused_reason: str | None       # When some items refused (e.g. tape mismatch + no force)
}
```

Job creation: `items=[A×2, B×3]` → 5 Jobs in DB, all enqueued with the same template+printer, sequential order.

Tape-mismatch behaviour:
- Default `strict_tape_match=true` on the server (refused with HTTP 422 + `refused_reason`).
- `force_tape_mismatch=true` in body bypasses the check. Each created Job carries `tape_match_override=true` in DB for audit.

Authorisation: `print` scope required.

### Job-DB extensions (small Alembic migration)

`Job` table gets five new optional columns:
```python
api_key_id: UUID | None              # Set by Phase 7c auth middleware
source_ip: str | None
tape_match_override: bool = False    # Whether user forced through tape mismatch
plugin: str | None                   # When the job came via a plugin's get_item flow
plugin_item_id: str | None           # The plugin-internal identifier
```

These power the audit trail (Section 9). All optional, all backwards-compatible.

## 5. QR Print Tab UI

New HTMX route `/qr-print` (server-rendered Go-templates in the frontend, no SPA framework).

### Layout

```
+-- Plugin-Toggle (radio): -------------------------------------+
|   (o) Grocy   ( ) Snipe-IT   ( ) Spoolman   ( ) Hangar         |
+---------------------------------------------------------------+
| Search:  [ schraubendreher                  ]  [Suchen]       |
+-- Results list (HTMX-swapped, 250ms debounce) ---------------+
| [img] Schraubendreher Set Bosch                              |
|       Werkstatt > Regal A > Box 3              [Auswählen]   |
|                                                              |
| [img] Schraubendreher Phillips PH2                           |
|       Werkstatt > Regal A > Box 3              [Auswählen]   |
+-- After user clicks Auswählen on a Hangar shelf item: -------+
| Item: Kallax 02 (Regal, Werkstatt)                           |
| [x] Auch alle 4 Fächer drucken     (Children-Toggle, Hangar) |
|                                                              |
| Printer:  [ PT-P750W ▼ ]                                     |
| Template: [ ikea-kallax-fach-12mm ▼ ]                        |
|                                                              |
| Copies pro Item:                                             |
|   Kallax 02              [1] copies                          |
|   Fach A                 [1] copies                          |
|   Fach B                 [1] copies                          |
|   Fach C                 [3] copies   <- Samla-Box-Use-Case  |
|   Fach D                 [1] copies                          |
|                                                              |
+-- Preview ---------------------------------------------------+
| Tape: 12mm white/black                          ◤            |
|  +--------------------------+                                |
|  |   ░░ Kallax 02 ░░       |  <- grüner Rahmen wenn tape ok |
|  +--------------------------+                                |
| "Vorschau Item 1 von 5 (Total 7 Labels)"                    |
+--------------------------------------------------------------+
[ Drucken ]
```

### HTMX endpoints

| Path | What it returns |
|---|---|
| `GET /qr-print/search?plugin=X&q=...` | `<div>` fragment with result-cards (200 OK, swap into results-list) |
| `GET /qr-print/select?plugin=X&item=...` | Print-form block (with optional children-toggle if `has_children=true`) |
| `GET /qr-print/children?plugin=X&item=...` | Children-list fragment (HTMX-merged into the items list when toggle activated) |
| `POST /qr-print/preview` | Preview block fragment (image + tape-match border + caption) |
| `POST /qr-print/print` | Toast fragment: "5 Jobs angelegt (#abc, #def, ...)" |

Auth: `GET /qr-print/*` requires Pangolin-SSO (browser cookie). `POST /qr-print/preview` and `POST /qr-print/print` also accept an API-Key header (for programmatic use). Full auth matrix in Section 9.

## 6. Tape-Match Indicator

The backend computes the match in the `/api/preview` response:

```python
def compute_tape_match(template, printer_status_cache_row):
    loaded_mm = parsed_cache.get("loaded_tape_mm") if parsed_cache else None
    required_mm = template.tape_width_mm
    if loaded_mm is None:
        return False, "Drucker meldet kein Tape (kein SNMP-Probe oder Probe veraltet)"
    if loaded_mm != required_mm:
        return False, f"Tape ist {loaded_mm}mm, Template benötigt {required_mm}mm"
    return True, None
```

Frontend renders:
- **Green border** on the preview image when `tape_match=true`
- **Red border** + tooltip with `tape_match_reason` when `tape_match=false`
- Top-right badge inside the preview frame: `Tape: 12mm white/black` (built from `current_tape.width_mm`, `current_tape.color_name`)

The badge is small, monospace, semitransparent — not blocking the preview content.

### Mismatch + Print

When user clicks [Drucken] and `tape_match=false`, the HTMX print-button opens a modal:

```
Tape passt nicht zu Template
- Eingelegt: 12mm white/black
- Benötigt:  24mm yellow

[Abbrechen]   [Trotzdem drucken]
```

[Trotzdem drucken] sends `force_tape_mismatch=true` in the body. Backend creates the Jobs with `tape_match_override=true` for audit.

## 7. Multi-Item Print + Copies

The print-flow turns `(items × copies)` into N Job rows:

```python
total_jobs = sum(item.copies for item in request.items)
for item in request.items:
    for _ in range(item.copies):
        session.add(Job(
            template_id=request.template_id,
            printer_id=request.printer_id,
            data=item.model_dump(),
            state="queued",
            tape_match_override=request.force_tape_mismatch and not tape_match,
            plugin=request.plugin,
            plugin_item_id=item.extras.get("plugin_item_id"),
            api_key_id=current_api_key.id,
            source_ip=request.client.host,
        ))
```

Mid-batch failure handling:
- If one job fails to enqueue (e.g. DB constraint), the response reports `accepted_count: 4, refused_count: 1, refused_reason: "Job for item B copy 2 conflicted"`.
- Already-enqueued jobs are NOT rolled back. The UI shows which ones succeeded.

## 8. Hangar Plugin

New plugin module: `backend/app/integrations/hangar/`

```python
# backend/app/integrations/hangar/__init__.py
from app.integrations.base import IntegrationPlugin
from app.integrations.hangar.client import HangarClient


class HangarPlugin:
    name = "hangar"
    display_name = "Hangar"

    def __init__(self):
        self._client = HangarClient()  # reads PRINTER_HUB_HANGAR_BASE_URL + PRINTER_HUB_HANGAR_API_KEY from settings

    async def lookup(self, identifier: str) -> PluginItem | None:
        """Slug lookup, e.g. 'kallax-02-fach-c'."""
        return await self._client.get_location(identifier)

    async def search(self, query: str, limit: int = 20) -> list[PluginItemSummary]:
        """GET /api/locations/search?q={query}&limit={limit} against Hangar."""
        rows = await self._client.search(query, limit)
        return [
            PluginItemSummary(
                id=row["slug"],
                name=row["name"],
                subtitle=row.get("subtitle"),
                image_url=row.get("image_url"),
                has_children=row["type"] in {"room", "cabinet", "shelf", "box"},
            )
            for row in rows
        ]

    async def get_item(self, item_id: str) -> PluginItem | None:
        """GET /api/locations/{slug} against Hangar — returns full data ready for printing."""
        loc = await self._client.get_location(item_id)
        if loc is None:
            return None
        return PluginItem(
            id=loc["slug"],
            name=loc["name"],
            subtitle=" > ".join(loc["path"][:-1]) if len(loc["path"]) > 1 else None,
            qr_url=f"https://hangar.example.com/locations/{loc['slug']}",
            image_url=loc.get("image_url"),
            extras={
                "slug": loc["slug"],
                "type": loc["type"],
                "parent_slug": loc.get("parent_slug"),
                **(loc.get("extras") or {}),
            },
        )

    async def get_children(self, item_id: str) -> list[PluginItemSummary]:
        """GET /api/locations/{slug}/children against Hangar."""
        rows = await self._client.get_children(item_id)
        return [
            PluginItemSummary(
                id=row["slug"],
                name=row["name"],
                subtitle=row.get("subtitle"),
                image_url=row.get("image_url"),
                has_children=row["type"] in {"room", "cabinet", "shelf", "box"},
            )
            for row in rows
        ]
```

`HangarClient` is a thin httpx wrapper:
- Base URL from `settings.PRINTER_HUB_HANGAR_BASE_URL` (e.g. `https://hangar.example.com`)
- API key from `settings.PRINTER_HUB_HANGAR_API_KEY` — sent as `X-Hangar-API-Key` header
- 5 s connect timeout, 10 s read timeout
- 404 → returns None; 401/403 → raises with clear log message; 5xx → exponential backoff retry once

The 3 Hangar endpoints the plugin calls are documented in **strausmann/hangar#63** which must ship before this plugin is deployable in production.

For local dev / tests without a running Hangar instance, the plugin auto-disables itself when `PRINTER_HUB_HANGAR_BASE_URL` is empty/unset.

## 9. Auth

Phase 7d depends on Phase 7c (#78) for API-key authentication:

| Endpoint | Required Auth | Scope |
|---|---|---|
| `GET /api/printers`, `GET /api/templates` | API-Key OR Pangolin-SSO | `read` |
| `POST /api/preview` | API-Key OR Pangolin-SSO | `read` |
| `POST /api/print` | API-Key OR Pangolin-SSO | `print` (or `admin`) |
| `GET /qr-print/*` (HTMX) | Pangolin-SSO required (browser) | — |
| `POST /qr-print/{preview,print}` | Pangolin-SSO OR API-Key | `read` / `print` |

When Phase 7c lands, the Hangar plugin needs an API-Key issued by Label-Hub admin UI. The key is stored in Hangar's env as `LABEL_HUB_API_KEY`.

Transition from `claude-automation` Basic-Auth-Bypass (Phase 7b state) → API-Key (Phase 7c):
- During the transition window, both work.
- After Phase 7c rolls out, `claude-automation` is downgraded to `read` scope only (recovery path).
- Hangar must have its API-Key configured before Hangar's Print-Page rolls out.

## 10. Testing Strategy

| Layer | Test type | Coverage target |
|---|---|---|
| Plugin search | Unit per plugin: `search("schrauben")` with mocked HTTP → asserts list of `PluginItemSummary` with expected fields | each plugin >= 90% |
| Plugin get_item | Unit per plugin: `get_item("known-id")` mocked → asserts `PluginItem` shape | each plugin >= 90% |
| HangarPlugin.get_children | Unit: mocked Hangar `/children` response → asserts hierarchy mapping | 100% |
| /api/preview | Integration: items + template + printer → PNG bytes valid, tape_match correct | full path |
| /api/print | Integration: 2 items × 3 copies + 1 item × 1 copy → 7 Job rows, all queued | full path |
| Tape-mismatch | Integration: template-tape 24mm + cache-tape 12mm → preview returns `tape_match=false` with reason | edge case |
| Tape-override | Integration: print with `force_tape_mismatch=true` on mismatch → Jobs with `tape_match_override=true` | edge case |
| QR-Tab UI | E2E Playwright: search → select → toggle children → set copies → preview → print → toast | golden path |
| Hangar smoke | Hardware-skip-able test against a real Hangar staging URL (if available) | optional |

Coverage threshold stays at 80% (`pyproject.toml` `fail_under`).

## 11. Hangar Cross-App Coordination

The Hangar side of this integration is tracked in **strausmann/hangar#63**. That issue describes:

- New `/print` page in Hangar UI (multi-select Locations, printer + template dropdowns sourced from Label-Hub, preview, print)
- 3 new Hangar API endpoints: `/api/locations/search`, `/api/locations/{slug}`, `/api/locations/{slug}/children`
- Hangar API-key generation for Label-Hub plugin authentication
- Acceptance criteria + dependency ordering

Both projects can proceed in parallel once the API contract (this spec, Sections 2-4) is locked.

## 12. Out-of-Scope for Phase 7d

These are real future-work items but explicitly out of the MVP PR:

- **Aggregations templates** ("one big label for an entire shelf showing all 4 compartment numbers") — needs template metadata `aggregate_children: bool` and a different renderer path. Phase 7e or later.
- **Per-plugin search-result filters** (e.g. Snipe-IT: filter by location/status; Grocy: filter by stock-level)
- **Saved searches / favourites in QR-Tab**
- **Plugin configuration via UI** — for now plugins read all settings from env vars
- **Multi-printer-fan-out** ("send half to PT-P750W, half to QL-820NWB") — single-printer per print request only
- **Job-rerun-from-history** ("re-print last 5 Hangar jobs") — Phase 7e
- **Authenticated webhook from Hangar** ("Hangar item just got created, auto-print a label") — Phase 7e
- **Image rendering on labels** (Phase 7d preview ignores `image_url`; renderer falls back to QR-only)

## 13. Definition of Done for Phase 7d

- [ ] Item schema + Plugin protocol extensions land with full unit-test coverage
- [ ] 3 existing plugins (Grocy, Snipe-IT, Spoolman) implement `search()` + `get_item()` with at least one passing integration test against a mock HTTP server
- [ ] Hangar plugin module implemented (search + get_item + get_children) — disabled when `PRINTER_HUB_HANGAR_BASE_URL` empty (for tests/local dev)
- [ ] `/api/preview` returns PNG + tape_match — integration test green
- [ ] `/api/print` creates the right number of Jobs (items × copies) — integration test green
- [ ] Tape mismatch refuses without override, accepts with override + audit flag
- [ ] `/qr-print` HTMX page renders end-to-end; children-toggle works for Hangar items; per-item copies input works
- [ ] Full test suite at ≥80% coverage, no failures
- [ ] Doku: README section on the new endpoints + screenshot of the QR-Tab UI
- [ ] strausmann/hangar#63 acknowledged + linked from this spec

## 14. Self-review notes

- **Privacy:** spec sanitised — personal-domain references and internal IPs replaced with `example.com` / RFC-5737 doc IPs (192.0.2.x range) per project privacy policy.
- **Internal consistency:** the per-item `copies` field is referenced consistently — `items × copies` everywhere.
- **Scope:** 4 plugins + new endpoints + UI page = larger than a typical phase, but within MVP scope per Phase-7d-decomposition decision. Splitting into 7d-foundation (endpoints) + 7d-UI (QR-Tab) is possible at writing-plans time if the PR feels too heavy.
- **Dependency declared:** Phase 7c (#78) hard-required for production; Phase 7b.1 (#77) currently merging in parallel.
- **External coordination:** strausmann/hangar#63 captures the Hangar side; cross-team alignment achieved before code starts.
