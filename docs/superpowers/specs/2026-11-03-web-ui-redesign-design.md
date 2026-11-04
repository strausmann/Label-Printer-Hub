# Web UI redesign: foundation

- **Date:** 2026-11-03
- **Status:** Approved by the maintainer 2026-11-04
- **Scope:** the new web UI's foundation. Feature modules for parts and partial retry (#149), page printers, the sheet archive and calibration (#150), Paperless ASN labels (#151) and the Kept integration (keptinventory/kept#421) get their own designs later and plug into this foundation.
- **Last step of the overall project:** a documentation and product site built with Zensical, in the style of the Gangway project's site, once the foundation and the feature modules have shipped. It gets its own design.
- **Mockups:** portal and token set (private draft, screenshots to be attached to the PR); sheet screens <https://claude.ai/artifact/BLKZ7Vhe1RkksXuwptB5ha>; Kept integration <https://claude.ai/artifact/5NUGZXqJ68seriPKwQB5fD>

## 1. Intent

The hub is about to grow well beyond "pick a printer, print a label": live printer and tape state, a print queue with parts and partial retry, page printers over IPP, a shared archive of label sheet types with numbered physical sheets and photo-based calibration, Paperless ASN labels, and clients like Kept and Hangar that print through it. The current UI (Go + chi + HTML templates + HTMX, ADR 0001/0003) was built for the first stage. The next features need interactive screens (sheet cell grids, rule and set editors, camera scanning, photo upload, live queue updates) that are painful to build as server-rendered fragments.

Nothing depends on the hub in production yet, so this is the moment to replace the UI rather than extend it.

## 2. Goals

1. A new web UI that **replaces every page of the current UI** (section 6) and becomes the single front door of the hub.
2. **One process to deploy**: the UI is static assets served by the FastAPI backend. The Go frontend container and its proxy layer go away.
3. **Usable on a phone next to the printer**: installable PWA, camera scanning, thumb-reachable navigation.
4. A **design system** of its own (section 5) that feels related to Kept (warm paper surfaces, calm type, one warm accent) without copying anything from it.
5. **Settings in the UI**, including printers. Only the infrastructure that the UI itself depends on stays in environment variables (section 8).
6. A **decision register** in the style of Kept's decision labels, linked to the existing ADRs (section 9).
7. A structure where the feature modules from #149, #150, #151 and the Kept integration can be added as screens without reworking the shell.

## 3. Non-goals

- No change to the print pipeline, layout engine, printer plugins or queue semantics (ADR 0004, 0005). The API stays the contract (ADR 0011); new endpoints are added only where the UI needs them (section 10).
- The feature modules themselves (parts, sheets, calibration, ASN, Kept) are not part of this design beyond the slots the shell keeps for them.
- No running old and new UI side by side. The new UI replaces the old one in the release that ships it.
- No native mobile app.

## 4. Anti-goals (failure even if it "works")

- Any file, token value or component copied from Kept (AGPL-3.0) into this MIT project. Same stack and similar feel are fine; copied code is not.
- A status shown by colour alone.
- Secrets readable back from the UI or the API after they were saved.
- A setting that the UI lets you change although an environment variable overrides it, without saying so.
- Private network artefacts (IPs, hostnames, domains, tokens) in code, docs, screenshots or fixtures (`docs/policies/privacy.md`).

## 5. Decided: stack, design system, layout

### 5.1 Stack

| Part | Choice |
|---|---|
| Language | TypeScript (strict) |
| Build | Vite |
| UI | React 19 |
| Routing / data | TanStack Router, TanStack Query |
| Accessible primitives | React Aria (Components) |
| Styling | Tailwind CSS v4, theme from the token file (5.2) |
| i18n | Lingui; English (default for a fresh install) and German from the start |
| API client | generated from the backend's OpenAPI (`openapi-typescript` + a thin fetch wrapper) |
| Live updates | the existing SSE endpoint (`GET /api/events`, ADR 0009) |
| Tests | Vitest + Testing Library for units, Playwright for end-to-end |
| PWA | web app manifest + service worker (offline shell, no offline printing) |
| Location in repo | `frontend/` is replaced by the new app; the backend serves its build output |

This is the same family of tools Kept uses, chosen so patterns and contributors carry over. No Kept code is reused.

### 5.2 Design system (tokens)

One token file, three layers: primitive values → semantic roles → component use. Light and dark, switched by `prefers-color-scheme` and an explicit choice.

**Primitives**

| Token | Value |
|---|---|
| paper-50 / 100 / 200 / 300 | `#F6F4EF` / `#EFEBE3` / `#E3DED3` / `#CFC8BA` |
| ink-900 / 700 / 500 | `#1F1D1A` / `#4A463F` / `#6B655A` (changed from `#777166` on 2026-11-04: the old value reached only 4.40:1 on `bg` and 4.07:1 on `sunken`) |
| amber-500 / 600 / 100 | `#D4912A` / `#B8771A` / `#F6E6C8` |
| stamp-600 / 100 | `#2F4E8F` / `#DDE5F3` |
| green-600, orange-600, red-600 | `#2E7A4E`, `#B5651B`, `#B0352B` |

**Semantic roles**

| Role | Light | Dark | Used for |
|---|---|---|---|
| `bg` | paper-50 | `#171614` | page |
| `surface` | `#FDFCF9` | `#201E1B` | cards, panels, tab bar |
| `sunken` | paper-100 | `#29261F` | fields, recessed areas |
| `line` / `line-strong` | paper-200 / paper-300 | `#35312A` / `#4A443A` | borders |
| `ink` / `ink-2` / `ink-3` | ink-900 / 700 / 500 | `#F1EEE7` / `#C4BEB2` / `#958E81` | text levels |
| `accent` (+ `accent-ink`, `accent-soft`) | amber-500 (`#2B1D06`, amber-100) | `#E2A445` (`#241703`, `#3A2D16`) | primary actions, new cells |
| `link` | stamp-600 | `#8FAEE6` | links, focus ring |
| `ok` / `warn` / `bad` | green / orange / red 600 | `#6CC58F` / `#E39A4F` / `#EE8579` | states |
| tape colours | white `#FFFFFF`, yellow `#F2D23C`, green `#5FAE5A`, blue `#3D78C9`, red `#D2473B` | same | material, never state |

**Rules**

- A state is always dot (or shape) **plus word**. `warn` uses a diamond instead of a dot, because the orange sits close to the amber accent.
- Tape colours describe the loaded material; they are never used for state.
- Radii 6 / 10 / 14 px; spacing on a 4 px grid; focus ring in `link`, 3 px.
- Type: **Atkinson Hyperlegible** for UI text, **Atkinson Hyperlegible Mono** for every code (label codes, ASNs, sheet IDs, tape names). Scale: title 28/700, section 20/700, body 15/400, small 13/400, code 15/600.
- Codes are always rendered in the mono face so 0/O, 1/l/I and 8/B stay distinct.
- Self-host the fonts (no third-party font CDN at runtime).

### 5.3 Layout

- **Desktop**: left sidebar — Overview, Printers, Jobs; *Material*: Sheets, Sheet archive, Calibration; *Integrations*: Paperless ASN, Kept / Hangar / Grocy; *System*: Settings. Top bar: global search and a Scan button. Entries for modules that don't exist yet are hidden until their backend ships (feature flags from `GET /api/info`).
- **Overview** answers three questions: what is printing, what is stuck and why, is material running out. Then printer cards (state, tape or toner), jobs, sheets with a reorder hint.
- **Phone**: bottom tab bar with five entries — Overview, Printers, **Scan (large, centre)**, Jobs, Sheets. Archive, calibration and integrations are reached from Overview. A scan result leads straight to the matching action (a sheet → "print onto this sheet", a label code → its item, an ASN → its Paperless document).
- **Printer detail**: state with Pause/Resume at the top; material (tape and tape colour, or toner per colour and trays) and queue with Cancel on the left; calibration and connection on the right.
- **Global search** finds printers, jobs, sheet IDs, ASNs and label codes from one field.

### 5.4 Scanning

- Primary: the browser's `BarcodeDetector`. Fallback where it's missing or lacks a format: a ZXing WebAssembly build in a Web Worker. Pick a build with a permissive licence; verify before adding the dependency.
- Formats: QR first; Code 128 and Data Matrix as well (ASN labels and some printed codes use them).
- Needs a secure context (HTTPS or localhost); the UI says so instead of failing silently.
- What a scan resolves is defined per module; the foundation provides the camera screen, the decoder and a resolver hook that modules register into.

## 6. The foundation must replace these pages

Current Go frontend routes and what replaces them:

| Current | New |
|---|---|
| `/` dashboard | Overview |
| `/printers/{id}` | Printer detail |
| `/jobs`, `/jobs/{id}`, `POST /jobs/{id}/retry` | Jobs list and job detail with Retry / Cancel |
| `/templates`, `/templates/{id}` (dead since 1k.1a, `ErrNotImplemented`) | **Removed.** Layouts are shown as the content types and tape widths the hub supports; editable templates are a later module (#104) |
| `/lookup/{app}/{id}` | Integration item view (look up an item in Snipe-IT / Grocy / Spoolman, preview, print), following the browse + cart pattern of ADR 0013 |
| `/admin/api-keys…` | Settings › Access and keys |
| `/admin/printers…` (list, new, edit, disable/enable) | Settings › Printers |
| proxied `/api/*`, `/loc`, `/asset`, `/spool`, `/product`, `/docs`, `/openapi.json`, `/redoc`, `/readiness`, `/print` | served by the backend directly; nothing proxied any more |

The QR resolver paths `/loc`, `/asset`, `/spool`, `/product` must keep working, because printed labels carry them.

## 7. Settings

Everything operational is a setting in the UI and lives in the database. Secrets are stored encrypted with the master key (section 8), never returned, only replaced. **A value set by an environment variable wins** and is shown read-only with the hint "set by the container", so GitOps deployments stay authoritative.

| Section | Contents |
|---|---|
| General | display name, language, time zone, public URL (read-only if set by env) |
| Printers | add, edit, disable printers; trays; default printer (the existing printer CRUD, 7.1) |
| Integrations | Paperless, Snipe-IT, Grocy, Spoolman: URL, token, timeout, "test connection" with the result. Clients (Kept, Hangar) listed with their API keys |
| Access and keys | API keys with scopes (read / print / admin), webhook key, SSO status (read-only) |
| Jobs | retention, default part size, half cut by default |
| Sheets and ASN | slots for #150/#151: reorder threshold, ASN prefix and padding, gap filling default, stale-reservation period |
| Notifications | slot; later (toner/tape low, printer offline) |
| System | version, health, export/backup of settings, logs |

### 7.1 Printers are managed in the UI

- Decided by the maintainer: printers are managed in the UI.
- This already holds in the backend: printers live in the database since Phase 5 (#124), with CRUD in `app/api/routes/admin_printers_api.py`. `printers.yaml` is no longer read; only the setting `printers_config` and its comments remain. Remove that dead setting and the remaining `printers.yaml` references (`config.py`, `main.py` messages, `app/seed/printers.yaml.example`, docs, examples). No import is needed.

## 8. Environment variables

Only what the UI depends on, or what defines a trust boundary, stays in the container.

**Required or security-relevant**

| Variable | Why it can't be a UI setting |
|---|---|
| `PRINTER_HUB_DATABASE_URL` (+ data volume) | the settings live there |
| `PRINTER_HUB_SECRET_KEY` (new) | master key that encrypts stored secrets; must never be in the database |
| `PRINTER_HUB_PUBLIC_URL` (new) | links, QR targets, cookies; a wrong value can lock you out of the UI |
| `PRINTER_HUB_SSO_TRUST_TOKEN`, `_SSO_TRUST_HEADER`, `_SSO_USER_HEADER` | trust boundary to the reverse proxy; editable in the UI, anyone with UI access could switch protection off |
| `PRINTER_HUB_PANGOLIN_BYPASS_SCOPE_DOWNGRADE` | same reason |
| `PRINTER_HUB_BOOTSTRAP_ADMIN_KEY` (new) | first sign-in on an empty install (8.2); afterwards keys are managed in the UI |
| `PRINTER_HUB_SERVER_PORT`, `_LOG_LEVEL` | container operation |

**Optional (pre-provision; locks the UI field)**

Integration URLs and tokens (`_SNIPEIT_*`, `_GROCY_*`, `_SPOOLMAN_*`, Paperless), webhook key, job retention, the SSE tuning values.

**Clean-up included in this work:** `backend/.env.example` still lists variables removed with the move to `printers.yaml` (`PRINTER_HUB_PT750W_HOST`, `_QL820_HOST`, `_PRINTER_BACKEND`, `_PRINTER_MODEL`, `_PRINTER_DISCOVER_VIA_SNMP`, …). `Settings` uses `extra="forbid"`, so copying the example file makes startup fail. Update it together with `examples/`.

### 8.1 Browser sign-in, sessions and CSRF

The backend has no cookie session today: each request authenticates by API key header or by the Pangolin SSO headers, and the Go frontend did CSRF itself. With the Go frontend gone:

- **Behind an SSO proxy** (Pangolin): the browser is identified by the proxy's headers as today; the backend additionally issues its own session cookie on the first request so the UI and the event stream work the same way in every deployment.
- **Without an SSO proxy** (`examples/compose.standalone.yml`, Caddy, Traefik): a sign-in screen exchanges an API key with `admin` or `print` scope for a session. The key is never stored in the browser.
- Session cookie: `HttpOnly`, `Secure` (except on localhost), `SameSite=Strict`, server-side session record with expiry and revoke on key revocation.
- **CSRF**: every state-changing request authenticated by the session cookie carries a CSRF token (double-submit, header). Requests authenticated by an API key header stay CSRF-exempt (not sent automatically by browsers).
- The bootstrap admin access (section 8) is how the first key or the first sign-in happens on an empty install.

### 8.2 First admin access and recovery

Decided with the maintainer: what makes sense for deployments **without** SSO.

- `PRINTER_HUB_BOOTSTRAP_ADMIN_KEY` is a **one-time** key. It only works while no admin key exists. Signing in with it leads straight to creating the first real admin key (shown once); from then on the bootstrap key is rejected, and the UI shows a hint to remove the variable.
- **Recovery** when every admin key is lost is a command inside the container, not a permanent backdoor in the environment: e.g. `docker compose exec backend printer-hub admin create-key --scope admin`. Whoever can run commands in the container already controls the hub, so this adds no new attack surface, unlike a long-lived key in an environment variable.
- **Only the trust token makes SSO headers trustworthy** (decided by the maintainer 2026-11-04). A browser session and admin rights from proxy headers require `sso_user_header` **plus** a matching `sso_trust_header` value. The legacy `X-Pangolin-User` header without a token and the `Authorization: Basic` bypass are accepted only when explicitly enabled (`PRINTER_HUB_TRUST_LEGACY_PANGOLIN_USER`, `PRINTER_HUB_TRUST_PANGOLIN_BASIC_BYPASS`, both default off; the Pangolin example sets what it needs). `PRINTER_HUB_PANGOLIN_BYPASS_SCOPE_DOWNGRADE`, a no-op today, becomes effective. This supersedes ADR 0014; without it, any client in front of a proxy that doesn't strip these headers could claim admin.

### 8.3 Live events for the UI

`GET /api/events?printer_id=…` today emits server-rendered HTML fragments for HTMX, per printer, without its own auth. The UI needs structured data across all printers:

- New **global event stream with JSON payloads** (printer state, tape/toner, queue and job transitions), authenticated by the session cookie (EventSource cannot send an `Authorization` header). Filters by printer optional.
- The HTML-fragment endpoint is removed together with the Go frontend. ADR 0009 (SSE over WebSockets) stays; `docs/architecture/sse.md` is updated.

### 8.4 Settings take effect without a restart

Settings changed in the UI apply immediately: the integrations and the queue read them from a runtime settings store, not from the cached `get_settings()` at import time. Env values still win and stay locked. "Test connection" uses the values in the form before saving.

## 9. Decision register

- ADRs stay the place for architecture decisions (Nygard format, supersede, never rewrite).
- Add short **decision labels** used in code comments, commits and docs, as Kept does: `D<n>` decision, `V<n>` assumption to be verified, `L<n>` lesson. A label names the choice a line of code follows, so related code can be found by searching for it.
- Unlike Kept, the register is **public**: `docs/decisions/register.md`, one line per label (title, date, status, link to an ADR where one exists). Changing a decided behaviour adds a new label that supersedes the old one.
- This design introduces the first labels for its own decisions (stack, tokens, settings vs. env, printers in the UI, one-process deployment).

**ADRs to write with this work**

- New ADR: single-process deployment, the backend serves the UI. **Supersedes 0001** (two-container architecture).
- New ADR: React + TypeScript web UI. **Supersedes 0003** (Go + Tailwind + HTMX + PWA). PWA progressive enhancement (0010) stays and is restated for the new stack.
- New ADR: settings in the database, env overrides and locks; secrets encrypted with a master key.
- New ADR: decision register.
- New ADR: proxy headers are trusted only with the trust token; legacy header and Basic bypass are opt-in. **Supersedes 0014.**
- ADR 0013 (browse + cart) stays valid and is implemented in the new UI.

## 10. Backend changes the foundation needs

- Serve the built UI (static files, SPA fallback for client routes) and keep the QR resolver paths.
- Move what the Go frontend did into the backend: CSRF protection for cookie-authenticated requests, the SSO header handling for browser sessions (already in `app/auth`), the lookup view data.
- Settings API: read/write settings with per-field "locked by env" information; secrets write-only.
- Encrypted secret storage with `PRINTER_HUB_SECRET_KEY` (envelope with per-record AAD; rotation can come later).
- Remove the dead `printers_config` setting and `printers.yaml` leftovers (7.1).
- Session sign-in, CSRF and the JSON event stream (8.1, 8.3); runtime settings store (8.4).
- `GET /api/info` extended with feature flags so the shell shows only modules whose backend exists.
- Remove the Go frontend, its container and compose services; update `examples/` and the docs.

### 10.1 Release and compatibility

- The release removes the frontend image and changes the deployment from two containers to one, so it is a **breaking release** (`feat!`, major version) with migration notes: compose changes, new required variables (`PRINTER_HUB_SECRET_KEY`, `PRINTER_HUB_PUBLIC_URL`), removed variables.
- API clients that talk to the backend directly (Hangar, Kept) are unaffected; clients that went through the frontend's `/api/*` proxy switch to the backend address. ADR 0007 (image tags) is updated for the single image.

## 11. Constraints

- MIT project; every new dependency's licence is checked and listed in the PR (`CLAUDE.md`: propose new dependencies).
- Public repository: English prose; no private network artefacts; Brother trademark fair use (`docs/policies/trademarks.md`).
- TDD and the existing CI gates; Conventional Commits; squash merge.
- Accessibility: keyboard reachable, visible focus, WCAG AA contrast in both themes, no colour-only state.
- Works on current Chromium, Firefox and Safari, desktop and mobile; camera scanning needs a secure context.

## 12. Left to the builder

- Screens the mockups don't show (job detail, the settings sub-pages, the integration item view) are designed by the builder within this document's design system and layout, using the design skills; this document is authoritative where it and a mockup differ. Mockup screenshots are attached to the PR.

- Project structure inside `frontend/`, component breakdown, state management details beyond TanStack Query.
- Choice of the ZXing WebAssembly package (licence permitting) and the service-worker tooling.
- How the static build is embedded or mounted into the backend image.
- Exact Tailwind v4 theme wiring of the tokens.
- Test split between unit and end-to-end, as long as every page in section 6 has an end-to-end path.

## 13. Open points

- None left from the brainstorming. Decided on review: one-time bootstrap key plus container command for recovery (8.2); English as the default language.
