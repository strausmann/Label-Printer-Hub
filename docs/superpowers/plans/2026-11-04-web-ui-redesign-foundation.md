# Web UI Redesign: Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Go/HTMX frontend with a React + TypeScript single-page app served by the FastAPI backend, add the backend pieces it needs (settings store with env locks and encrypted secrets, browser sessions with CSRF, bootstrap key, JSON event stream, `/api/info`), and ship it as one container.

**Architecture:** The backend gains a runtime settings store, a session/CSRF layer inside the existing `require_scope` dependency, a JSON SSE stream and a static/SPA mount. The new app lives in `frontend/` (Vite build → `frontend/dist`), is copied into the backend image and served at `/`. The Go module, its image, its CI jobs and the HTML-fragment SSE endpoint are removed.

**Tech Stack:** Python 3.12, FastAPI, SQLModel/aiosqlite, Alembic, `cryptography` (AES-GCM); Node 22 + pnpm, TypeScript strict, Vite, React 19, TanStack Router + Query, React Aria Components, Tailwind CSS v4, Lingui, `openapi-typescript`, Vitest + Testing Library, Playwright, `vite-plugin-pwa`.

**Spec:** `docs/superpowers/specs/2026-11-03-web-ui-redesign-design.md` (approved 2026-11-04). Read it before any task; where this plan and the spec disagree, stop and ask.

## Global Constraints

- MIT project. Nothing copied from Kept (AGPL-3.0): no files, token values, components. Every new dependency's licence is checked and listed in the PR description.
- Public repo: English prose everywhere; no private IPs, hostnames, domains, tokens in code, fixtures, docs or screenshots (`docs/policies/privacy.md`). Use `example.invalid`, `192.0.2.0/24`.
- Conventional Commits; the release commit is `feat!` (major). No AI attribution trailers. Author `bjoern@strausmann.net`.
- TDD: every task writes the failing test first. Backend gates: `ruff check .`, `ruff format --check .`, `mypy app/` (strict), `pytest -m "not slow" --cov=app --cov-fail-under=80`, `alembic upgrade head && alembic check`. Frontend gates (added in Task 8): `pnpm typecheck`, `pnpm lint`, `pnpm test --coverage` (lines/functions/branches ≥ 70), `pnpm e2e`.
- Every new route either uses `require_read/print/admin` or is added to `_PUBLIC_BY_DESIGN` in `backend/tests/unit/api/test_route_auth_coverage_guardrail.py` with a one-line reason.
- Token values exactly as spec §5.2 — note `ink-500` is `#6B655A` (changed 2026-11-04 for AA contrast) — (paper/ink/amber/stamp/green/orange/red primitives, semantic light/dark roles, tape colours). State = shape + word; `warn` uses a diamond. Radii 6/10/14, 4 px grid, focus ring `link` 3 px. Type scale title 28/700, section 20/700, body 15/400, small 13/400, code 15/600. Atkinson Hyperlegible + Atkinson Hyperlegible Mono, self-hosted.
- English is the default language of a fresh install; German ships from the start.
- Env always wins over a UI setting; a locked field is shown read-only with the hint "Set by the container".
- Secrets are write-only: no API response ever contains a stored secret value.
- Accessibility: keyboard reachable, visible focus, WCAG AA contrast in both themes, no colour-only state.
- New test directories get an `__init__.py` like the existing ones. Commit scopes used here (`config`, `settings`, `auth`, `events`, `web`, `decisions`, `api`, `integrations`) are added to `scope-enum` in `commitlint.config.cjs` in Task 1.
- Proxy headers are trusted only together with the SSO trust token; the legacy `X-Pangolin-User` header and the Basic bypass are opt-in (maintainer decision 2026-11-04, supersedes ADR 0014).
- Label every decision this work introduces with a `D<n>` from `docs/decisions/register.md` (Task 15) in the code comment where the code follows it.

## Review Focus

1. **Env var set after a value was stored in the UI** — the env value wins at runtime, the stored value is kept but shown as overridden; `PUT` on a locked key returns 409 `setting_locked`. (Task 2)
2. **`PRINTER_HUB_SECRET_KEY` changed or wrong** — stored secrets become undecryptable; the hub still starts, the affected settings report `state: "undecryptable"`, the integration is treated as unconfigured, the UI asks to re-enter the value. Missing key on startup → exit 78 with a message naming the variable. (Tasks 1, 2)
3. **API key revoked while its browser session is open** — the next request with that session cookie gets 401 and the event stream closes within one heartbeat. (Task 4, 6)
4. **A printer added after the event stream was opened** — its events still reach the UI (stream receives `hub.printers_changed`, client re-opens). (Task 6, 10)
5. **A request that carries only proxy headers (no trust token)** behind a proxy that does not strip them — no admin, no session; 401. (Task 4)
6. **Browser navigation or refresh on a client route that shares a path with a legacy JSON route** (`/jobs/{id}`) — a browser (`Accept: text/html`) gets the app, an API client gets JSON as before. (Task 7)

---

## File map

Backend (new unless marked):
- `backend/app/config.py` (modify) — remove `printers_config`; add `secret_key`, `public_url`, `bootstrap_admin_key`, `web_dist_dir`, `paperless_url/_token/_timeout`, `trust_legacy_pangolin_user`, `trust_pangolin_basic_bypass`.
- `backend/app/security/secret_box.py` — AES-GCM envelope.
- `backend/app/models/app_setting.py`, `backend/app/models/ui_session.py` + one Alembic revision.
- `backend/app/settings_store/registry.py` — setting definitions; `backend/app/settings_store/store.py` — runtime store.
- `backend/app/api/routes/settings_api.py` — `/api/v1/settings`.
- `backend/app/auth/sessions.py`, `backend/app/auth/csrf.py`; `backend/app/auth/dependencies.py` (modify).
- `backend/app/api/routes/auth_session.py` — `/api/v1/auth/session`.
- `backend/app/cli.py` — `printer-hub` command.
- `backend/app/api/routes/events_v1.py` — JSON stream; `backend/app/api/routes/events.py` (delete in Task 7).
- `backend/app/api/routes/info.py` — `/api/info`.
- `backend/app/web/spa.py` — static mount and SPA fallback.
- `backend/Dockerfile` (modify), `backend/.env.example` (rewrite).

Frontend (`frontend/` is emptied of Go and becomes the app):
- `frontend/package.json`, `pnpm-lock.yaml`, `vite.config.ts`, `tsconfig.json`, `eslint.config.js`, `playwright.config.ts`, `.nvmrc` (`22`).
- `frontend/src/design/tokens.css`, `frontend/src/design/fonts.css`.
- `frontend/src/api/schema.gen.ts` (generated), `frontend/src/api/client.ts`, `frontend/src/api/events.ts`.
- `frontend/src/i18n/` (`en`, `de` catalogues).
- `frontend/src/shell/` (AppShell, Sidebar, TabBar, TopBar, StatusBadge, SignIn, features).
- `frontend/src/features/{overview,printers,jobs,lookup,settings,scan,search}/`.
- `frontend/e2e/*.spec.ts`.

Docs / ops: `docs/decisions/0015…0019-*.md`, `docs/decisions/register.md`, `docs/decisions/0007-*.md` (modify), `docs/architecture.md`, `docs/architecture/sse.md`, `examples/compose.*.yml`, `.github/workflows/{ci,docker-publish}.yml`, `docs/migration/v-next-single-container.md`.

---

### Task 1: Settings clean-up, new env fields, secret box

**Files:**
- Modify: `backend/app/config.py` (fields at 60–127), `backend/app/main.py` (startup messages mentioning `printers.yaml`), `backend/.env.example`, `examples/.env.example` (lines 27–33), `backend/tests/conftest.py`, `backend/tests/unit/test_startup_error.py` (`_run_import`), `backend/tests/**/test_config.py` and `test_config_printer.py` (drop `printers_config` assertions), `.github/workflows/ci.yml` (python job env), `commitlint.config.cjs`
- Delete: `backend/app/seed/printers.yaml.example`
- Create: `backend/app/security/__init__.py`, `backend/app/security/secret_box.py`
- Test: `backend/tests/unit/test_config_env_fields.py`, `backend/tests/unit/security/test_secret_box.py`, `backend/tests/unit/test_env_example_matches_settings.py`

**Interfaces:**
- Produces: `Settings.secret_key: SecretStr` (required; base64url of exactly 32 bytes), `Settings.public_url: AnyHttpUrl` (required), `Settings.bootstrap_admin_key: SecretStr = SecretStr("")` (empty or ≥ 32 chars), `Settings.web_dist_dir: Path = Path("/opt/app/web")`, `Settings.paperless_url: str = ""`, `Settings.paperless_token: SecretStr = SecretStr("")`, `Settings.paperless_timeout: float = 5.0`.
- Produces: `class SecretBox: __init__(self, key: bytes)`, `seal(self, plaintext: str, *, aad: str) -> str`, `open(self, token: str, *, aad: str) -> str`; `class UndecryptableSecret(Exception)`; `def secret_box_from_settings(settings: Settings) -> SecretBox`.

- [ ] **Step 1: Write failing tests**
  - `test_printers_config_field_removed`: `"printers_config" not in Settings.model_fields`.
  - `test_secret_key_required`: constructing `Settings` without `PRINTER_HUB_SECRET_KEY` raises `ValidationError` naming `secret_key`.
  - `test_secret_key_must_decode_to_32_bytes`: a 16-byte base64url value raises.
  - `test_bootstrap_key_short_rejected`: 10 chars raises; empty passes.
  - `test_seal_open_roundtrip`: `open(seal("t0k", aad="integrations.snipeit.api_key"), aad=same) == "t0k"`; token starts with `"v1."`.
  - `test_open_with_other_aad_fails`: different `aad` → `UndecryptableSecret`.
  - `test_open_with_other_key_fails`: second `SecretBox` with another key → `UndecryptableSecret`.
  - `test_seal_is_randomised`: two seals of the same value differ.
  - `test_env_example_matches_settings`: parse every `PRINTER_HUB_*=` line in `backend/.env.example`; each name maps to a `Settings` field (extra="forbid" guard), and `SECRET_KEY`, `PUBLIC_URL` are present.
- [ ] **Step 2: Run** `cd backend && pytest tests/unit/test_config_env_fields.py tests/unit/security tests/unit/test_env_example_matches_settings.py -v` → FAIL.
- [ ] **Step 3: Implement.** `SecretBox` uses `cryptography.hazmat.primitives.ciphers.aead.AESGCM`, 12-byte random nonce, token format `v1.<b64url nonce>.<b64url ciphertext>`, `aad.encode()` as associated data (spec §10: per-record AAD = the setting key). Add `cryptography` to `pyproject.toml` dependencies (Apache-2.0/BSD, list in PR). Rewrite `.env.example` grouped "Required" / "Security" / "Optional (locks the UI field)" with placeholders `CHANGE_ME`; drop `PT750W_HOST`, `QL820_HOST`, `PRINTER_BACKEND`, `PRINTER_MODEL`, `PRINTER_DISCOVER_VIA_SNMP`, `PRINTERS_CONFIG`. In `main.py`'s early validation (lines ~30–67) the exit-78 message lists missing required variables by env name. `app/main.py:45–48` and `app/db/engine.py:17` call `get_settings()` at import time, so a fixture is too late: set `os.environ.setdefault("PRINTER_HUB_SECRET_KEY", <fixed test key>)` and `os.environ.setdefault("PRINTER_HUB_PUBLIC_URL", "http://localhost:8000")` at the top of `backend/tests/conftest.py`, add both to the CI python job's `env:`, and pass both in `test_startup_error.py::_run_import` so "short key exits 78" fails for its own reason.
- [ ] **Step 4: Run** the three test files → PASS; then the full backend suite → PASS.
- [ ] **Step 5: Counter-test** — pass `None` as associated data in both `seal` and `open`: `test_open_with_other_aad_fails` must go red. Restore.
- [ ] **Step 6: Commit** `refactor(config)!: drop printers_config, add secret key, public URL and bootstrap key`

---

### Task 2: Runtime settings store and settings API

**Files:**
- Create: `backend/app/models/app_setting.py`, `backend/app/models/ui_session.py` (model only; behaviour in Task 4, so `alembic check` stays clean), `backend/alembic/versions/2026_11_04_0001-20261104a1_app_settings_ui_sessions.py` (both tables of Tasks 2 and 4, down_revision `42fbd015698d`), `backend/app/settings_store/{__init__,registry,store}.py`, `backend/app/api/routes/settings_api.py`, `backend/app/schemas/settings_api.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/main.py` (lifespan: `app.state.settings_store`; include router)
- Test: `backend/tests/unit/settings_store/test_store.py`, `backend/tests/integration/api/test_settings_api.py`

**Interfaces:**
- Produces model `AppSetting(SQLModel, table=True)`, table `app_settings`: `key: str` (PK), `value_json: str | None`, `secret_token: str | None`, `updated_at: datetime`.
- Produces model `UiSession` (table `ui_sessions`, fields listed in Task 4 incl. `allowed_printer_ids`) — model file and migration both in this task.
- Produces `@dataclass(frozen=True) class SettingDef: key: str; kind: Literal["str","int","float","bool","url","secret","enum"]; default: Any; env_field: str | None; choices: tuple[str, ...] = ()`. `SETTINGS: dict[str, SettingDef]` with exactly these keys: `general.display_name` ("Label Printer Hub"), `general.language` (enum `en`,`de`; default `en`), `general.time_zone` ("UTC"), `general.public_url` (url, env `public_url`, always locked — shown read-only), `integrations.snipeit.url|api_key|timeout` (env `snipeit_url|snipeit_api_key|snipeit_timeout`), `integrations.grocy.url|api_key|timeout`, `integrations.spoolman.url|timeout`, `integrations.paperless.url|token|timeout`, `access.webhook_api_key` (env `webhook_api_key`), `jobs.retention_days` (env `job_retention_days`, 30). (Planner's call, D-label in Task 15: the spec's "default part size" belongs to the #149 module and is added there; "half cut by default" already exists per printer as `cut_defaults` and is edited in Settings › Printers — no global duplicate.)
- Produces `class SettingsStore`: `async load(self, session: AsyncSession) -> None`; `get(self, key: str) -> Any` (effective value: env if locked, else stored, else default; secrets return the plaintext only inside the process); `describe(self) -> list[SettingView]`; `async set_many(self, session: AsyncSession, values: dict[str, Any]) -> None`; `is_locked(self, key: str) -> bool`; `subscribe(self, callback: Callable[[set[str]], None]) -> None` (called with changed keys after `set_many`).
- Produces schema `SettingView(BaseModel)`: `key, kind, value: Any | None` (always `None` for secrets), `is_set: bool`, `locked: bool`, `state: Literal["ok","undecryptable"]`, `choices: list[str]`.
- Produces routes (admin scope): `GET /api/v1/settings -> list[SettingView]`; `PUT /api/v1/settings` body `{"values": {key: value}}` → 200 `list[SettingView]`; 409 `setting_locked` if any key is locked (nothing written); 422 on unknown key or wrong type; a secret value of `""` clears it.
- Produces `GET /api/v1/settings/export` (admin) → non-secret settings as JSON download.
- Rule: a secret is sent only to the URL it was saved with; changing an integration's URL requires re-entering its secret in the same request.
- Produces `POST /api/v1/settings/integrations/{name}/test` (admin), `name ∈ {snipeit,grocy,spoolman,paperless}`, body = unsaved form values for that integration merged over effective values → `{"ok": bool, "status": int | None, "detail": str}`; never echoes the token.

- [ ] **Step 1: Write failing tests**
  - `test_locked_when_env_set`: `monkeypatch.setenv("PRINTER_HUB_SNIPEIT_URL", "https://snipeit.example.invalid")`, `get_settings.cache_clear()` → `is_locked("integrations.snipeit.url")` and `get(...)` returns the env value even after `set_many` stored another value. Locked = the `env_field` is in `get_settings().model_fields_set` **and** its value is not empty (`${VAR:-}` in compose must not lock a field to empty); add `test_empty_env_value_does_not_lock`.
  - `test_put_locked_key_returns_409_and_writes_nothing`.
  - `test_secret_never_returned`: after `PUT` of `integrations.grocy.api_key`, `GET` shows `value is None`, `is_set is True`; the raw response text does not contain the secret.
  - `test_secret_stored_encrypted`: the `app_settings.secret_token` column does not contain the plaintext and starts with `v1.`.
  - `test_undecryptable_secret_reported`: store with key A, reload store with key B → `state == "undecryptable"`, `get()` returns the default `""`, app still answers `GET /healthz` 200.
  - `test_unknown_key_422`, `test_wrong_type_422` (`jobs.retention_days: "x"`).
  - `test_subscribe_called_with_changed_keys`.
  - `test_integration_test_uses_unsaved_values`: respx mock on `https://grocy.example.invalid/api/system/info` → 200; body carries that URL; result `ok: true`; mock 401 → `ok: false, status: 401`; `httpx.ConnectError` → `ok: false, status: None`; response text never contains the token.
  - `test_settings_routes_require_admin`: print-scope key → 403.
  - `test_changing_url_requires_secret`: stored Grocy URL A + token; `PUT` or test-connection with URL B and no token → 422 `secret_required_for_new_url`; nothing sent to B (respx asserts no call). Same URL without token → stored token is used.
  - `test_url_with_userinfo_rejected`: `https://u:p@grocy.example.invalid` → 422.
  - `test_validation_error_never_echoes_secret`: wrong type for a secret key → 422 body has no `input` field containing the value.
  - `test_settings_export_has_no_secrets`: `GET /api/v1/settings/export` (admin) returns JSON `{key: value}` of non-secret, non-locked settings only.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the model, migration, registry, store and routes. Test-connection probes: Snipe-IT `GET {url}/api/v1/hardware?limit=1` (Bearer), Grocy `GET {url}/api/system/info` (`GROCY-API-KEY`), Spoolman `GET {url}/api/v1/info`, Paperless `GET {url}/api/` (`Authorization: Token …`); timeout from the form or effective value.
- [ ] **Step 4: Run** tests → PASS; `alembic upgrade head && alembic check` → clean.
- [ ] **Step 5: Counter-test** — make `is_locked` always return `False`: `test_locked_when_env_set` and the 409 test go red. Restore.
- [ ] **Step 6: Commit** `feat(settings): runtime settings store with env locks and encrypted secrets`

---

### Task 3: Integrations read the runtime store

**Files:**
- Modify: `backend/app/integrations/{snipeit,grocy,spoolman}/plugin.py` (constructors at 58–65 / 35–42 / 37–43), `backend/app/integrations/base.py` (protocol gains `bind` and `is_configured`), `backend/app/integrations/README.md`, `backend/app/main.py` (bind the store after discovery; retention from the store), `backend/app/api/dependencies/webhook_auth.py:56` (read `access.webhook_api_key` from the store), `backend/tests/**/test_webhook_auth.py` (it overrides `get_settings`)
- Test: `backend/tests/unit/integrations/test_live_settings.py`

**Interfaces:**
- Consumes: `SettingsStore.get`, `SettingsStore.subscribe` (Task 2).
- Produces: plugins keep their no-argument constructor (discovery calls `plugin_cls()` at `integrations/__init__.py:46`); new `bind(self, store: SettingsStore) -> None`, called in lifespan after `load()`; `async reconfigure(self) -> None` closes and recreates its `httpx.AsyncClient` from current store values; `is_configured(self) -> bool` added to the protocol in `base.py` (URL non-empty and, where needed, key set and decryptable). Before `bind`, `is_configured()` is `False`.
- Produces: `CleanupTask` reads `jobs.retention_days` from the store on each run instead of once at `main.py:324`.

- [ ] **Step 1: Failing tests:** `test_retention_change_applies_on_next_cleanup_run`, `test_discovery_still_constructs_without_args` (existing `test_discovery.py`/`test_registry.py` stay green), `test_url_change_applies_without_restart` (respx: lookup goes to host A, `set_many` URL B, next lookup goes to B); `test_unconfigured_lookup_returns_503_problem` (`GET /api/lookup/grocy/1` with empty URL → 503 `integration_not_configured`); `test_webhook_key_from_store` (store value accepted, wrong value 401, empty → 503 as today).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** The store callback schedules `reconfigure()` for plugins whose keys changed (prefix `integrations.<name>.`).
- [ ] **Step 4: Run** → PASS; full suite → PASS.
- [ ] **Step 5: Counter-test** — remove the subscribe call: `test_url_change_applies_without_restart` goes red. Restore.
- [ ] **Step 6: Commit** `feat(integrations): apply settings changes without restart`

---

### Task 4: Browser sessions, CSRF, bootstrap key, recovery CLI

**Files:**
- Create: `backend/app/models/ui_session.py`, `backend/app/auth/sessions.py`, `backend/app/auth/csrf.py`, `backend/app/api/routes/auth_session.py`, `backend/app/cli.py`
- Modify: `backend/app/auth/dependencies.py` (`AuthContext` at 73, `_has_pangolin_sso_session` at 97/124, `require_scope` at 286), `backend/app/repositories/api_keys.py` (`revoke` at 48 also revokes sessions), `backend/pyproject.toml` (`[project.scripts]`)
- Test: `backend/tests/integration/api/test_auth_session.py`, `backend/tests/unit/auth/test_csrf.py`, `backend/tests/unit/test_cli.py`

**Interfaces:**
- Consumes: the `UiSession` model and table from Task 2.
- Produces settings `trust_legacy_pangolin_user: bool = False`, `trust_pangolin_basic_bypass: bool = False`; `pangolin_bypass_scope_downgrade` becomes effective (bypass gets `read` when true).
- `UiSession` fields: `id: UUID` PK, `token_hash: str` (sha256 hex, unique index), `csrf_token: str`, `source: Literal["api-key","pangolin-sso","bootstrap"]`, `scope: Literal["read","print","admin"]`, `api_key_id: UUID | None` (FK `api_keys.id`), `allowed_printer_ids: list[str]` (JSON, copied from the key), `user: str | None`, `created_at`, `expires_at` (created + 12 h, absolute), `revoked_at: datetime | None`.
- Produces `AuthContext.source` gains `"session"` and `"bootstrap"`; new field `user: str | None = None`; new field `session_id: UUID | None = None`.
- Produces cookies: when `public_url` is `https`, `__Host-lph_session` (HttpOnly, Secure, SameSite=Strict, Path=/) and `__Host-lph_csrf` (same, not HttpOnly); when `http`, `lph_session`/`lph_csrf` without `Secure` and one startup warning ("cookies are sent unencrypted"). Header `X-CSRF-Token`.
- Produces routes:
  - `POST /api/v1/auth/session` body `{"key": str}` (public by design: it is the sign-in). Key with `print` or `admin` scope → 204 + cookies; `read`-only key → 403 `scope_too_low`; invalid → 401. The bootstrap key is accepted only while `api_keys` has no enabled, unexpired key with `admin` scope → session `source="bootstrap"`, scope admin.
  - `GET /api/v1/auth/session` (public by design) → `{"signed_in": bool, "scope": …, "source": …, "user": …, "bootstrap": bool, "csrf_token": str | None}`; when valid SSO headers are present and no valid session cookie exists, it creates a `pangolin-sso` session (scope admin, `user` from `sso_user_header`) and sets the cookies.
  - `DELETE /api/v1/auth/session` → 204, session revoked, cookies cleared.
- Produces trust rules (spec §8.2): SSO headers count only with `sso_user_header` **and** `hmac.compare_digest(trust_header, sso_trust_token)` with a non-empty token; legacy `X-Pangolin-User` only if `trust_legacy_pangolin_user`; Basic bypass only if `trust_pangolin_basic_bypass`. Only the trust-token path may mint a session.
- Produces `require_scope` order: API key header → session cookie → SSO headers → bypass → 401. Every session use re-checks: not revoked, not expired, linked key still enabled and unexpired, and for `bootstrap` sessions that still no admin key exists. `check_printer_access` applies `allowed_printer_ids` to sessions too.
- State-changing requests authenticated by SSO headers (no session) require an `Origin` header equal to the origin of `public_url`, else 403 `origin_mismatch`.
- Sign-in route is rate limited per client IP (10 per minute, 429 with `Retry-After`, a new IP-keyed bucket next to `_rate_limiter`, which is keyed by API-key id and can't be reused as is). At most 20 active sessions per user/key; creating one more revokes the oldest. `CleanupTask` purges sessions expired > 1 day. Session path enforces CSRF for `POST/PUT/PATCH/DELETE` via `csrf.verify(request, session) -> None` (`hmac.compare_digest`, 403 `csrf_failed`). Bootstrap sessions are rejected (403 `bootstrap_only`) on every route except `POST /api/admin/api-keys` and `GET|DELETE /api/v1/auth/session`.
- Produces CLI: `printer-hub admin create-key --scope {read,print,admin} --name TEXT` prints the plaintext key once on stdout, exit 0; `def main(argv: list[str] | None = None) -> int`.
- Also: replace the `==` trust-token comparison at `dependencies.py:124` with `hmac.compare_digest`; the bootstrap key comparison uses `hmac.compare_digest` too.

- [ ] **Step 1: Failing tests**
  - `test_sign_in_with_print_key_sets_cookies` (default test `public_url` is `http://localhost:8000`): response has both cookies; `lph_session` has `HttpOnly` and `SameSite=Strict`.
  - `test_secure_flag_off_only_on_localhost`: `public_url=https://hub.example.invalid` → `Secure` present.
  - `test_read_key_cannot_sign_in` → 403.
  - `test_session_cookie_authenticates_get` (`GET /api/printers` 200 with cookie only).
  - `test_post_without_csrf_header_403` and `test_post_with_csrf_header_ok` (`POST /api/printers/{id}/pause`).
  - `test_api_key_header_post_needs_no_csrf`.
  - `test_revoking_key_revokes_its_sessions` → next cookie request 401.
  - `test_expired_session_401` (freeze time +12 h 1 s).
  - `test_bootstrap_only_until_admin_key_exists`: bootstrap sign-in 204; `GET /api/printers` 403 `bootstrap_only`; `POST /api/admin/api-keys` 201; after that a new bootstrap sign-in → 401.
  - `test_sso_get_session_creates_cookie` with trust token and `Remote-User: alice` → `user == "alice"`.
  - `test_sso_wrong_trust_token_no_session`.
  - `test_legacy_pangolin_user_header_rejected_by_default` and `test_basic_bypass_rejected_by_default` → 401; each accepted with its opt-in flag; `test_bypass_downgraded_to_read_when_flag_set`.
  - `test_disabled_key_kills_session` (`PATCH enabled=false`) and `test_expired_key_kills_session`.
  - `test_bootstrap_session_dies_when_admin_key_exists` (session created before the key, used after → 401).
  - `test_session_keeps_printer_restriction`: key restricted to printer A → session gets 403 on printer B.
  - `test_sso_header_post_without_origin_403`.
  - `test_sign_in_rate_limited` (11th attempt in a minute → 429).
  - `test_http_public_url_cookies_without_secure` and `test_https_uses_host_prefix`.
  - `test_cli_create_key_prints_once_and_key_works`.
  - Update `_PUBLIC_BY_DESIGN` with the two `/api/v1/auth/session` methods and reasons.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** The session token is `secrets.token_urlsafe(32)`; only its sha256 is stored. `api_keys_repo.revoke` sets `revoked_at` on sessions with that `api_key_id` in the same transaction.
- [ ] **Step 4: Run** → PASS; guardrail test → PASS.
- [ ] **Step 5: Counter-tests** — (a) skip `csrf.verify`: `test_post_without_csrf_header_403` goes red; (b) drop the "no admin key exists" check: the bootstrap test goes red; (c) default `trust_legacy_pangolin_user` to `True`: the default-rejection test goes red. Restore all.
- [ ] **Step 6: Commit** `feat(auth)!: trust proxy headers only with the trust token; browser sessions with CSRF, bootstrap key and recovery command`

---

### Task 5: `GET /api/info` with feature flags

**Files:**
- Create: `backend/app/api/routes/info.py`, `backend/app/schemas/info.py`
- Modify: `backend/app/main.py` (include router)
- Test: `backend/tests/integration/api/test_info.py`

**Interfaces:**
- Produces `GET /api/info` (public by design: the shell and the sign-in screen need it before sign-in) → `Info`: `version, revision, build_date` (from the `Healthz` sources, `main.py:125–130`), `default_language: Literal["en","de"]` (store `general.language`), `display_name: str`, `auth: {"sso_configured": bool, "bootstrap_open": bool}`, `features: dict[str, bool]` with exactly the keys `jobs`, `lookup`, `scan`, `parts`, `sheets`, `calibration`, `asn`, `kept` — the first three `true`, the rest `false` until their modules ship.
- Produces constant `FEATURES` in `backend/app/api/routes/info.py` that later modules flip.
- Produces `backend/app/observability/log_buffer.py`: a logging handler keeping the last 500 records of level ≥ WARNING in memory; `GET /api/v1/system/logs?limit=200` (admin) → `[{ts, level, logger, message}]`.

- [ ] **Step 1: Failing tests:** `test_system_logs_admin_only_and_capped`, `test_info_shape` (exact key sets), `test_bootstrap_open_reflects_admin_keys`, `test_info_never_contains_secrets` (with all secret settings set, response text contains none of them), guardrail entry.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Counter-test** — hard-code `bootstrap_open: True`: the reflect test goes red. Restore.
- [ ] **Step 6: Commit** `feat(api): add /api/info with feature flags`

---

### Task 6: Global JSON event stream

**Files:**
- Create: `backend/app/api/routes/events_v1.py`, `backend/app/services/sse_snapshot.py` (move `_build_initial_snapshot` from `events.py:126`, returning dicts), `backend/app/observability/sse_metrics.py` (move the Prometheus objects from `events.py:51–76`; `events.py` imports them until Task 7 deletes it)
- Modify: `backend/app/api/routes/admin_printers_api.py` (publish `hub.printers_changed` via `request.app.state.event_bus` after create/update/disable/enable — the service module stays DB-only), `backend/app/main.py`, `docs/architecture/sse.md`
- Test: `backend/tests/integration/api/test_events_v1.py`

**Interfaces:**
- Consumes: `EventBus.subscribe/unsubscribe/next_event_id` (`backend/app/services/event_bus.py:84–106`), `BusEvent`.
- Produces `GET /api/v1/events?printer_id=<uuid>` (optional; `require_read`, so a session cookie works). Subscribes to `hub` plus `printer:{id}:{queue,state,tape}` of every enabled printer (or only the given one). Frames: `: connected`, then an initial snapshot per printer (reuse the data of `_build_initial_snapshot`, `events.py:126`, as JSON), then `id: N\nevent: <event_type>\ndata: <json>\n\n` where json is `{"channel": str, "printer_id": str | null, "type": str, "ts": ISO-8601, "data": {...}}`, keep-alive comment every `sse_heartbeat_s`. Same subscriber cap/429 as today.
- Produces event `hub.printers_changed` on channel `hub` with `data: {"printer_id": str, "change": "created"|"updated"|"disabled"|"enabled"}`.
- On each heartbeat the stream re-checks its session/key in a short-lived DB session (`async with async_session()`, not one held for the stream's lifetime); if no longer valid it sends `event: auth.expired` and closes. Printers outside the caller's `allowed_printer_ids` are never subscribed.

- [ ] **Step 1: Failing tests:** `test_stream_requires_auth` (401 without credentials), `test_stream_json_frames` (publish a `job.state_changed` on a printer channel → `json.loads(data)["type"] == "job.state_changed"`), `test_stream_without_printer_filter_gets_all_printers`, `test_printer_created_emits_hub_event`, `test_revoked_session_gets_auth_expired` (heartbeat set to 0.05 s via settings override), `test_restricted_key_stream_excludes_other_printers`, `test_subscriber_cap_429`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Counter-test** — drop the `hub` subscription: `test_printer_created_emits_hub_event` goes red. Restore.
- [ ] **Step 6: Commit** `feat(events): global JSON event stream for the web UI`

---

### Task 7: Serve the app from the backend; remove the Go frontend and HTML fragments

**Files:**
- Create: `backend/app/web/__init__.py`, `backend/app/web/spa.py`
- Modify: `backend/app/main.py` (mount after all routers; remove the `/static` mount at 717–719), `backend/app/api/routes/print.py` (`GET /jobs/{job_id}` at 109), `backend/app/api/routes/qr.py`, `backend/Dockerfile`, `.github/workflows/ci.yml` (remove jobs `go` and `oapi-codegen-drift`), `.github/workflows/docker-publish.yml` (matrix `service: [backend]` only)
- Delete: `frontend/` (Go module), `backend/app/api/routes/events.py`, `backend/app/templates/fragments/`, `backend/app/templates/qr/`, `backend/app/static/`, and the tests of removed code: `backend/tests/unit/api/test_events_route.py`, `backend/tests/integration/test_phase6b_sse*.py`, `backend/tests/**/test_sse_flush.py`, `backend/tests/unit/test_job_state_fragment.py`; port anything they cover that still exists (event bus, producers) to `test_events_v1.py`
- Modify also: `backend/tests/api/test_openapi_completeness.py` (drop the `/api/events` checks at lines 20 and 261; raise `test_endpoint_count_in_range` upper bound from 45 to 60), `backend/pyproject.toml` (drop `jinja2` if nothing else imports it — check with `grep -rn jinja2 backend/app`), `.github/workflows/docker-publish.yml:190–191` (`context: .`, `file: backend/Dockerfile`), the CI `docker-build` job (build `docker build -f backend/Dockerfile .` instead of checking for a root `Dockerfile`)
- Test: `backend/tests/integration/api/test_spa_serving.py`

**Interfaces:**
- Produces `def mount_spa(app: FastAPI, dist_dir: Path) -> None`. Serves `dist_dir/assets/*` with `Cache-Control: public, max-age=31536000, immutable`, `index.html` with `no-cache`. For any `GET` not matched by a route and not under `/api/`, `/docs`, `/redoc`, `/openapi.json`: return `index.html` (200). Unknown `/api/...` stays a JSON 404. If `dist_dir/index.html` is missing, log one warning and mount nothing (API-only mode; tests and `compose.backend-only.yml` keep working).
- Produces content negotiation in legacy `GET /jobs/{job_id}`: if the SPA is mounted and `Accept` contains `text/html`, return `index.html`; otherwise JSON as today.
- Produces QR paths `/loc/{id}`, `/asset/{id}`, `/spool/{id}`, `/product/{id}` returning `index.html` (the app renders the item view, Task 12); they stay in `_PUBLIC_BY_DESIGN`. `/api/events` is removed from that list.
- Produces `add_security_headers(app)`: responses served by the SPA mount get `Content-Security-Policy: default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; img-src 'self' data: blob:; connect-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'`, `Permissions-Policy: camera=(self)`; every response gets `X-Content-Type-Options: nosniff` and `Referrer-Policy: same-origin`. `/docs` and `/redoc` keep working (no CSP there).
- Produces backend image: a `web-builder` stage (`node:22-bookworm-slim`, `corepack enable`, `pnpm install --frozen-lockfile`, `pnpm build`) whose `frontend/dist` is copied to `/opt/app/web`; the Docker build context becomes the repo root (`docker build -f backend/Dockerfile .`).

- [ ] **Step 1: Failing tests** (with a temporary `dist` fixture holding `index.html` and `assets/app.js`): `test_root_serves_index`, `test_client_route_falls_back_to_index` (`/printers/abc`), `test_unknown_api_path_is_json_404`, `test_assets_are_immutable`, `test_legacy_job_route_html_for_browser_json_for_client`, `test_qr_paths_serve_app` (all four), `test_no_dist_means_api_only`, `test_spa_has_csp_docs_has_none`, `test_old_fragment_stream_gone` (`GET /api/events?printer_id=…` → 404).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**, delete the listed paths, update CI and the image workflow.
- [ ] **Step 4: Run** the backend suite → PASS; `docker build -f backend/Dockerfile .` succeeds. Until Task 8 creates the app, the runtime stage copies from a stub stage (`FROM scratch AS web-stub` with an empty `/dist`), chosen by `ARG WEB_SOURCE=web-stub` and `FROM ${WEB_SOURCE} AS web`; Task 8 switches the default to `web-builder`.
- [ ] **Step 5: Counter-test** — register the fallback before the routers: `test_unknown_api_path_is_json_404` or the API tests go red. Restore.
- [ ] **Step 6: Commit** `feat!: serve the web UI from the backend and remove the Go frontend`

---

### Task 8: Frontend scaffold — tooling, tokens, fonts, i18n, API client

**Files:**
- Create: everything under `frontend/` listed in the file map except features; `backend/scripts/export_openapi.py`; CI job `web` in `.github/workflows/ci.yml`
- Test: `frontend/src/design/tokens.test.ts`, `frontend/src/api/client.test.ts`, `frontend/src/i18n/catalog.test.ts`

**Interfaces:**
- Produces `frontend/src/design/tokens.css`: CSS custom properties `--paper-50 … --red-600`, semantic `--bg --surface --sunken --line --line-strong --ink --ink-2 --ink-3 --accent --accent-ink --accent-soft --link --ok --warn --bad`, tape `--tape-white --tape-yellow --tape-green --tape-blue --tape-red`, radii `--r-1:6px --r-2:10px --r-3:14px`; light under `:root`, dark under `[data-theme="dark"]` and `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) }`. Tailwind v4 `@theme` maps them to utilities. Values verbatim from spec §5.2.
- Produces `frontend/src/design/tokens.ts`: the same values as a typed object (single source for the contrast test; a test asserts CSS and TS agree).
- Produces `frontend/src/api/schema.gen.ts` generated by `pnpm gen:api` (= `python backend/scripts/export_openapi.py > frontend/openapi.json && openapi-typescript frontend/openapi.json -o src/api/schema.gen.ts`).
- Produces `frontend/src/api/client.ts`: `apiFetch<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T>` — `credentials: "same-origin"`, adds `X-CSRF-Token` from the session state for non-GET, throws `ApiError { status: number; code: string | null; detail: string }` parsed from the backend problem body; on 401 calls the registered `onUnauthorized()`.
- Produces `frontend/src/i18n/index.ts`: `initI18n(lang: "en" | "de")`, catalogues `src/i18n/locales/{en,de}/messages.po`; language order: user choice in `localStorage` (`lph.lang`, wrapped in try/catch) → `/api/info.default_language` → `en`.
- Fonts: `@fontsource/atkinson-hyperlegible` and `@fontsource/atkinson-hyperlegible-mono` (OFL-1.1, verify), imported in `fonts.css`; no external font URL anywhere (`test_no_external_font_urls` greps the built `dist`).
- Scripts: `dev`, `build` (runs `i18n:compile` first), `typecheck` (`tsc -b`), `lint` (ESLint + typescript-eslint + jsx-a11y), `test` (Vitest jsdom), `e2e` (Playwright), `gen:api`, `i18n:extract`, `i18n:compile`.

- [ ] **Step 1: Failing tests**
  - `tokens.test.ts › every text role meets WCAG AA on bg and surface in both themes` (ink, ink-2 ≥ 4.5:1; ink-3 ≥ 4.5:1 on `bg`; `accent-ink` on `accent` ≥ 4.5:1; `link` on `bg` ≥ 4.5:1; ok/warn/bad on `surface` ≥ 3:1 as non-text shapes).
  - `tokens.test.ts › css custom properties equal tokens.ts`.
  - `client.test.ts › sends csrf header on POST, not on GET`, `› parses problem body into ApiError`, `› calls onUnauthorized on 401`, `› network failure rejects with ApiError status 0`.
  - `catalog.test.ts › de catalogue has a translation for every en message id`.
  - `build.test.ts › test_no_external_font_urls` (runs after `pnpm build`; no `http(s)://` font URL in `dist/**/*.css`).
- [ ] **Step 2: Run** `pnpm --dir frontend test` → FAIL.
- [ ] **Step 3: Implement** the scaffold. If a spec token fails the contrast test, stop and report the failing pair; do not change token values silently.
- [ ] **Step 4: Run** `pnpm --dir frontend typecheck && pnpm --dir frontend lint && pnpm --dir frontend test` → PASS. Add CI job `web`: `pnpm typecheck`, `pnpm lint`, `pnpm test --coverage` (thresholds 70), `pnpm gen:api && git diff --exit-code frontend/src/api/schema.gen.ts` (drift gate) and `pnpm build`; `pnpm e2e` joins this job in Task 9. Switch `WEB_SOURCE` default to `web-builder`; `docker build -f backend/Dockerfile .` → success.
- [ ] **Step 5: Counter-test** — change `--ink-3` light to `#A8A296`: the contrast test goes red. Restore.
- [ ] **Step 6: Commit** `feat(web): scaffold the React app with tokens, fonts, i18n and API client`

---

### Task 9: App shell, sign-in, status badge, theme

**Files:**
- Create: `frontend/src/shell/{AppShell,Sidebar,TabBar,TopBar,StatusBadge,SignIn,BootstrapKeyCreated,ThemeSwitch,features}.tsx`, `frontend/src/app/{router,queryClient,session}.ts`, `backend/tests/e2e_app.py`, `frontend/playwright.config.ts`, `frontend/e2e/fixtures.ts`
- Test: `frontend/src/shell/*.test.tsx`, `frontend/e2e/shell.spec.ts`

**Interfaces:**
- Consumes: `apiFetch`, `/api/info`, `/api/v1/auth/session` (Tasks 4, 5).
- Produces `useInfo(): UseQueryResult<Info>`; `useSession(): { signedIn: boolean; scope; source; bootstrap: boolean; csrfToken: string | null; signIn(key: string): Promise<void>; signOut(): Promise<void> }`.
- Produces `function useFeature(name: keyof Info["features"]): boolean`; sidebar/tab entries declare `feature?: string` and are hidden when the flag is false (spec §5.3).
- Produces `<StatusBadge state: "ok" | "warn" | "bad" | "idle" label: string />` — dot for ok/bad/idle, diamond for warn, always renders `label` text.
- Routes (TanStack Router): `/`, `/printers`, `/printers/$printerId`, `/jobs`, `/jobs/$jobId`, `/lookup/$app/$id`, `/loc/$id`, `/asset/$id`, `/spool/$id`, `/product/$id`, `/scan`, `/settings/*`, `/sign-in`.
- Layout: sidebar ≥ 1024 px (groups Overview/Printers/Jobs; Material; Integrations; System), top bar with search and Scan; < 1024 px bottom tab bar Overview · Printers · **Scan** (centre, large) · Jobs · Sheets (Sheets hidden while `features.sheets` is false).
- Sign-in: shown when `signed_in` is false and SSO did not create a session; one key field (`type="password"`, `autocomplete="off"`), never stored. Bootstrap session → screen to create the first admin key (calls `POST /api/admin/api-keys`, shows the key once with copy button, then hint "Remove PRINTER_HUB_BOOTSTRAP_ADMIN_KEY from the container").
- Theme: `data-theme` on `<html>`, choice system/light/dark in `localStorage` key `lph.theme` (try/catch).
- Produces the e2e harness `backend/tests/e2e_app.py`: `def build_e2e_app() -> ASGIApp` — temp SQLite, migrations applied, two mock printers created through `printer_admin_service` (that conftest only patches `BackendRouter._build_one` to return `MockPrinterBackend`; do the same, the printers must be created here), fake Snipe-IT/Grocy/Spoolman plugins, one admin key whose plaintext is written to the path in `E2E_KEY_FILE`; env `E2E_BOOTSTRAP=1` starts it with no keys and a bootstrap key instead. Playwright `webServer`: `pnpm build && cd ../backend && uvicorn tests.e2e_app:app --port 8765` with `PRINTER_HUB_WEB_DIST_DIR=../frontend/dist`. `frontend/e2e/fixtures.ts` exports `signedInPage` (signs in with the key file).

- [ ] **Step 1: Failing tests:** `StatusBadge › warn renders a diamond and the label`, `› never renders without text`; `Sidebar › hides entries whose feature is off`; `SignIn › submits key and clears the field`; `session › 401 from any query routes to /sign-in`; add `pnpm e2e` to the CI `web` job; e2e `shell.spec.ts › desktop shows sidebar, 390px shows tab bar with Scan centred`, `› keyboard: Tab reaches every nav entry with visible focus`, `› bootstrap flow creates first admin key`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.**
- [ ] **Step 4: Run** unit + e2e → PASS.
- [ ] **Step 5: Counter-test** — make `StatusBadge` drop the label for `ok`: the "never renders without text" test goes red. Restore.
- [ ] **Step 6: Commit** `feat(web): app shell with navigation, sign-in and status badge`

---

### Task 10: Live events in the client

**Files:**
- Create: `frontend/src/api/events.ts`, `frontend/src/api/events.test.ts`

**Interfaces:**
- Consumes: `GET /api/v1/events` (Task 6).
- Produces `useHubEvents(): { connected: boolean }` mounted once in `AppShell`; opens one `EventSource("/api/v1/events")` (cookie auth); maps events to TanStack Query invalidations: `job.state_changed` → `["jobs"]`, `["printers", printerId, "queue"]`; `printer.status` → `["printers"]`, `["printers", printerId]`; `printer.tape_changed` → `["printers", printerId]`; `hub.printers_changed` → `["printers"]` and re-open the stream; `auth.expired` → close and call `onUnauthorized()`. Reconnect with backoff 1 s → 30 s.
- Shows a non-blocking "Live updates paused" note with `StatusBadge state="warn"` while disconnected > 5 s.

- [ ] **Step 1: Failing tests** (fake `EventSource`): each mapping above; `auth.expired closes and signs out`; `backoff caps at 30s`; `printers_changed reopens the stream`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Counter-test** — remove the reopen on `hub.printers_changed`: its test goes red. Restore.
- [ ] **Step 6: Commit** `feat(web): live updates from the event stream`

---

### Task 11: Overview, printers, printer detail

**Files:**
- Create: `frontend/src/features/overview/`, `frontend/src/features/printers/`
- Test: unit tests next to components; `frontend/e2e/printers.spec.ts`, `frontend/e2e/overview.spec.ts`

**Interfaces:**
- Consumes: `GET /api/printers`, `/api/printers/{id}`, `/status`, `/tape`, `/queue`, `POST /pause`, `/resume`, `/queue/clear`, `POST /api/jobs/{id}/cancel`.
- Produces Overview with three answers in this order: "Printing now" (running jobs), "Needs attention" (paused printers, failed jobs, each with its reason text from the API), "Material" (tape loaded per printer; low/empty states). Then printer cards (state badge, tape width + tape colour swatch labelled with its name), recent jobs.
- Produces printer detail: state + Pause/Resume at the top; left: material and queue with Cancel on queued jobs; right: connection (model, backend, host shown as stored) and a calibration placeholder only when `features.calibration`.
- Tape colour swatches always carry the colour name next to them; never used as a state.

- [ ] **Step 1: Failing tests:** `Overview › lists a failed job under Needs attention with its reason`, `› paused printer shows Resume`, `PrinterDetail › Cancel only on queued jobs`, `› pause posts with CSRF header`; e2e against the e2e server (Task 9 harness): pause → badge changes via the event stream without reload.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Counter-test** — render Cancel for running jobs too: its test goes red. Restore.
- [ ] **Step 6: Commit** `feat(web): overview, printer list and printer detail`

---

### Task 12: Jobs, integration item view, QR paths, cart printing

**Files:**
- Create: `frontend/src/features/jobs/`, `frontend/src/features/lookup/` (incl. `cart.ts`)
- Test: unit tests; `frontend/e2e/jobs.spec.ts`, `frontend/e2e/lookup.spec.ts`

**Interfaces:**
- Consumes: `GET /api/jobs?state&since&limit`, `GET /api/jobs/{id}`, `POST /api/jobs/{id}/retry|cancel`, `GET /api/lookup/{app}/{id}`, `POST /api/render/preview`, `POST /api/print/{printer_key}/batch`, `GET /api/batches/{batch_id}`.
- Produces jobs list (filter by state, newest first) and job detail (payload summary, state history, error text, Retry on failed, Cancel on queued).
- Produces item view at `/lookup/$app/$id`; `/loc/$id` → `snipeit` location, `/asset/$id` → `snipeit` asset, `/spool/$id` → `spoolman`, `/product/$id` → `grocy` (same mapping as `backend/app/api/routes/qr.py:99–241`). Shows name, link to the source app, preview image, printer picker, "Print now" and "Add to cart" (ADR 0013).
- Produces `useCart(): { items: CartItem[]; add(item); remove(id); clear(); print(printerKey): Promise<BatchRead> }`, persisted in `localStorage` key `lph.cart` (try/catch; the cart is a per-browser convenience). `CartItem = { app; id; name; content_type; copies: number }`.
- Unknown item → in-app "Not found in <App>" with the id in mono; integration not configured → message linking to Settings › Integrations.

- [ ] **Step 1: Failing tests:** `JobDetail › Retry only on failed`, `ItemView › 503 integration_not_configured links to settings`, `cart › survives reload`, `› print sends one batch with all items and clears on success`, `› keeps items when the batch is rejected`; e2e `lookup.spec.ts › opening /asset/<id> shows the item and prints it` (respx-free: the e2e server registers a fake Snipe-IT plugin), `jobs.spec.ts › retry a failed job`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Counter-test** — clear the cart before awaiting the batch result: `keeps items when the batch is rejected` goes red. Restore.
- [ ] **Step 6: Commit** `feat(web): jobs, integration item view and cart printing`

---

### Task 13: Settings pages

**Files:**
- Create: `frontend/src/features/settings/{General,Printers,PrinterForm,Integrations,AccessKeys,Jobs,System,SettingField}.tsx`
- Test: unit tests; `frontend/e2e/settings.spec.ts`

**Interfaces:**
- Consumes: `GET /api/v1/system/logs` (Task 5), `GET /api/v1/settings/export`, `GET/PUT /api/v1/settings`, `POST /api/v1/settings/integrations/{name}/test`, `/api/v1/admin/printers` CRUD (`admin_printers_api.py:102–252`, `PrinterCreatePayload`/`PrinterUpdatePayload`), `/api/admin/api-keys` (`admin_api_keys.py:110–217`), `/healthz`, `/readiness`.
- Produces `<SettingField view: SettingView />`: locked → read-only with "Set by the container"; secret → empty input with placeholder "Saved — enter a new value to replace" when `is_set`, "Not set" otherwise; `undecryptable` → `StatusBadge warn` "Can't be read with the current secret key — enter it again".
- Sections exactly: General, Printers, Integrations (Paperless, Snipe-IT, Grocy, Spoolman; each with "Test connection" using unsaved form values and showing ok/status/detail), Access and keys (keys with scopes read/print/admin, create shows the key once, revoke; webhook key; SSO status read-only), Jobs (retention, default part size, half cut), System (version, health, readiness, settings export download, the last 200 warning/error log records, link to API docs). Integrations also lists **clients** (Kept, Hangar, …) as the API keys whose names identify them, with scope and last use. Sheets/ASN and Notifications are hidden until their flags exist.
- Only `admin` sessions see Settings; others get a "You need an admin key" page.

- [ ] **Step 1: Failing tests:** `SettingField › locked field is read-only and says Set by the container`, `› secret input never shows a value`, `› undecryptable shows warning`; `Integrations › test connection sends unsaved values`; `Printers › create then disable a printer`; `AccessKeys › new key shown once and gone after closing`; e2e `settings.spec.ts › locked env value cannot be edited` (e2e server sets `PRINTER_HUB_GROCY_URL`).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Counter-test** — render locked fields editable: the locked unit and e2e tests go red. Restore.
- [ ] **Step 6: Commit** `feat(web): settings pages for printers, integrations, keys and jobs`

---

### Task 14: Scanning, global search, PWA

**Files:**
- Create: `frontend/src/features/scan/{ScanScreen,decoder,decoder.worker,resolvers}.ts(x)`, `frontend/src/features/search/`, PWA config in `vite.config.ts`, `frontend/public/manifest.webmanifest`, icons
- Test: unit tests; `frontend/e2e/scan.spec.ts`

**Interfaces:**
- Produces `createDecoder(): Promise<Decoder>` with `decode(frame: ImageBitmap): Promise<ScanHit | null>`; uses `BarcodeDetector` when it exists and supports the needed format, else a ZXing WebAssembly worker (candidate `zxing-wasm`, MIT — verify licence and record it in the PR). Formats `qr_code`, `code_128`, `data_matrix`.
- Produces `type ScanHit = { format: string; text: string }`; `registerScanResolver(r: { id: string; match(hit: ScanHit): boolean; resolve(hit: ScanHit): string /* route */ })`. Foundation resolvers: URL whose path starts with `/loc/`, `/asset/`, `/spool/`, `/product/` → that route (host ignored); bare job UUID → `/jobs/$id`. No match → "Unknown code" with the text in mono and a copy button.
- Produces `registerSearchSource(s: { id: string; search(q: string): Promise<SearchResult[]> })`; foundation sources: printers (name/slug, from the printers query), jobs (id prefix, `GET /api/jobs?limit=50`). Field in the top bar; `/` focuses it.
- Insecure context (`!window.isSecureContext`) → the scan screen explains that the camera needs HTTPS or localhost; camera denied → explains how to allow it.
- PWA: `vite-plugin-pwa` (MIT), app-shell precache, `navigateFallback: "/index.html"` with `navigateFallbackDenylist` for `/api/`, `/docs`, `/openapi.json`, `/redoc`; no runtime caching of `/api/*`.

- [ ] **Step 1: Failing tests:** `resolvers › printed asset URL from any host resolves to /asset/<id>`, `› unknown code returns null`, `decoder › falls back to worker when BarcodeDetector lacks data_matrix`, `ScanScreen › insecure context shows the HTTPS message`, `search › finds a printer by slug and a job by id prefix`, `pwa › service worker never caches /api` (asserts the generated workbox config); e2e `scan.spec.ts` with Playwright's fake camera feeding a QR image of `https://hub.example.invalid/asset/42` → lands on `/asset/42`; `scan.spec.ts › zxing worker decodes a data-matrix image under the production CSP` (BarcodeDetector stubbed away).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (load `mobile-native` for the phone screens). **Step 4: Run** → PASS.
- [ ] **Step 5: Counter-test** — drop the worker fallback: the data-matrix test goes red. Restore.
- [ ] **Step 6: Commit** `feat(web): camera scanning, global search and installable app`

---

### Task 15: Decision register and ADRs

**Files:**
- Create: `docs/decisions/register.md`, `docs/decisions/0015-single-process-deployment.md` (supersedes 0001), `0016-react-typescript-web-ui.md` (supersedes 0003; restates 0010 PWA), `0017-settings-in-database-env-locks-encrypted-secrets.md`, `0018-decision-register.md`, `0019-proxy-headers-need-trust-token.md` (supersedes 0014)
- Modify: headers of `0001-*.md`, `0003-*.md`, `0014-*.md` (status `superseded` + `Superseded by`), `0007-*.md` (single image), `docs/decisions/README.md` index
- Test: `backend/tests/unit/test_decision_register.py`

**Interfaces:**
- Produces `register.md` table: `| Label | Title | Date | Status | ADR |`; first labels: `D1` single process serves the UI (ADR 0015), `D2` React + TypeScript stack (0016), `D3` token set §5.2 (—), `D4` env wins over settings, locked fields (0017), `D5` secrets encrypted with `PRINTER_HUB_SECRET_KEY`, write-only (0017), `D6` printers managed in the UI (—), `D7` one-time bootstrap key + container recovery command (0017), `D8` English default language (—), `D9` decision register is public (0018), `D10` proxy headers only with trust token, legacy header and Basic bypass opt-in (0019), `D11` no global part size / half-cut setting in the foundation (—), `D12` `ink-500` darkened to `#6B655A` for AA (—).
- The `D<n>` comments named in earlier tasks reference these labels.

- [ ] **Step 1: Failing test:** `test_register_labels_unique_and_linked` — labels unique, every ADR link resolves to a file, every `D<n>` in `backend/app/**/*.py` and `frontend/src/**/*.ts(x)` exists in the register.
- [ ] **Step 2: Run** → FAIL. **Step 3: Write** the ADRs (Nygard format, `docs/decisions/_template.md`). **Step 4: Run** → PASS.
- [ ] **Step 5: Counter-test** — add a stray `# D99` comment: test goes red. Remove.
- [ ] **Step 6: Commit** `docs(decisions): add decision register and ADRs 0015–0019`

---

### Task 16: End-to-end harness, compose examples, migration notes

**Files:**
- Create: `docs/migration/v-next-single-container.md`
- Modify: `backend/tests/e2e_app.py` (only if a §6 path needs another fixture)
- Modify: `examples/compose.{standalone,caddy,traefik,pangolin}.yml` (drop the `frontend` service; proxies point at `backend:8000`; add `PRINTER_HUB_SECRET_KEY`, `PRINTER_HUB_PUBLIC_URL` placeholders; `compose.pangolin.yml` sets `PRINTER_HUB_SSO_TRUST_TOKEN` and, with a comment, `PRINTER_HUB_TRUST_PANGOLIN_BASIC_BYPASS`), `examples/compose.backend-only.yml` (keep; note it is API-only), `dev/docker-compose.smoke.yml`, `docs/architecture.md`, `README.md` quick start
- Test: `frontend/e2e/*.spec.ts` (all pages of spec §6), `backend/tests/unit/test_examples_compose.py`

**Interfaces:**
- Consumes: the e2e harness from Task 9.
- Every row of spec §6 has at least one e2e path: overview, printer detail, jobs list/detail/retry, item view, settings keys, settings printers; plus QR path, sign-in and bootstrap.

- [ ] **Step 1: Failing tests:** `test_examples_have_no_frontend_service`, `test_examples_set_secret_key_and_public_url`, `test_examples_have_no_private_artefacts` (no RFC1918/100.64/10. addresses, no non-`example.invalid` domains); the e2e suite lists one spec per §6 row.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; write the migration note: compose diff, new required variables, removed variables (`PRINTERS_CONFIG`, frontend `PORT`/`BACKEND_URL`/`CSRF_KEY`), the `/api/events` fragment stream removal, the new trust rules for proxy headers (opt-in flags), the bootstrap/recovery flow, image name `label-printer-hub-backend` (frontend image no longer published).
- [ ] **Step 4: Run** full backend suite, `pnpm --dir frontend e2e`, `docker compose -f examples/compose.standalone.yml config --quiet`, then start the standalone example with a built image and check `curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/` → `200` and `/api/info` → `200` (a real start, not only config validation).
- [ ] **Step 5: Counter-test** — re-add a `frontend` service to one example: the compose test goes red. Restore.
- [ ] **Step 6: Commit** `docs: single-container examples, e2e harness and migration notes`

---

## Finish

- Whole-branch review with the four lenses (taint of secrets into responses/logs/SSE; run the app and check output against purpose; unchanged dependencies `require_scope`, `EventBus`, plugin registry; ordering of mounts, migrations and CI jobs).
- Security audit (6 phases) on the changed surface before the PR is opened; HIGH/CRITICAL block.
- PR description: dependency licence list, mockup screenshots, the `feat!` release note, link to the spec and this plan.
