# Rename "Label Printer Hub" to Labelyard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The project, its image, its web app and its documentation are called **Labelyard**, with "Label Printer Hub" kept as the descriptive subtitle, while an existing installation upgrades by changing one image line, pulling and restarting.

**Architecture:** One branch `feat/labelyard-rename`, merged as the **last** pull request into `milestone/1.5.0` before the milestone merges into `main`. A stdlib-only guard script (`scripts/brand_guard.py`) lists every remaining old name outside an explicit allow-list; it starts red, each task shrinks its output, the last task makes it a CI gate. Identifiers that live in users' data, configuration or clients stay (see the compatibility table); the environment prefix gets a new canonical name with the old one still read.

**Tech Stack:** Python 3.12 / FastAPI / pydantic-settings (backend), React + TypeScript + Lingui + Vite PWA (web app), GitHub Actions (`docker-publish.yml`, `ghcr-cleanup.yml`, `preview-image.yml`), semantic-release.

**Spec:** Maintainer decisions of 2026-11-09 (recorded below under Global Constraints and in ADR 0022, created in Task 6). There is no separate spec file; the decision record is part of this plan.

## Global Constraints

- New name: **Labelyard** (capital L only; lowercase `labelyard` in every technical identifier).
- Subtitle for findability: **Label Printer Hub**. English tagline: `Labelyard — the self-hosted Label Printer Hub for all your labels`. German tagline (informal "du"): `Labelyard — der selbst gehostete Label Printer Hub für all deine Etiketten`.
- Hard cut for images: after the cut, CI publishes **only** `ghcr.io/strausmann/labelyard` and `docker.io/${DOCKERHUB_USERNAME}/labelyard` (no `-backend` suffix). `ghcr.io/strausmann/label-printer-hub-backend` and `docker.io/${DOCKERHUB_USERNAME}/label-printer-hub-backend` receive no further pushes; they are not deleted by this plan.
- No transition images, no dual publishing, no retagging of old versions under the new name.
- Configuration and data compatibility: an upgrade from 1.4.x is "change the image line, pull, restart". Every break of that rule is listed in the compatibility table with its reason.
- Public repo: English prose everywhere (commits, comments, docs). No AI attribution trailers or footers. Commit author `bjoern@strausmann.net`.
- No private deployment details (hostnames, IPs, stack names) in any file of this repo; the internal follow-ups at the end stay generic.
- Commit types: `feat:`/`docs:`/`ci:`/`chore:` only. **No `!` and no `BREAKING CHANGE:` footer on any commit of this branch** — the release guard of ADR 0021 would compute `2.0.0` and stop the `1.5.0` release. The break is announced in the migration guide and the release notes instead.
- Inventory baseline: counts below were measured on `main` at `6effebc` (1.4.1). The 1.5.0 tasks add more occurrences; Task 1's guard output on the milestone head is the authoritative list, not these numbers.

## Timing

**Recommendation: inside milestone 1.5.0, as the last pull request before `milestone/1.5.0` → `main`.**

1.5.0 already makes every API client and every operator touch their setup (`/api/v1` paths without compatibility); a second break one release later would mean two upgrade notes, two rounds of client changes and a release (1.5.x) whose image name changes between patch versions. Landing it last avoids conflicts with the 21 running tasks of `docs/superpowers/plans/2026-11-09-api-v1-live-printers-manifest.md`, and the milestone preview workflow lets the renamed image be tested as `labelyard:1.5.0-rc.N` before anything is released.

Option (b), an own release right after, was rejected: it would ship as `1.5.1` (a patch, which the release guard allows but which hides a breaking image change in a patch number) or force a `1.6.0` milestone for a pure rename.

Preconditions for starting the branch:

- PR #270 (milestone branches) merged and `milestone/1.5.0` exists. If it is not merged yet, the same rule applies to the 1.5.0 integration branch (`feat/api-v1-status-manifest`): the rename is its last merge.
- PR #269 (GHCR cleanup + preview image) merged into `main` and synced into the milestone. If not, Task 4 edits only `docker-publish.yml` and #269 is rebased onto the new image name before it merges.
- All other 1.5.0 tasks merged into the milestone. New work started after the rename branches from the renamed milestone.

Release sequence (operator steps in Task 9):

1. Merge `feat/labelyard-rename` into `milestone/1.5.0`; build preview `1.5.0-rc.N` and run the verification of Task 8.
2. Create the Docker Hub repo `labelyard` (public) and rename the GitHub repo.
3. Merge `milestone/1.5.0` → `main` (merge commit). The next release run publishes `labelyard:1.5.0` only.
4. Edit the GitHub Release body with the release-notes text of Task 9.

## Inventory (baseline `6effebc`, history excluded)

"History" = `CHANGELOG.md`, `docs/superpowers/**`, `docs/plans/**`, `docs/designs/**`, `docs/research/**`, `docs/decisions/0001–0021`, `docs/migration/v-next-single-container.md`. History is never rewritten (247 occurrences in the changelog, 392 in 49 historical docs).

| # | Category | Example | Occurrences / files | Decision |
|---|---|---|---|---|
| 1 | Image names | `label-printer-hub-backend`, `-frontend` (old docs) | 33 / 17 | **Rename** to `labelyard` (hard cut) |
| 2 | Image ref derivation | `${repo_lc}-${matrix.service}` in `docker-publish.yml`; `docker.io/{0}/label-printer-hub-{1}` | 2 / 1 | **Rename**, and hard-code the name (no longer derived from `github.repository`, which changes with the repo rename) |
| 3 | GHCR cleanup / preview package path | `IMAGE_PATH: …/label-printer-hub-backend` (PR #269) | 2 / 2 | **Rename** |
| 4 | OCI labels, `HUB_REPO_URL` | `org.opencontainers.image.title="label-printer-hub-backend"` | 7 / 2 | **Rename** |
| 5 | Repo URLs, badges, Codecov, CLA assistant | `github.com/strausmann/label-printer-hub/issues/22` | 52 / 26 (+ ~330 issue links in history) | **Rename** in live files to `github.com/strausmann/labelyard`; history keeps old links (GitHub redirects) |
| 6 | Display name | `Label Printer Hub` in UI, OpenAPI title, CLI help, docstrings | 48 / 36 | **Rename** to Labelyard; keep "Label Printer Hub" only as subtitle next to "Labelyard" |
| 7 | PWA manifest | `name`, `short_name: "Label Hub"`, `<title>` | 3 / 2 | **Rename** (`id: "/"` unchanged) |
| 8 | Environment prefix | `PRINTER_HUB_*` (47 variables) | 335 / 70 | **New canonical `LABELYARD_*`, old prefix still read** |
| 9 | Other env names | `PRINTHUB_PDF_FONT`, `PRINTERHUB_HOST` (examples), `LABEL_HUB_URL/KEY` (examples) | 27 / 10 | `LABELYARD_PDF_FONT` with old read; example-only vars renamed |
| 10 | API key header | `X-Label-Hub-Key` | 77 / 26 | **Keep** |
| 11 | API key prefix | `lh_…` | — | **Keep** |
| 12 | Cookies | `lph_session`, `lph_csrf` (`__Host-` over https) | 26 / 5 | **Keep** |
| 13 | Browser storage | `lph.cart`, `lph.recent.*`, `lph.lang`, `lph.theme`, `lph.printer`, `lph.sheetType.*` | 65 / 24 | **Keep** |
| 14 | Database file | `/data/printer-hub.db` | 13 / 13 | **Keep** |
| 15 | Export format id | `label-printer-hub.sheet-type` | 44 / 7 | **Keep** |
| 16 | Plugin entry-point groups | `label_hub.integrations`, `.printer_backends`, `.printer_models` | 21 / 11 | **Keep** |
| 17 | CLI | `printer-hub admin create-key` | 16 / 12 | **New `labelyard`, `printer-hub` kept as alias** |
| 18 | Package names | `label-printer-hub-backend` (pyproject), `label-printer-hub` / `label-printer-hub-web` (package.json) | 3 / 3 | **Rename** (never published) |
| 19 | Default display-name setting | `general.display_name` default `Label Printer Hub` | 1 / 1 (+ test fixtures) | **New default `Labelyard`**; stored values untouched |
| 20 | Example compose | Pangolin/Traefik keys `printerhub`, container names, hostnames `printerhub.example.*` | ~25 / 6 | **Rename**, with a note to keep an existing Pangolin key |
| 21 | semantic-release / package.json repository | `repositoryUrl` | 2 / 2 | **Rename** |
| 22 | Generic noun "the hub" in UI copy | "The hub could not be reached." | many | **Keep** — "hub" stays the product category, matches the subtitle |

## Compatibility decisions (why the kept identifiers stay)

| Identifier | Decision | Reason |
|---|---|---|
| Image names | Hard cut | Maintainer decision. Old packages frozen at their last 1.4.x version; deletion is a later maintainer decision (suggested: not before 2.0.0). |
| `PRINTER_HUB_*` | `LABELYARD_*` canonical; `PRINTER_HUB_*` still read at lower priority; one startup warning that lists the legacy **names** (never values); removal not before 2.0.0 | Renaming without fallback would stop every install at startup (`secret_key`, `public_url` are required). With the fallback the upgrade stays pull-and-restart. |
| Both prefixes set | `LABELYARD_*` wins, warning names the conflicting variable | Deterministic; the operator sees the leftover. |
| `PRINTHUB_PDF_FONT` | `LABELYARD_PDF_FONT` canonical, old still read | Same reason as the prefix. |
| `HUB_VERSION`, `HUB_REVISION`, `HUB_BUILD_DATE`, `HUB_REPO_URL` | Keep names, update `HUB_REPO_URL` value | Build-time image env, set by our own Dockerfile, neutral name. |
| `X-Label-Hub-Key` | Keep, no alias | Every client (other apps, scripts, webhooks) sends it; an alias doubles the auth path and the OpenAPI security scheme for no user benefit. "Label Hub" matches the subtitle. |
| `lh_` key prefix | Keep | Stored in the database (`key_prefix`), printed on existing keys. |
| `lph_session`, `lph_csrf` | Keep | Renaming signs every user out and breaks CSRF for open tabs; opaque names nobody reads. |
| `lph.*` storage keys | Keep | Renaming silently drops carts, recent lists, language and theme. |
| `/data/printer-hub.db` | Keep (also for new installs) | A new default would make every existing install start on an empty database. |
| `label-printer-hub.sheet-type` | Keep | File-format identifier; files exported by 1.4.x and 1.5.0 must import into each other. |
| `label_hub.*` entry-point groups | Keep | Third-party plugins register against these names. |
| CLI `printer-hub` | Keep as alias of `labelyard` | Documented in runbooks and the first-admin flow; costs one line in `pyproject.toml`. |
| `general.display_name` | New default only | An explicitly stored name is the operator's choice. |
| PWA `id: "/"` | Keep | Installed apps keep their identity and only show the new name and icon. |
| Example Pangolin resource keys | Rename in examples; migration guide says to keep the existing key | Changing a blueprint key makes Pangolin create a second resource. |

## Review Focus

1. Both `PRINTER_HUB_SECRET_KEY` and `LABELYARD_SECRET_KEY` set with different values → the new one is used, the warning names the variable, never a value (Task 2: `test_new_prefix_wins_over_legacy`, `test_legacy_warning_has_no_values`).
2. A legacy variable set to an empty string by compose (`${VAR:-}`) → neither overrides a new value nor locks the setting (Task 2: `test_empty_legacy_does_not_override`, `test_empty_legacy_does_not_lock`).
3. Legacy keys in the `.env` file (pydantic `env_file`), not only in the process environment → still read (Task 2: `test_legacy_prefix_from_dotenv`).
4. A 1.4.x install with no `DATABASE_URL` set finds its existing `/data/printer-hub.db` (Task 3: `test_default_database_path_unchanged`).
5. Signed-in browsers and existing API clients keep working: cookie names, header name and key prefix unchanged (Task 3: `test_compat_identifiers_unchanged`).

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/brand_guard.py` (create) | Lists old-name hits outside the allow-list; exit 1 on any hit |
| `scripts/test_brand_guard.py` (create) | unittest for the guard rules |
| `backend/app/config_legacy.py` (create) | Legacy `PRINTER_HUB_` settings source and the warning helper |
| `backend/app/config.py` | `env_prefix="LABELYARD_"`, `settings_customise_sources` |
| `backend/tests/unit/test_config_legacy_prefix.py` (create) | Prefix fallback tests |
| `backend/tests/unit/test_brand_identity.py` (create) | CLI, OpenAPI title, display-name default, compat identifiers |
| `frontend/public/brand/` (create) | Logo sources from the design task |
| `docs/migration/labelyard.md` (create) | Operator upgrade guide |
| `docs/decisions/0022-rename-to-labelyard.md` (create) | ADR; amends ADR 0007 (image name) |
| `website/` (create) | Source of https://labelyard.app and the user docs (Task 7; generator per decision D-W1) |
| `.github/workflows/website.yml` (create) | Strict site build + link check on PRs touching `website/**` |

---

### Task 1: Brand guard

**Files:**
- Create: `scripts/brand_guard.py`, `scripts/test_brand_guard.py`

**Interfaces:**
- Produces: `find_hits(root: Path) -> list[Hit]` with `Hit = NamedTuple(path: str, line: int, rule: str, text: str)`; `main(argv: list[str] | None = None) -> int` (0 = clean, 1 = hits, prints `path:line: rule: text`). CLI: `python3 scripts/brand_guard.py [--root .]`. Files are taken from `git ls-files`.

Rules (constants in the script, each with a comment saying why it exists):

| Rule | Pattern (regex) | Allowed when |
|---|---|---|
| `slug` | `label-printer-hub` (case-insensitive) | followed by `.sheet-type` |
| `env-prefix` | `PRINTER_HUB_` | file in `LEGACY_ENV_FILES` |
| `env-other` | `PRINTHUB_\|PRINTERHUB_\|LABEL_HUB_` | file in `LEGACY_ENV_FILES` |
| `cli` | `printer-hub` | followed by `.db`; or file in `LEGACY_CLI_FILES` |
| `nickname` | `Print-Hub\|PrintHub\|printerhub\|Label Hub` | `Label Hub` inside `X-Label-Hub-Key` |
| `display` | `Label Printer Hub` | the same line contains `Labelyard` |

- `EXCLUDED` (history, never scanned): `CHANGELOG.md`, `docs/superpowers/`, `docs/plans/`, `docs/designs/`, `docs/research/`, `docs/decisions/00(0[1-9]|1[0-9]|2[01])-`, `docs/migration/v-next-single-container.md`, `frontend/pnpm-lock.yaml`, binary files.
- `LEGACY_ENV_FILES`: `backend/app/config_legacy.py`, `backend/app/page_render/pdf.py`, `backend/tests/unit/test_config_legacy_prefix.py`, `backend/tests/unit/test_pdf_font_env.py`, `docs/migration/labelyard.md`, `docs/decisions/0022-rename-to-labelyard.md`, `scripts/brand_guard.py`, `scripts/test_brand_guard.py`.
- `LEGACY_CLI_FILES`: `backend/pyproject.toml`, `backend/tests/unit/test_brand_identity.py`, `docs/migration/labelyard.md`, the two guard files.

- [ ] **Step 1: Write the failing tests** (`unittest`, temp git repo built in `setUp`): `test_slug_hit`, `test_sheet_type_format_allowed`, `test_display_alone_is_hit`, `test_display_with_labelyard_allowed`, `test_header_name_allowed` (`X-Label-Hub-Key` → no hit), `test_db_file_allowed` (`printer-hub.db` → no hit), `test_history_excluded` (hit in `CHANGELOG.md` and `docs/decisions/0007-…` → none), `test_adr_0022_not_excluded` (display hit in `docs/decisions/0022-…` without Labelyard → hit), `test_env_prefix_allowed_in_legacy_file`, `test_exit_code` (`main` returns 1 with hits, 0 without).
- [ ] **Step 2:** `python3 -m unittest scripts/test_brand_guard.py -v` → FAIL (module missing).
- [ ] **Step 3:** Implement `scripts/brand_guard.py` (stdlib only).
- [ ] **Step 4:** Tests PASS. Run `python3 scripts/brand_guard.py | tee /tmp/brand-inventory.txt | tail -1`; expected exit 1 and a hit list. Paste the per-rule counts (`cut -d: -f3 | sort | uniq -c`) into the PR description as the inventory on the milestone head.
- [ ] **Step 5:** Commit `chore(scripts): add brand guard for the Labelyard rename`.

### Task 2: `LABELYARD_*` environment prefix with legacy fallback

**Files:**
- Create: `backend/app/config_legacy.py`, `backend/tests/unit/test_config_legacy_prefix.py`, `backend/tests/unit/test_pdf_font_env.py`
- Modify: `backend/app/config.py:47-60` (prefix, docstrings, `settings_customise_sources`), `backend/app/main.py:51-64` (log-level check reads `LABELYARD_LOG_LEVEL`, then `PRINTER_HUB_LOG_LEVEL`, then `LOG_LEVEL`; validation messages print `LABELYARD_<FIELD>`), `backend/app/page_render/pdf.py:37-55`, every `PRINTER_HUB_` in `backend/app` docstrings and error messages (13 files), `backend/.env.example`, `backend/app/integrations/README.md`, backend tests that `setenv("PRINTER_HUB_…")` (switch to `LABELYARD_`, except the legacy tests)

**Interfaces:**
- Produces: `LEGACY_ENV_PREFIX = "PRINTER_HUB_"`, `ENV_PREFIX = "LABELYARD_"` in `app/config_legacy.py`; `class LegacyPrefixEnvSource(EnvSettingsSource)` and `class LegacyPrefixDotEnvSource(DotEnvSettingsSource)` (same settings class, `env_prefix=LEGACY_ENV_PREFIX`, empty strings ignored); `legacy_env_report(environ: Mapping[str, str], dotenv_keys: Iterable[str]) -> LegacyReport` with `LegacyReport(used: list[str], shadowed: list[str])` (variable names only); `warn_legacy_env(report: LegacyReport, logger: logging.Logger) -> None` — one `WARNING` line per list, e.g. `Deprecated PRINTER_HUB_* variables in use, rename them to LABELYARD_*: PRINTER_HUB_SECRET_KEY, …`.
- Source order in `Settings.settings_customise_sources`: init → `LABELYARD_` env → `LABELYARD_` dotenv → legacy env → legacy dotenv → secrets.
- `pdf.py`: `FONT_ENV = "LABELYARD_PDF_FONT"`, `LEGACY_FONT_ENV = "PRINTHUB_PDF_FONT"`; new wins.
- The warning is emitted once from the app lifespan startup, after logging is configured.

- [ ] **Step 1: Write the failing tests** in `test_config_legacy_prefix.py` (monkeypatch env, `get_settings.cache_clear()`):
  - `test_new_prefix_read`: `LABELYARD_SECRET_KEY`, `LABELYARD_PUBLIC_URL` set → `Settings()` builds.
  - `test_legacy_prefix_read`: only `PRINTER_HUB_*` set → same values; `report.used == ["PRINTER_HUB_PUBLIC_URL", "PRINTER_HUB_SECRET_KEY"]` (sorted).
  - `test_new_prefix_wins_over_legacy`: both set, different `public_url` → new value; `report.shadowed == ["PRINTER_HUB_PUBLIC_URL"]`.
  - `test_empty_legacy_does_not_override`: `LABELYARD_LOG_LEVEL=DEBUG`, `PRINTER_HUB_LOG_LEVEL=""` → `DEBUG`.
  - `test_legacy_prefix_from_dotenv`: `.env` in `tmp_path` (chdir) with `PRINTER_HUB_*` only → builds.
  - `test_legacy_warning_has_no_values` (caplog): secret value string not in any record; both variable names are.
  - `test_legacy_var_locks_setting`: `PRINTER_HUB_SNIPEIT_URL` set → `store.is_locked("integrations.snipeit.url")` (use the key the registry defines for `snipeit_url`) is `True`.
  - `test_empty_legacy_does_not_lock`: `PRINTER_HUB_SNIPEIT_URL=""` → `False`.
  - `test_extra_forbid_kept`: `LABELYARD_NO_SUCH_FIELD=x` still ignored as before (pydantic-settings ignores unknown env; assert `Settings()` builds) — guards against the custom source turning unknown legacy vars into `extra_forbidden` errors.
  - `test_pdf_font_env.py`: `test_new_font_env_wins`, `test_legacy_font_env_read`.
- [ ] **Step 2:** `cd backend && pytest tests/unit/test_config_legacy_prefix.py tests/unit/test_pdf_font_env.py -v` → FAIL.
- [ ] **Step 3:** Implement as in Interfaces; switch existing backend tests to `LABELYARD_`.
- [ ] **Step 4:** `pytest -q` (full backend suite) PASS; `ruff check . && ruff format --check . && mypy app` clean. Counter-test: remove the two legacy sources from `settings_customise_sources` → `test_legacy_prefix_read`, `test_legacy_prefix_from_dotenv` and `test_legacy_var_locks_setting` go red; restore.
- [ ] **Step 5:** Commit `feat(config): read LABELYARD_* settings and keep PRINTER_HUB_* as a fallback`.

### Task 3: Backend identity — CLI, OpenAPI, defaults, image labels

**Files:**
- Create: `backend/tests/unit/test_brand_identity.py`
- Modify: `backend/pyproject.toml` (`name = "labelyard"`, description `Labelyard — the self-hosted Label Printer Hub (backend and web app server)`, scripts `labelyard = "app.cli:main"` **and** `printer-hub = "app.cli:main"`), `backend/app/cli.py` (`prog="labelyard"`, description `Labelyard admin`, key note `created with: labelyard admin create-key`), `backend/app/main.py:848-850` and `backend/app/web/api_docs.py:35` (title `Labelyard API`, description starts `REST + SSE API of Labelyard, the self-hosted Label Printer Hub, …`), `backend/app/settings_store/registry.py:31` (default `Labelyard`), `backend/app/__init__.py:1`, `backend/app/main.py:161` default and `backend/Dockerfile:120-145` (`org.opencontainers.image.title="labelyard"`, description `Labelyard — the self-hosted Label Printer Hub for Brother PT/QL and office printers`, url/source/documentation `https://github.com/strausmann/labelyard`, `HUB_REPO_URL` same), `backend/README.md`, `frontend/src/api/schema.gen.ts` (regenerated), any committed OpenAPI snapshot the completeness test compares

**Interfaces:**
- Consumes: Task 2 prefix (docstrings mention `LABELYARD_`).
- Produces: `/api/v1` info `source_url` = `https://github.com/strausmann/labelyard` (AGPL source offer; the old URL keeps working through GitHub's redirect).

- [ ] **Step 1: Write the failing tests** in `test_brand_identity.py`:
  - `test_cli_prog_name`: `build_parser().prog == "labelyard"` (extract `build_parser()` from `cli.main` if it is inline).
  - `test_cli_alias_installed`: parse `backend/pyproject.toml` with `tomllib`; `scripts` contains `labelyard` and `printer-hub`, both `app.cli:main`.
  - `test_openapi_title`: `app.openapi()["info"]["title"] == "Labelyard API"`.
  - `test_display_name_default`: registry default for `general.display_name` is `"Labelyard"`.
  - `test_default_database_path_unchanged`: `Settings.model_fields["database_url"].default == "sqlite+aiosqlite:////data/printer-hub.db"`.
  - `test_compat_identifiers_unchanged`: session/CSRF cookie names `lph_session`/`lph_csrf`, API key header `X-Label-Hub-Key`, generated key starts with `lh_`, seed sheet types carry `format == "label-printer-hub.sheet-type"`.
  - `test_source_url`: info endpoint `source_url == "https://github.com/strausmann/labelyard"`.
- [ ] **Step 2:** `pytest tests/unit/test_brand_identity.py -v` → FAIL on the renamed ones, PASS on the compat ones.
- [ ] **Step 3:** Apply the modifications; regenerate the schema with `python backend/scripts/export_openapi.py` and the frontend type generator the repo uses (`pnpm -C frontend run gen:api` or the documented equivalent); update fixtures that assert the old title/default (`frontend/src/test-utils.tsx`, `frontend/src/features/test-api.ts`).
- [ ] **Step 4:** Full backend suite and `pnpm -C frontend test` PASS; `docker build -f backend/Dockerfile -t labelyard:local .` succeeds and `docker inspect labelyard:local --format '{{index .Config.Labels "org.opencontainers.image.title"}}'` prints `labelyard`.
- [ ] **Step 5:** Commit `feat: name the backend, CLI and API Labelyard`.

### Task 4: Image publishing under `labelyard` (hard cut)

**Files:**
- Modify: `.github/workflows/docker-publish.yml:136-142` (ref `${REGISTRY_GHCR}/strausmann/labelyard`, from a new top-level `env: IMAGE_NAME: labelyard`; no `-${matrix.service}`), `:204-213` (title `labelyard`, description, url/source), `:386` (`format('docker.io/{0}/labelyard', secrets.DOCKERHUB_USERNAME)`); `.github/workflows/ghcr-cleanup.yml` header comment and `IMAGE_PATH: ${{ github.repository_owner }}/labelyard`; `.github/workflows/preview-image.yml` `IMAGE_PATH` likewise; `dev/docker-compose.smoke.yml`; `docs/decisions/0007-docker-image-tag-scheme.md` is **not** edited (history) — ADR 0022 amends it (Task 6)

**Interfaces:**
- Produces: published image refs `ghcr.io/strausmann/labelyard:<tag>` and `docker.io/<DOCKERHUB_USERNAME>/labelyard:<tag>`; tag scheme of ADR 0007 unchanged (`x.y.z`, `x.y`, `x`, `latest`, `dev`, `x.y.z-rc.N` GHCR-only).
- The owner `strausmann` is written lowercase literally; nothing in the image ref depends on `github.repository` any more (it changes with the repo rename).

- [ ] **Step 1:** Add a check to `scripts/test_brand_guard.py`: `test_workflows_publish_only_labelyard` — parse the three workflow files as text; assert no `label-printer-hub` substring and that `docker-publish.yml` contains `IMAGE_NAME: labelyard`. Run → FAIL.
- [ ] **Step 2:** Apply the workflow changes.
- [ ] **Step 3:** `python3 -m unittest scripts/test_brand_guard.py -v` PASS; `actionlint .github/workflows/*.yml` clean (install per CONTRIBUTING if missing — report it if unavailable, do not skip silently).
- [ ] **Step 4:** Commit `ci: publish the image as labelyard only`.

### Task 5: Web app brand — name, PWA, icons, i18n

**Files:**
- Create: `frontend/public/brand/labelyard-mark.svg`, `frontend/public/brand/labelyard-wordmark.svg`, `frontend/public/brand/labelyard-wordmark-dark.svg`, `frontend/public/favicon.svg` (from the design task; until delivered, the task is blocked — no placeholder art is committed)
- Replace (same paths, so the manifest paths stay): `frontend/public/icon-192.png`, `icon-512.png`, `icon-maskable-512.png` (safe zone: mark within the central 80 %), `apple-touch-icon.png` (180×180)
- Modify: `frontend/public/manifest.webmanifest` (`name: "Labelyard"`, `short_name: "Labelyard"`, `description: "Label Printer Hub — print labels, scan codes and watch your label printers."`; `id`, `start_url`, `scope`, colours unchanged), `frontend/index.html` (`<title>Labelyard</title>`, `<link rel="icon" href="/favicon.svg" type="image/svg+xml" />`), `frontend/src/i18n/messages.ts:8` (`appName: msg\`Labelyard\``, new `tagline: msg\`The self-hosted Label Printer Hub for all your labels\``), `frontend/src/shell/Sidebar.tsx:35`, `frontend/src/shell/SignIn.tsx:64` (wordmark image with `alt="Labelyard"` above the tagline), `frontend/package.json` (`name: "labelyard-web"`), root `package.json` (`name: "labelyard"`, description, repository url), `frontend/pnpm-lock.yaml` (regenerated by `pnpm install`), `frontend/src/i18n/locales/{en,de}/messages.po` (extracted + compiled; German tagline `Der selbst gehostete Label Printer Hub für all deine Etiketten`), `frontend/e2e/settings.spec.ts:84`, `frontend/src/pwa.test.ts`

**Interfaces:**
- Consumes: Task 3 display-name default `Labelyard` (Sidebar falls back to `appName`).
- Produces: `appName`, `tagline` message descriptors.

- [ ] **Step 1: Write the failing tests** in `frontend/src/pwa.test.ts`: `it("carries the Labelyard name")` — `m.name === "Labelyard"`, `m.short_name === "Labelyard"`, `m.short_name.length <= 12`, `m.description` contains `Label Printer Hub`, `m.id === "/"`; `it("every manifest icon exists")` — each `icons[].src` and shortcut icon resolves to a file in `public/`; `it("index.html names the app and links the favicon")` — `<title>Labelyard</title>` and `href="/favicon.svg"`. In `SignIn` test: heading/wordmark accessible name `Labelyard`; tagline text present in `en` and in `de` (`Der selbst gehostete Label Printer Hub für all deine Etiketten`).
- [ ] **Step 2:** `pnpm -C frontend test -- pwa SignIn` → FAIL.
- [ ] **Step 3:** Apply the changes; `pnpm -C frontend run i18n:extract && pnpm -C frontend run i18n:compile` (use the script names in `frontend/package.json`); translate the new German strings with "du".
- [ ] **Step 4:** `pnpm -C frontend test`, `pnpm -C frontend run lint`, `pnpm -C frontend run build` PASS; `pnpm -C frontend exec playwright test settings archive` PASS (archive e2e must still see `label-printer-hub.sheet-type`).
- [ ] **Step 5:** Commit `feat(web): show the Labelyard name, logo and tagline`.

### Task 6: Docs, community files, examples, ADR and migration guide

**Files:**
- Create: `docs/migration/labelyard.md`, `docs/decisions/0022-rename-to-labelyard.md` (next free number at implementation time; status Accepted, amends ADR 0007 image name, lists the compatibility table), entries in `docs/decisions/README.md` and `docs/decisions/register.md`
- Modify: `README.md` (hero: wordmark image `frontend/public/brand/labelyard-wordmark.svg` with a dark variant via `<picture>`, H1 `Labelyard`, first line `**The self-hosted Label Printer Hub for all your labels.**`, one sentence "Formerly *Label Printer Hub*." with a link to the migration guide; a "Website: https://labelyard.app" line under the hero; badges and links to `strausmann/labelyard`; config table with `LABELYARD_*` names and a note that `PRINTER_HUB_*` is still read; image refs; `docker exec labelyard labelyard admin create-key …`), `CONTRIBUTING.md`, `SECURITY.md`, `CLA.md`, `CODE_OF_CONDUCT.md`, `THIRD_PARTY_NOTICES.md`, `.github/ISSUE_TEMPLATE/*.yml`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/copilot-instructions.md`, `CLAUDE.md`, `.gemini/*`, `codecov.yml` comment, `.releaserc.json:2` (`git@github.com:strausmann/labelyard.git`), `docs/architecture.md`, `docs/architecture/*`, `docs/site/**`, `docs/policies/*` (trademarks: add a short "Labelyard" section — our project name, no registered mark claimed), `docs/learnings/*`, `examples/compose.*.yml` (image `ghcr.io/strausmann/labelyard:1.5.0`, container/service `labelyard`, Pangolin/Traefik keys `labelyard`, `LABELYARD_HOST`), `examples/.env.example`, `examples/README.md` (client env `LABELYARD_URL`, header stays `X-Label-Hub-Key`), `licence-policy.yml` and `Makefile` if the guard lists them

**Interfaces:**
- Consumes: names from Tasks 2–5.
- Produces: `docs/migration/labelyard.md` sections (exact headings): `## What changes`, `## Upgrade in three steps`, `## What stays the same`, `## Environment variables`, `## Reverse proxy and Pangolin`, `## Old images`.

Migration guide content to pin:

- Three steps: (1) change `image:` to `ghcr.io/strausmann/labelyard:1.5.0` (or `docker.io/<user>/labelyard:1.5.0`); (2) pull; (3) restart. Data volume, database file, API keys, sessions and the `X-Label-Hub-Key` header keep working.
- Optional: rename `PRINTER_HUB_*` to `LABELYARD_*`; the old names are read until at least 2.0.0 and logged as deprecated at startup.
- Pangolin: keep your existing resource key; changing it creates a new resource.
- Old images receive no updates; Watchtower/Renovate pinned to them will never offer 1.5.0.
- 1.5.0 also moves the API to `/api/v1` — link to that release's API notes.

- [ ] **Step 1:** `python3 scripts/brand_guard.py` → list for docs/examples/community files (expected non-zero).
- [ ] **Step 2:** Apply the changes. Repo links: `github.com/strausmann/label-printer-hub` and `github.com/strausmann/Label-Printer-Hub` → `github.com/strausmann/labelyard` in live files only.
- [ ] **Step 3:** `python3 scripts/brand_guard.py` → exit 0. `docker compose -f examples/compose.standalone.yml config --quiet` (and the caddy/traefik/pangolin variants with a dummy `.env`) succeeds; then **start** `compose.standalone.yml` against the locally built image from Task 3 (`IMAGE` override or temporary edit) and confirm `/healthz` returns 200 — a syntax check alone does not prove the example starts. Run the repo's markdown link check if one exists.
- [ ] **Step 4:** Commit `docs: rename the project to Labelyard`.

### Task 7: Project website and user docs (labelyard.app)

**Blocked on maintainer decision D-W1 (generator) below.** Everything else in this task holds for both options.

#### Model: Kept's documentation site

Read on 2026-11-09 from `keptinventory/kept` → `apps/docs/astro.config.mjs` and `apps/docs/src/content/docs/` (live at https://keptinventory.info). Starlight 0.42.5, Astro 7.3.5, `starlight-links-validator` 0.26.0, `starlight-openapi` 0.26.3. What we copy is the **structure**, not the code:

- One docs site that *is* the user documentation (written in the site tree, not linked out to repo files), with the landing page at `/`.
- Pages keep stable URLs by topic folder (`install/`, `users/`, `admin/`, `developers/`, `reference/`); the sidebar groups them **by audience**.
- English at the root and complete; other languages carry their own copies of user, admin and install pages; developer/reference pages may stay English with a "not translated yet" fallback. Locale list in one module (`src/locales.mjs`), group labels per language in another (`src/sidebar-labels.mjs`).
- The API reference is generated at build time from the app's own OpenAPI document; the configuration reference is generated from the settings schema into a committed page with a drift check.
- Strict internal link validation in the build; the theme colours come from the app's own design tokens; a social share card image is rendered by a script.

Labelyard sidebar (URL folder → group):

| Group | Pages (folder) |
|---|---|
| Try | `try/` — what it is, screenshots (#260), the demo/quick look |
| Install | `install/` — compose (standalone), reverse proxy (Caddy, Traefik, Pangolin), HTTPS, hardware/printer connection |
| Using | `using/` — printers (PT/QL tape, IPP page printers), sheets and layouts, print inbox and queue, scanning, cart and bulk print |
| Admin | `admin/` — API keys, users and SSO, backups and restore, upgrades (incl. *Coming from Label Printer Hub*), security model, troubleshooting |
| Integrations | `integrations/` — Snipe-IT, Grocy, Spoolman (plugins); Paperless and Kept as apps that print through the API; webhooks |
| Developers | `developers/` — API reference (generated), architecture, plugin authoring, contributing |
| Reference | `reference/configuration` — every `LABELYARD_*` variable, generated from `app/config.py` + `settings_store/registry.py` |

Languages: `en` at root (complete), `de` with its own copies of Try, Install, Using and Admin (informal "du", same tone as the web app); Developers and Reference English only.

**Link vs include — decision: move, then link back.** The audience structure and the translations need the pages inside the site tree, so the user-facing docs move there: `docs/site/operations/api-keys.md`, `docs/site/operations/templates/*`, the README configuration table and the example walkthroughs (`examples/README.md`) become site pages; `docs/migration/labelyard.md` (Task 6) becomes `admin/upgrades/from-label-printer-hub` and the old path keeps a one-line pointer (update the guard's `LEGACY_ENV_FILES` path). README keeps a short quick start and links to https://labelyard.app for the rest. Repo-internal material (ADRs, plans, research, learnings) stays out of the site.

#### Decision D-W1 (maintainer): Zensical or Starlight

Verified against Zensical's own documentation on 2026-11-09, version `zensical==0.1.0` (latest on PyPI, released 2026-11-05):

| Need | Zensical 0.1.0 | Source |
|---|---|---|
| en + de in one site | **Not supported.** "Zensical only supports setting a canonical language for the entire project"; a header language selector (`[project.extra] alternate = [{ name, link, lang }]`) can only link to *separately built* sites. Internationalization appears on the roadmap without status or date. | https://zensical.org/docs/setup/language/ , https://zensical.org/roadmap/ |
| OpenAPI reference | **Not supported.** No OpenAPI plugin in the supported list; "Zensical does not currently run arbitrary MkDocs plugins"; OpenAPI references are a planned capability (API docs today only via mkdocstrings for Python). | https://zensical.org/compatibility/plugins/ , https://zensical.org/roadmap/ |
| Strict link validation | **Supported.** `strict = true` / `--strict` aborts with exit 1; `[project.validation] invalid_links`, `invalid_link_anchors`. Smoke-tested locally: a broken internal link failed the build with exit 1. | https://zensical.org/docs/setup/validation/ |

Options and their cost:

- **A — Zensical (maintainer's preference).** Two builds from one tree: `website/en/zensical.toml` (root) and `website/de/zensical.toml` (`site_dir` → `/de/`), each with its own `nav` (labels duplicated in two files instead of one label module), cross-linked via `extra.alternate`; no automatic "not translated yet" fallback — untranslated Developer/Reference pages are simply not in the German nav and link to the English site; `hreflang`/sitemap alternates handled by `alternate` only. API reference: a standalone static page that renders a committed `openapi.json` with a self-hosted renderer (e.g. Redoc or Scalar as a vendored bundle, no CDN), outside the site's navigation/search and styled separately. Gains: the tool the maintainer uses for other sites, Python-only toolchain. Risk: when Zensical ships i18n/OpenAPI, the two-build layout and the standalone API page get reworked.
- **B — Starlight, as Kept.** Native locales with fallback, `starlight-openapi` generates the API reference into the sidebar, `starlight-links-validator` checks links; a working template exists in Kept. Costs: a second Node toolchain in the repo (`website/package.json`, pnpm lock, Dependabot npm entry), Astro/Starlight upgrade churn, and not the generator the maintainer uses elsewhere.

My recommendation: **B if German must be there at launch; A if the site may launch English-only** (German as a second build later, API reference as a standalone page). Either way the content plan above stays the same.

#### Files (option A shown; for B the equivalents are `website/astro.config.mjs`, `website/src/content/docs/**`, `website/src/locales.mjs`, `website/src/sidebar-labels.mjs`, `website/package.json` pinned like Kept)

- Create: `website/requirements.txt` (`zensical==0.1.0`, bumped deliberately), `website/en/zensical.toml`, `website/de/zensical.toml`, `website/en/docs/**` and `website/de/docs/**` per the sidebar table, `website/shared/assets/` (logo/favicon from `frontend/public/brand/` (Task 5), screenshots from #260 when they exist — no placeholder images are published), `website/api/index.html` + `website/api/openapi.json` (exported by `backend/scripts/export_openapi.py`), `website/scripts/gen_config_reference.py` (writes `website/en/docs/reference/configuration.md` from the settings schema), `website/scripts/render_social_card.py` (1200×630 PNG; optional, same card for GitHub's social preview), `.github/workflows/website.yml`
- Modify: `README.md` (website link and slimmed config section), `docs/site/operations/*` and `docs/migration/labelyard.md` (pointers), `.github/dependabot.yml`, `CONTRIBUTING.md` (paragraph "Website": build and serve commands)

Zensical keys used (each from the docs, not guessed): `[project]` `site_name = "Labelyard"`, `site_url = "https://labelyard.app/"` (de: `https://labelyard.app/de/`), `site_description = "The self-hosted Label Printer Hub for all your labels"` (de: `Der selbst gehostete Label Printer Hub für all deine Etiketten`), `docs_dir = "docs"`, `site_dir` (relative), `nav`, `repo_url = "https://github.com/strausmann/labelyard"`, `repo_name = "strausmann/labelyard"`, `strict = true` — https://zensical.org/docs/setup/basics/ , /setup/navigation/ , /setup/repository/ , /setup/validation/ ; `[project.validation] invalid_links = true, invalid_link_anchors = true` — /setup/validation/ ; `[project.theme] language` (`"en"` / `"de"`) — /setup/language/ ; `logo`, `favicon` (files inside `docs_dir`) — /setup/logo-and-icons/ ; `features = ["navigation.instant", "navigation.sections", "navigation.indexes", "navigation.top", "toc.follow"]` — /setup/navigation/ ; `[project.extra] alternate = [{ name = "English", link = "/", lang = "en" }, { name = "Deutsch", link = "/de/", lang = "de" }]` — /setup/language/ . CLI: `zensical build --strict -f <config>` (`-s/--strict`, `-f/--config-file`; from `zensical build --help` of 0.1.0).

Landing page (`index.md`, both languages): wordmark, H1 `Labelyard`, subtitle `The self-hosted Label Printer Hub for all your labels`, three-sentence pitch, screenshots (#260), feature list (PT/QL tape printers, IPP page printers and sheets, scan-to-print PWA, print queue and inbox, API keys and webhooks, Snipe-IT/Grocy/Spoolman), quick start with `ghcr.io/strausmann/labelyard:1.5.0` and `LABELYARD_SECRET_KEY` / `LABELYARD_PUBLIC_URL`, links to GitHub, the GHCR package, Docker Hub and the docs groups. Brother named descriptively only (`docs/policies/trademarks.md`).

- [ ] **Step 1:** Maintainer decides D-W1; record it in ADR 0022 (or its own ADR 0023 if it grows).
- [ ] **Step 2:** Write `.github/workflows/website.yml`: on `pull_request` and `push` to `main`, `paths: ['website/**', 'backend/app/config.py', 'backend/app/settings_store/registry.py', '.github/workflows/website.yml']`. Jobs: (1) regenerate the configuration reference and the OpenAPI export, `git diff --exit-code website/` (drift check); (2) strict build of every config; (3) external link check of the built HTML with lychee (`lycheeverse/lychee-action`, pinned by commit SHA like every action here; resolve it from the latest release at implementation time), excluding `https://labelyard.app` until it is deployed. No deploy. Upload the built site as an artifact (7 days) for review.
- [ ] **Step 3:** Run the build before the pages exist → fails on the missing nav targets (strict mode bites). Then write the pages per the sidebar table.
- [ ] **Step 4:** All builds exit 0. Counter-tests: a link to `missing.md` → exit 1; an extra variable in `Settings` without regenerating → drift job red. `python3 scripts/brand_guard.py` exit 0 (the site is scanned like any live file). Open the built site locally and walk Try → Install → Admin/Upgrades in both languages.
- [ ] **Step 5:** Commit `docs(website): add the Labelyard site with audience-grouped user docs`.

### Task 8: Gate and end-to-end verification

**Files:**
- Modify: `.github/workflows/ci.yml` (new job `brand-guard`: `python3 -m unittest scripts/test_brand_guard.py` then `python3 scripts/brand_guard.py`; no `continue-on-error`)

- [ ] **Step 1:** Add the job; push the branch; CI green (all existing jobs plus `brand-guard`).
- [ ] **Step 2: Counter-test.** Temporarily add `Label Printer Hub` alone to `README.md` → `brand-guard` fails locally with `README.md:<n>: display:`; revert.
- [ ] **Step 3: Upgrade test from a 1.4.1 data volume.** Start `ghcr.io/strausmann/label-printer-hub-backend:1.4.1` with only `PRINTER_HUB_*` set on a fresh volume, create an admin key, sign in, put one item in the cart. Stop it, start the locally built `labelyard:local` with the **same** env and volume. Expected: `/healthz` 200; the existing key authenticates via `X-Label-Hub-Key` (200 on an authenticated `/api/v1` call); the browser session is still signed in and the cart survives a reload; the log shows exactly one deprecation warning listing `PRINTER_HUB_*` names and no values; `docker exec … labelyard admin create-key` and `… printer-hub admin create-key` both work.
- [ ] **Step 4:** Open the PR `feat/labelyard-rename` → `milestone/1.5.0` with the Task 1 inventory and the Step 3 results; run the internal review with the four lenses (`code-review-lenses` checklist: taint — the warning path; outcome — run the container; unchanged dependencies — `settings_store.is_locked`; temporal — workflow image ref vs. repo rename order); external bot review before merge.
- [ ] **Step 5:** After merge: run **Preview image** on `milestone/1.5.0` with version `1.5.0`; `docker pull ghcr.io/strausmann/labelyard:1.5.0-rc.N`, repeat Step 3 against it; confirm `ghcr.io/strausmann/label-printer-hub-backend` got no new tag.

### Task 9: Maintainer steps outside the repo (checklist, no code)

GitHub:
- [ ] Rename the repo `strausmann/Label-Printer-Hub` → `strausmann/labelyard` (lowercase, matching the image and avoiding the lowercasing step registries need). GitHub redirects web, API and git URLs; update local remotes anyway (`git remote set-url origin git@github.com:strausmann/labelyard.git`). Do this after Task 8 Step 5 and before the milestone PR merges.
- [ ] Description: `Labelyard — the self-hosted Label Printer Hub for Brother PT/QL label printers and office printers. Scan, print, queue, from any browser or app.`; website field: `https://labelyard.app`.
- [ ] Topics: `labelyard`, `label-printer`, `label-printer-hub`, `brother-ptouch`, `brother-ql`, `ipp`, `self-hosted`, `pwa`, `fastapi`, `homelab`.
- [ ] Social preview image from the design task (1280×640).
- [ ] GHCR: after the first push, set package `labelyard` to **public**, link it to the repo, and grant the repo the Admin role under "Manage Actions access" (needed by `ghcr-cleanup.yml`).
- [ ] Codecov and CLA assistant: confirm the next CI run uploads and the CLA check reports on a PR; re-link the repo in their dashboards if not.
- [ ] Release-run secrets (`DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`) unchanged; confirm the token may push to the new repo.

Docker Hub:
- [ ] Create repo `labelyard` (public) before the release run. Short description: `Labelyard — the self-hosted Label Printer Hub for Brother PT/QL and office printers.` Full description: README hero section, link to https://labelyard.app, image/tag table, link to the migration guide and GitHub.
- [ ] Old repo `label-printer-hub-backend`: replace the short description with `Moved to <user>/labelyard — this image is no longer updated.` and add the same line at the top of the full description. Do not delete.

Release notes (paste at the top of the `v1.5.0` GitHub Release body, above the generated notes):

```markdown
## Label Printer Hub is now Labelyard

From 1.5.0 the project is called **Labelyard** — still the self-hosted Label Printer Hub for all your labels.

**The image name changes and the old one stops here.** Change one line, pull, restart:

    image: ghcr.io/strausmann/labelyard:1.5.0     # was ghcr.io/strausmann/label-printer-hub-backend
    # or docker.io/<user>/labelyard:1.5.0

Your data, database, API keys, sign-ins and the `X-Label-Hub-Key` header keep working. `PRINTER_HUB_*` variables are still read and logged as deprecated; rename them to `LABELYARD_*` when convenient. `label-printer-hub-backend` receives no further updates — switch Watchtower or Renovate pins now.

This release also moves the API to `/api/v1` (see below). Full upgrade guide: docs/migration/labelyard.md
```

Maintainer decisions (not tasks):
- When to delete the frozen packages `label-printer-hub-backend` on GHCR and Docker Hub (suggested: not before 2.0.0; deletion breaks every `docker pull` of an old version).
- When to drop the `PRINTER_HUB_*` fallback and the `printer-hub` CLI alias (suggested: 2.0.0, announced one minor release earlier).
- Register `labelyard.dev` as well (`labelyard.app` is registered; `labelyard.com` is for sale) — only if it is to redirect to `labelyard.app`.
- Run a proper DPMA/EUIPO register search for "Labelyard" in classes 9 and 42 (the 2026-11-09 check was a web search, not a register search) before investing in a domain or logo rollout beyond the repo.

Deployment follow-ups (internal, done by the operator, no details in this repo):
- [ ] Every compose file that pins `label-printer-hub-backend` → `labelyard:1.5.0`, including the stack that serves the label hub to the inventory app.
- [ ] Update-automation pins (Watchtower scope, Renovate rules) for the new image name.
- [ ] Client integrations (inventory app, scripts): base URL unchanged, header unchanged; rename visible labels "Print-Hub"/"Label Printer Hub" to "Labelyard" where they show the product name.
- [ ] Reverse-proxy/tunnel resource: rename the **display name** only, keep the resource key.
- [ ] Container-management stack: keep the stack name (renaming creates a new stack directory); rename the container only if desired.
- [ ] Internal documentation, runbooks and the operator's agent skill for the hub: new name, new image, `labelyard admin create-key`.
- [ ] Monitoring/uptime check names.
- [ ] Website hosting: build `website/` (strict build of the chosen generator) into a static artifact or a small static-file image (non-root web server, healthcheck), deployed as a GitOps stack behind the reverse proxy.
- [ ] Proxy resource for `labelyard.app` (public, no SSO) and a permanent redirect `www.labelyard.app` → apex; TLS via the existing proxy setup; DNS already points apex + wildcard at the proxy.
- [ ] After the first deploy: drop the `--exclude https://labelyard.app` from the website link check.
- [ ] If option A (two Zensical builds): serve `/` and `/de/` from the same artifact.
