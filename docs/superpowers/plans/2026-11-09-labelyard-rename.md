# Rename "Label Printer Hub" to Labelyard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The project, its image, its web app and its documentation are called **Labelyard**, with "Label Printer Hub" kept as the descriptive subtitle, while an existing installation upgrades by changing one image line, pulling and restarting.

**Architecture:** One branch `feat/labelyard-rename`, merged as the **last** pull request into `milestone/1.5.0` before the milestone merges into `main`. A stdlib-only guard script (`scripts/brand_guard.py`) lists every remaining old name outside an explicit allow-list; it starts red, each task shrinks its output, the last task makes it a CI gate. Identifiers that live in users' data, configuration or clients stay (see the compatibility table); the environment prefix gets a new canonical name with the old one still read.

**Tech Stack:** Python 3.12 / FastAPI / pydantic-settings (backend), React + TypeScript + Lingui + Vite PWA (web app), GitHub Actions (`docker-publish.yml`, `ghcr-cleanup.yml`, `preview-image.yml`), semantic-release.

**Spec:** Maintainer decisions of 2026-11-09 (recorded below under Global Constraints and in ADR 0022, created in Task 6). There is no separate spec file; the decision record is part of this plan.

## Global Constraints

- New name: **Labelyard** (capital L only; lowercase `labelyard` in every technical identifier).
- Subtitle for findability: **Label Printer Hub**. English tagline: `Labelyard — the self-hosted Label Printer Hub for all your labels`. German tagline (informal "du"): `Labelyard — der selbst gehostete Label Printer Hub für all deine Etiketten`.
- Hard cut for images: after the cut, CI publishes (with identical tags and retention on both registries) **only** `ghcr.io/strausmann/labelyard` and `docker.io/${DOCKERHUB_USERNAME}/labelyard` (no `-backend` suffix). `ghcr.io/strausmann/label-printer-hub-backend` and `docker.io/${DOCKERHUB_USERNAME}/label-printer-hub-backend` receive no further pushes; they are not deleted by this plan.
- No transition images, no dual publishing, no retagging of old versions under the new name.
- Configuration and data compatibility: an upgrade from 1.4.x is "change the image line, pull, restart". Every break of that rule is listed in the compatibility table with its reason.
- Website: English and German always together for every page, in the same pull request (maintainer rule, enforced by the locale parity check in Task 7).
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

Release sequence (metadata in Task 9, operator steps in Task 10):

1. Merge `feat/labelyard-rename` into `milestone/1.5.0`; build preview `1.5.0-rc.N` and run the verification of Task 8.
2. Create the Docker Hub repo `labelyard` (public) and rename the GitHub repo.
3. Merge `milestone/1.5.0` → `main` (merge commit). The next release run publishes `labelyard:1.5.0` only.
4. Edit the GitHub Release body with the release-notes text of Task 10.

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
| `website/` (create) | Source of https://labelyard.app and the user docs (Task 7; Astro Starlight) |
| `scripts/registry_retention.py` (create) | One retention rule for GHCR and Docker Hub cleanup (Task 4) |
| `.github/workflows/registry-cleanup.yml` (from `ghcr-cleanup.yml`), `.github/workflows/dockerhub-description.yml`, `.github/dockerhub/README.md` | Registry housekeeping and Docker Hub page (Task 4) |
| `.github/workflows/website.yml` (create) | Freshness check, Starlight build with link validation, external link check on PRs touching `website/**` |

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

### Task 4: Image publishing, Docker Hub as full release target, registry housekeeping

Decisions:
- **Docker Hub gets exactly the tags GHCR gets:** `x.y.z`, `x.y`, `x`, `latest` for releases, `dev` from `main`, and previews `x.y.z-rc.N`. Change against today: `docker-publish.yml:386` pushes to Docker Hub only for releases without `-`; after this task the Docker Hub ref is added for every flavor that GHCR receives (release, pre-release/preview, dev). Pre-releases still get only their exact tag on both registries (no `latest`/`x.y`/`x`). Branch images stay abolished (PR #269).
- **Retention for `labelyard`, identical on both registries:** keep every release tag (`x.y.z`, `x.y`, `x`), `latest`, `dev` and open previews (`x.y.z-rc.N` whose release `x.y.z` does not exist yet); delete closed previews (release exists). On GHCR additionally delete untagged versions. Docker Hub exposes no untagged-manifest deletion through its API — untagged images there age out by Docker Hub's own policy; this is stated in the workflow header, not worked around.
- **The old packages are not cleaned any more:** after the cut `label-printer-hub-backend` (GHCR and Docker Hub) is frozen; the cleanup from PR #269 is retargeted to `labelyard`, with no job for the old name.

**Files:**
- Modify: `.github/workflows/docker-publish.yml:136-142` (ref `${REGISTRY_GHCR}/strausmann/labelyard` from a new top-level `env: IMAGE_NAME: labelyard`; no `-${matrix.service}`), `:204-213` (OCI annotations, see below), `:386` (`format('docker.io/{0}/labelyard', secrets.DOCKERHUB_USERNAME)`, condition: `secrets.DOCKERHUB_USERNAME` set, any flavor except `branch`); `.github/workflows/ghcr-cleanup.yml` → rename to `registry-cleanup.yml` with two jobs `ghcr` (existing logic, `IMAGE_PATH: ${{ github.repository_owner }}/labelyard`, keep-regex per the decision) and `dockerhub`; `.github/workflows/preview-image.yml` (`IMAGE_PATH` → `labelyard`; the rc number is computed from the GHCR tags as today — both registries receive the same number); `dev/docker-compose.smoke.yml`
- Create: `.github/workflows/dockerhub-description.yml`, `.github/dockerhub/README.md` (Docker Hub full description, ≤ 25,000 bytes), `scripts/registry_retention.py` + `scripts/test_registry_retention.py`
- `docs/decisions/0007-docker-image-tag-scheme.md` is **not** edited (history) — ADR 0022 amends it (Task 6)

OCI annotations/labels (index and per-platform; they fill the GHCR package page and link the package to the repo): `org.opencontainers.image.title=Labelyard`, `org.opencontainers.image.description=Labelyard — the self-hosted Label Printer Hub for all your labels`, `org.opencontainers.image.url=https://labelyard.app`, `org.opencontainers.image.documentation=https://labelyard.app/`, `org.opencontainers.image.source=https://github.com/strausmann/labelyard`, licences/version/revision/created as today. Same values in `backend/Dockerfile` (Task 3 sets `title`; this task aligns description/url/documentation).

**Interfaces:**
- Produces: published refs `ghcr.io/strausmann/labelyard:<tag>` and `docker.io/<DOCKERHUB_USERNAME>/labelyard:<tag>`; `select_deletions(tags: Iterable[str], releases: set[str]) -> list[str]` in `scripts/registry_retention.py` — the one rule both cleanup jobs call (CLI: `python3 scripts/registry_retention.py --releases <file> < tags.txt` prints the tags to delete).
- Docker Hub API (current reference https://docs.docker.com/reference/api/hub/latest/): list tags `GET /v2/namespaces/{namespace}/repositories/{repository}/tags` (paginated via `next`), bearer token from `POST /v2/auth/token`. **Tag deletion is not in the current reference**; the long-standing `DELETE https://hub.docker.com/v2/repositories/{namespace}/{repository}/tags/{tag}/` exists (answers `401` without auth on 2026-11-09) — confirm it in a spike before relying on it (Step 4).
- Secrets: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` (push, unchanged) and new **`DOCKERHUB_ADMIN_TOKEN`** — a Docker Hub personal access token with Read, Write, Delete permission, created by the maintainer, used only by `registry-cleanup.yml` (`dockerhub` job) and `dockerhub-description.yml`.
- Description action: `peter-evans/dockerhub-description@1b9a80c056b620d92cedb9d9b5a223409c68ddfa # v5.0.0` (latest release, 2025-10-01; inputs `username`, `password`, `repository`, `short-description`, `readme-filepath`, `enable-url-completion`; password must be a PAT with read/write/delete scope; limits: README 25,000 bytes, short description 100 bytes — from the action's README). Trigger: `workflow_dispatch` and `push` to `main` touching `.github/dockerhub/README.md`. `short-description: "Labelyard — the self-hosted Label Printer Hub for all your labels"` (66 bytes).
- The owner `strausmann` is written lowercase literally; nothing in an image ref depends on `github.repository` (it changes with the repo rename).

- [ ] **Step 1: Failing tests.** `scripts/test_registry_retention.py`: `test_keeps_releases_latest_dev` (`1.5.0`, `1.5`, `1`, `latest`, `dev` never deleted), `test_keeps_open_preview` (`1.6.0-rc.2` kept when `1.6.0` not released), `test_deletes_closed_preview` (`1.5.0-rc.1`, `1.5.0-rc.3` deleted when `1.5.0` released), `test_ignores_foreign_tags` (`sha-abc`, `feat-x` → not deleted, reported; the job prints them so a stray tag is seen, it does not guess). `scripts/test_brand_guard.py`: `test_workflows_publish_only_labelyard` (no `label-printer-hub` in the four workflow files; `IMAGE_NAME: labelyard` present; the Docker Hub ref expression in `docker-publish.yml` no longer contains `!contains(steps.tag.outputs.tag, '-')`). Run → FAIL.
- [ ] **Step 2:** Implement `select_deletions`; apply the workflow changes; write `.github/dockerhub/README.md` (hero line, `docker pull` for both registries, tag table, quick start, links to https://labelyard.app, GitHub and the migration guide; logo as absolute `raw.githubusercontent.com` URL — Docker Hub does not resolve relative paths).
- [ ] **Step 3:** Unit tests PASS; `actionlint` clean (report if unavailable, do not skip).
- [ ] **Step 4: Spike (one question, ≤ 30 min):** with `DOCKERHUB_ADMIN_TOKEN`, push a throwaway tag `labelyard:spike-delete`, delete it via the endpoint above, confirm it is gone with the list endpoint. If deletion does not work, the `dockerhub` job stays report-only (lists what it would delete, exits 0 with a summary) and that is written into the PR — no undocumented workaround.
- [ ] **Step 5:** `registry-cleanup.yml` with `workflow_dispatch` input `dry_run: true` on the branch: both jobs list the same deletions for `labelyard` (empty at first) and nothing for `label-printer-hub-backend`.
- [ ] **Step 6:** Commit `ci: publish labelyard to GHCR and Docker Hub with one tag and retention policy`.

### Task 5: Web app brand — name, PWA, icons, i18n

**Files:**
- Logo: **blue-4** (hang tag whose string forms the L). The final set is committed in `docs/brand/labelyard/` (source of truth, with `palette.md`: light tag `#3F73EC` on tile `#0B1429`, dark tag `#7FA3F5` on tile `#22366A`, contrast table). This task **copies** the files to their destinations; it never edits them — a change to the logo is made in `docs/brand/labelyard/` and copied again.

| Source (`docs/brand/labelyard/`) | Destination |
|---|---|
| `mark.svg`, `mark-dark.svg` | `frontend/public/brand/` (sidebar/app header); website theme `logo` (Task 7) |
| `lockup.svg`, `lockup-dark.svg` | README hero (`<picture>` with `prefers-color-scheme`, referenced directly from `docs/brand/labelyard/`), website landing hero, Docker Hub README (absolute `raw.githubusercontent.com` URL) |
| `wordmark.svg` | `frontend/public/brand/` — sign-in page above the tagline |
| `mark-mono.svg` | `frontend/public/brand/` — single-colour use (print, docs) |
| `favicon.svg`, `favicon.ico`, `favicon-16.png`, `favicon-32.png` | `frontend/public/`; website `favicon` |
| `apple-touch-icon.png` | `frontend/public/apple-touch-icon.png` (replace) |
| `icon-192.png`, `icon-512.png`, `icon-maskable-512.png` | `frontend/public/` (replace, same paths, so the manifest paths stay) |
| `social-card.png` (1200×630) | GitHub social preview (Task 9), website `og:image` (Task 7), `frontend/public/brand/social-card.png` |
| `icon-512.png` | Docker Hub repository logo, if the account offers one (UI only — Task 9) |

- Add a test `it("brand copies match docs/brand/labelyard")` in `frontend/src/pwa.test.ts`: every copied file is byte-identical to its source (catches a stale copy after a logo change).
- The manifest `theme_color`/`background_color` and the app's accent colour stay as they are: whether blue becomes the UI accent is decision **D-UI1** (maintainer), not part of this plan.
- Modify: `frontend/public/manifest.webmanifest` (`name: "Labelyard"`, `short_name: "Labelyard"`, `description: "Label Printer Hub — print labels, scan codes and watch your label printers."`; `id`, `start_url`, `scope`, colours unchanged), `frontend/index.html` (`<title>Labelyard</title>`, `<link rel="icon" href="/favicon.svg" type="image/svg+xml" />`, `<link rel="icon" href="/favicon.ico" sizes="32x32" />`), `frontend/src/i18n/messages.ts:8` (`appName: msg\`Labelyard\``, new `tagline: msg\`The self-hosted Label Printer Hub for all your labels\``), `frontend/src/shell/Sidebar.tsx:35`, `frontend/src/shell/SignIn.tsx:64` (wordmark image with `alt="Labelyard"` above the tagline), `frontend/package.json` (`name: "labelyard-web"`), root `package.json` (`name: "labelyard"`, description, repository url), `frontend/pnpm-lock.yaml` (regenerated by `pnpm install`), `frontend/src/i18n/locales/{en,de}/messages.po` (extracted + compiled; German tagline `Der selbst gehostete Label Printer Hub für all deine Etiketten`), `frontend/e2e/settings.spec.ts:84`, `frontend/src/pwa.test.ts`

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
- Modify: `README.md` (hero: lockup `docs/brand/labelyard/lockup.svg` with `lockup-dark.svg` via `<picture>`, H1 `Labelyard`, first line `**The self-hosted Label Printer Hub for all your labels.**`, one sentence "Formerly *Label Printer Hub*." with a link to the migration guide; a "Website: https://labelyard.app" line under the hero; badges and links to `strausmann/labelyard`; config table with `LABELYARD_*` names and a note that `PRINTER_HUB_*` is still read; image refs; `docker exec labelyard labelyard admin create-key …`), `CONTRIBUTING.md`, `SECURITY.md`, `CLA.md`, `CODE_OF_CONDUCT.md`, `THIRD_PARTY_NOTICES.md`, `.github/ISSUE_TEMPLATE/*.yml`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/copilot-instructions.md`, `CLAUDE.md`, `.gemini/*`, `codecov.yml` comment, `.releaserc.json:2` (`git@github.com:strausmann/labelyard.git`), `docs/architecture.md`, `docs/architecture/*`, `docs/site/**`, `docs/policies/*` (trademarks: add a short "Labelyard" section — our project name, no registered mark claimed), `docs/learnings/*`, `examples/compose.*.yml` (image `ghcr.io/strausmann/labelyard:1.5.0`, container/service `labelyard`, Pangolin/Traefik keys `labelyard`, `LABELYARD_HOST`), `examples/.env.example`, `examples/README.md` (client env `LABELYARD_URL`, header stays `X-Label-Hub-Key`), `licence-policy.yml` and `Makefile` if the guard lists them

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

#### Model: Kept's documentation site

Read on 2026-11-09 from `keptinventory/kept` → `apps/docs/astro.config.mjs` and `apps/docs/src/content/docs/` (live at https://keptinventory.info). Starlight 0.42.5, Astro 7.3.5, `starlight-links-validator` 0.26.0, `starlight-openapi` 0.26.3. What we copy is the **structure**, not the code:

- One docs site that *is* the user documentation (written in the site tree, not linked out to repo files), with the landing page at `/`.
- Pages keep stable URLs by topic folder (`install/`, `users/`, `admin/`, `developers/`, `reference/`); the sidebar groups them **by audience**.
- English at the root and complete; Kept translates user, admin and install pages and lets developer/reference pages fall back to English — **Labelyard does not copy that part** (see Languages below). Locale list in one module (`src/locales.mjs`), group labels per language in another (`src/sidebar-labels.mjs`).
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

Languages (binding maintainer rule): **English and German are always maintained together, for the whole site.** Every page exists in `en` (root) and `de` (`/de/`) from the first commit — landing page, Try, Install, Using, Admin, Integrations, Developers, Reference — with the same slug; German in informal "du", same tone as the web app. No Starlight "not translated yet" fallback is relied on anywhere.

The one exception, verified in `starlight-openapi` 0.27.0 source (commit `80c29f4`, 2026-10-07; https://github.com/HiDeoo/starlight-openapi): the plugin has no localisation — its section headings are hard-coded English (`Parameters`, `Responses`, `Request Body`, `Authorizations`, `Headers`, `Callbacks` in `packages/starlight-openapi/components/**`) and the operation summaries/descriptions come from our OpenAPI document, which is English. The plan registers the same schema twice, `base: "developers/api"` and `base: "de/developers/api"`, so both languages have the API reference at the same slug with German Starlight chrome and a German sidebar label (`API-Referenz`); operation text and the plugin's headings stay English. A sentence on the German Developers overview says so. If the double registration does not render under `/de/` (Task 7 Step 2 spike), the German sidebar links to the English reference — the only page not duplicated, and it is generated, not a content file.

**Link vs include — decision: move, then link back.** The audience structure and the translations need the pages inside the site tree, so the user-facing docs move there: `docs/site/operations/api-keys.md`, `docs/site/operations/templates/*`, the README configuration table and the example walkthroughs (`examples/README.md`) become site pages; `docs/migration/labelyard.md` (Task 6) becomes `admin/upgrades/from-label-printer-hub` and the old path keeps a one-line pointer (update the guard's `LEGACY_ENV_FILES` path). README keeps a short quick start and links to https://labelyard.app for the rest. Repo-internal material (ADRs, plans, research, learnings) stays out of the site.

#### Decision D-W1 (resolved 2026-11-09): Astro Starlight

The maintainer chose Starlight, structured like Kept. Reason, verified in Zensical's own docs the same day: `zensical==0.1.0` supports only one language per project (https://zensical.org/docs/setup/language/) and has no OpenAPI reference (https://zensical.org/compatibility/plugins/, https://zensical.org/roadmap/); both are required here.

Pinned versions (exact, no ranges; checked on npm 2026-11-09):

| Package | Version | Published |
|---|---|---|
| `astro` | `7.4.7` | 2026-11-05 |
| `@astrojs/starlight` | `0.42.10` (peer `astro ^7.2.10`) | 2026-11-06 |
| `starlight-openapi` | `0.27.0` (peers `astro >=7.0.2`, `@astrojs/starlight >=0.41.0`, `@astrojs/markdown-satteri >=0.3.2`) | 2026-10-07 |
| `starlight-links-validator` | `0.27.0` (peer `@astrojs/starlight >=0.42.0`) | 2026-10-09 |
| `@astrojs/markdown-satteri` | latest satisfying `>=0.3.2`, pinned exactly at implementation | — |

Node: `website/.nvmrc` = `22` (same as `frontend/.nvmrc`), `engines.node: ">=22"`, `packageManager: "pnpm@9.15.9"` (same as `frontend/package.json`).

#### Files

- Create: `website/package.json` (name `labelyard-website`, private; scripts `dev`, `build` = `node scripts/export-openapi.mjs && astro build`, `check:openapi`), `website/pnpm-lock.yaml`, `website/.nvmrc`, `website/astro.config.mjs`, `website/src/locales.mjs` (`root` = English `lang: "en"`, `de` = Deutsch `lang: "de"`), `website/src/sidebar-labels.mjs` (German label for every group), `website/src/content.config.ts` (Starlight `docsLoader`/`docsSchema`), `website/src/content/docs/**` (English, root) and `website/src/content/docs/de/**` (every page, same slugs), `website/scripts/check-locale-parity.mjs` + `website/scripts/check-locale-parity.test.mjs` (`node --test`), `website/src/styles/labelyard.css`, `website/src/assets/` (copied from `docs/brand/labelyard/`: `mark.svg`, `mark-dark.svg`, `lockup.svg`, `lockup-dark.svg`), `website/public/` (`favicon.svg`, `favicon.ico`, `social-card.png` copied from `docs/brand/labelyard/`), `website/src/route-data.ts` (`og:image`/`twitter:image` = absolute `https://labelyard.app/social-card.png`, `og:locale` per language), `website/openapi/labelyard.json` (committed, generated), `website/scripts/export-openapi.mjs` (runs `python backend/scripts/export_openapi.py` into `website/openapi/labelyard.json`), `website/scripts/gen-config-reference.py` (writes `src/content/docs/reference/configuration.md` **and** `src/content/docs/de/reference/configuration.md` from `app/config.py` + `settings_store/registry.py`; headings and intro from a two-language string table in the script, variable descriptions in both languages from a committed `website/src/config-descriptions.yml` — a variable without a German description fails generation), `.github/workflows/website.yml`
- Modify: `.github/dependabot.yml` (npm ecosystem for `/website`, grouped like `/frontend`), `README.md` (website link, slimmed config section), `docs/site/operations/*` and `docs/migration/labelyard.md` (one-line pointers after the move), `CONTRIBUTING.md` (paragraph "Website": `pnpm -C website install && pnpm -C website dev`, plus the rule below), `CLAUDE.md` and `.github/copilot-instructions.md` (same rule, short form), `.github/PULL_REQUEST_TEMPLATE.md` (checkbox "Website pages changed in English and German")

Rule text (CONTRIBUTING, verbatim): *"The website is maintained in English and German together. A change to any page under `website/src/content/docs/` is complete only when the English and the German page change in the same pull request. The `website / locale parity` check fails when a page exists in one language only."*

`astro.config.mjs` decisions (Kept's config as the model):
- `site: "https://labelyard.app"`; `starlight({ title: "Labelyard", description: "The self-hosted Label Printer Hub for all your labels", logo: { light: "./src/assets/lockup.svg", dark: "./src/assets/lockup-dark.svg", alt: "Labelyard", replacesTitle: true }, favicon: "/favicon.svg", defaultLocale: "root", locales, social: [GitHub → https://github.com/strausmann/labelyard], customCss: ["./src/styles/labelyard.css"], routeMiddleware: "./src/route-data.ts", sidebar, plugins: [starlightLinksValidator(), starlightOpenAPI([{ base: "developers/api", schema: "./openapi/labelyard.json", sidebar: { label: "API reference" } }, { base: "de/developers/api", schema: "./openapi/labelyard.json", sidebar: { label: "API-Referenz" } }])] })`.
- Sidebar built with Kept's `group(label, items)` helper that throws when a label has no entry in `sidebar-labels.mjs`, so a missing German label fails the build.
- No remote fonts, scripts or stylesheets; `ASTRO_TELEMETRY_DISABLED=1` in the package scripts.
- `labelyard.css` maps Starlight's `--sl-color-*` variables onto the web app's theme tokens (ground/text/neutral scale from `frontend/src/design/`, imported by relative path like Kept imports `apps/web/src/styles/tokens.css`). The brand blue from `docs/brand/labelyard/palette.md` appears only in the logo files; it becomes `--sl-color-accent` **only if D-UI1 decides blue is the UI accent** — until then the accent is the app's current accent token.

Parity gate `website/scripts/check-locale-parity.mjs`: exports `findParityGaps(root: string): { missingDe: string[], missingEn: string[] }` — slugs are paths under `src/content/docs/` without extension (`.md`/`.mdx` equal), English = everything outside `de/`, German = everything under `de/`; the CLI prints `missing de: using/printers` / `missing en: …` per gap and exits 1 on any gap. No allow-list (the API reference is generated by the plugin, not a content file). Tests (`node --test`): `reports a page missing in de`, `reports a page missing in en`, `md and mdx count as the same slug`, `index pages pair up` (`index.mdx` ↔ `de/index.mdx`), `passes on a complete tree`.

Landing page (`index.mdx`, `template: splash`, both languages): lockup, H1 `Labelyard`, tagline `The self-hosted Label Printer Hub for all your labels` / `Der selbst gehostete Label Printer Hub für all deine Etiketten`, three-sentence pitch, screenshots (#260; omitted until they exist, no placeholder images), feature cards (PT/QL tape printers, IPP page printers and sheets, scan-to-print PWA, print queue and inbox, API keys and webhooks, Snipe-IT/Grocy/Spoolman), quick start with `ghcr.io/strausmann/labelyard:1.5.0` and `LABELYARD_SECRET_KEY` / `LABELYARD_PUBLIC_URL`, links to GitHub, the GHCR package, Docker Hub and each docs group. Brother named descriptively only (`docs/policies/trademarks.md`).

- [ ] **Step 1:** Write `.github/workflows/website.yml`: on `pull_request` and `push` to `main` with `paths: ['website/**', 'docs/brand/labelyard/**', 'backend/app/**', '.github/workflows/website.yml']`. Jobs: (0) **locale parity** — `node website/scripts/check-locale-parity.mjs` (no install needed); (1) **freshness** — set up Python 3.12 + backend deps, run `website/scripts/export-openapi.mjs` and `gen-config-reference.py`, then `git diff --exit-code website/openapi website/src/content/docs/reference` (a changed API or setting without regenerated site files fails); (2) **build** — `pnpm/action-setup` + `actions/setup-node` with `node-version-file: website/.nvmrc`, `pnpm -C website install --frozen-lockfile`, `pnpm -C website build` (links validator fails the build on a broken internal link or anchor); (3) **external links** — lychee (`lycheeverse/lychee-action`, pinned by commit SHA like every action here; resolve it from the latest release at implementation time) over `website/dist/**/*.html`, excluding `https://labelyard.app` until it is deployed. No deploy; upload `website/dist` as an artifact (7 days) for review.
- [ ] **Step 2:** Write the parity tests, `node --test website/scripts` → FAIL; implement `check-locale-parity.mjs` → PASS. Scaffold `package.json`, config, locales, sidebar labels and one page per group in both languages; spike (≤ 30 min): does the second `starlightOpenAPI` entry render `/de/developers/api/…` with German Starlight chrome? Record the answer in the PR; `pnpm -C website build` → expect a failure from the links validator for sidebar entries whose pages do not exist yet (proves the validator runs).
- [ ] **Step 3:** Move/write the pages per the sidebar table, every page in English and German in the same commit; brand files copied from `docs/brand/labelyard/`.
- [ ] **Step 4:** `pnpm -C website build` exit 0. Counter-tests: delete `de/using/printers.md` → `locale parity` fails with `missing de: using/printers` (an English-only new page fails the same way); a link to `/using/missing/` → build fails; add a field to `Settings` without regenerating → freshness job red; drop the German label of one group → build fails. Each copied brand file is byte-identical to its source (`cmp` in the freshness job). `python3 scripts/brand_guard.py` exit 0 (the site is scanned like any live file). `pnpm -C website preview` and walk every sidebar group in English and German; the language menu switches to the same page on every page, including the API reference; the API reference lists the `/api/v1` operations.
- [ ] **Step 5:** Commit `docs(website): add the Labelyard site with audience-grouped user docs`.

### Task 8: Gate and end-to-end verification

**Files:**
- Modify: `.github/workflows/ci.yml` (new job `brand-guard`: `python3 -m unittest scripts/test_brand_guard.py` then `python3 scripts/brand_guard.py`; no `continue-on-error`)

- [ ] **Step 1:** Add the job; push the branch; CI green (all existing jobs plus `brand-guard`).
- [ ] **Step 2: Counter-test.** Temporarily add `Label Printer Hub` alone to `README.md` → `brand-guard` fails locally with `README.md:<n>: display:`; revert.
- [ ] **Step 3: Upgrade test from a 1.4.1 data volume.** Start `ghcr.io/strausmann/label-printer-hub-backend:1.4.1` with only `PRINTER_HUB_*` set on a fresh volume, create an admin key, sign in, put one item in the cart. Stop it, start the locally built `labelyard:local` with the **same** env and volume. Expected: `/healthz` 200; the existing key authenticates via `X-Label-Hub-Key` (200 on an authenticated `/api/v1` call); the browser session is still signed in and the cart survives a reload; the log shows exactly one deprecation warning listing `PRINTER_HUB_*` names and no values; `docker exec … labelyard admin create-key` and `… printer-hub admin create-key` both work.
- [ ] **Step 4:** Open the PR `feat/labelyard-rename` → `milestone/1.5.0` with the Task 1 inventory and the Step 3 results; run the internal review with the four lenses (`code-review-lenses` checklist: taint — the warning path; outcome — run the container; unchanged dependencies — `settings_store.is_locked`; temporal — workflow image ref vs. repo rename order); external bot review before merge.
- [ ] **Step 5:** After merge: run **Preview image** on `milestone/1.5.0` with version `1.5.0`; `docker pull ghcr.io/strausmann/labelyard:1.5.0-rc.N`, repeat Step 3 against it; confirm `ghcr.io/strausmann/label-printer-hub-backend` got no new tag.

### Task 9: GitHub repository, GHCR package and Docker Hub metadata

Runs after the repo rename (Task 10, first GitHub item) and before the milestone PR merges. Commands use the maintainer's `gh` login; nothing here is a CI job except the Docker Hub description workflow from Task 4.

Values:
- Description (GitHub, ≤ 350 chars): `Labelyard — the self-hosted Label Printer Hub for all your labels. Brother P-touch and QL tape printers, office printers and sheets, scan-to-print from your phone, API and webhooks.`
- Homepage: `https://labelyard.app`
- Topics (lowercase, ≤ 20): `labelyard`, `label-printer`, `label-printer-hub`, `brother`, `ptouch`, `brother-ql`, `ql-printer`, `ipp`, `label-maker`, `barcode`, `qr-code`, `grocy`, `snipe-it`, `spoolman`, `paperless`, `self-hosted`, `homelab`, `pwa`, `fastapi`
- Social preview: `docs/brand/labelyard/social-card.png` (1200×630)
- Docker Hub: short description `Labelyard — the self-hosted Label Printer Hub for all your labels`, full description `.github/dockerhub/README.md`, logo = `docs/brand/labelyard/icon-512.png`.

- [ ] **Step 1:** `gh repo edit strausmann/labelyard --description "<description>" --homepage https://labelyard.app` and `--add-topic` for each topic; remove stale topics (`gh repo view --json repositoryTopics`) that name the old project.
- [ ] **Step 2:** Upload the social preview in Settings → General → Social preview (no API for it).
- [ ] **Step 3:** After the first `labelyard` push (preview `1.5.0-rc.N`): GHCR package `labelyard` → public, "Connect repository" if not linked by `org.opencontainers.image.source`, Admin role for the repo under "Manage Actions access" (cleanup needs it). Package page shows title and description from the OCI annotations of Task 4.
- [ ] **Step 4:** Run **Docker Hub description** (`workflow_dispatch`); upload the logo in the Docker Hub UI if the account offers repository logos, otherwise note it as not possible.
- [ ] **Step 5: Verify at the outcome.** `gh api repos/strausmann/labelyard --jq '.description, .homepage, (.topics|length)'` prints the values and ≥ 15 topics; a link to the repo pasted into a chat/preview tool shows the social card; `https://github.com/users/strausmann/packages/container/package/labelyard` shows the description and the repo link; `curl -s https://hub.docker.com/v2/namespaces/<user>/repositories/labelyard | jq -r .description` prints the short description; the Docker Hub page renders the README with the logo.

### Task 10: Maintainer steps outside the repo (checklist, no code)

GitHub:
- [ ] Rename the repo `strausmann/Label-Printer-Hub` → `strausmann/labelyard` (lowercase, matching the image and avoiding the lowercasing step registries need). GitHub redirects web, API and git URLs; update local remotes anyway (`git remote set-url origin git@github.com:strausmann/labelyard.git`). Do this after Task 8 Step 5 and before the milestone PR merges.
- [ ] Repository metadata, social preview and package pages: Task 9.
- [ ] GHCR: after the first push, set package `labelyard` to **public**, link it to the repo, and grant the repo the Admin role under "Manage Actions access" (needed by `ghcr-cleanup.yml`).
- [ ] Codecov and CLA assistant: confirm the next CI run uploads and the CLA check reports on a PR; re-link the repo in their dashboards if not.
- [ ] Release-run secrets (`DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`) unchanged; confirm the token may push to the new repo.

Docker Hub:
- [ ] Create the access token `DOCKERHUB_ADMIN_TOKEN` (Read, Write, Delete) and store it as a repo secret; confirm `DOCKERHUB_TOKEN` may push to the new repo.
- [ ] Create repo `labelyard` (public) before the first preview run that pushes to Docker Hub (descriptions come from Task 9).
- [ ] Old repo `label-printer-hub-backend`: short description `Moved to <user>/labelyard — this image is no longer updated.`, same line on top of its full description. Do not delete.

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
- **D-UI1:** whether the logo's blue (`#3F73EC`, dark `#7FA3F5`, see `docs/brand/labelyard/palette.md`) becomes the web app's accent colour and PWA `theme_color`. Not decided; this plan changes no UI colours.
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
- [ ] Website hosting: build `website/` (`pnpm -C website build`, output `website/dist/`) into a static artifact or a small static-file image (non-root web server, healthcheck), deployed as a GitOps stack behind the reverse proxy.
- [ ] Proxy resource for `labelyard.app` (public, no SSO) and a permanent redirect `www.labelyard.app` → apex; TLS via the existing proxy setup; DNS already points apex + wildcard at the proxy.
- [ ] After the first deploy: drop the `--exclude https://labelyard.app` from the website link check.
