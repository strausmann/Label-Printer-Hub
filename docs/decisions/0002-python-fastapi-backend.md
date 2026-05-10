# 0002 — Python + FastAPI for the backend

- **Status:** Accepted
- **Date:** 2026-05-10
- **Deciders:** maintainer

## Context

The backend's job is to talk to Brother label printers (TCP/9100 raster bytes, SNMP for status, IPP optional later), parse the 32-byte Brother status block, run an asyncio print queue per device, persist state in SQLite, and expose a JSON+SSE API.

Two ecosystems are realistic for this kind of work: Python (with `nbuchwitz/ptouch`, `pklaus/brother_ql`, `pysnmp` already mature) and Go (which would require either porting these libraries or shelling out).

## Decision

We use **Python 3.12+ with FastAPI** for the backend.

- Existing Python libraries already implement Brother PT-Series and QL-Series raster encoding correctly. Re-implementing them in another language is wasted effort.
- FastAPI gives us OpenAPI 3.1 generation for free, which the Go frontend (ADR 0003) consumes as a typed client.
- asyncio-native printer queue and SSE endpoint are ergonomic in FastAPI.
- SQLModel (Pydantic + SQLAlchemy) integrates cleanly with FastAPI request/response schemas.

## Options considered

### Option A — Python + FastAPI (chosen)
- Pros: existing printer libraries; fast OpenAPI; asyncio-first; minimal boilerplate for our scale; large ecosystem for testing (`pytest`, `respx`, `httpx`)
- Cons: slower than Go for raw HTTP throughput (irrelevant at this scale); larger container image (~200 MB vs ~20 MB Go)

### Option B — Go for the entire backend
- Pros: smaller image, faster startup, single binary
- Cons: would have to either port Brother raster libraries or rely on shelling out to a Python helper — both are worse than just using Python; no equivalent of `nbuchwitz/ptouch` exists in Go (May 2026)

### Option C — Node.js backend
- Pros: would let us share TypeScript types with the frontend
- Cons: no mature Brother libraries; doesn't match maintainer's stack preferences

## Consequences

- Backend container is Python-based (likely `python:3.12-slim`)
- Dependencies: `fastapi`, `uvicorn[standard]`, `pydantic`, `sqlmodel`, `aiosqlite`, `httpx`, `pysnmp` (≥6.2 asyncio API), `nbuchwitz/ptouch`, `brother_ql`, `Pillow`, `qrcode`
- Tests use `pytest` + `pytest-asyncio` + `respx` for HTTP mocks
- Lint with `ruff`, type-check with `mypy --strict`
- Image size acceptable; multi-stage build keeps it under 250 MB
- Backend exposes port 8000 on the internal docker network only

## References

- Issue [#1](https://github.com/strausmann/label-printer-hub/issues/1)
- Library deep-dive: research doc in maintainer's private mono-repo (summary included in [`../research/`](../research/))
- Related: ADR 0001 (two-container), ADR 0004 (plugin architecture), ADR 0005 (queue)
