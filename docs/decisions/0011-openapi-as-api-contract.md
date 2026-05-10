# 0011 — OpenAPI as the canonical API contract

- **Status:** Accepted
- **Date:** 2026-05-10
- **Deciders:** maintainer

## Context

The two-container architecture (ADR 0001) means the Go frontend talks to the Python backend over HTTP/JSON. The contract between them must be:

1. **Authoritative** — there is one machine-readable source of truth for endpoint shapes, request/response types, status codes, and error schemas
2. **Type-safe in Go** — the frontend shouldn't hand-write fragile struct definitions that drift from the backend
3. **Discoverable** — third-party integrations (Spoolman/Grocy webhook payloads, future plugins, contributors writing tests) need to inspect the API without reading FastAPI source code
4. **Browseable** — humans need an interactive UI to try requests during development and debugging

FastAPI generates an OpenAPI 3.1 specification automatically from Pydantic models, type hints, and route declarations. We can lean on that.

## Decision

OpenAPI 3.1 is the **canonical API contract**. The contract surfaces in three forms, all served by the backend:

| Path | What | Used by |
|---|---|---|
| `/openapi.json` | Raw OpenAPI 3.1 spec, JSON | Tooling (codegen, contract tests, Postman, etc.) |
| `/docs` | Swagger UI — interactive try-it-now interface | Developers during development |
| `/redoc` | ReDoc — clean reference rendering, optimised for reading | Contributors and integrators reading the API |

The Go frontend client is **generated from `/openapi.json` using [`oapi-codegen`](https://github.com/oapi-codegen/oapi-codegen)** at frontend build time. Hand-written backend clients are not allowed — schema drift must not be possible.

**Code generation pipeline:**

```
backend (FastAPI)
   │
   │ generates at runtime
   ▼
backend exposes /openapi.json  ◄──── frontend build fetches/imports this
                                            │
                                            │ oapi-codegen
                                            ▼
                                  frontend/internal/api/client.go
                                  frontend/internal/api/types.go
                                            │
                                            │ used by
                                            ▼
                                  frontend HTTP handlers
```

The `/openapi.json` snapshot is checked into the repo at `backend/openapi.json` and refreshed by a CI step on backend changes (`task openapi:snapshot`). The frontend's `oapi-codegen` step reads this committed snapshot, not a live backend, so frontend builds are reproducible offline.

## Options considered

### Option A — OpenAPI + oapi-codegen + Swagger UI + ReDoc (chosen)
- Pros: deterministic generation; type safety in Go; rich contributor tooling; FastAPI generates the spec for free; ReDoc + Swagger UI cover both browse and try-it use cases
- Cons: requires keeping the snapshot fresh; codegen step in CI

### Option B — Hand-written Go client + ad-hoc API doc page
- Pros: no codegen tooling
- Cons: drift inevitable; refactoring backend models breaks frontend silently until runtime; doc page rots

### Option C — gRPC instead of REST
- Pros: native code generation; strict contract
- Cons: overkill for ~20 endpoints; browser fetch API doesn't speak gRPC natively (would need gRPC-Web proxy); excludes curl/Postman from the toolbox

### Option D — Use a third interactive doc tool (Scalar, Stoplight Elements, RapiDoc) instead of Swagger/ReDoc
- Pros: arguably nicer UX (Scalar, in particular)
- Cons: extra dependency; FastAPI ships Swagger UI + ReDoc out of the box; may revisit later as a separate ADR

We choose Option A. Option D may supersede via a future ADR if the maintainer wants Scalar.

## Consequences

- FastAPI app sets:
  - `openapi_url="/openapi.json"`
  - `docs_url="/docs"` (Swagger UI, default)
  - `redoc_url="/redoc"` (ReDoc, default)
  - `openapi_version="3.1.0"`
- All public endpoints have explicit Pydantic request/response models with field descriptions and examples — these become rich OpenAPI schemas
- Errors use `HTTPException` with consistent `detail` shape; documented as a single `Error` schema
- Backend CI step: `task openapi:snapshot` runs `python -c "from app.main import app; import json; json.dump(app.openapi(), open('openapi.json', 'w'), indent=2)"` and fails if the diff isn't committed (forces contributors to refresh the snapshot)
- Frontend CI step: `oapi-codegen -config oapi-codegen.yaml backend/openapi.json` regenerates `frontend/internal/api/`
- `oapi-codegen.yaml` config:
  ```yaml
  package: api
  generate:
    models: true
    client: true
    strict-server: false
  output: internal/api/api.gen.go
  ```
- `Taskfile.yml` (or Makefile) wires both steps into single commands for contributors
- The committed `backend/openapi.json` is reviewable in PR diffs — contract changes are visible
- README "Documentation" section adds links to `/docs` and `/redoc` for users running the hub locally
- API reference doc (`docs/api.md`) becomes a thin pointer to `/redoc` rather than hand-maintained Markdown
- Contract-breaking changes (renaming a field, removing an endpoint) require `feat!` Conventional Commit and explicit migration notes — the diff in `openapi.json` makes them visible

## Future enhancements (separate ADRs if pursued)

- **Scalar API Reference** as a third interactive UI option (`/scalar` route, modern UX)
- **Mock server** generated from OpenAPI for frontend dev without running backend (`prism mock backend/openapi.json`)
- **Contract tests** in CI — schemathesis fuzzing or dredd verification

## References

- [FastAPI OpenAPI generation](https://fastapi.tiangolo.com/tutorial/openapi/)
- [oapi-codegen](https://github.com/oapi-codegen/oapi-codegen)
- [Swagger UI](https://swagger.io/tools/swagger-ui/) (bundled with FastAPI)
- [ReDoc](https://github.com/Redocly/redoc) (bundled with FastAPI)
- [OpenAPI 3.1 spec](https://spec.openapis.org/oas/v3.1.0)
- Related: ADR 0001 (two-container — establishes the contract need), ADR 0002 (FastAPI generates the spec), ADR 0003 (Go frontend consumes the generated client)
