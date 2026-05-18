# Phase 7c Foundation Design — App-side API Authentication

**Date:** 2026-05-17
**Status:** Draft
**Tracking:** strausmann/label-printer-hub#22 (master), #78 (Phase 7c)
**Dependencies:**
- Phase 7b foundation (merged) provides the `/readiness` deep-check + status cache used by middleware sanity probes
- Hard-blocks Phase 7d (#80) — every external API caller needs an authenticated key before Phase 7d can ship to production

## 1. Executive Summary

Phase 7c introduces **app-side API-Key authentication** to close the security gap exposed by Phase 7b's first production deploy:

- Currently the API has NO own authentication. All access control hangs at the Pangolin edge (SSO for browsers, Basic-Auth-Bypass `claude-automation` for tooling).
- Single shared secret → if leaked, full unrestricted access to every endpoint.
- No per-caller audit trail, no rate limiting, no scoping.

Phase 7c delivers:

1. **Multi-key management** through a new HTMX UI at `/admin/api-keys`
2. **3-level scope model:** `read`, `print`, `admin` per key (no finer granularity needed for HomeLab scope)
3. **bcrypt-hashed key storage** with prefix preserved for UI display (`lh_pat_ab12cd34...`)
4. **60 prints/min default rate-limit** per key, configurable per-key in the UI (in-memory token-bucket sufficient for single-instance HomeLab)
5. **Audit trail** in the Jobs table — `api_key_id`, `source_ip` on every print
6. **Pangolin-Basic-Auth-Bypass downgrade** — after Phase 7c lands, `claude-automation` is scoped to `read`-only as recovery path, all writes require app-key
7. **Transition window** — both auth paths work during deployment, switch-over communicated via docs

The auth layer is implemented as a FastAPI dependency that runs before any other route handler, so endpoint definitions stay clean (`Depends(require_scope("print"))`).

## 2. Database Schema

### New `api_keys` table

```python
class ApiKey(SQLModel, table=True):
    __tablename__ = "api_keys"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True)              # User-facing display name, e.g. "Plex Print"
    key_hash: str                              # bcrypt hash of the full plaintext key
    key_prefix: str = Field(index=True)        # First 16 chars for display, e.g. "lh_pat_ab12cd34"
    scopes: list[str] = Field(sa_column=Column(JSON, nullable=False))   # ["read"] / ["read", "print"] / ["admin"]
    allowed_printer_ids: list[UUID] = Field(   # Empty list = all printers; non-empty = restricted
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10000)
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_used_at: datetime | None = None
    last_used_ip: str | None = None
    expires_at: datetime | None = None         # NULL = no expiry; future date = auto-disable after
    notes: str | None = None                   # User-facing free text
```

`scopes` is a JSON list rather than a single string so future scopes can be added without schema migration. Values constrained at the Pydantic layer to the canonical set `{"read", "print", "admin"}`.

### Job table extensions

```python
# Add to existing Job model:
api_key_id: UUID | None = None     # ForeignKey hint, no constraint (allow key deletion without losing job history)
source_ip: str | None = None
```

Both nullable so historical jobs from before Phase 7c retain integrity. Backfill is unnecessary — old jobs predate the auth concept.

### Alembic migration

Single migration `20260517_phase7c_api_keys` that:

1. Creates `api_keys` table with all columns above
2. Adds `api_key_id` + `source_ip` to `jobs` table (nullable, no default)
3. Indices on `api_keys.key_prefix` (lookup hot path) and `jobs.api_key_id` (audit queries)
4. Seeds ONE initial admin key on first migration (only if `api_keys` is empty): name `"bootstrap-admin"`, scope `["admin"]`, prefix shown in startup log so operator can copy it. After first deploy, operator rotates it.

The seed prevents a chicken-and-egg lockout — without a first key, no one can create more keys via the API.

## 3. Authentication Middleware

### Dependency factory

```python
# backend/app/auth/dependencies.py

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-Label-Hub-Key", auto_error=False)


def require_scope(required: str):
    """Returns a FastAPI dependency that validates X-Label-Hub-Key
    contains at least the `required` scope OR falls back to Pangolin-bypass
    (read-only) OR Pangolin-SSO (browser session)."""

    async def _check(
        request: Request,
        key_header: str | None = Security(_api_key_header),
        session: AsyncSession = Depends(get_session),
    ) -> AuthContext:
        # Path 1: API-Key header
        if key_header:
            context = await _validate_api_key(session, key_header, required, request.client.host)
            return context

        # Path 2: Pangolin-SSO browser session (read scope only)
        if _has_pangolin_sso_session(request) and required == "read":
            return AuthContext(source="pangolin-sso", scope="read", api_key_id=None, ip=request.client.host)

        # Path 3: Pangolin-Bypass with claude-automation (read scope only after 7c)
        if _is_pangolin_bypass(request) and required == "read":
            return AuthContext(source="pangolin-bypass", scope="read", api_key_id=None, ip=request.client.host)

        raise HTTPException(401, "Missing or insufficient credentials")

    return _check
```

### `AuthContext` propagation

The dependency returns an `AuthContext` Pydantic model:
```python
class AuthContext(BaseModel):
    source: Literal["api-key", "pangolin-sso", "pangolin-bypass"]
    scope: Literal["read", "print", "admin"]
    api_key_id: UUID | None
    ip: str
```

Routes that create jobs receive this context and persist `api_key_id` + `ip` to the new Job columns. Other routes ignore it.

### Endpoint scope mapping

| Endpoint | Required scope |
|---|---|
| `GET /api/printers`, `GET /api/templates`, `GET /api/jobs/{id}` | `read` |
| `GET /api/printers/{id}/status`, `GET /readiness`, `GET /healthz` | `read` (but `/healthz` is publicly readable for Docker — no auth) |
| `POST /api/render/preview` | `read` (preview is side-effect-free) |
| `POST /api/print`, `POST /print` (legacy), `POST /api/webhook/print` | `print` |
| `POST /api/printers/{id}/pause`, `/resume`, `/clear` | `print` |
| `DELETE /api/templates/{id}`, `POST /api/templates` | `admin` |
| All `/api/admin/api-keys/*` endpoints | `admin` |

The `admin` scope subsumes `print` and `read`. `print` subsumes `read`. `read` is the lowest.

### Performance: bcrypt verify on every request

bcrypt verify is ~100ms per call (intentionally slow). To keep request latency low, the middleware caches the `(key_hash → AuthContext)` mapping in an in-memory LRU with 5-minute TTL. Cache invalidation on:
- Key delete: explicit cache flush by key_id
- Key rotation (recreate): old hash naturally expires after TTL

For a HomeLab with a handful of keys, this keeps per-request auth latency under 1ms after warm-up.

## 4. Key Generation + Format

### Generation

```python
import secrets

def generate_api_key() -> tuple[str, str, str]:
    """Returns (plaintext, prefix, bcrypt_hash).

    The plaintext is shown to the user ONCE on creation, never persisted.
    """
    body = secrets.token_urlsafe(32)            # 256 bits of entropy
    plaintext = f"lh_pat_{body}"
    prefix = plaintext[:16]                     # "lh_pat_ab12cd34X" — includes full PAT infix + 9 body discriminator chars
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=12)).decode()
    return plaintext, prefix, hashed
```

- `lh_pat_` PAT-style infix to unambiguously distinguish from other token formats (GitHub PAT `ghp_`, GitLab `glpat-`, etc.) and enable secret-scanning tool detection via the `pat_` discriminator
- 256-bit entropy from `secrets.token_urlsafe` — URL-safe charset, no padding issues in headers
- bcrypt rounds=12 (industry default 2024-2026, ~100-200ms verify)

### Custom Detector Configs

Both `.gitleaks.toml` and `.gitguardian.yaml` are included in the repo root with a custom rule matching `lh_pat_[A-Za-z0-9_-]{43}`. This ensures CI-side secret scanning catches any accidental commits of real tokens.

```toml
# .gitleaks.toml
[[rules]]
id = "labelhub-pat"
regex = '''lh_pat_[A-Za-z0-9_-]{43}'''
keywords = ["lh_pat_"]
```

### Display in UI

After creation, the plaintext is shown ONCE in a copy-to-clipboard modal. The DB only stores the hash. Subsequent UI views show only `key_prefix` plus metadata (name, scope, last_used_at, etc.).

## 5. Rate Limiting

### In-memory token bucket

Implemented as a global dict in `app.services.rate_limiter`:

```python
class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[UUID, _TokenBucket] = {}

    async def check_and_consume(self, key_id: UUID, limit_per_minute: int) -> bool:
        """Returns True if the call is allowed; False if rate-limit exceeded.

        Uses one token = one request, refill at `limit_per_minute / 60` tokens/second,
        capacity = limit_per_minute.
        """
        bucket = self._buckets.setdefault(key_id, _TokenBucket(limit_per_minute))
        bucket.refill_to_now(limit_per_minute / 60)
        if bucket.tokens >= 1:
            bucket.tokens -= 1
            return True
        return False
```

### Why in-memory + not Redis

- Single instance (single backend container) — no need for cross-process coordination
- HomeLab volume → ~tens of prints/day, rate-limit rarely hit
- Restarting the backend resets buckets → not a correctness issue, just gives an extra "free" minute after restart
- A Redis-backed limiter is a Phase 7c.1 follow-up if/when the HomeLab grows multi-instance

### Response on rate-limit

```json
HTTP 429 Too Many Requests
{
  "error_code": "rate_limit_exceeded",
  "error_message": "Key 'Plex Print' exceeded 60 prints/minute. Retry after 12 seconds.",
  "retry_after_seconds": 12
}
```

Standard `Retry-After` header included.

## 6. Admin UI — `/admin/api-keys`

### Route + Layout

New HTMX page rendered by the Frontend Go server, proxying to the backend for data. Path: `/admin/api-keys`. Requires Pangolin-SSO (browser context) + the backend dependency checks for `admin` scope OR an SSO-authenticated user (HomeLab uses single-user → SSO = admin).

Page sections:

```
+-- Top bar -----------------------------------------------------+
| API Keys                                  [+ Neuer Key]        |
+-- Key list ----------------------------------------------------+
| Name              Prefix           Scopes       Last used  ⚙ ❌ |
| Plex Print        lh_pat_ab12cd34X [print]      5 min ago      |
| Snipe-IT Asset    lh_pat_xyz98qwer [print]      2 days ago     |
| Bootstrap Admin   lh_pat_seed00dea [admin]      never          |
+----------------------------------------------------------------+
```

### Endpoints

| Method + Path | Purpose |
|---|---|
| `GET /admin/api-keys` | List page (HTMX-rendered, all keys via backend `GET /api/admin/api-keys`) |
| `POST /admin/api-keys/new` | Create form: name, scopes, allowed-printers, rate-limit, expires-at, notes |
| `POST /api/admin/api-keys` | Backend: create key, return `{key_id, plaintext, prefix}` (plaintext ONLY on creation) |
| `DELETE /api/admin/api-keys/{id}` | Backend: revoke key, returns 204 |
| `PATCH /api/admin/api-keys/{id}` | Backend: update enabled/rate_limit_per_minute/notes (NOT the key value) |
| `GET /api/admin/api-keys/{id}` | Backend: return single key metadata (no plaintext) |

### Audit log on key page

Each key's detail view shows last 100 jobs that used it:
```
Jobs created by this key:
- job 6b692989  2026-05-17 21:26  template grocy-12mm  → completed
- job a8c4b234  2026-05-17 18:12  template snipeit-12mm → completed
```

Sourced from `jobs.api_key_id` index.

## 7. Transition from Pangolin-Basic-Auth-Bypass

### Current state (post-Phase-7b)

- `claude-automation` user with 64-hex-secret can hit ANY endpoint
- Standard for all automation (curl, Plex, SnipeIt, this assistant's tooling)

### Target state (post-Phase-7c)

- `claude-automation` Pangolin-Bypass remains as a RECOVERY pathway, but the FastAPI middleware downgrades its effective scope to `read` only
- All writes (POST/DELETE) require an `X-Label-Hub-Key` header
- Plex, SnipeIt, Hangar, etc. each get their own `print`-scoped key in the new UI

### Migration

1. Phase 7c lands with seeded bootstrap-admin key
2. Operator (user) creates dedicated keys via UI:
   - "Plex Print" → scope `print`, all printers allowed
   - "SnipeIt Print" → scope `print`, all printers allowed
   - "Hangar Print" → scope `print`, all printers allowed (used by Hangar's Print-Page, see strausmann/hangar#63)
3. Operator updates each consumer's env / config to send `X-Label-Hub-Key: lh_...`
4. After all consumers migrated, the `claude-automation` scope downgrade is enforced
5. Recovery pathway documented — if all keys lost, `claude-automation` can still GET /readiness for diagnostics

The downgrade is implemented as a feature flag `settings.pangolin_bypass_scope_downgrade: bool = False` initially, flipped to `True` once migration confirmed. This avoids surprise breakage on the day of deploy.

## 8. Testing Strategy

| Layer | Test type | What it covers |
|---|---|---|
| Key creation | Unit | `generate_api_key()` produces `lh_pat_` infix + 256-bit entropy + valid bcrypt hash |
| bcrypt verify | Unit | Correct plaintext verifies; wrong plaintext rejects |
| LRU cache | Unit | After verify, subsequent calls return cached AuthContext within TTL; expires after TTL |
| Auth dependency | Integration | Valid key → AuthContext; invalid key → 401; missing key + no Pangolin → 401; missing key + Pangolin-bypass + read scope → AuthContext source=pangolin-bypass |
| Scope rejection | Integration | print-scope key on admin endpoint → 403 with scope-mismatch detail |
| Rate-limit | Integration | 61 requests/min → 61st returns 429 with retry-after |
| Printer ACL | Integration | Key with allowed_printer_ids=[A] used on printer B → 403 |
| Audit trail | Integration | POST /api/print with key X → Job row has api_key_id=X and source_ip set |
| UI CRUD | E2E Playwright | Create key (plaintext shown once) → revoke (key rejected on next use) |
| Transition (feature flag off) | Integration | claude-automation can still POST /api/print until flag flipped |
| Transition (feature flag on) | Integration | claude-automation POST /api/print → 401, GET /readiness still 200 |

Coverage target stays at `fail_under = 80`. The new auth module should reach >= 95% on the core middleware path.

## 9. Out-of-Scope

These are explicit non-goals for Phase 7c (deferred to later phases):

- **OAuth flow** — single-user HomeLab, no need for delegated auth
- **Per-user keys** — only one human user, scoping is per-application not per-person
- **Redis-backed rate limiter** — single-instance design
- **Webhook signature verification** beyond the existing webhook-API-key (orthogonal feature)
- **Key auto-rotation policy** — manual rotation in UI is fine
- **Hardware-backed (TPM/HSM) key storage** — overkill for HomeLab, file-based DB is acceptable
- **OpenAPI security scheme advertising the X-Label-Hub-Key** — Phase 7c.1 polish (oapi-codegen client will auto-detect once added)

## 10. Definition of Done

- [ ] Alembic migration creates `api_keys` + extends `jobs` table
- [ ] `ApiKey` model + repository implemented
- [ ] `generate_api_key()` + bcrypt verify + LRU cache implemented
- [ ] `require_scope(level)` FastAPI dependency implemented
- [ ] All existing routes annotated with `Depends(require_scope(...))`
- [ ] Rate limiter implemented with token-bucket per key
- [ ] `/admin/api-keys` HTMX UI (list + create + revoke + detail)
- [ ] Backend API for key CRUD under `/api/admin/api-keys/*`
- [ ] Pangolin-bypass scope-downgrade feature flag
- [ ] Bootstrap-admin seed key emitted in startup log on first migration
- [ ] All tests passing, coverage >= 80%
- [ ] `make oapi` regenerates the client with the new auth header + admin routes
- [ ] Doku in README + a new `docs/site/operations/api-keys.md` operator guide
- [ ] Refs #22 + Closes #78 in PR

## 11. Self-Review

- **Privacy:** spec uses RFC 5737 (192.0.2.x) and example.com placeholders consistently
- **Internal consistency:** scopes named identically everywhere (`read`/`print`/`admin`)
- **Backward compat:** existing routes get auth gracefully, old jobs survive (nullable cols)
- **Recovery:** Pangolin-bypass-as-read-only ensures the system is never bricked if all keys lost
- **Observability:** audit fields `api_key_id` + `source_ip` on Job make post-incident forensics trivial
