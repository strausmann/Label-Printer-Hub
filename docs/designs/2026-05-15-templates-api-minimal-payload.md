# Design: Templates Discovery API + Minimal-Payload Validation

**Date:** 2026-05-15
**Status:** Approved (brainstorming)
**Tracking issue:** strausmann/Label-Printer-Hub#22
**Depends on:** PR #59 (feat/first-print) — must merge before this spec is implemented.
**Author:** Brainstormed via superpowers:brainstorming.

## Goals

Three closely coupled improvements to the `POST /print` API and surrounding
machinery, all targeting the same usability gap: the API requires a payload
shape that is bigger than any single template actually consumes, and clients
have no programmatic way to discover what each template needs.

1. **Templates Discovery API.** Expose `GET /templates` (and the singular
   `GET /templates/{template_id}`) so a client can enumerate available
   templates and learn — per template — which payload fields the renderer
   will use, what role each field plays on the label, and what the
   tape-width / app-binding constraints are.

2. **Template-aware payload validation.** Relax `RawLabelData.title` and
   `RawLabelData.primary_id` and `RawLabelData.qr_payload` to be optional
   (default `""`) at the schema level, then let the `PrintService` reject
   requests at submit-time when the chosen template references a field that
   the caller did not supply. A QR-only template requires only `qr_payload`;
   anything more is acceptable noise, anything missing is a 422.

3. **Field-descriptions in OpenAPI.** Annotate `RawLabelData` and the new
   templates-API response schemas with `Field(..., description=...)` so the
   FastAPI Swagger UI at `/docs` becomes the canonical user-facing field
   reference. Closes the documentation gap identified in the conversation
   ("nirgends steht was `title` vs. `primary_id` bedeutet").

## Out of scope

- **Plugin-specific dotted-path fields** (e.g. `snipeit.serial`,
  `grocy.barcode`). ADR 0012 mentions them as a future direction, but no
  template currently ships such elements. The role-derivation table in
  this spec covers only the canonical `LabelData` keys.
- **Authentication/authorization** for the new endpoints. The Label-Hub
  backend is unauthenticated today; that is tracked separately and not
  part of this work.
- **Persistence.** Templates are still loaded from `app/seed/templates/`
  YAML at startup (Phase-5 SQLite persistence is deferred per the
  existing roadmap).
- **Front-end changes.** No PWA / frontend work — this PR ships
  backend-only.
- **DELETE/PUT/POST /templates.** Templates remain seed-defined; this
  is read-only discovery.

## Architecture

```
backend/app/
├── api/
│   └── routes/
│       ├── print.py                (extend: map MissingTemplateFieldsError → 422)
│       └── templates.py            (NEW: GET /templates, GET /templates/{id})
├── schemas/
│   ├── label_data.py               (extend: Field(..., description=...))
│   ├── print_request.py            (modify: title/primary_id/qr_payload default "")
│   ├── template.py                 (extend: required_fields() method)
│   └── template_response.py        (NEW: TemplateResponse, TemplateFieldInfo)
├── services/
│   ├── print_service.py            (extend: validate against template required_fields)
│   └── template_loader.py          (unchanged — already exposes .all() / .get())
└── api/
    └── errors.py                   (NEW or extend: MissingTemplateFieldsError)
```

A separate router for `/templates` keeps discovery (read-only, idempotent)
isolated from print operations (mutating, queue-affecting). Both routers
are wired into the FastAPI app in `main.py` via `app.include_router(...)`.

## Component 1: Templates Discovery API

### Endpoints

| Method | Path | Purpose | Response |
|---|---|---|---|
| `GET` | `/templates` | List all templates, optionally filtered. | `200` → `list[TemplateResponse]` |
| `GET` | `/templates/{template_id}` | One template by id. | `200` → `TemplateResponse`, `404` → `error_code: "template_not_found"` |

Query parameters on `/templates`:

| Parameter | Type | Behaviour |
|---|---|---|
| `tape_mm` | `int` | Return only templates where `tape_mm` matches exactly. Values matching no template return `200 []`, not 404. |
| `app` | `str` | Return only templates where `app` matches exactly. Reserved literal `app=none` matches templates with `app: null` (generic templates such as `qr-only-*`). |

Filters compose with AND semantics. Unknown query params are ignored
(FastAPI default — no `extra="forbid"` on query-param validation).

### Response shape

```python
class TemplateFieldInfo(BaseModel):
    """Per-field metadata describing how a template uses a payload key."""
    required: bool
    role: Literal["qr-content", "headline", "subtitle", "extra-line"]
    description: str


class TemplateResponse(BaseModel):
    """Public-facing template metadata for discovery clients."""
    id: str                                 # e.g. "qr-only-12mm"
    name: str                               # human-readable name
    app: str | None                         # plugin binding ("snipeit", "grocy", "spoolman") or null
    tape_mm: int                            # 12, 18, 24, ...
    has_qr: bool                            # at least one element.type == "qr"
    text_lines: int                         # number of element.type == "text"
    fields: dict[str, TemplateFieldInfo]    # key = "qr_payload" | "primary_id" | "title" | "secondary[0]" ...
```

### Example response

`GET /templates/qr-only-12mm`:

```jsonc
{
  "id": "qr-only-12mm",
  "name": "QR-Code only (12mm)",
  "app": null,
  "tape_mm": 12,
  "has_qr": true,
  "text_lines": 0,
  "fields": {
    "qr_payload": {
      "required": true,
      "role": "qr-content",
      "description": "Data encoded INTO the QR code (typically a URL)."
    }
  }
}
```

`GET /templates/snipeit-12mm`:

```jsonc
{
  "id": "snipeit-12mm",
  "name": "Snipe-IT Asset (12mm)",
  "app": "snipeit",
  "tape_mm": 12,
  "has_qr": true,
  "text_lines": 2,
  "fields": {
    "qr_payload":  { "required": true, "role": "qr-content", "description": "Data encoded INTO the QR code (typically a URL)." },
    "primary_id":  { "required": true, "role": "headline",   "description": "Primary identifier displayed prominently (e.g. asset tag 'ITX-0042')." },
    "title":       { "required": true, "role": "subtitle",   "description": "Human-readable label of the item (e.g. 'Dell Latitude 5520')." }
  }
}
```

### Field-role derivation (deterministic, name-based)

Roles are derived from the payload key, **not** from font sizes. This avoids
heuristics over template geometry that could change under refactoring.

| Element source | Payload key | Role |
|---|---|---|
| `data_field: qr_payload` (qr element) | `qr_payload` | `qr-content` |
| `field: primary_id` (text element) | `primary_id` | `headline` |
| `field: title` (text element) | `title` | `subtitle` |
| `field: secondary[N]` (text element) | `secondary[N]` | `extra-line` |

`required` is always `true` for any field that appears in a template's
elements — the template wouldn't render correctly without it.

### Field-description map

Single source of truth in `schemas/template_response.py`:

```python
_FIELD_DESCRIPTIONS: dict[str, str] = {
    "qr_payload":  "Data encoded INTO the QR code (typically a URL).",
    "primary_id":  "Primary identifier displayed prominently (e.g. asset tag 'ITX-0042').",
    "title":       "Human-readable label of the item (e.g. 'Dell Latitude 5520').",
    # secondary[N] uses a format string:
    "_secondary":  "Extra line {n} below the primary identifier (typically 18mm/24mm tapes).",
}
```

The `secondary[N]` key is special-cased: the description is interpolated
from `_secondary` with `n = N` so `secondary[0]` → `"...line 0 below..."`.

## Component 2: Template-aware Validation

### Schema change: `RawLabelData`

`backend/app/schemas/print_request.py`:

```python
class RawLabelData(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    title: str = Field(default="", description="...")
    primary_id: str = Field(default="", description="...")
    qr_payload: str = Field(default="", description="...")
    secondary: list[str] = Field(default_factory=list, description="...")
```

All scalar fields now default to `""`. Existing callers that send all
three continue to work unchanged.

### `TemplateSchema.required_fields()`

`backend/app/schemas/template.py`:

```python
def required_fields(self) -> set[str]:
    """Payload keys this template's renderer will read.

    Returns the set of LabelData attribute paths (e.g. {"qr_payload",
    "primary_id"} or {"qr_payload", "primary_id", "secondary[0]"}).
    Used by PrintService to fail-fast when a client submits an incomplete
    payload for the chosen template.
    """
    result: set[str] = set()
    for el in self.elements:
        if el.type == "qr" and el.data_field:
            result.add(el.data_field)
        elif el.type == "text" and el.field:
            result.add(el.field)
    return result
```

The method is on the `TemplateSchema` class so callers can derive it
from any template instance without re-implementing the iteration logic.

### Validation flow in `PrintService.submit_print_job`

Inserted **after** `template_loader.get(template_id)` (existing path that
raises `TemplateNotFoundError` → 404) and **before** `LabelData(...)`
construction:

```python
template = template_loader.get(request.template_id)
if request.data is not None:
    required = template.required_fields()
    missing = _find_missing_fields(request.data, required)
    if missing:
        raise MissingTemplateFieldsError(
            template_id=request.template_id,
            missing=missing,
        )
# ...continue with LabelData(...) construction
```

Where `_find_missing_fields` implements:

| Required key | "Missing" check |
|---|---|
| `qr_payload`, `primary_id`, `title` | corresponding attribute is the empty string |
| `secondary[N]` | `len(data.secondary) <= N` **or** `data.secondary[N]` is empty string |

Both empty-string-for-scalar and out-of-range-or-empty-for-list are treated
as missing. Empty string is the new schema default, so anything the caller
explicitly cleared is also rejected — the field counts only if it carries
content.

### Lookup-mode interaction

When `request.data is None` (i.e. the caller used `lookup` instead of
`data`), validation against template-required fields is **skipped**. The
integration plugin is trusted to produce a complete `LabelData` (a plugin
that ships incomplete data is its own bug, surfaced as a 502
`integration_lookup_failed` if rendering throws downstream).

### New error: `MissingTemplateFieldsError`

`backend/app/services/errors.py` — service-layer errors live here
alongside `AppLookupNotFoundError`; `printer_backends/exceptions.py` is
reserved for transport-layer (TCP/SNMP/ptouch) errors which this is not:

```python
class MissingTemplateFieldsError(Exception):
    def __init__(self, template_id: str, missing: list[str]) -> None:
        super().__init__(f"Template {template_id!r} requires fields not in payload: {sorted(missing)}")
        self.template_id = template_id
        self.missing = sorted(missing)
```

### API-layer mapping

Append to `_SYNC_ERROR_MAP` in `backend/app/api/routes/print.py`:

```python
MissingTemplateFieldsError: (422, "missing_template_fields"),
```

Response body when 422 fires:

```jsonc
{
  "error_code": "missing_template_fields",
  "error_detail": {
    "template_id": "snipeit-12mm",
    "missing": ["primary_id", "title"]
  }
}
```

422 is correct because the request is **structurally** valid (Pydantic
accepts it) but **semantically** mismatched against the chosen template.
This mirrors FastAPI's own 422 for Pydantic-validation failures.

## Component 3: Field-descriptions

`RawLabelData` (`backend/app/schemas/print_request.py`):

```python
class RawLabelData(BaseModel):
    title: str = Field(
        default="",
        description=(
            "Human-readable label of the item (e.g. 'Dell Latitude 5520', "
            "'Apfel Bio'). Rendered as smaller subtitle text on templates "
            "that include a `field: title` element. Ignored by qr-only-* "
            "templates."
        ),
    )
    primary_id: str = Field(
        default="",
        description=(
            "Primary identifier displayed prominently (e.g. asset tag "
            "'ITX-0042'). Rendered large as the headline on templates "
            "that include a `field: primary_id` element."
        ),
    )
    qr_payload: str = Field(
        default="",
        description=(
            "Data encoded INTO the QR code (typically a URL pointing to "
            "the asset/product in the source application). The QR encoder "
            "is content-agnostic — plain text works too."
        ),
    )
    secondary: list[str] = Field(
        default_factory=list,
        description=(
            "Additional lines printed below primary_id on templates that "
            "support multi-line layouts (typically 18mm/24mm tapes). Order "
            "matters — `secondary[0]` appears above `secondary[1]`. "
            "Plugins populate this with integration-specific extras "
            "(e.g. Snipe-IT serial, Spoolman material/colour)."
        ),
    )
```

`TemplateResponse` and `TemplateFieldInfo` get analogous `description=`
arguments so the discovery API is self-explanatory in Swagger.

## Component interactions

```
client                  FastAPI                PrintService            TemplateLoader
  │                       │                       │                       │
  │  GET /templates       │                       │                       │
  ├──────────────────────▶│                       │                       │
  │                       │  TemplateLoader.all() ├──────────────────────▶│
  │                       │                       │◀──────────────────────┤  dict[id, TemplateSchema]
  │                       │  derive TemplateResponse[]                    │
  │◀──────────────────────┤                       │                       │
  │                                                                       │
  │  POST /print          │                       │                       │
  │  template=snipeit-12mm│                       │                       │
  │  data={qr_payload:..} │                       │                       │
  ├──────────────────────▶│                       │                       │
  │                       │  submit_print_job(req)│                       │
  │                       ├──────────────────────▶│  template_loader.get  │
  │                       │                       ├──────────────────────▶│
  │                       │                       │◀──────────────────────┤  TemplateSchema
  │                       │                       │  required = .required_fields()
  │                       │                       │  missing = {primary_id, title}
  │                       │                       │  raise MissingTemplateFieldsError
  │                       │◀──────────────────────┤
  │                       │  map → 422            │
  │◀──────────────────────┤                       │                       │
```

## Testing strategy

TDD-strict: every behaviour change starts with a failing test, then minimal
implementation. The plan (writing-plans output) will lay out the exact
task-by-task ordering.

### New test files

| File | What it covers |
|---|---|
| `tests/unit/schemas/test_template_required_fields.py` | `TemplateSchema.required_fields()` returns the right set for every seed template variant (qr-only, snipeit, grocy, spoolman × {12, 18, 24}mm). |
| `tests/unit/schemas/test_template_response.py` | `TemplateResponse` field derivation: roles, has_qr, text_lines, fields dict. Includes the `secondary[N]` interpolation case. |
| `tests/unit/schemas/test_raw_label_data_optional.py` | Defaults for title/primary_id/qr_payload are `""`, `secondary` is `[]`. |
| `tests/unit/api/test_templates_routes.py` | `GET /templates` happy path, `?tape_mm=` filter, `?app=` filter, `?app=none` for generics, `GET /templates/{id}` happy path + 404 + error body shape. |
| `tests/unit/services/test_print_service_validation.py` | `MissingTemplateFieldsError` raised for empty required fields, raised for `secondary[N]` out-of-range/empty, NOT raised when all required fields are present, NOT raised in lookup-mode. |

### Extended test files

| File | What's added |
|---|---|
| `tests/unit/api/test_print_routes.py` | New 422 path: `error_code: "missing_template_fields"`, `error_detail.template_id`, `error_detail.missing` shape. |
| `tests/unit/schemas/test_print_request.py` | Confirm that `data={"qr_payload": "x"}` now parses (was rejected before due to required title/primary_id). |

### Coverage targets

- Project-wide floor stays at 80% (CI gate is `--cov-fail-under=80`).
- Realistic target: keep current 91.84% repo average, raise `api/routes/`
  component above 95%.

## Acceptance criteria

1. `GET /templates` returns one entry per seed template in
   `backend/app/seed/templates/`, every entry has the documented schema.
2. `GET /templates?tape_mm=12` returns only 12mm templates; `?app=snipeit`
   returns only Snipe-IT templates; `?app=none` returns only generic ones.
3. `GET /templates/qr-only-12mm` returns the documented JSON exactly (modulo
   description-string changes).
4. `GET /templates/does-not-exist` returns 404 with
   `error_code: "template_not_found"`.
5. `POST /print` with `template_id="qr-only-12mm"` and
   `data={"qr_payload":"https://example.com"}` (no `title`, no `primary_id`)
   returns 202 with a `job_id` — previously rejected for missing fields.
6. `POST /print` with `template_id="snipeit-12mm"` and
   `data={"qr_payload":"x"}` (missing `primary_id` and `title`) returns 422
   with `error_code: "missing_template_fields"` and
   `error_detail.missing = ["primary_id", "title"]` (sorted).
7. `POST /print` with `template_id="spoolman-18mm"` and `secondary=["one"]`
   when the template uses `secondary[0]` AND `secondary[1]` returns 422
   listing `"secondary[1]"` in `missing`.
8. Swagger UI at `/docs` shows `description` strings for every
   `RawLabelData` field and every `TemplateResponse` / `TemplateFieldInfo`
   field.
9. All 355 existing tests still pass. New tests bring the project to
   ≥ 91% coverage.
10. Privacy / secret scan still passes (no internal IPs / hostnames in
    new fixtures — use `192.0.2.x` per RFC 5737).

## Branch strategy

Per user decision (clarification on 2026-05-15):

1. PR #59 (`feat/first-print`) merges to `main` first.
2. New branch `feat/templates-api-and-minimal-payload` is created off
   updated `main`.
3. This spec file is committed as the first commit on that branch.
4. Implementation proceeds via `superpowers:writing-plans` →
   `superpowers:subagent-driven-development`.

If #59 takes longer than expected, this spec can be re-evaluated and
optionally split into two PRs (discovery API on its own off main; validation
stacked on first-print). The default path assumes #59 merges within days.

## References

| Document | Link |
|---|---|
| Master tracking issue | strausmann/Label-Printer-Hub#22 |
| First-Print spec | `docs/designs/2026-05-15-first-print.md` |
| First-Print plan | `docs/plans/2026-05-15-first-print.md` |
| ADR 0012 — label layout management | `docs/decisions/0012-label-layout-management.md` |
| Current `LabelData` schema | `backend/app/schemas/label_data.py` |
| Current `TemplateSchema` | `backend/app/schemas/template.py` |
| Current `PrintService` | `backend/app/services/print_service.py` |
| `TemplateLoader` | `backend/app/services/template_loader.py` |
