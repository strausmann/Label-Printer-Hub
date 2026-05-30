# Phase 7c Implementation Plan — App-side API Authentication

**Date:** 2026-05-17
**Spec:** `docs/superpowers/specs/2026-05-17-phase-7c-api-auth-design.md`
**Branch:** `feat/phase-7c-api-auth`
**Tracking:** master #22, Closes #78

## Commit Cadence Rule

Every 2-3 files → commit → push immediately. No accumulation beyond 5 uncommitted files.

## Step 0 — Branch + Plan (THIS COMMIT)

Files:
- `docs/superpowers/specs/2026-05-17-phase-7c-api-auth-design.md` (copied from spec branch)
- `docs/superpowers/plans/2026-05-17-phase-7c-api-auth.md` (this file)

## Step 1 — Database Layer

### TDD Tasks

**Task 1a: ApiKey model — RED test first**
- Test file: `backend/tests/unit/models/test_api_key_model.py`
  - Test column types present (id UUID, name str, key_hash str, key_prefix str, scopes JSON, allowed_printer_ids JSON, rate_limit_per_minute int, enabled bool, created_at datetime-tz, last_used_at nullable, last_used_ip nullable, expires_at nullable, notes nullable)
- Production file: `backend/app/models/api_key.py`

**Task 1b: Job model extensions — RED test first**
- Test file: `backend/tests/unit/models/test_api_key_model.py` (add job column tests)
  - Test Job has `api_key_id: UUID | None` and `source_ip: str | None` columns
- Production file: `backend/app/models/job.py` (add 2 nullable columns)

Commit after model tests pass.

**Task 1c: Alembic migration — RED consistency test first**
- Test file: `backend/tests/integration/db/test_alembic_phase7c_migration.py`
  - Test upgrade creates `api_keys` table
  - Test upgrade adds `api_key_id` + `source_ip` to `jobs`
  - Test upgrade seeds bootstrap-admin key
  - Test downgrade removes the table + columns
- Production file: `backend/alembic/versions/20260517_phase7c_api_keys.py`

**Task 1d: ApiKey repository — RED test first**
- Test file: `backend/tests/db/test_api_keys_repo.py`
  - `get_by_prefix` returns key matching prefix
  - `list_active` returns only enabled, non-expired keys
  - `create` inserts key and returns it
  - `revoke` sets enabled=False
  - `update_last_used` sets last_used_at + last_used_ip
- Production file: `backend/app/repositories/api_keys.py`

Commit after repo tests pass.

## Step 2 — Key Generation + bcrypt + LRU Cache

### TDD Tasks

**Task 2a: Key generator — RED test first**
- Test file: `backend/tests/unit/auth/test_key_generator.py`
  - `generate_api_key()` returns tuple (plaintext, prefix, hash)
  - plaintext starts with `lh_`
  - prefix == plaintext[:12]
  - hash verifies correctly with bcrypt
  - prefix is exactly 12 chars
  - entropy: 10 consecutive calls produce unique plaintexts
- Production file: `backend/app/auth/key_generator.py`

**Task 2b: Verifier + LRU cache — RED test first**
- Test file: `backend/tests/unit/auth/test_verifier.py`
  - `verify_api_key(plaintext, hash)` returns True for correct match
  - `verify_api_key(wrong, hash)` returns False
  - Cache: second call to verify() with same plaintext does NOT call bcrypt again (mock bcrypt)
  - Cache expiry: TTL-expired entries are re-verified via bcrypt
- Production file: `backend/app/auth/verifier.py`

Commit after gen + verify tests pass.

## Step 3 — FastAPI Dependency `require_scope`

### TDD Tasks

**Task 3a: AuthContext model — RED test first**
- Test file: `backend/tests/unit/auth/test_dependencies.py`
  - `AuthContext` has fields: source, scope, api_key_id, ip
  - `source` constrained to Literal["api-key", "pangolin-sso", "pangolin-bypass"]
  - `scope` constrained to Literal["read", "print", "admin"]

**Task 3b: Path 1 — Valid API key — RED test first**
- Test: request with valid `X-Label-Hub-Key` header → returns AuthContext(source="api-key")
- Test: request with invalid key → raises 401

**Task 3c: Path 2 — Pangolin SSO — RED test first**
- Test: request without key but with `X-Pangolin-User` header on read endpoint → AuthContext(source="pangolin-sso")
- Test: same on print endpoint → raises 401

**Task 3d: Path 3 — Pangolin bypass — RED test first**
- Test: `Authorization: Basic claude-automation:...` on read endpoint → AuthContext(source="pangolin-bypass")
- Test: flag `pangolin_bypass_scope_downgrade=True` → POST print → 401
- Test: flag `pangolin_bypass_scope_downgrade=False` (default) → POST print → AuthContext (bypass still passes write)

**Task 3e: Scope hierarchy — RED test first**
- Test: `admin` key on `read` endpoint → allowed
- Test: `print` key on `admin` endpoint → raises 403
- Test: `read` key on `print` endpoint → raises 403

**Task 3f: Settings — add `pangolin_bypass_scope_downgrade: bool = False`**
- Test file: `backend/tests/unit/test_config.py` (extend existing)

Commit after all dependency tests pass.

## Step 4 — Wire Dependency into Routes

### TDD Tasks

**Task 4a: printers.py route annotations — RED test first**
- Test file: `backend/tests/unit/api/test_printers_routes.py` (extend)
  - Without auth header → 401 on all printer endpoints
  - With `read` key → 200/204 on GET endpoints
  - With `print` key → 204 on POST pause/resume/clear

**Task 4b: templates.py route annotations — RED test first**
- Test file: `backend/tests/unit/api/test_templates_routes.py` (extend)
  - GET templates without key → 401
  - DELETE template without key → 401, with admin key → 204

**Task 4c: print.py route annotations — RED test first**
- Test file: `backend/tests/unit/api/test_print_routes.py` (extend)
  - GET /jobs/{id} without key → 401
  - POST /print without key → 401, with print key → 202

**Task 4d: render/preview annotation — RED test first**
- Test file: `backend/tests/unit/api/test_render_routes.py` (new)
  - POST /api/render/preview without key → 401, with read key → passthrough

Commit after all route tests pass.

## Step 5 — Rate Limiter

### TDD Tasks

**Task 5a: Token bucket — RED test first**
- Test file: `backend/tests/unit/services/test_rate_limiter.py`
  - 60 tokens: first 60 calls → True, 61st → False
  - Refill: after `capacity / rate` seconds → token available again
  - Different key IDs have independent buckets

**Task 5b: Rate limiter in require_scope — RED integration test first**
- Test file: `backend/tests/integration/api/test_rate_limit.py`
  - 61 POST /api/print calls with same key → 61st returns 429
  - 429 body has `error_code: "rate_limit_exceeded"` and `retry_after_seconds > 0`
  - 429 response has `Retry-After` header

Commit after rate limiter tests pass.

## Step 6 — Per-Key Printer ACL

### TDD Tasks

**Task 6a: Printer ACL check in require_scope_for_printer — RED test first**
- Test file: `backend/tests/unit/auth/test_dependencies.py` (extend)
  - Key with `allowed_printer_ids=[A]` on printer B → 403
  - Key with empty `allowed_printer_ids` → all printers allowed
  - Key with `allowed_printer_ids=[A]` on printer A → allowed

**Task 6b: Wire into printers routes — RED integration test first**
- Test file: `backend/tests/integration/api/test_printer_acl.py`
  - POST /api/printers/{B}/pause with key restricted to {A} → 403

Commit after ACL tests pass.

## Step 7 — Audit Trail on Jobs

### TDD Tasks

**Task 7a: create_queued accepts AuthContext — RED test first**
- Test file: `backend/tests/db/test_api_keys_repo.py` (extend) or new file
  - `create_queued(..., auth_context=...)` stores `api_key_id` + `source_ip` on job
  - Old call without auth_context → `api_key_id=None`, `source_ip=None` (backward compat)

**Task 7b: print route passes AuthContext — RED integration test first**
- Test file: `backend/tests/integration/api/test_audit_trail.py`
  - POST /api/print with key X → Job DB row has `api_key_id=X` and `source_ip` set

Commit after audit trail tests pass.

## Step 8 — Backend API for /api/admin/api-keys CRUD

### TDD Tasks

**Task 8a: admin_api_keys routes — RED test first**
- Test file: `backend/tests/unit/api/test_admin_api_keys_routes.py`
  - GET /api/admin/api-keys without admin key → 403
  - POST /api/admin/api-keys → creates key, response includes `plaintext` (once)
  - GET /api/admin/api-keys/{id} → metadata only, no plaintext
  - PATCH /api/admin/api-keys/{id} → updates enabled/rate_limit/notes
  - DELETE /api/admin/api-keys/{id} → 204, key rejected on next use

**Task 8b: CRUD lifecycle integration — RED test first**
- Test file: `backend/tests/integration/api/test_admin_api_keys.py`
  - Full create → use → revoke → verify-rejected cycle

Commit after admin CRUD tests pass.

## Step 9 — Frontend HTMX /admin/api-keys UI

### TDD Tasks

- `frontend/internal/handlers/admin_api_keys.go` — handlers
- `frontend/web/templates/admin_api_keys.html`
- `frontend/web/templates/admin_api_keys_create.html`
- `frontend/web/templates/admin_api_keys_detail.html`
- Go test file: `frontend/internal/handlers/admin_api_keys_test.go`
  - GET /admin/api-keys → 200 HTML containing key list
  - POST /admin/api-keys/new → creates key, shows plaintext modal
  - Revoke flow → key marked revoked

Note: `make oapi` must be run after Step 8 to regenerate Go client with admin endpoints.

Commit after Go handler tests pass.

## Step 10 — Final Integration + Production-Readiness

- Full test suite: `pytest` + `ruff check` + `ruff format --check` + `mypy` + `go test ./...` + `go vet ./...`
- Coverage check: `pytest --cov=app --cov-fail-under=80`
- Auth modules separately: `pytest tests/unit/auth/ --cov=app/auth --cov-fail-under=95`
- README section on API keys
- `docs/site/operations/api-keys.md` operator guide
- `mkdocs.yml` nav update

Commit after all checks pass.

## Step 11 — Open PR

```bash
gh pr create --base main --head feat/phase-7c-api-auth \
  --title "feat(api): Phase 7c — app-side API-Key authentication with 3-scope keys + rate-limit + admin UI"
```

## Dependencies to add to pyproject.toml

- `bcrypt>=4.0` — key hashing
- `cachetools>=5.0` — LRU TTL cache for bcrypt verify

## Files Modified/Created Summary

| File | Action |
|------|--------|
| `backend/app/models/api_key.py` | Create |
| `backend/app/models/job.py` | Extend (2 nullable columns) |
| `backend/alembic/versions/20260517_phase7c_api_keys.py` | Create |
| `backend/app/repositories/api_keys.py` | Create |
| `backend/app/auth/__init__.py` | Create |
| `backend/app/auth/key_generator.py` | Create |
| `backend/app/auth/verifier.py` | Create |
| `backend/app/auth/dependencies.py` | Create |
| `backend/app/services/rate_limiter.py` | Create |
| `backend/app/api/routes/admin_api_keys.py` | Create |
| `backend/app/api/routes/printers.py` | Extend (auth deps) |
| `backend/app/api/routes/templates.py` | Extend (auth deps) |
| `backend/app/api/routes/print.py` | Extend (auth deps) |
| `backend/app/api/routes/webhooks.py` | Extend (auth deps) |
| `backend/app/config.py` | Extend (pangolin_bypass_scope_downgrade) |
| `backend/app/main.py` | Extend (register admin router) |
| `backend/pyproject.toml` | Extend (bcrypt, cachetools deps) |
| `frontend/cmd/server/main.go` | Extend (admin route) |
| `frontend/internal/handlers/admin_api_keys.go` | Create |
| `frontend/web/templates/admin_api_keys.html` | Create |
| `frontend/web/templates/admin_api_keys_create.html` | Create |
| `frontend/web/templates/admin_api_keys_detail.html` | Create |
| `docs/site/operations/api-keys.md` | Create |
