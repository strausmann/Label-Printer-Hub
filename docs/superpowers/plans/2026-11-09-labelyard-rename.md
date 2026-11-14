# Rename "Label Printer Hub" to Labelyard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The project, its image, its web app and its documentation are called **Labelyard**, with "Label Printer Hub" kept as the descriptive subtitle, while an existing installation upgrades by changing one image line, pulling and restarting.

**Architecture:** All work is committed **directly on `milestone/1.6.0`** — one commit per task step, no feature branch and no rename PR into the milestone (maintainer rule, 2026-11-11; same model as `milestone/1.5.x`). The milestone carries two plans: AGPL Part B (#154, `docs/superpowers/plans/2026-11-11-licence-part-b.md`) and this rename (#280); their joint order is fixed in the section "Order on milestone 1.6.0". At the end one PR `milestone/1.6.0` → `main`, merged with a merge commit. A stdlib-only guard script (`scripts/brand_guard.py`) lists every remaining old name outside an explicit allow-list; it stays red through all rename tasks and becomes a CI gate only in Task 11. Identifiers that live in users' data, configuration or clients stay (see the compatibility table); the environment prefix gets a new canonical name with the old one still read. The website is built in CI and deployed to GitHub Pages on `labelyard.app` from `main` only.

**Tech Stack:** Python 3.12 / FastAPI / pydantic-settings (backend), React + TypeScript + Lingui + Vite PWA (web app), Astro Starlight (website), GitHub Actions (`docker-publish.yml`, `registry-cleanup.yml`, `preview-image.yml`, `website.yml`, GitHub Pages), semantic-release.

**Spec:** Maintainer decisions of 2026-11-09 and 2026-11-11 (recorded below under Global Constraints, in issue https://github.com/strausmann/Label-Printer-Hub/issues/280 and in the rename ADR created in Task 6). There is no separate spec file; the decision record is part of this plan. Related plans: 1.5.x (`docs/superpowers/plans/2026-11-11-milestone-1-5-1.md` on `milestone/1.5.x`; its Tasks 1, 1b, 14, 23a and 23b are preconditions here) and AGPL Part B (above).

## Revision 2 (2026-11-11) — plan review NEEDS_FIXES and maintainer rules

| Finding | Handled in |
|---|---|
| B1 repo rename vs. GHCR address from `github.repository` and the nightly release | Global Constraints (explicit addresses), Timing ruling, Task 4 Decisions, Task 13 order |
| B2 `preview-image.yml` 403 on a package without tags | Timing precondition (fix belongs to 1.5.x Task 1b, checked before Task 4), Task 11 Step 5 |
| B3 previews without Docker Hub secrets | Task 4 Decisions, `test_preview_passes_docker_hub_secrets` |
| W4 `test_prerelease_never_floats_or_reaches_docker_hub` | Task 4 Step 1 (replaced by two tests) |
| W5 step id `image` / output `ref` in both jobs | Task 4 Decisions, `test_image_ref_is_explicit`, counter-test |
| W6 `extra="forbid"` with two dotenv readers | Task 2 (`PrefixFilteredDotEnvSource`, `test_dotenv_with_both_prefixes_builds`), Review Focus 3 |
| W7 release guard, open #280/#154, close milestone | Task 11 Step 6, Task 13 GitHub |
| W8 old naming (1.5.1), #269 = D4, #270 CI on `milestone/**` | Global Constraints, Timing, Tasks 10, 11 |
| W9 brand files only on the plan branch; personal mail domain in the plan | Timing precondition (merge the plan branch, order Step 0); Global Constraints (maintainer's git identity) |
| W10 tests broken by moved docs; README screenshots; German screenshot generator | Task 7 test table and Files; Task 5 Step 4b |
| W11 design skills, on-screen keyboard viewports | Task 5 UI protocol and Step 4b; Task 7 Step 4 |
| Klein: line numbers, `CANONICAL_REPO_URL`, 11 files, e2e env files, `cli` lookbehind, OCI title once, `dry-run`/`package:`, pinning test, `configure-pages`, scopes, merge method and PR title | Tasks 1–4, 7–9, Global Constraints |
| Maintainer: milestone work directly on `milestone/1.6.0`, joint order with Part B, B9 last | Architecture, Global Constraints, "Order on milestone 1.6.0" |
| "Can start before the 1.5.x release" list | merged into the order table (Steps 0–11 need no release) |
| Re-check 2026-11-11: Step 0 merges both plan branches; deploy `needs` without `freshness` until Step 19; 403/404 fix carried by the controller; Part B at `40ac022`; `github-pages` checked under the old name; guard exit 0 always in Step 20; rename right after the merge (`repositoryUrl`); local privacy scan for Steps 0–11 | Timing, order table, Tasks 7, 9, 13, Global Constraints |

## Global Constraints

- New name: **Labelyard** (capital L only; lowercase `labelyard` in every technical identifier).
- Subtitle for findability: **Label Printer Hub**. English tagline: `Labelyard — the self-hosted Label Printer Hub for all your labels`. German tagline (informal "du"): `Labelyard — der selbst gehostete Label Printer Hub für all deine Etiketten`.
- Release: **1.6.0**, its own minor release (milestone 1.6.0, branch `milestone/1.6.0`), together with AGPL Part B (#154). 1.5.0 shipped under the old name (`ghcr.io/strausmann/label-printer-hub-backend:1.5.0`); the patch milestone 1.5.x (`milestone/1.5.x`) is released **before** 1.6.0 — its release `1.5.Z` (the next free patch, 1.5.1 unless a fix was released before) is the last release under the old name.
- Branch and merge: every task commits directly on `milestone/1.6.0` (`git branch --show-current` = `milestone/1.6.0` and `git pull --ff-only` before each task). The milestone PR `milestone/1.6.0` → `main` is merged with a **merge commit** (never squash or rebase; only a merge commit keeps the commits that drive the version and makes the milestone merge visible to the release guard). PR title: `Release 1.6.0: Labelyard and AGPL Part B` — no `!`, no conventional prefix that implies a major.
- Hard cut for images: after the cut, CI publishes (with identical tags and retention on both registries) **only** `ghcr.io/strausmann/labelyard` and `docker.io/${DOCKERHUB_USERNAME}/labelyard` (no `-backend` suffix). `ghcr.io/strausmann/label-printer-hub-backend` and `docker.io/${DOCKERHUB_USERNAME}/label-printer-hub-backend` receive no further pushes; they are not deleted by this plan. Every image address is written explicitly; none is derived from `github.repository` (the repository is renamed after the milestone merge, Task 13).
- No transition images, no dual publishing, no retagging of old versions under the new name.
- Configuration and data compatibility: an upgrade from 1.5.x is "change the image line, pull, restart". Every break of that rule is listed in the compatibility table with its reason.
- Website: English and German always together for every page, in the same commit (maintainer rule, enforced by the locale parity check in Task 7). Hosted on **GitHub Pages** with the custom domain **`labelyard.app`**, deployed from `main` only; pushes to the milestone and pull requests build and check but never deploy (Task 9).
- Terminology: one canonical term per concept and language from `docs/glossary.toml` (Task 8), used by the UI catalogues and all docs; house style "German written natively, not translated word for word; informal du; short sentences; reader first".
- Public repo: English prose everywhere (commits, comments, docs). No AI attribution trailers or footers. Commits are authored with the maintainer's git identity. Stage explicit paths only and read `git status --short` before every commit.
- No private deployment details (hostnames, IPs, stack names, personal mail domains) in any file of this repo; the internal follow-ups at the end stay generic. The public GitHub Pages addresses in Task 13 are GitHub's, not ours.
- GitHub Actions in new or changed workflows are pinned by full commit SHA with the version as a comment (`uses: owner/action@<40-hex> # vX.Y.Z`), as `docker-publish.yml` and `release.yml` do; the SHA is resolved from the action's latest release at implementation time, never from memory. `test_actions_are_pinned_to_full_commit_shas` (`backend/tests/unit/test_release_workflows.py`) is extended to every workflow this plan creates or changes (Task 4, Task 7, Task 8, Task 9).
- Commit types: `feat:`/`docs:`/`ci:`/`chore:`/`test:` only. **No `!` and no `BREAKING CHANGE:` footer on any commit of this plan** — semantic-release would compute `2.0.0` instead of `1.6.0` (and so would the release guard of #270). The break is announced in the migration guide and the release notes instead.
- Commit scopes only from the `scope-enum` of `commitlint.config.cjs` (`ci`, `config`, `docker`, `docs`, `examples`, `pwa`, `ui`, `web`, `api`, `release`, `plans`, …) or no scope; `scripts` and `website` are not in the enum and are not used. Check each message as CI does (`npm install --no-save --ignore-scripts @commitlint/cli@19 @commitlint/config-conventional@19` once per clone, then `echo "<msg>" | npx commitlint --config commitlint.config.cjs`).
- CI on milestone pushes: `ci.yml` runs on `milestone/**` only from #270 (1.5.x Task 1) once it is on `main` and synced in. Until then every task runs its checks locally and records them — including the privacy scan of `ci.yml` (job `privacy-scan`: the same `git grep` IPv4 patterns with `-P` and string patterns with `-E`, the same exempt paths, copied from `ci.yml` at the time of the run, not from memory) for order Steps 0–11; the first CI run after the first sync covers everything committed before.
- Inventory baseline: counts below were measured on `main` at `045ca55` (1.5.0). 1.5.x and Part B add more occurrences; Task 1's guard output on the milestone head — and again after each Task 10 sync — is the authoritative list, not these numbers.

## Timing

**Decision (2026-11-11): own minor release 1.6.0 with AGPL Part B; the rename tasks come after the Part B tasks that touch the same files, on the same branch.**

The new image name is a change every operator has to make by hand; this plan itself rules out hiding it in a patch number, so it gets a minor release of its own milestone and its own release notes. The earlier recommendation (inside 1.5.0) is void: 1.5.0 shipped without the rename.

**Parallel 1.5.x.** `milestone/1.5.x` runs in parallel and is released first. Its changes reach `main` with the `1.5.Z` release; they still carry the old name. After every patch release on `main` (1.5.x, Dependabot or single fixes), `main` is merged into `milestone/1.6.0` (R1 pattern of the 1.5.x plan, Task 10 here) and the guard is cleared again.

Preconditions (checked at the start of the task that needs them, not up front):

- `milestone/1.6.0` exists on origin (it does, at `045ca55` = `main`).
- **Both plans and the brand files on the milestone (order Step 0).** The logo set lives only on `docs/labelyard-rename-plan` (commit `26acd5e`, `docs/brand/labelyard/`), the Part B plan only on `docs/agpl-part-b-plan`. Before Task 1 and B2: merge **both** branches into `milestone/1.6.0`, each with a merge commit (`git merge --no-ff origin/docs/labelyard-rename-plan -m "docs(plans): bring the Labelyard plan and logo set onto milestone 1.6.0"`, then `git merge --no-ff origin/docs/agpl-part-b-plan -m "docs(plans): bring the licence part B plan onto milestone 1.6.0"`), push. Both merges are conflict-free (`git merge-tree --write-tree` on 2026-11-11: `milestone/1.6.0` + rename plan, rename plan + Part B plan); re-check before merging. Plans and brand files keep their history; no cherry-picks, no copies.
- **#269 in `main`** (1.5.x Task 1b, decision D4 of the 1.5.x plan) and synced in, before Task 4 (except its spike).
- **The 403/404 fix in #269** (carried by the controller into 1.5.x Task 1b; the ruling is in the 1.5.x ledger, not in the 1.5.x plan): the tag list of a package that does not exist yet answers `403`/`404`; `preview-image.yml` (next rc) and the cleanup keep step must treat that as an empty tag list. The first `labelyard` preview (Task 11 Step 5) is exactly that case. Check before Task 4: `git grep -n -E '403|404' origin/main -- .github/workflows/preview-image.yml .github/workflows/ghcr-cleanup.yml scripts/ghcr_rules.py` shows the handling, and `scripts/test_ghcr_rules.py` has a test for it; if not, stop and report to the 1.5.x owner — it is not fixed here.
- **#270 in `main`** (1.5.x Task 1) and synced in: needed for CI on `milestone/**` and for the release guard (milestone-empty rule). This plan does not need its code otherwise; its `milestone-sync.yml` opens the Task 10 sync PRs.
- Part B's own preconditions (its section "Preconditions"; B1, B5, B6 wait for the 1.5.x sync).

**Ruling on the repository rename (Blocker 1 of the plan review):** `docker-publish.yml` (build job `:136-142`, merge job `:316-321`) derives the GHCR address from `github.repository`, and the nightly `release.yml` builds images. Task 4 writes every image address explicitly (`ghcr.io/strausmann/labelyard`), so nothing depends on the repository name any more. The repository is renamed **after** `milestone/1.6.0` is merged into `main` and **before** the next release run (Task 13 order). Everything that runs earlier — previews, metadata on the GHCR package — runs under the old repository name and must work with it.

## Order on milestone 1.6.0 (both plans)

"Part B" = `docs/superpowers/plans/2026-11-11-licence-part-b.md` (branch `docs/agpl-part-b-plan`, `40ac022`, Tasks B1–B9), "Rename" = this plan. Rules:

1. A Part B task comes before every rename task that touches one of its files (Part B's table "Files both plans touch": `docker-publish.yml` B5/B6 → Task 4; `backend/Dockerfile` B1/B2 → Task 3; `frontend/package.json`, lockfile B2 → Task 5; `frontend/playwright.config.ts` B3 → Task 2; `messages.po` B3 → Tasks 5, 8; `THIRD_PARTY_NOTICES.md` B4 → Task 6; `README.md`, `docs/supply-chain.md` B7 → Tasks 6, 7; `ci.yml` B5 → Task 11).
2. B1, B5 and B6 wait for the 1.5.x sync; the rename tasks that need neither the sync nor a waiting Part B task are pulled forward, then the order returns to Part B.
3. **B9 (SPDX headers, REUSE) is the last code task of the milestone** — after every rename task and the last sync, before the gate, the whole-branch review and the security audit (coordinator ruling 2026-11-11; it supersedes point 3 of Part B's section "Ordering with the rename", which put B9 before the first rename task, so that the rename can start early). Consequence: files the rename creates carry no SPDX header yet; B9 adds them in one sweep, and `reuse lint` becomes a CI gate only with B9.
4. The rename keeps step id `image` with output `ref` in the `merge` job of `docker-publish.yml`; Part B's `merge.outputs.image-ref` points at it (`test_sbom_uses_merge_image_ref`).
5. After every patch release on `main`: Task 10 sync before the next task.

| Step | Plan | Task | Precondition |
|---|---|---|---|
| 0 | both | Merge `docs/labelyard-rename-plan` (plan + logo set) and `docs/agpl-part-b-plan` (Part B plan) into the milestone, two merge commits | `git merge-tree` clean |
| 1 | Part B | B2 Frontend licence list and CycloneDX of the web bundle | — |
| 2 | Part B | B3 Dependency licences on the About page | B2 |
| 3 | Part B | B4 Third-party notices | B2 |
| 4 | Part B | B7 Documentation (`docs/supply-chain.md`, README link) | — |
| 5 | Rename | Task 1 Brand guard (red, not in CI) | Step 0 |
| 6 | Rename | Task 2 `LABELYARD_*` prefix | Task 1; B3 (`playwright.config.ts`) |
| 7 | Rename | Task 6 Docs, community files, examples, ADR, migration guide | B4, B7 |
| 8 | Rename | Task 7 Website — scaffold, parity, pages **without** the #20 move and without the freshness job | Step 0, Task 6 |
| 9 | Rename | Task 8 Glossary, house style, Vale | Task 7; B3 (`messages.po`) |
| 10 | Rename | Task 9 GitHub Pages deploy job | Task 7 |
| 11 | Rename | Task 4 Step 4 only (Docker Hub delete spike) and the Task 13 items that need no release: Docker Hub repo `labelyard`, `DOCKERHUB_ADMIN_TOKEN`, domain verification, DNS records, Pages settings | — |
| 12 | both | Task 10 Sync after the 1.5.x release (`1.5.Z`) | 1.5.x released |
| 13 | Part B | B1 Backend licence list in the image | Step 12 |
| 14 | Part B | B5 Provenance and image check | Step 12 |
| 15 | Part B | B6 CycloneDX SBOM of the image as release asset | B5 |
| 16 | Rename | Task 3 Backend identity | B1 (`backend/Dockerfile`), Task 2 |
| 17 | Rename | Task 4 Image publishing (rest) | B5, B6; #269 with the 403/404 fix |
| 17a | Part B | B10 Keyless cosign signature (#311, added 2026-11-13) | Task 4 |
| 18 | Rename | Task 5 Web app brand (README screenshots regenerated) | Step 12 (1.5.x UI, Task 23a generator), Task 3, B2 |
| 19 | Rename | Task 7 rest — #20 move, freshness job (and `freshness` added to the deploy job's `needs`), German screenshots | Step 12, Task 5 |
| 20 | both | Task 10 again if `main` moved since Step 12; **always** (also when `main` did not move) `python3 scripts/brand_guard.py` → exit 0 here | — |
| 21 | Part B | B9 SPDX headers and REUSE | Step 20 (final file set) |
| 22 | Rename | Task 11 Gate — guard becomes a CI job, upgrade test, preview `1.6.0-rc.N`, whole-branch review, security audit, milestone PR | Step 21 |
| 23 | Part B | B8 Live check on the preview, close #154 | Task 11 Step 5 |
| 24 | Rename | Task 11 Step 6 (#280 closed), merge, Task 13 remainder (repo rename, release, HTTPS, close milestone), Task 12 metadata | Steps 22, 23 |

The brand guard stays red until Step 19 and reaches exit 0 in Step 20; Task 11 adds it to CI.

Release sequence (metadata in Task 12, operator steps in Task 13):

1. `1.5.Z` released from `milestone/1.5.x` → `main`; Task 10 syncs it in.
2. Order table Steps 12–20 on `milestone/1.6.0`; preview `1.6.0-rc.N` and the verification of Task 11.
3. #280 and #154 closed (or labelled `release:waived-by-maintainer`), Docker Hub repo, Pages settings and DNS in place (Task 13).
4. Merge `milestone/1.6.0` → `main` (merge commit). `website.yml` deploys the site from `main`.
5. Rename the GitHub repository, then the release run publishes `labelyard:1.6.0` only.
6. Edit the GitHub Release body with the release-notes text of Task 13; enforce HTTPS once the certificate is issued; drop the link-check exclusion for `labelyard.app`; close milestone 1.6.0.

## Inventory (baseline `045ca55` = v1.5.0, history excluded)

"History" = `CHANGELOG.md`, `docs/superpowers/**`, `docs/plans/**`, `docs/designs/**`, `docs/research/**`, every ADR except the rename ADR (`docs/decisions/0001–0024` on `045ca55`), `docs/migration/v-next-single-container.md`. History is never rewritten (352 lines in the changelog, 417 lines in 50 historical docs). Counts are lines / files from `git grep` on `045ca55`, measured roughly on 2026-11-11; rows marked "≈" were not re-measured (pattern too broad for `git grep`).

| # | Category | Example | Occurrences / files | Decision |
|---|---|---|---|---|
| 1 | Image names | `label-printer-hub-backend`, `-frontend` (old docs) | 30 / 16 | **Rename** to `labelyard` (hard cut) |
| 2 | Image ref derivation | `${repo_lc}-${matrix.service}` in `docker-publish.yml`; `docker.io/{0}/label-printer-hub-{1}` | 5 / 1 | **Rename**, and hard-code the name (no longer derived from `github.repository`, which changes with the repo rename) |
| 3 | GHCR cleanup / preview package path | `IMAGE_PATH: …/label-printer-hub-backend` (PR #269, not on `main` yet) | 2 / 2 on #269 | **Rename** |
| 4 | OCI labels, `HUB_REPO_URL` | `org.opencontainers.image.title="label-printer-hub-backend"` | 13 / 8 | **Rename** |
| 5 | Repo URLs, badges, Codecov, CLA assistant | `github.com/strausmann/label-printer-hub/issues/22` | 39 / 19 (+ issue links in history) | **Rename** in live files to `github.com/strausmann/labelyard`; history keeps old links (GitHub redirects) |
| 6 | Display name | `Label Printer Hub` in UI, OpenAPI title, CLI help, docstrings | 43 / 33 | **Rename** to Labelyard; keep "Label Printer Hub" only as subtitle next to "Labelyard" |
| 7 | PWA manifest | `name`, `short_name: "Label Hub"`, `<title>` | 3 / 2 | **Rename** (`id: "/"` unchanged) |
| 8 | Environment prefix | `PRINTER_HUB_*` | 330 / 75 | **New canonical `LABELYARD_*`, old prefix still read** |
| 9 | Other env names | `PRINTHUB_PDF_FONT`, `PRINTERHUB_HOST` (examples), `LABEL_HUB_URL/KEY` (examples) | 26 / 11 | `LABELYARD_PDF_FONT` with old read; example-only vars renamed |
| 10 | API key header | `X-Label-Hub-Key` | 84 / 31 | **Keep** |
| 11 | API key prefix | `lh_…` | — | **Keep** |
| 12 | Cookies | `lph_session`, `lph_csrf` (`__Host-` over https) | 27 / 6 | **Keep** |
| 13 | Browser storage | `lph.cart`, `lph.recent.*`, `lph.lang`, `lph.theme`, `lph.printer`, `lph.sheetType.*` | 73 / 28 | **Keep** |
| 14 | Database file | `/data/printer-hub.db` | 13 / 13 | **Keep** |
| 15 | Export format id | `label-printer-hub.sheet-type` | 44 / 7 | **Keep** |
| 16 | Plugin entry-point groups | `label_hub.integrations`, `.printer_backends`, `.printer_models` | 21 / 11 | **Keep** |
| 17 | CLI | `printer-hub admin create-key` | 14 / 11 | **New `labelyard`, `printer-hub` kept as alias** |
| 18 | Package names | `label-printer-hub-backend` (pyproject), `label-printer-hub` / `label-printer-hub-web` (package.json) | ≈ 3 / 3 | **Rename** (never published) |
| 19 | Default display-name setting | `general.display_name` default `Label Printer Hub` | ≈ 1 / 1 (+ test fixtures) | **New default `Labelyard`**; stored values untouched |
| 20 | Example compose | Pangolin/Traefik keys `printerhub`, container names, hostnames `printerhub.example.*` | ≈ 25 / 6 (nicknames overall: 58 / 13) | **Rename**, with a note to keep an existing Pangolin key |
| 21 | semantic-release / package.json repository | `repositoryUrl` | ≈ 2 / 2 | **Rename** |
| 22 | Generic noun "the hub" in UI copy | "The hub could not be reached." | many | **Keep** — "hub" stays the product category, matches the subtitle |

## Compatibility decisions (why the kept identifiers stay)

| Identifier | Decision | Reason |
|---|---|---|
| Image names | Hard cut | Maintainer decision. Old packages frozen at their last 1.5.x version; deletion is a later maintainer decision (suggested: not before 2.0.0). |
| `PRINTER_HUB_*` | `LABELYARD_*` canonical; `PRINTER_HUB_*` still read at lower priority; one startup warning that lists the legacy **names** (never values); removal not before 2.0.0 | Renaming without fallback would stop every install at startup (`secret_key`, `public_url` are required). With the fallback the upgrade stays pull-and-restart. |
| Both prefixes set | `LABELYARD_*` wins, warning names the conflicting variable | Deterministic; the operator sees the leftover. |
| `PRINTHUB_PDF_FONT` | `LABELYARD_PDF_FONT` canonical, old still read | Same reason as the prefix. |
| `HUB_VERSION`, `HUB_REVISION`, `HUB_BUILD_DATE`, `HUB_REPO_URL` | Keep names, update `HUB_REPO_URL` value | Build-time image env, set by our own Dockerfile, neutral name. |
| `X-Label-Hub-Key` | Keep, no alias | Every client (other apps, scripts, webhooks) sends it; an alias doubles the auth path and the OpenAPI security scheme for no user benefit. "Label Hub" matches the subtitle. |
| `lh_` key prefix | Keep | Stored in the database (`key_prefix`), printed on existing keys. |
| `lph_session`, `lph_csrf` | Keep | Renaming signs every user out and breaks CSRF for open tabs; opaque names nobody reads. |
| `lph.*` storage keys | Keep | Renaming silently drops carts, recent lists, language and theme. |
| `/data/printer-hub.db` | Keep (also for new installs) | A new default would make every existing install start on an empty database. |
| `label-printer-hub.sheet-type` | Keep | File-format identifier; files exported by 1.4.x/1.5.x and 1.6.0 must import into each other. |
| `label_hub.*` entry-point groups | Keep | Third-party plugins register against these names. |
| CLI `printer-hub` | Keep as alias of `labelyard` | Documented in runbooks and the first-admin flow; costs one line in `pyproject.toml`. |
| `general.display_name` | New default only | An explicitly stored name is the operator's choice. |
| PWA `id: "/"` | Keep | Installed apps keep their identity and only show the new name and icon. |
| Example Pangolin resource keys | Rename in examples; migration guide says to keep the existing key | Changing a blueprint key makes Pangolin create a second resource. |
| IPP job user name | New jobs `labelyard`, old name still recognised (`LEGACY_IPP_USER_NAME` in `job_attrs.py`, accepted by `is_own_job`) | A job sent by 1.5.x can still be on the printer during the upgrade; only the old name marks it as the hub's own (restart recovery and tracking compare it). Ruling 2026-11-14. |

## Review Focus

1. Both `PRINTER_HUB_SECRET_KEY` and `LABELYARD_SECRET_KEY` set with different values → the new one is used, the warning names the variable, never a value (Task 2: `test_new_prefix_wins_over_legacy`, `test_legacy_warning_has_no_values`).
2. A legacy variable set to an empty string by compose (`${VAR:-}`) → neither overrides a new value nor locks the setting (Task 2: `test_empty_legacy_does_not_override`, `test_empty_legacy_does_not_lock`).
3. Legacy keys in the `.env` file (pydantic `env_file`), alone or mixed with `LABELYARD_` keys in the same file → still read, no `Extra inputs are not permitted` (Task 2: `test_legacy_prefix_from_dotenv`, `test_dotenv_with_both_prefixes_builds`).
4. A 1.5.x install with no `DATABASE_URL` set finds its existing `/data/printer-hub.db` (Task 3: `test_default_database_path_unchanged`).
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
| `docs/decisions/NNNN-rename-to-labelyard.md` (create; `NNNN` = next free number at implementation, `0025` on `045ca55`) | Rename ADR; amends ADR 0007 (image name) |
| `website/` (create) | Source of https://labelyard.app and the user docs (Task 7; Astro Starlight) |
| `docs/glossary.toml`, `scripts/glossary.py`, `.vale.ini`, `.vale/styles/**`, `.github/workflows/prose.yml` (create) | Terminology source, generated glossary/vocabularies, prose checks (Task 8) |
| `scripts/ghcr_rules.py` (from 1.5.x Task 1b; extended) | One keep rule for GHCR and Docker Hub cleanup (Task 4) |
| `.github/workflows/registry-cleanup.yml` (from `ghcr-cleanup.yml`), `.github/workflows/dockerhub-description.yml`, `.github/dockerhub/README.md` | Registry housekeeping and Docker Hub page (Task 4) |
| `.github/workflows/website.yml` (create) | Locale parity, freshness check, Starlight build with link validation, external link check on PRs touching `website/**`; on `main` additionally the GitHub Pages deploy (Task 9) |

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
| `cli` | `(?<!label-)printer-hub(?!\.db)` (lookbehind: `label-printer-hub` is the `slug` rule's job, so `label-printer-hub.sheet-type` stays allowed and is not reported twice) | file in `LEGACY_CLI_FILES` |
| `nickname` | `Print-Hub\|PrintHub\|printerhub\|Label[ -]Hub` (space or hyphen: the hyphenated form is how the header and prose spell it) | `Label-Hub` inside `X-Label-Hub-Key` |
| `display` | `Label Printer Hub` | the same line contains `Labelyard` |

- `EXCLUDED` (history, never scanned): `CHANGELOG.md`, `docs/superpowers/`, `docs/plans/`, `docs/designs/`, `docs/research/`, every `docs/decisions/[0-9][0-9][0-9][0-9]-*.md` **except** a file whose name ends in `-rename-to-labelyard.md` (rule by name, not by number: 1.5.x and Part B may add ADRs before the rename ADR gets its number), `docs/migration/v-next-single-container.md`, `frontend/pnpm-lock.yaml`, binary files, and the files that must name the old names to reject them: `docs/glossary.toml`, `.vale/styles/**/OldName.yml`, `.vale/styles/config/vocabularies/*/reject.txt`, `scripts/fixtures/vale/`.
- `LEGACY_ENV_FILES`: `backend/app/config_legacy.py`, `backend/app/page_render/pdf.py`, `backend/tests/unit/test_config_legacy_prefix.py`, `backend/tests/unit/test_pdf_font_env.py`, `docs/migration/labelyard.md`, `docs/decisions/*-rename-to-labelyard.md` (glob), `scripts/brand_guard.py`, `scripts/test_brand_guard.py`.
- `LEGACY_CLI_FILES`: `backend/pyproject.toml`, `backend/tests/unit/test_brand_identity.py`, `docs/migration/labelyard.md`, the two guard files.

- [ ] **Step 1: Write the failing tests** (`unittest`, temp git repo built in `setUp`): `test_slug_hit`, `test_sheet_type_format_allowed`, `test_display_alone_is_hit`, `test_display_with_labelyard_allowed`, `test_header_name_allowed` (`X-Label-Hub-Key` → no hit; the allowance is load-bearing because the pattern matches the hyphen), `test_bare_hyphenated_nickname_is_hit` (a bare `Label-Hub` prose line → `nickname`), `test_missing_git_repo_exits_2` (non-git `--root` → one-line error, exit 2), `test_db_file_allowed` (`printer-hub.db` → no hit), `test_sheet_type_not_a_cli_hit` (`label-printer-hub.sheet-type` → no hit of any rule), `test_cli_hit` (`printer-hub admin create-key` → `cli`), `test_history_excluded` (hit in `CHANGELOG.md`, `docs/decisions/0007-…` and `docs/decisions/0024-…` → none), `test_rename_adr_not_excluded` (display hit in `docs/decisions/0031-rename-to-labelyard.md` without Labelyard → hit; the number is deliberately not 0025), `test_env_prefix_allowed_in_legacy_file`, `test_exit_code` (`main` returns 1 with hits, 0 without).
- [ ] **Step 2:** `python3 -m unittest scripts/test_brand_guard.py -v` → FAIL (module missing).
- [ ] **Step 3:** Implement `scripts/brand_guard.py` (stdlib only).
- [ ] **Step 4:** Tests PASS. Run `python3 scripts/brand_guard.py | tee /tmp/brand-inventory.txt | tail -1`; expected exit 1 and a hit list. Paste the per-rule counts (`cut -d: -f3 | sort | uniq -c`) into the task report as the inventory on the milestone head (Task 10 repeats this after each sync; the milestone PR carries the first and the last list).
- [ ] **Step 5:** Commit `ci: add the brand guard script for the Labelyard rename` (the guard is not wired into CI before Task 11; it stays red until then).

### Task 2: `LABELYARD_*` environment prefix with legacy fallback

**Files:**
- Create: `backend/app/config_legacy.py`, `backend/tests/unit/test_config_legacy_prefix.py`, `backend/tests/unit/test_pdf_font_env.py`
- Modify: `backend/app/config.py:47-60` (prefix, docstrings, `settings_customise_sources`), `backend/app/main.py:51-64` (log-level check reads `LABELYARD_LOG_LEVEL`, then `PRINTER_HUB_LOG_LEVEL`, then `LOG_LEVEL`; validation messages print `LABELYARD_<FIELD>`), `backend/app/page_render/pdf.py:37-55`, every `PRINTER_HUB_` in `backend/app` docstrings and error messages (11 files besides `config.py` on `045ca55`: `api/dependencies/webhook_auth.py`, `api/routes/auth_session.py`, `api/routes/events_v1.py`, `api/routes/webhooks.py`, `db/engine.py`, `integrations/README.md`, `main.py`, `models/ui_session.py`, `printer_backends/ptouch_backend.py`, `security/secret_box.py`, `settings_store/store.py`), `backend/.env.example`, `backend/app/integrations/README.md`, backend tests that `setenv("PRINTER_HUB_…")` (switch to `LABELYARD_`, except the legacy tests), `backend/tests/e2e_app.py` (`os.environ["PRINTER_HUB_*"]` → `LABELYARD_*`, docstring line 4), `frontend/playwright.config.ts` (env passed to the e2e server)

**Interfaces:**
- Produces: `LEGACY_ENV_PREFIX = "PRINTER_HUB_"`, `ENV_PREFIX = "LABELYARD_"` in `app/config_legacy.py`; `class LegacyPrefixEnvSource(EnvSettingsSource)` and `class LegacyPrefixDotEnvSource(DotEnvSettingsSource)` (same settings class, `env_prefix=LEGACY_ENV_PREFIX`, empty strings ignored); `class PrefixFilteredDotEnvSource(DotEnvSettingsSource)` for the `LABELYARD_` `.env` reader. **Why the filter:** `Settings` keeps `extra="forbid"`, and a prototype of the two dotenv readers failed with `printer_hub_public_url: Extra inputs are not permitted` — each dotenv reader passes keys of the other prefix through as extras. So the `LABELYARD_` dotenv reader drops every key starting with `PRINTER_HUB_`, and the legacy dotenv reader drops every key starting with `LABELYARD_`; unknown keys with their **own** prefix keep today's behaviour; `legacy_env_report(environ: Mapping[str, str], dotenv_keys: Iterable[str]) -> LegacyReport` with `LegacyReport(used: list[str], shadowed: list[str])` (variable names only); `warn_legacy_env(report: LegacyReport, logger: logging.Logger) -> None` — one `WARNING` line per list, e.g. `Deprecated PRINTER_HUB_* variables in use, rename them to LABELYARD_*: PRINTER_HUB_SECRET_KEY, …`.
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
  - `test_dotenv_with_both_prefixes_builds`: `.env` with `LABELYARD_SECRET_KEY` and `PRINTER_HUB_PUBLIC_URL` → `Settings()` builds, both values set (red on the unfiltered prototype with the `Extra inputs are not permitted` error, which is the counter-test).
  - `test_dotenv_unknown_own_prefix_unchanged`: `.env` with `LABELYARD_NO_SUCH_FIELD=x` behaves exactly as `PRINTER_HUB_NO_SUCH_FIELD=x` does on `045ca55` (measure first with a scratch run, then pin that outcome — error or ignore — in the test).
  - `test_pdf_font_env.py`: `test_new_font_env_wins`, `test_legacy_font_env_read`.
- [ ] **Step 2:** `cd backend && pytest tests/unit/test_config_legacy_prefix.py tests/unit/test_pdf_font_env.py -v` → FAIL.
- [ ] **Step 3:** Implement as in Interfaces; switch existing backend tests to `LABELYARD_`.
- [ ] **Step 4:** `pytest -q` (full backend suite) PASS; `ruff check . && ruff format --check . && mypy app` clean. Counter-test: remove the two legacy sources from `settings_customise_sources` → `test_legacy_prefix_read`, `test_legacy_prefix_from_dotenv` and `test_legacy_var_locks_setting` go red; remove the prefix filter → `test_dotenv_with_both_prefixes_builds` goes red with `Extra inputs are not permitted`; restore. `pnpm -C frontend exec playwright test settings` PASS (e2e server starts on `LABELYARD_*`).
- [ ] **Step 5:** Commit `feat(config): read LABELYARD_* settings and keep PRINTER_HUB_* as a fallback`.

### Task 3: Backend identity — CLI, OpenAPI, defaults, image labels

**Files:**
- Create: `backend/tests/unit/test_brand_identity.py`
- Modify: `backend/pyproject.toml` (`name = "labelyard"`, description `Labelyard — the self-hosted Label Printer Hub (backend and web app server)`, scripts `labelyard = "app.cli:main"` **and** `printer-hub = "app.cli:main"`), `backend/app/cli.py` (`prog="labelyard"`, description `Labelyard admin`, key note `created with: labelyard admin create-key`), `backend/app/main.py:568-570` and `backend/app/web/api_docs.py:35` (title `Labelyard API`, description starts `REST + SSE API of Labelyard, the self-hosted Label Printer Hub, …`), `backend/app/settings_store/registry.py:31` (default `Labelyard`), `backend/app/__init__.py:1`, `backend/app/main.py:155-156` (`HUB_REPO_URL` default), `backend/app/build_info.py:15` (`CANONICAL_REPO_URL = "https://github.com/strausmann/labelyard"`) and `backend/Dockerfile:120-145` (`org.opencontainers.image.title="Labelyard"` — the **display** title, capital L, the same string as the workflow annotation in Task 4; the lowercase `labelyard` is the image **name** only, description `Labelyard — the self-hosted Label Printer Hub for Brother PT/QL and office printers`, url/source/documentation `https://github.com/strausmann/labelyard`, `HUB_REPO_URL` same), `backend/README.md`, `frontend/src/api/schema.gen.ts` (regenerated), any committed OpenAPI snapshot the completeness test compares

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
  - `test_source_url`: info endpoint `source_url == "https://github.com/strausmann/labelyard"` and `build_info.CANONICAL_REPO_URL` equals it.
- [ ] **Step 2:** `pytest tests/unit/test_brand_identity.py -v` → FAIL on the renamed ones, PASS on the compat ones.
- [ ] **Step 3:** Apply the modifications; regenerate the schema with `python backend/scripts/export_openapi.py` and the frontend type generator the repo uses (`pnpm -C frontend run gen:api` or the documented equivalent); update fixtures that assert the old title/default (`frontend/src/test-utils.tsx`, `frontend/src/features/test-api.ts`).
- [ ] **Step 4:** Full backend suite and `pnpm -C frontend test` PASS; `docker build -f backend/Dockerfile -t labelyard:local .` succeeds and `docker inspect labelyard:local --format '{{index .Config.Labels "org.opencontainers.image.title"}}'` prints `Labelyard`. `pytest backend/tests/unit/test_licence_metadata.py backend/tests/integration/api/test_info.py backend/tests/integration/test_healthz.py` PASS (they read `HUB_REPO_URL`/`CANONICAL_REPO_URL`).
- [ ] **Step 5:** Commit `feat: name the backend, CLI and API Labelyard`.

### Task 4: Image publishing, Docker Hub as full release target, registry housekeeping

**Preconditions:** #269 merged into `main` (1.5.x Task 1b) with its 403/404 handling (Timing), synced into `milestone/1.6.0`; Part B B5 and B6 committed on the milestone. Step 4 (spike) may run earlier (order table Step 11). If a precondition is missing, stop and report; do not plan around it.

Decisions:
- **Every image address is explicit.** Top-level `env: IMAGE_NAME: labelyard` in `docker-publish.yml`; the GHCR ref is `${{ env.REGISTRY_GHCR }}/strausmann/${{ env.IMAGE_NAME }}` in both the build job (`:136-142`) and the merge job (`:316-321`). Nothing reads `github.repository` for an image address. **The step id `image` and its output `ref` stay in both jobs** — Part B's `merge.outputs.image-ref` and every `steps.image.outputs.ref` consumer (`:205`, `:236`, `:385`, `:418` on Part B's branch) depend on them (`test_sbom_uses_merge_image_ref`). The lowercase step loses its `REPO` env and `${REPO,,}`; its comment explains that the name is fixed because the repository is renamed after the milestone merge.
- **Docker Hub gets exactly the tags GHCR gets:** `x.y.z`, `x.y`, `x`, `latest` for releases, `dev` from `main`, and previews `x.y.z-rc.N`. Change against today: `docker-publish.yml:386` (merge job, the only Docker Hub line) pushes to Docker Hub only for releases without `-`; after this task the Docker Hub ref is added for every flavor that GHCR receives (release, pre-release/preview, dev). Pre-releases still get only their exact tag on both registries (no `latest`/`x.y`/`x`). Branch images stay abolished (#269).
- **Previews reach Docker Hub:** the `publish` job of `preview-image.yml` calls `docker-publish.yml` without secrets today; it gets `secrets: { DOCKERHUB_USERNAME: ${{ secrets.DOCKERHUB_USERNAME }}, DOCKERHUB_TOKEN: ${{ secrets.DOCKERHUB_TOKEN }} }`, passed by name as `release.yml:124-126` does (no `secrets: inherit`). Its header comment ("no Docker Hub") is corrected.
- **Retention for `labelyard`, identical on both registries:** keep every release tag (`x.y.z`, `x.y`, `x`), `latest`, `dev` and open previews (`x.y.z-rc.N` whose release `x.y.z` does not exist yet); delete closed previews (release exists). On GHCR additionally delete untagged versions as #269 does (platform children and attestations of kept images stay). Docker Hub exposes no untagged-manifest deletion through its API — untagged images there age out by Docker Hub's own policy; this is stated in the workflow header, not worked around.
- **One rule, one script:** the keep rule lives in `scripts/ghcr_rules.py` (1.5.x Task 1b: `keep_regex`, `next_preview_tag`). This task adds `select_deletions(tags: Iterable[str], released: set[str]) -> list[str]` there and the Docker Hub job calls the same script; no second retention script. The file keeps its name (renaming it is not part of this plan).
- **The old packages are not cleaned any more:** after the cut `label-printer-hub-backend` (GHCR and Docker Hub) is frozen; the cleanup is retargeted to `labelyard`, with no job for the old name.
- **OCI title defined once:** `org.opencontainers.image.title=Labelyard` (capital L, display title) — the same string in `backend/Dockerfile` (Task 3) and in the build job's `labels` (`:204-213`) and the merge job's `annotations` (`:400-409`) of `docker-publish.yml`; the image **name** is lowercase `labelyard`. A test compares them (Step 1).
- `test_image_labels_and_licence_file` counts `licenses=AGPL-3.0-or-later` exactly twice in `docker-publish.yml` (Part B constraint): the annotation edit adds no further `licenses=` text.

**Files:**
- Modify: `.github/workflows/docker-publish.yml:136-142` and `:316-321` (ref steps, see Decisions), `:204-213` (labels) and `:400-409` (annotations), `:386` (`format('docker.io/{0}/labelyard', secrets.DOCKERHUB_USERNAME)`, condition: `secrets.DOCKERHUB_USERNAME` set, any flavor except `branch`); `.github/workflows/ghcr-cleanup.yml` → `git mv` to `registry-cleanup.yml` with two jobs `ghcr` (existing logic; `IMAGE_PATH: ${{ github.repository_owner }}/labelyard` → write `strausmann/labelyard` literally; the cleanup action input `package: label-printer-hub-backend` → `package: labelyard`; the `workflow_dispatch` input keeps its name `dry-run`) and `dockerhub`; `.github/workflows/preview-image.yml` (`IMAGE_PATH` → `strausmann/labelyard`, Docker Hub secrets on `publish`, header comment; the rc number is computed by `ghcr_rules.next_preview_tag` from the GHCR tags as today — both registries receive the same number); `dev/docker-compose.smoke.yml`; `scripts/ghcr_rules.py`, `scripts/test_ghcr_rules.py`; `backend/tests/unit/test_release_workflows.py` (see Step 1); `CONTRIBUTING.md` paragraph on previews (Docker Hub now included)
- Create: `.github/workflows/dockerhub-description.yml`, `.github/dockerhub/README.md` (Docker Hub full description, ≤ 25,000 bytes)
- `docs/decisions/0007-docker-image-tag-scheme.md` is **not** edited (history) — the rename ADR amends it (Task 6)

OCI annotations/labels (index and per-platform; they fill the GHCR package page and link the package to the repo): `org.opencontainers.image.title=Labelyard`, `org.opencontainers.image.description=Labelyard — the self-hosted Label Printer Hub for all your labels`, `org.opencontainers.image.url=https://labelyard.app`, `org.opencontainers.image.documentation=https://labelyard.app/`, `org.opencontainers.image.source=https://github.com/strausmann/labelyard`, licences/version/revision/created as today. Same values in `backend/Dockerfile` (Task 3 sets `title`; this task aligns description/url/documentation). Until the repository rename (Task 13) the `source` URL points at a repository name that does not exist yet; the GHCR package is linked by hand after the rename (Task 12 Step 3).

**Interfaces:**
- Consumes: `keep_regex`, `next_preview_tag` from `scripts/ghcr_rules.py` (1.5.x Task 1b); Part B's `merge.outputs.image-ref`.
- Produces: published refs `ghcr.io/strausmann/labelyard:<tag>` and `docker.io/<DOCKERHUB_USERNAME>/labelyard:<tag>`; `select_deletions(tags, released)` and CLI `python3 scripts/ghcr_rules.py select-deletions --released <file> < tags.txt` (prints the tags to delete, one per line; foreign tags on stderr).
- Docker Hub API (current reference https://docs.docker.com/reference/api/hub/latest/): list tags `GET /v2/namespaces/{namespace}/repositories/{repository}/tags` (paginated via `next`), bearer token from `POST /v2/auth/token`. **Tag deletion is not in the current reference**; the long-standing `DELETE https://hub.docker.com/v2/repositories/{namespace}/{repository}/tags/{tag}/` exists (answers `401` without auth on 2026-11-09) — confirm it in a spike before relying on it (Step 4). A `404` on the tag list of a repository that has no tags yet is an empty list (same rule as the GHCR 403/404 fix).
- Secrets: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` (push, unchanged) and new **`DOCKERHUB_ADMIN_TOKEN`** — a Docker Hub personal access token with Read, Write, Delete permission, created by the maintainer, used only by `registry-cleanup.yml` (`dockerhub` job) and `dockerhub-description.yml`.
- Description action: `peter-evans/dockerhub-description@1b9a80c056b620d92cedb9d9b5a223409c68ddfa # v5.0.0` (latest release, 2025-10-01 — re-resolve at implementation; inputs `username`, `password`, `repository`, `short-description`, `readme-filepath`, `enable-url-completion`; password must be a PAT with read/write/delete scope; limits: README 25,000 bytes, short description 100 bytes — from the action's README). Trigger: `workflow_dispatch` and `push` to `main` touching `.github/dockerhub/README.md`. `short-description: "Labelyard — the self-hosted Label Printer Hub for all your labels"` (66 bytes).

- [ ] **Step 1: Failing tests.**
  - `scripts/test_ghcr_rules.py`: `test_select_keeps_releases_latest_dev` (`1.6.0`, `1.6`, `1`, `latest`, `dev` never deleted), `test_select_keeps_open_preview` (`1.7.0-rc.2` kept when `1.7.0` not released), `test_select_deletes_closed_preview` (`1.6.0-rc.1`, `1.6.0-rc.3` deleted when `1.6.0` released), `test_select_ignores_foreign_tags` (`sha-abc`, `feat-x` → not deleted, reported on stderr), `test_select_agrees_with_keep_regex` (for a mixed tag list, `select_deletions` deletes exactly the tags `keep_regex` does not match — one rule for both registries).
  - `backend/tests/unit/test_release_workflows.py`: replace `test_prerelease_never_floats_or_reaches_docker_hub` (`:56-68`) by `test_prerelease_never_floats` (the `{{major}}.{{minor}}`, `{{major}}` and `latest` lines keep the `!contains(steps.tag.outputs.tag, '-')` guard) and `test_docker_hub_gets_every_flavor_but_branch` (every `docker.io/` `format(` line names `labelyard`, requires `secrets.DOCKERHUB_USERNAME`, excludes `branch`, and no longer contains the `-` guard); add `test_image_ref_is_explicit` (build and merge job both have a step `id: image` whose `run` writes `ref=` with `strausmann/${{ env.IMAGE_NAME }}` and contains no `github.repository`; top-level `env.IMAGE_NAME == "labelyard"`), `test_preview_passes_docker_hub_secrets` (`preview-image.yml` job `publish` passes exactly `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` by name, no `inherit`), `test_cleanup_targets_labelyard_only` (`registry-cleanup.yml`: `package: labelyard`, input `dry-run`, no `label-printer-hub`), `test_oci_title_matches_dockerfile` (title and description in the `labels` and `annotations` blocks equal the `LABEL` values in `backend/Dockerfile`); extend `test_actions_are_pinned_to_full_commit_shas` to `registry-cleanup.yml`, `preview-image.yml`, `dockerhub-description.yml`.
  - Run → FAIL (the old Docker Hub test passes on the old file; that is why it is replaced, not kept).
- [ ] **Step 2:** Implement `select_deletions` and the CLI; apply the workflow changes; write `.github/dockerhub/README.md` (hero line, `docker pull` for both registries, tag table, quick start, links to https://labelyard.app, GitHub and the migration guide; logo as absolute `raw.githubusercontent.com` URL — Docker Hub does not resolve relative paths).
- [ ] **Step 3:** Unit tests PASS, including Part B's `test_sbom_uses_merge_image_ref` and `test_image_labels_and_licence_file`; `actionlint` clean (report if unavailable, do not skip). Counter-tests: rename step id `image` to `ref` in the merge job → `test_sbom_uses_merge_image_ref` red; put `${REPO,,}` back → `test_image_ref_is_explicit` red; drop the secrets from `publish` → `test_preview_passes_docker_hub_secrets` red; restore each.
- [ ] **Step 4: Spike (one question, ≤ 30 min, may run early):** with `DOCKERHUB_ADMIN_TOKEN`, push a throwaway tag `labelyard:spike-delete`, delete it via the endpoint above, confirm it is gone with the list endpoint. If deletion does not work, the `dockerhub` job stays report-only (lists what it would delete, exits 0 with a summary) and that is written into the task report — no undocumented workaround.
- [ ] **Step 5:** `registry-cleanup.yml` with `workflow_dispatch` input `dry-run: true` on `milestone/1.6.0`: both jobs list the same deletions for `labelyard` (empty at first — the 404/403 path) and nothing for `label-printer-hub-backend`.
- [ ] **Step 6:** Commit `ci(docker): publish labelyard to GHCR and Docker Hub with one tag and retention rule`.

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
| `social-card.png` (1200×630) | GitHub social preview (Task 12), website `og:image` (Task 7), `frontend/public/brand/social-card.png` |
| `icon-512.png` | Docker Hub repository logo, if the account offers one (UI only — Task 12) |

- Add a test `it("brand copies match docs/brand/labelyard")` in `frontend/src/pwa.test.ts`: every copied file is byte-identical to its source (catches a stale copy after a logo change).
- The manifest `theme_color`/`background_color` and the app's accent colour stay as they are: D-UI1 (2026-11-09): blue stays logo-only, the accent stays amber.
- Modify: `frontend/public/manifest.webmanifest` (`name: "Labelyard"`, `short_name: "Labelyard"`, `description: "Label Printer Hub — print labels, scan codes and watch your label printers."`; `id`, `start_url`, `scope`, colours unchanged), `frontend/index.html` (`<title>Labelyard</title>`, `<link rel="icon" href="/favicon.svg" type="image/svg+xml" />`, `<link rel="icon" href="/favicon.ico" sizes="32x32" />`), `frontend/src/i18n/messages.ts:8` (`appName: msg\`Labelyard\``, new `tagline: msg\`The self-hosted Label Printer Hub for all your labels\``), `frontend/src/shell/Sidebar.tsx:35`, `frontend/src/shell/SignIn.tsx:64` (wordmark image with `alt="Labelyard"` above the tagline), `frontend/package.json` (`name: "labelyard-web"`), root `package.json` (`name: "labelyard"`, description, repository url), `frontend/pnpm-lock.yaml` (regenerated by `pnpm install`), `frontend/src/i18n/locales/{en,de}/messages.po` (extracted + compiled; German tagline `Der selbst gehostete Label Printer Hub für all deine Etiketten`), `frontend/e2e/settings.spec.ts:84`, `frontend/src/pwa.test.ts`

- UI protocol (`.claude`-side rule of the maintainer, same as 1.5.x): before writing UI code load `taste-skill:design-taste-frontend`, `emil-design-eng` and `mobile-native`; if a skill is not available in the session, report it, do not build without it.
- README screenshots from 1.5.x Task 23a (`docs/screenshots/*.png`) show the old name and logo after this task: regenerate them with `pnpm -C frontend screenshots` in Step 4 and commit them with this task.

**Interfaces:**
- Consumes: Task 3 display-name default `Labelyard` (Sidebar falls back to `appName`); the screenshot generator of 1.5.x Task 23a.
- Produces: `appName`, `tagline` message descriptors.

- [ ] **Step 1: Write the failing tests** in `frontend/src/pwa.test.ts`: `it("carries the Labelyard name")` — `m.name === "Labelyard"`, `m.short_name === "Labelyard"`, `m.short_name.length <= 12`, `m.description` contains `Label Printer Hub`, `m.id === "/"`; `it("every manifest icon exists")` — each `icons[].src` and shortcut icon resolves to a file in `public/`; `it("index.html names the app and links the favicon")` — `<title>Labelyard</title>` and `href="/favicon.svg"`. In `SignIn` test: heading/wordmark accessible name `Labelyard`; tagline text present in `en` and in `de` (`Der selbst gehostete Label Printer Hub für all deine Etiketten`).
- [ ] **Step 2:** `pnpm -C frontend test -- pwa SignIn` → FAIL.
- [ ] **Step 3:** Apply the changes; `pnpm -C frontend run i18n:extract && pnpm -C frontend run i18n:compile` (use the script names in `frontend/package.json`); translate the new German strings with "du".
- [ ] **Step 4:** `pnpm -C frontend test`, `pnpm -C frontend run lint`, `pnpm -C frontend run build` PASS; `pnpm -C frontend exec playwright test settings archive` PASS (archive e2e must still see `label-printer-hub.sheet-type`).
- [ ] **Step 4b: Look at it.** Sign-in page with the wordmark and the sidebar at 1280 × 800 and 390 × 844, light and dark, and with the on-screen keyboard open (#279 viewports 390 × 400 and 1280 × 500, focus in the username field): wordmark, tagline and the focused field stay visible, nothing overlaps, no horizontal scroll. Screenshots are artifacts in the task report, not a gate. Then `pnpm -C frontend screenshots`; review each regenerated PNG by eye (new name and logo, no old name).
- [ ] **Step 5:** Commit `feat(web): show the Labelyard name, logo and tagline` (includes `docs/screenshots/*.png`).

### Task 6: Docs, community files, examples, ADR and migration guide

**Files:**
- Create: `docs/migration/labelyard.md`, `docs/decisions/NNNN-rename-to-labelyard.md` (next free number at implementation time — `0025` on `045ca55`, higher if 1.5.x or Part B adds ADRs; status Accepted, amends ADR 0007 image name, lists the compatibility table), entries in `docs/decisions/README.md` and `docs/decisions/register.md`
- Modify: `README.md` (hero: lockup `docs/brand/labelyard/lockup.svg` with `lockup-dark.svg` via `<picture>`, H1 `Labelyard`, first line `**The self-hosted Label Printer Hub for all your labels.**`, one sentence "Formerly *Label Printer Hub*." with a link to the migration guide; a "Website: https://labelyard.app" line under the hero; badges and links to `strausmann/labelyard`; config table with `LABELYARD_*` names and a note that `PRINTER_HUB_*` is still read; image refs; `docker exec labelyard labelyard admin create-key …`), `CONTRIBUTING.md`, `SECURITY.md`, `CLA.md`, `CODE_OF_CONDUCT.md`, `THIRD_PARTY_NOTICES.md`, `.github/ISSUE_TEMPLATE/*.yml`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/copilot-instructions.md`, `CLAUDE.md`, `.gemini/*`, `codecov.yml` comment, `docs/architecture.md`, `docs/architecture/*`, `docs/site/**`, `docs/policies/*` (trademarks: add a short "Labelyard" section — our project name, no registered mark claimed), `docs/learnings/*`, `examples/compose.*.yml` (image `ghcr.io/strausmann/labelyard:1.6.0`, container/service `labelyard`, Pangolin/Traefik keys `labelyard`, `LABELYARD_HOST`), `examples/.env.example`, `examples/README.md` (client env `LABELYARD_URL`, header stays `X-Label-Hub-Key`), `licence-policy.yml` and `Makefile` if the guard lists them

**Interfaces:**
- Consumes: the names this plan pins for Tasks 2–5 (Task 6 runs before Tasks 3–5 in the order table; those tasks make the documented names true).
- Produces: `docs/migration/labelyard.md` sections (exact headings): `## What changes`, `## Upgrade in three steps`, `## What stays the same`, `## Environment variables`, `## Reverse proxy and Pangolin`, `## Old images`.

Migration guide content to pin:

- Three steps: (1) change `image:` to `ghcr.io/strausmann/labelyard:1.6.0` (or `docker.io/<user>/labelyard:1.6.0`); (2) pull; (3) restart. Data volume, database file, API keys, sessions and the `X-Label-Hub-Key` header keep working.
- Optional: rename `PRINTER_HUB_*` to `LABELYARD_*`; the old names are read until at least 2.0.0 and logged as deprecated at startup.
- Pangolin: keep your existing resource key; changing it creates a new resource.
- Old images receive no updates; Watchtower/Renovate pinned to them will never offer 1.6.0.
- Coming from 1.4.x: upgrade the API clients for 1.5.0 first (`/api/v1` paths without compatibility) — link to the 1.5.0 release notes; the rename itself changes no API path.

- [ ] **Step 1:** `python3 scripts/brand_guard.py` → list for docs/examples/community files (expected non-zero).
- [ ] **Step 2:** Apply the changes. Repo links: `github.com/strausmann/label-printer-hub` and `github.com/strausmann/Label-Printer-Hub` → `github.com/strausmann/labelyard` in live files only.
- [ ] **Step 3:** `python3 scripts/brand_guard.py | grep -E '^(README\.md|CONTRIBUTING\.md|SECURITY\.md|CLA\.md|CODE_OF_CONDUCT\.md|THIRD_PARTY_NOTICES\.md|docs/|examples/|\.github/(ISSUE_TEMPLATE|PULL_REQUEST))'` → empty (the guard as a whole stays red until Step 20 of the order table). `pytest backend/tests/unit/test_licence_metadata.py` PASS (`test_readme_states_licence_history` needs `HUB_REPO_URL` in the README; Part B's `test_supply_chain_doc` and the README link to `docs/supply-chain.md` stay). `docker compose -f examples/compose.standalone.yml config --quiet` (and the caddy/traefik/pangolin variants with a dummy `.env`) succeeds; then **start** `compose.standalone.yml` against an image built locally from the milestone head (`docker build -f backend/Dockerfile -t labelyard:local .`; `IMAGE` override or temporary edit) and confirm `/healthz` returns 200 — a syntax check alone does not prove the example starts. Run the repo's markdown link check if one exists.
- [ ] **Step 4:** Commit `docs: rename the project to Labelyard`. Note: Task 6 runs before Task 3 (order table); README sentences that describe the CLI or OpenAPI title already use the new names, which Task 3 then makes true.

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
| Try | `try/` — what it is, screenshots (#260); the in-browser demo with fake printers ("Try Labelyard", like Kept's try-app) is a separate future issue, not part of this plan |
| Install | `install/` — compose (standalone), reverse proxy (Caddy, Traefik, Pangolin), HTTPS, hardware/printer connection |
| Using | `using/` — printers (PT/QL tape, IPP page printers), sheets and layouts, print inbox and queue, scanning, cart and bulk print, glossary (Task 8) |
| Admin | `admin/` — API keys, users and SSO, backups and restore, upgrades (incl. *Coming from Label Printer Hub*), security model, troubleshooting |
| Integrations | `integrations/` — Snipe-IT, Grocy, Spoolman (plugins); Paperless and Kept as apps that print through the API; webhooks |
| Developers | `developers/` — API reference (generated), architecture, plugin authoring, contributing, writing the docs (house style, Task 8) |
| Reference | `reference/configuration` — every `LABELYARD_*` variable, generated from `app/config.py` + `settings_store/registry.py` |

Languages (binding maintainer rule): **English and German are always maintained together, for the whole site.** Every page exists in `en` (root) and `de` (`/de/`) from the first commit — landing page, Try, Install, Using, Admin, Integrations, Developers, Reference — with the same slug; German in informal "du", same tone as the web app. No Starlight "not translated yet" fallback is relied on anywhere.

The one exception, verified in `starlight-openapi` 0.27.0 source (commit `80c29f4`, 2026-10-07; https://github.com/HiDeoo/starlight-openapi): the plugin has no localisation — its section headings are hard-coded English (`Parameters`, `Responses`, `Request Body`, `Authorizations`, `Headers`, `Callbacks` in `packages/starlight-openapi/components/**`) and the operation summaries/descriptions come from our OpenAPI document, which is English. The plan registers the same schema twice, `base: "developers/api"` and `base: "de/developers/api"`, so both languages have the API reference at the same slug with German Starlight chrome and a German sidebar label (`API-Referenz`); operation text and the plugin's headings stay English. A sentence on the German Developers overview says so. If the double registration does not render under `/de/` (Task 7 Step 2 spike), the German sidebar links to the English reference — the only page not duplicated, and it is generated, not a content file.

**Link vs include — decision: move, then link back.** The audience structure and the translations need the pages inside the site tree, so the user-facing docs move there: `docs/site/operations/api-keys.md`, `docs/site/operations/templates/*`, the README configuration table, the example walkthroughs (`examples/README.md`) and the project docs written for #20 in 1.5.x (table below) become site pages; `docs/migration/labelyard.md` (Task 6) becomes `admin/upgrades/from-label-printer-hub` and the old path keeps a one-line pointer (update the guard's `LEGACY_ENV_FILES` path). README keeps a short quick start and links to https://labelyard.app for the rest. Repo-internal material (ADRs, plans, research, learnings) stays out of the site.

Project docs from #20 (written in 1.5.x Task 23b, reach the milestone through the Task 10 sync; paths as named there — if 1.5.x lands them elsewhere, the guard/`git log` on the synced head decides, the targets stay):

| Source after 1.5.x | Site page (en root + `de/`, same slug) | Old path afterwards |
|---|---|---|
| `docs/getting-started.md` (deployment, PWA install on the phone, notifications) | `install/getting-started` (first entry of the Install group) | one-line pointer to https://labelyard.app/install/getting-started/ |
| `docs/plugin-development.md` | `developers/plugin-authoring` | pointer |
| `docs/architecture.md` | `developers/architecture` | pointer |
| `docs/architecture/sse.md` | `developers/architecture/sse` | pointer |

They arrive English-only; the German pages are written in Task 7's second part (order table Step 19), in the same commit as the move, so the parity check never sees one language alone. README and CONTRIBUTING links to the old paths switch to the site URLs.

Tests that name moved files (update them in the same commit as the move, never weaken them):

| Test | What it pins | Change |
|---|---|---|
| 1.5.x Task 23b guard (`test_architecture_paths_exist`, in `backend/tests/unit/test_docs_paths.py`) | every code path cited in `architecture.md` / `plugin-development.md` exists | point it at `website/src/content/docs/developers/architecture.md`, `…/plugin-authoring.md` **and** their `de/` pages |
| `test_readme_states_licence_history` (`backend/tests/unit/test_licence_metadata.py:46`) | README names `HUB_REPO_URL` and the licence history | README slimming keeps that paragraph |
| Part B `test_supply_chain_doc` (constant `SUPPLY_CHAIN_DOC = "docs/supply-chain.md"`) | supply-chain how-to content | if the page moves into the site (`admin/supply-chain`, en + de), update `SUPPLY_CHAIN_DOC` to the English site page, leave a pointer at `docs/supply-chain.md`; the README keeps its link |

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

Node: `website/.nvmrc` = `22` (same as `frontend/.nvmrc`), `engines.node: ">=22.23.4"` (the minimum of `astro` 7.4.7), `packageManager: "pnpm@9.15.9"` (same as `frontend/package.json`).

#### Files

- Create: `website/package.json` (name `labelyard-website`, private; scripts `dev`, `build` = `node scripts/export-openapi.mjs && astro build`, `check:openapi`), `website/pnpm-lock.yaml`, `website/.nvmrc`, `website/astro.config.mjs`, `website/src/locales.mjs` (`root` = English `lang: "en"`, `de` = Deutsch `lang: "de"`), `website/src/sidebar-labels.mjs` (German label for every group), `website/src/content.config.ts` (Starlight `docsLoader`/`docsSchema`), `website/src/content/docs/**` (English, root) and `website/src/content/docs/de/**` (every page, same slugs), `website/scripts/check-locale-parity.mjs` + `website/scripts/check-locale-parity.test.mjs` (`node --test`), `website/src/styles/labelyard.css`, `website/src/assets/` (copied from `docs/brand/labelyard/`: `mark.svg`, `mark-dark.svg`, `lockup.svg`, `lockup-dark.svg`), `website/public/` (`favicon.svg`, `favicon.ico`, `social-card.png` copied from `docs/brand/labelyard/`), `frontend/e2e/readme-screenshots.spec.ts` and `frontend/playwright.screenshots.config.ts` (1.5.x Task 23a: add the `de` locale and write WebP copies to `website/src/assets/screens/<shot>.<en|de>.<light|dark>.webp` via `frontend/scripts/optimise-screenshots.mjs`), `website/src/route-data.ts` (`og:image`/`twitter:image` = absolute `https://labelyard.app/social-card.png`, `og:locale` per language), `website/openapi/labelyard.json` (committed, generated), `website/scripts/export-openapi.mjs` (runs `python backend/scripts/export_openapi.py` into `website/openapi/labelyard.json`), `website/scripts/gen-config-reference.py` (writes `src/content/docs/reference/configuration.md` **and** `src/content/docs/de/reference/configuration.md` from `app/config.py` + `settings_store/registry.py`; headings and intro from a two-language string table in the script, variable descriptions in both languages from a committed `website/src/config-descriptions.yml` — a variable without a German description fails generation), `.github/workflows/website.yml`
- Modify: `.github/dependabot.yml` (npm ecosystem for `/website`, grouped like `/frontend`), `README.md` (website link, slimmed config section), `docs/site/operations/*`, `docs/migration/labelyard.md`, `docs/getting-started.md`, `docs/plugin-development.md`, `docs/architecture.md`, `docs/architecture/sse.md` (one-line pointers after the move), `CONTRIBUTING.md` (paragraph "Website": `pnpm -C website install && pnpm -C website dev`, plus the rule below), `CLAUDE.md` and `.github/copilot-instructions.md` (same rule, short form), `.github/PULL_REQUEST_TEMPLATE.md` (checkbox "Website pages changed in English and German")

Rule text (CONTRIBUTING, verbatim): *"The website is maintained in English and German together. A change to any page under `website/src/content/docs/` is complete only when the English and the German page change in the same pull request. The `website / locale parity` check fails when a page exists in one language only."*

`astro.config.mjs` decisions (Kept's config as the model):
- `site: "https://labelyard.app"`; `starlight({ title: "Labelyard", description: "The self-hosted Label Printer Hub for all your labels", logo: { light: "./src/assets/lockup.svg", dark: "./src/assets/lockup-dark.svg", alt: "Labelyard", replacesTitle: true }, favicon: "/favicon.svg", defaultLocale: "root", locales, social: [GitHub → https://github.com/strausmann/labelyard], customCss: ["./src/styles/labelyard.css"], routeMiddleware: "./src/route-data.ts", sidebar, plugins: [starlightLinksValidator(), starlightOpenAPI([{ base: "developers/api", schema: "./openapi/labelyard.json", sidebar: { label: "API reference" } }, { base: "de/developers/api", schema: "./openapi/labelyard.json", sidebar: { label: "API-Referenz" } }])] })`.
- Sidebar built with Kept's `group(label, items)` helper that throws when a label has no entry in `sidebar-labels.mjs`, so a missing German label fails the build.
- No remote fonts, scripts or stylesheets; `ASTRO_TELEMETRY_DISABLED=1` in the package scripts.
- `labelyard.css` maps Starlight's `--sl-color-*` variables onto the web app's theme tokens (ground/text/neutral scale from `frontend/src/design/`, imported by relative path like Kept imports `apps/web/src/styles/tokens.css`). The brand blue from `docs/brand/labelyard/palette.md` appears only in the logo files; per D-UI1 the accent stays the app's amber accent token.

Parity gate `website/scripts/check-locale-parity.mjs`: exports `findParityGaps(root: string): { missingDe: string[], missingEn: string[] }` — slugs are paths under `src/content/docs/` without extension (`.md`/`.mdx` equal), English = everything outside `de/`, German = everything under `de/`; the CLI prints `missing de: using/printers` / `missing en: …` per gap and exits 1 on any gap. No allow-list (the API reference is generated by the plugin, not a content file). Tests (`node --test`): `reports a page missing in de`, `reports a page missing in en`, `md and mdx count as the same slug`, `index pages pair up` (`index.mdx` ↔ `de/index.mdx`), `passes on a complete tree`.

Screenshots (maintainer decision): the generator from #260 renders every screenshot from the e2e fixtures in **en and de, light and dark** — four files per shot, named `website/src/assets/screens/<shot>.<en|de>.<light|dark>.webp`. Pages use the file of their own language inside `<picture>` with a `prefers-color-scheme: dark` source; README and the Docker Hub README use the `en` pair the same way. `check-locale-parity.mjs` also exports `findScreenshotGaps(dir: string): string[]` (a shot missing any of its four variants) — test `reports a screenshot missing its de dark variant`; the CLI fails on it like on a page gap.

Landing page (`index.mdx`, `template: splash`, both languages): lockup, H1 `Labelyard`, tagline `The self-hosted Label Printer Hub for all your labels` / `Der selbst gehostete Label Printer Hub für all deine Etiketten`, three-sentence pitch, screenshots (#260; omitted until they exist, no placeholder images) in the page's language and in both themes, feature cards (PT/QL tape printers, IPP page printers and sheets, scan-to-print PWA, print queue and inbox, API keys and webhooks, Snipe-IT/Grocy/Spoolman), quick start with `ghcr.io/strausmann/labelyard:1.6.0` and `LABELYARD_SECRET_KEY` / `LABELYARD_PUBLIC_URL`, links to GitHub, the GHCR package, Docker Hub and each docs group. Brother named descriptively only (`docs/policies/trademarks.md`).

- [ ] **Step 1:** Write `.github/workflows/website.yml`: on `pull_request` and `push` to `main` and `milestone/**` with `paths: ['website/**', 'docs/brand/labelyard/**', 'backend/app/**', '.github/workflows/website.yml']`. Jobs: (0) **locale parity** — `node website/scripts/check-locale-parity.mjs` (no install needed); (1) **freshness** — **only in the second part (order Step 19)**, when the API and settings of 1.5.x are on the milestone: set up Python 3.12 + backend deps, run `website/scripts/export-openapi.mjs` and `gen-config-reference.py`, then `git diff --exit-code website/openapi website/src/content/docs/reference` (a changed API or setting without regenerated site files fails); (2) **build** — `pnpm/action-setup` + `actions/setup-node` with `node-version-file: website/.nvmrc`, `pnpm -C website install --frozen-lockfile`, `pnpm -C website build` (links validator fails the build on a broken internal link or anchor); (3) **external links** — lychee (`lycheeverse/lychee-action`, pinned by commit SHA like every action here; resolve it from the latest release at implementation time) over `website/dist/**/*.html`, excluding `https://labelyard.app` (`--exclude '^https://(www\.)?labelyard\.app'`) until the first GitHub Pages deploy is live with HTTPS (removed in Task 13). No deploy in this task — Task 9 adds the deploy job; upload `website/dist` as an artifact (7 days) for review.
- [ ] **Step 2:** Write the parity tests, `node --test website/scripts` → FAIL; implement `check-locale-parity.mjs` → PASS. Scaffold `package.json`, config, locales, sidebar labels and one page per group in both languages; spike (≤ 30 min): does the second `starlightOpenAPI` entry render `/de/developers/api/…` with German Starlight chrome? Record the answer in the PR; `pnpm -C website build` → expect a failure from the links validator for sidebar entries whose pages do not exist yet (proves the validator runs).
- [ ] **Step 3:** Move/write the pages per the sidebar table, every page in English and German in the same commit; brand files copied from `docs/brand/labelyard/`.
- [ ] **Step 4:** `pnpm -C website build` exit 0. Counter-tests: delete `de/using/printers.md` → `locale parity` fails with `missing de: using/printers` (an English-only new page fails the same way); a link to `/using/missing/` → build fails; (second part only) add a field to `Settings` without regenerating → freshness job red; drop the German label of one group → build fails. Each copied brand file is byte-identical to its source (`cmp` step in the `build` job, so it runs from the first part on). `python3 scripts/brand_guard.py | grep '^website/'` empty (the site is scanned like any live file; the whole guard reaches exit 0 only in order Step 20). Extend `test_actions_are_pinned_to_full_commit_shas` to `website.yml`. Landing page and one page per group checked at 1280 × 800 and 390 × 844, light and dark, after loading `taste-skill:design-taste-frontend`, `emil-design-eng` and `mobile-native` (report a missing skill). `pnpm -C website preview` and walk every sidebar group in English and German; the language menu switches to the same page on every page, including the API reference; the API reference lists the `/api/v1` operations.
- [ ] **Second part (order Step 19), in addition to the move:** commit the OpenAPI document — remove the `website/openapi/labelyard.json` line from `.gitignore` and commit the generated file with the freshness job.
- [ ] **Second part (order Step 19):** turn the old user docs into one-line pointers to their site pages — `docs/site/operations/api-keys.md`, `docs/site/operations/templates/*`, `examples/README.md` walkthroughs, the README configuration table, `docs/migration/labelyard.md` (keep the guard's `LEGACY_*` entries in step) — after diffing each old file against its site page so nothing only the old file says is lost.
- [ ] **Step 5:** Commit `docs: add the Labelyard site with audience-grouped user docs` (first part, order Step 8); the second part (order Step 19: #20 move, freshness job, German screenshots, test updates from the table above) commits `docs: move the project docs into the Labelyard site`.

### Task 8: Glossary, house style and Vale

One terminology source feeds the website glossary, the prose linter and a check of the UI catalogues, so the three cannot drift.

**House style** (rule text for `CONTRIBUTING.md` section "Writing", short form in `CLAUDE.md` and `.github/copilot-instructions.md`, full form on the website page `developers/writing-docs` in en and de): *"Write for the reader: what they want to do, then how. Short sentences, one idea each. German is written natively, not translated word for word, and addresses the reader as „du". Use the glossary term for every concept, in both languages. A change to the docs is complete only with English and German in the same pull request."*

**Glossary** — source `docs/glossary.toml` (stdlib `tomllib`), one entry per concept: `id`, `en`, `de`, `definition_en`, `definition_de`, optional `reject_en = [...]`, `reject_de = [...]`. Starting set (German terms marked † are not in the 1.4.1 catalogue yet; the maintainer confirmed all four on 2026-11-09 — Druckeingang, Rolle, Vorlage, Stapel; the others are the terms the catalogue already uses most):

| id | en | de | reject_de |
|---|---|---|---|
| sheet | sheet | Bogen | — |
| cell | cell | Zelle | — |
| sheet-type | sheet type | Bogentyp | — |
| inbox | print inbox | Druckeingang † | `Inbox`, `Posteingang` |
| tape | tape | Band | `Schriftband` |
| roll | roll | Rolle † | — |
| template | template | Vorlage † | `Template` |
| printer | printer | Drucker | — |
| tray | tray | Fach | `Schacht` |
| calibration | calibration | Kalibrierung | — |
| preview | preview | Vorschau | — |
| job | print job | Auftrag | `Job`, `Druckjob` |
| batch | batch | Stapel † | `Batch` |
| queue | queue | Warteschlange | `Queue` |
| label | label | Etikett | `Label` (except in the product subtitle and `X-Label-Hub-Key`) |
| api-key | API key | API-Schlüssel | `API-Key` |

Product-name entries (both languages): accept `Labelyard`; reject `Label Printer Hub` except on a line that also contains `Labelyard` (the subtitle rule of the brand guard), and reject `printer-hub`, `Print-Hub`, `PrintHub`.

**Vale** — verified 2026-11-09: Vale `v3.26.0` (released 2026-10-31, https://github.com/errata-ai/vale/releases); config reference https://docs.vale.sh/topics/.vale.ini.md (a later matching section replaces `BasedOnStyles`; a section may name its own `Vocab` from v3.22.0); vocabularies https://docs.vale.sh/keys/vocabularies.md (`<StylesPath>/config/vocabularies/<name>/accept.txt|reject.txt`, `reject.txt` entries are errors via `Vale.Avoid`). Packages: the official package library (`errata-ai/packages`, `library.json`) has **no German style**; for English only `write-good` `v0.4.1` (https://github.com/vale-cli/write-good) is used, and of it only `Weasel` and `TooWordy`; `MDX` `v0.3.0` for `.mdx` comments. German rules are our own. `Vale.Spelling` is off in both languages (dictionaries for product terms and German compounds would make the check red without a defect).

Levels — **error fails CI, warning and suggestion are reported only:**

| Rule | Level | en | de |
|---|---|---|---|
| `Vale.Avoid` from `reject.txt` (old names, rejected glossary terms) | error | ✓ | ✓ |
| `Labelyard.OldName` / `Labelyard-de.OldName` (existence; `Label Printer Hub` without `Labelyard` on the line) | error | ✓ | ✓ |
| `Labelyard.Terms` / `Labelyard-de.Terms` (substitution, rejected → canonical glossary term) | warning | ✓ | ✓ |
| `…Filler` (existence: en `simply`, `just`, `basically`, `obviously`, `easily`; de `einfach`, `eigentlich`, `halt`, `natürlich`, `ja` as filler is not matchable and is left out) | warning | ✓ | ✓ |
| `…SentenceLength` (occurrence, scope `sentence`, max tokens en 30, de 25) | warning | ✓ | ✓ |
| `write-good.Weasel`, `write-good.TooWordy` | suggestion | ✓ | — |

Scope: `README.md`, `CONTRIBUTING.md`, `docs/**/*.md` except the history paths of the brand guard (`docs/superpowers/`, `docs/plans/`, `docs/designs/`, `docs/research/`, every ADR except the rename ADR (same rule as the guard), `docs/migration/v-next-single-container.md`), `website/src/content/docs/**/*.{md,mdx}`. Code blocks are not linted (Vale default). Sections: `[*.{md,mdx}]` → `BasedOnStyles = Vale, Labelyard, write-good`, `Vocab = Labelyard-en`; then `[website/src/content/docs/de/**/*.{md,mdx}]` → `BasedOnStyles = Vale, Labelyard-de`, `Vocab = Labelyard-de`.

**Files:**
- Create: `docs/glossary.toml`, `scripts/glossary.py` + `scripts/test_glossary.py`, `.vale.ini`, `.vale/styles/Labelyard/{OldName,Terms,Filler,SentenceLength}.yml`, `.vale/styles/Labelyard-de/{OldName,Terms,Filler,SentenceLength}.yml`, `.vale/styles/config/vocabularies/Labelyard-en/{accept,reject}.txt`, `.vale/styles/config/vocabularies/Labelyard-de/{accept,reject}.txt`, `website/src/content/docs/using/glossary.md`, `website/src/content/docs/de/using/glossary.md`, `website/src/content/docs/developers/writing-docs.md` + `de/` counterpart, `.github/workflows/prose.yml`, `scripts/fixtures/vale/rejected-term.md` (counter-test fixture, outside the linted scope)
- Modify: `CONTRIBUTING.md`, `CLAUDE.md`, `.github/copilot-instructions.md`, `.gitignore` (`.vale/styles/write-good/`, `.vale/styles/MDX/` — installed by `vale sync`), `frontend/src/i18n/locales/de/messages.po` and docs pages where the catalogue check or Vale flags a rejected term

**Interfaces:**
- Produces: `load_glossary(path: Path) -> list[Term]`; `render(terms, target: Literal["glossary-en", "glossary-de", "vale-terms-en", "vale-terms-de", "accept-en", "reject-en", "accept-de", "reject-de"]) -> str`; CLI `python3 scripts/glossary.py write` (regenerates the two glossary pages, the two `Terms.yml` and the four vocabulary files) and `python3 scripts/glossary.py check-catalog frontend/src/i18n/locales/de/messages.po` (exit 1 when a `msgstr` contains a `reject_de` term as a whole word; English catalogue against `reject_en`). Generated files carry a header line `Generated from docs/glossary.toml — edit that file`.

- [ ] **Step 1: Failing tests** (`scripts/test_glossary.py`): `test_every_term_has_both_languages` (a term without `de` or `definition_de` → error naming the id), `test_rendered_glossary_pages_pair` (en and de page list the same ids in the same order), `test_reject_list_written`, `test_catalog_check_flags_rejected` (`msgstr "Der Job läuft"` → hit `job`), `test_catalog_check_ignores_substrings` (`Jobs` inside `Jobsuche` → no hit; `Label` inside `X-Label-Hub-Key` → no hit). Run → FAIL.
- [ ] **Step 2:** Implement `scripts/glossary.py`; write `docs/glossary.toml`; `python3 scripts/glossary.py write`; write the Vale styles and `.vale.ini`; `vale sync`.
- [ ] **Step 3:** `.github/workflows/prose.yml` on `pull_request`/`push` to `main` and `milestone/**` with `paths: ['**/*.md', '**/*.mdx', '.vale.ini', '.vale/**', 'docs/glossary.toml', 'frontend/src/i18n/locales/**']`: install Vale `v3.26.0` from the release archive with its published checksum (or `errata-ai/vale-action` `v3.0.0`, pinned by commit SHA), `vale sync`; job **errors**: `vale --minAlertLevel=error <scope>` (fails on any error); job **report**: `vale --minAlertLevel=suggestion --no-exit <scope>` (warnings and suggestions in the job summary, never failing); job **glossary**: `python3 scripts/glossary.py write && git diff --exit-code` plus `check-catalog` for both catalogues.
- [ ] **Step 4: Start small, then green.** Run the errors job locally on `milestone/1.6.0`; fix every error in the live files (they are real: old names, rejected terms). If a rule produces an error that is not a defect, narrow the rule — never add `continue-on-error` or lower the job; record each narrowing in the PR. Warnings are triaged, not fixed in this PR unless trivial.
- [ ] **Step 5: Counter-tests.** `vale --minAlertLevel=error scripts/fixtures/vale/rejected-term.md` (contains `printer-hub` and `Label Printer Hub` alone) → exit 1 with `Vale.Avoid` and `Labelyard.OldName`; copy one German page with `Druckjob` into a temp path under the de glob → `Vale.Avoid` error; a sentence of 40 words → warning only, exit 0.
- [ ] **Step 6:** Extend `test_actions_are_pinned_to_full_commit_shas` to `prose.yml`. Commit `docs: add the glossary, house style and Vale prose checks`.

### Task 9: Deploy the website to GitHub Pages (labelyard.app)

Decisions:
- **Publishing source: GitHub Actions** (`build_type: workflow`), not a branch. GitHub's docs on custom domains: when publishing from a custom Actions workflow "no `CNAME` file is created, and any existing `CNAME` file is ignored and is not required" (https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site). So there is **no** `website/public/CNAME`; the custom domain `labelyard.app` lives in the repository's Pages settings (Task 13). Astro's `site: "https://labelyard.app"` (Task 7) stays the single in-repo statement of the domain.
- **Deploy only from `main`:** the `deploy` job runs only for `push` to `main` and `workflow_dispatch` on `main`; pushes to `milestone/1.6.0` and pull requests build, check and upload the review artifact as in Task 7 and never deploy (`website.yml` triggers on `milestone/**` pushes too). The environment `github-pages` additionally allows deployments from `main` only (Task 13) — a second layer, not the primary one.
- **Gates of the deploy:** `needs: [parity, build]` from this task (order Step 10) until Task 7's second part (order Step 19) adds the `freshness` job — then `needs: [parity, freshness, build]`, in the same commit as the job. A `needs` entry naming a job that does not exist makes the whole workflow invalid on every milestone push, so the entry never comes before the job. The external link job (`links`) is **not** a deploy gate: a third-party site being down must not stop a docs deploy (it stays a failing check on pull requests and is reported on `main`).
- **HTTPS:** "Enforce HTTPS" is switched on in Task 13 once GitHub has issued the certificate; `www.labelyard.app` redirects to the apex by GitHub Pages itself once both records exist.
- One deployment at a time: job-level `concurrency: { group: pages, cancel-in-progress: false }`.

**Files:**
- Modify: `.github/workflows/website.yml` (from Task 7): add `workflow_dispatch`; in the `build` job, on `main` only, `actions/upload-pages-artifact` (`path: website/dist`) — **no `actions/configure-pages`**: the site is at the domain root with a fixed `site` in `astro.config.mjs`, so there is nothing to configure, and the step would need `pages: read` on the build job; new job `deploy` (`environment: { name: github-pages, url: ${{ steps.deployment.outputs.page_url }} }`, `permissions: { pages: write, id-token: write }`, step `actions/deploy-pages` with `id: deployment`); top-level `permissions: {}`, every job names its own. Both Pages actions are pinned by commit SHA resolved from their latest releases at implementation time (Global Constraints) — https://github.com/actions/upload-pages-artifact/releases, https://github.com/actions/deploy-pages/releases.
- Modify: `CONTRIBUTING.md` paragraph "Website" (one sentence: merged changes go live on https://labelyard.app from `main`; pull requests only build).

**Interfaces:**
- Consumes: `website/dist` from the Task 7 `build` job; jobs `parity`, `build`, `links` (`freshness` from order Step 19).
- Produces: job `deploy`, environment `github-pages`, output `page_url` (`https://labelyard.app/` once the custom domain is set).

- [ ] **Step 1:** Edit `website.yml` as above. `actionlint .github/workflows/website.yml` clean (report if unavailable, do not skip).
- [ ] **Step 2: Counter-test on a milestone push.** For the run on `milestone/1.6.0`, `gh run view <id> --json jobs --jq '.jobs[] | [.name, .conclusion] | @tsv'` lists `deploy` as `skipped` and `parity`, `build` as `success` (and `freshness` once Step 19 has added it); the run carries the review artifact and no `github-pages` artifact. The job must be **skipped by its `if:`**, not **failed by the environment rule** — a `failure` here means the primary guard is missing and only the second layer caught it.
- [ ] **Step 3: Job graph check.** `yq '.jobs.deploy.needs' .github/workflows/website.yml` lists exactly `parity`, `build` (after order Step 19: `parity`, `freshness`, `build`; Step 19 repeats this check), and every name in it is a job of the file (`actionlint` reports an unknown `needs` too), and `yq '.jobs.deploy.if'` requires `github.ref == 'refs/heads/main'` and `github.event_name != 'pull_request'` (report if `yq` is unavailable and read the file instead). Counter-test: a `workflow_dispatch` run on `milestone/1.6.0` shows `deploy` as `skipped`.
- [ ] **Step 4:** Commit `ci: deploy labelyard.app to GitHub Pages from main`.
- [ ] **Step 5 (after the milestone merges, together with Task 13 "GitHub Pages and DNS"):** the first `push` to `main` runs `deploy`; outcome checks are listed in Task 13.

### Task 10: Sync the 1.5.x release and clear the guard

Runs after `v1.5.Z` is tagged on `main` (order Step 12) and again after every later patch release on `main` before the milestone PR merges (Step 20, R1 pattern). The last run brings the guard to exit 0.

**Interfaces:**
- Consumes: `scripts/brand_guard.py` (Task 1), the #20 mapping table and parity check (Task 7), the glossary checks (Task 8).
- Produces: `milestone/1.6.0` that contains `main` (`git merge-base --is-ancestor origin/main HEAD` → exit 0) and a guard with exit 0.

- [ ] **Step 1: Sync the milestone.** Open the PR `main` → `milestone/1.6.0` titled `chore: sync main into milestone/1.6.0` (normally opened by `milestone-sync.yml` from #270; by hand if it is not on `main` yet); merge it with a **merge commit**, never squash or rebase (only a merge commit makes `main` an ancestor). Check: `git fetch && git merge-base --is-ancestor origin/main origin/milestone/1.6.0` → exit 0.
- [ ] **Step 2:** `git pull --ff-only` on `milestone/1.6.0`. Conflicts are resolved in the sync PR towards the new names, keeping both sides' content; a conflict resolution that touches audited code is listed for the Task 11 security audit (a sync after the audit makes it stale).
- [ ] **Step 3:** `python3 scripts/brand_guard.py | cut -d: -f3 | sort | uniq -c` → the hits the release introduced (expected at least the #20 docs and anything 1.5.x added to README, examples, UI copy or env docs). Paste the list into the task report under "after the `1.5.Z` sync".
- [ ] **Step 4: Clear each hit by its inventory category** (the decision column of the inventory table, nothing new decided here): renamed strings → new name; new `PRINTER_HUB_*` mentions in docs → `LABELYARD_*` (new settings fields need no code change, the Task 2 sources read both prefixes; regenerate `website/openapi/labelyard.json` and the configuration reference); the #20 docs → move to their site pages with German counterparts per the Task 7 table; new ADRs from 1.5.x stay untouched (history by the guard's name rule); new UI strings → `messages.po` extract/compile and the glossary `check-catalog`.
- [ ] **Step 5: Verify.** On the last run `python3 scripts/brand_guard.py` exit 0 (earlier runs: no hit in files the sync brought); `python3 -m unittest scripts/test_brand_guard.py` PASS (incl. `test_history_excluded`); backend `pytest -q`, `pnpm -C frontend test`, `pnpm -C website build`, `node website/scripts/check-locale-parity.mjs`, `vale --minAlertLevel=error` on the Task 8 scope — all green. `git diff origin/milestone/1.6.0...HEAD --stat -- CHANGELOG.md docs/superpowers docs/plans docs/designs docs/research` is empty for files the release added (history is not rewritten).
- [ ] **Step 6:** Commit `chore: carry the 1.5.Z changes over to the Labelyard names` (no `!`).

### Task 11: Gate and end-to-end verification

**Files:**
- Modify: `.gitleaks.toml` (title and description only; the rule id `labelhub-pat` and the `lh_pat_` regex stay)
- Modify: `scripts/brand_guard.py` (`LEGACY_ENV_FILES` gains `backend/app/config.py`, `backend/app/main.py`, `backend/.env.example`, which describe the fallback; `LEGACY_SLUG_FILES` for the migration guide and the rename ADR exists since the Task 6 fix round)
- Modify: `.github/workflows/ci.yml` (new job `brand-guard`: `python3 -m unittest scripts/test_brand_guard.py` then `python3 scripts/brand_guard.py`; no `continue-on-error`)

- [ ] **Step 1:** Precondition: Task 10 done for the latest release on `main` (`git merge-base --is-ancestor origin/main HEAD` → exit 0). Add the job; push `milestone/1.6.0`; CI green (all existing jobs plus `brand-guard`).
- [ ] **Step 2: Counter-test.** Temporarily add `Label Printer Hub` alone to `README.md` → `brand-guard` fails locally with `README.md:<n>: display:`; revert.
- [ ] **Step 3: Upgrade test from a `1.5.Z` data volume** (the last release under the old name). Start `ghcr.io/strausmann/label-printer-hub-backend:1.5.Z` with only `PRINTER_HUB_*` set on a fresh volume, create an admin key, sign in, put one item in the cart. Stop it, start the locally built `labelyard:local` with the **same** env and volume. Expected: `/healthz` 200; the existing key authenticates via `X-Label-Hub-Key` (200 on an authenticated `/api/v1` call); the browser session is still signed in and the cart survives a reload; the log shows exactly one deprecation warning listing `PRINTER_HUB_*` names and no values; `docker exec … labelyard admin create-key` and `… printer-hub admin create-key` both work.
- [ ] **Step 4: Whole-branch review and security audit** over `origin/main...milestone/1.6.0` (both plans), after B9 (order Step 21): one reviewer with the whole repo and the four lenses (`code-review-lenses`: taint — the legacy-env warning path and Part B's licence lists; outcome — run the container; unchanged dependencies — `settings_store.is_locked`, `steps.image.outputs.ref` consumers; temporal — image ref vs. repository rename order, release guard vs. open issues); then the `security-audit` skill (6 phases) on the changed surface. HIGH/CRITICAL block. A later sync or rebase makes both stale; rerun them on the conflict hunks.
- [ ] **Step 5: Preview.** Run **Preview image** on `milestone/1.6.0` with version `1.6.0` (first push of the package `labelyard` — the 403/404 path of #269); `docker pull ghcr.io/strausmann/labelyard:1.6.0-rc.N` and `docker pull docker.io/<DOCKERHUB_USERNAME>/labelyard:1.6.0-rc.N`, repeat Step 3 against it; confirm `ghcr.io/strausmann/label-printer-hub-backend` got no new tag. Part B's B8 runs on this preview.
- [ ] **Step 6: Release guard.** The 1.5.x guard refuses a milestone merge while the milestone has open issues. Before the PR merges: #154 is closed by B8 Step 5; #280 is closed with a summary comment (checklist of this plan, preview results, links) — or either is labelled `release:waived-by-maintainer` by the maintainer only. Every other open issue of milestone 1.6.0 is closed, moved to 1.7.0 with a reason, or waived. Check: `gh api 'repos/strausmann/Label-Printer-Hub/issues?milestone=<number>&state=open' --jq '[.[] | select(.pull_request|not) | .number]'` → `[]` or only waived numbers.
- [ ] **Step 7: Milestone PR.** Open `milestone/1.6.0` → `main`, title `Release 1.6.0: Labelyard and AGPL Part B` (no `!`), body with the Task 1 inventory, the Step 3 and Step 5 results, the audit verdict and `Closes #280`/`Refs #154`; external bots (Codex, Copilot) as merge gate, re-review after each fix; merge with a **merge commit**.

### Task 12: GitHub repository, GHCR package and Docker Hub metadata

Runs after the repository rename (Task 13), i.e. after the milestone merge into `main`. Commands use the maintainer's `gh` login; nothing here is a CI job except the Docker Hub description workflow from Task 4.

Values:
- Description (GitHub, ≤ 350 chars): `Labelyard — the self-hosted Label Printer Hub for all your labels. Brother P-touch and QL tape printers, office printers and sheets, scan-to-print from your phone, API and webhooks.`
- Homepage: `https://labelyard.app`
- Topics (lowercase, ≤ 20): `labelyard`, `label-printer`, `label-printer-hub`, `brother`, `ptouch`, `brother-ql`, `ql-printer`, `ipp`, `label-maker`, `barcode`, `qr-code`, `grocy`, `snipe-it`, `spoolman`, `paperless`, `self-hosted`, `homelab`, `pwa`, `fastapi`
- Social preview: `docs/brand/labelyard/social-card.png` (1200×630)
- Docker Hub: short description `Labelyard — the self-hosted Label Printer Hub for all your labels`, full description `.github/dockerhub/README.md`, logo = `docs/brand/labelyard/icon-512.png`.

- [ ] **Step 1:** `gh repo edit strausmann/labelyard --description "<description>" --homepage https://labelyard.app` and `--add-topic` for each topic; remove stale topics (`gh repo view --json repositoryTopics`) that name the old project.
- [ ] **Step 2:** Upload the social preview in Settings → General → Social preview (no API for it).
- [ ] **Step 3:** After the repository rename (the package `labelyard` exists since the preview `1.6.0-rc.N`; its `org.opencontainers.image.source` pointed at a repository name that did not exist yet, so it is not linked automatically): GHCR package `labelyard` → public, "Connect repository", Admin role for the repo under "Manage Actions access" (cleanup needs it). Package page shows title and description from the OCI annotations of Task 4.
- [ ] **Step 4:** Run **Docker Hub description** (`workflow_dispatch`); upload the logo in the Docker Hub UI if the account offers repository logos, otherwise note it as not possible.
- [ ] **Step 5: Verify at the outcome.** `gh api repos/strausmann/labelyard --jq '.description, .homepage, (.topics|length)'` prints the values and ≥ 15 topics; a link to the repo pasted into a chat/preview tool shows the social card; `https://github.com/users/strausmann/packages/container/package/labelyard` shows the description and the repo link; `curl -s https://hub.docker.com/v2/namespaces/<user>/repositories/labelyard | jq -r .description` prints the short description; the Docker Hub page renders the README with the logo.

### Task 13: Maintainer steps outside the repo (checklist, no code)

Order of the items below (Blocker 1 of the plan review): Docker Hub, domain verification, DNS and Pages settings **before** the milestone merge (order table Step 11); the repository rename **immediately after** `milestone/1.6.0` is merged into `main` and **before** the next release run (nightly `release.yml` at 04:00 UTC, or a manual run started right after the rename) — Task 6 changes `.releaserc.json` `repositoryUrl` to `git@github.com:strausmann/labelyard.git`, and semantic-release pushes the release commit and tag over that URL, so a release run between merge and rename would push to a repository that does not exist yet. Image addresses do not depend on the repository name (Task 4), so the order protects the links, the Pages source and the GHCR package link, not the build.

GitHub (after the milestone merge):
- [ ] Rename the repo `strausmann/Label-Printer-Hub` → `strausmann/labelyard` (lowercase, matching the image). GitHub redirects web, API and git URLs; update local remotes anyway (`git remote set-url origin git@github.com:strausmann/labelyard.git`). Then start the release run (`gh workflow run release.yml`) if the nightly one is not imminent; it publishes `labelyard:1.6.0`.
- [ ] Right after the rename and before the first release run, in **one commit**: `.releaserc.json` `repositoryUrl` → `git@github.com:strausmann/labelyard.git`, the pin in `backend/tests/unit/test_release_workflows.py::test_semantic_release_pushes_over_ssh`, and `repository` in the root `package.json`. (Not in Task 6: until the rename the new address does not exist, and the release runs on merge.)
- [ ] In that same commit, remove the temporary guard allowance for `.releaserc.json` and `test_release_workflows.py` after the rename (`TEMPORARY_REPO_URL_FILES` in `scripts/brand_guard.py` and its test `test_temporary_repo_url_allowance_covers_exactly_two_paths`); `python3 scripts/brand_guard.py` stays at exit 0.
- [ ] Release checklist, every release: lift the example image default (`HUB_VERSION:-<version>`) in `examples/*.yml`, `examples/.env.example` and `examples/README.md` to the new version, or add a test that fails when the default differs from the current version.
- [ ] Repository metadata, social preview and package pages: Task 12.
- [ ] GHCR: the package `labelyard` exists since the first preview (Task 11 Step 5); set it to **public**, link it to the renamed repo, and grant the repo the Admin role under "Manage Actions access" (needed by `registry-cleanup.yml`).
- [ ] Codecov and CLA assistant: confirm the next CI run uploads and the CLA check reports on a PR; re-link the repo in their dashboards if not.
- [ ] Release-run secrets (`DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`) unchanged; confirm the token may push to the new repo.
- [ ] Close milestone 1.6.0 after the release (`gh api -X PATCH repos/strausmann/labelyard/milestones/<number> -f state=closed`); delete the branch `milestone/1.6.0` only after the close-out issues are done.

Docker Hub (before the first preview):
- [ ] Create the access token `DOCKERHUB_ADMIN_TOKEN` (Read, Write, Delete) and store it as a repo secret; confirm `DOCKERHUB_TOKEN` may push to the new repo.
- [ ] Create repo `labelyard` (public) before the first preview run that pushes to Docker Hub (descriptions come from Task 12).
- [ ] Old repo `label-printer-hub-backend`: short description `Moved to <user>/labelyard — this image is no longer updated.`, same line on top of its full description. Do not delete.

GitHub Pages and DNS (done by the orchestrator; `labelyard.app` is registered, DNS at Cloudflare). Order matters: verify the domain **before** the repository claims it, so nobody else can take it over in between.

Addresses from GitHub's documentation (https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site, read 2026-11-11 from the `github/docs` source; re-read before creating the records):

| Record | Name | Value | Cloudflare proxy |
|---|---|---|---|
| `A` | `labelyard.app` (apex, `@`) | `185.199.108.153` | DNS only |
| `A` | `labelyard.app` | `185.199.109.153` | DNS only |
| `A` | `labelyard.app` | `185.199.110.153` | DNS only |
| `A` | `labelyard.app` | `185.199.111.153` | DNS only |
| `AAAA` | `labelyard.app` | `2606:50c0:8000::153` | DNS only |
| `AAAA` | `labelyard.app` | `2606:50c0:8001::153` | DNS only |
| `AAAA` | `labelyard.app` | `2606:50c0:8002::153` | DNS only |
| `AAAA` | `labelyard.app` | `2606:50c0:8003::153` | DNS only |
| `CNAME` | `www` | `strausmann.github.io` (account domain, **without** the repository name, per the same page) | DNS only |
| `TXT` | `_github-pages-challenge-strausmann` (FQDN `_github-pages-challenge-strausmann.labelyard.app`) | the value GitHub shows under profile Settings → Pages → Add a domain | — |

"DNS only" because GitHub requests the Let's Encrypt certificate only after its DNS check sees the records pointing at the Pages addresses; a proxied record resolves to Cloudflare instead (our reading — confirm with the `dig` checks below, which must return GitHub's addresses).

- [ ] Remove a wildcard record `*.labelyard.app` if one exists — GitHub: wildcard records "put you at an immediate risk of domain takeovers, even if you verify the domain" (https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/verifying-your-custom-domain-for-github-pages).
- [ ] If any `CAA` record exists for the zone, add `0 issue "letsencrypt.org"` (https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/troubleshooting-custom-domains-and-github-pages).
- [ ] Verify the domain: profile Settings → Pages → Add a domain `labelyard.app` → create the `TXT` record → `dig _github-pages-challenge-strausmann.labelyard.app +short TXT` shows it → Verify.
- [ ] Before the milestone merge (Pages settings survive the repository rename): set the publishing source to GitHub Actions and the custom domain (repo Settings → Pages, or `gh api` against https://docs.github.com/en/rest/pages/pages — `build_type=workflow`, `cname=labelyard.app`; check the field names on that page at execution).
- [ ] Environment `github-pages`: deployment branches limited to `main`. Checked **before** the repository rename, so under the old name: `gh api repos/strausmann/Label-Printer-Hub/environments/github-pages/deployment-branch-policies --jq '.branch_policies[].name'` prints only `main` (after the rename the same call under `strausmann/labelyard` must print the same).
- [ ] Create the `A`, `AAAA` and `CNAME` records of the table.
- [ ] After the first deploy from `main` and once the certificate is issued: switch on **Enforce HTTPS** (`https_enforced=true`).
- [ ] Outcome checks: `dig +short labelyard.app A` → the four `185.199.x.153`; `dig +short labelyard.app AAAA` → the four `2606:50c0:800x::153`; `curl -sS -o /dev/null -w '%{http_code}' https://labelyard.app/` → `200`, same for `https://labelyard.app/de/`; `curl -sSI http://labelyard.app/ | grep -i '^location: https://labelyard.app/'`; `curl -sSI https://www.labelyard.app/ | grep -i '^location: https://labelyard.app/'`; `gh api repos/strausmann/labelyard/pages --jq '.build_type, .cname, .https_enforced'` → `workflow`, `labelyard.app`, `true`.
- [ ] Then, on `main`: drop the `labelyard.app` exclusion from the lychee step of `website.yml` (commit `ci: check labelyard.app links now that the site is live`) and confirm the `links` job is green.

Release notes (paste at the top of the `v1.6.0` GitHub Release body, above the generated notes):

```markdown
## Label Printer Hub is now Labelyard

From 1.6.0 the project is called **Labelyard** — still the self-hosted Label Printer Hub for all your labels.

**The image name changes and the old one stops here.** Change one line, pull, restart:

    image: ghcr.io/strausmann/labelyard:1.6.0     # was ghcr.io/strausmann/label-printer-hub-backend
    # or docker.io/<user>/labelyard:1.6.0

Your data, database, API keys, sign-ins and the `X-Label-Hub-Key` header keep working. `PRINTER_HUB_*` variables are still read and logged as deprecated; rename them to `LABELYARD_*` when convenient. `label-printer-hub-backend` receives no further updates — switch Watchtower or Renovate pins now.

Coming from 1.4.x? Read the 1.5.0 notes first: 1.5.0 moved the API to `/api/v1`. Full upgrade guide: https://labelyard.app/admin/upgrades/from-label-printer-hub/ — documentation now lives on https://labelyard.app.
```

Maintainer decisions (not tasks):
- **D-UI1 (decided for now, 2026-11-09):** blue stays logo-only; the UI accent stays amber. Revisit once logo and UI have been seen together — no task.
- When to delete the frozen packages `label-printer-hub-backend` on GHCR and Docker Hub (suggested: not before 2.0.0; deletion breaks every `docker pull` of an old version).
- When to drop the `PRINTER_HUB_*` fallback and the `printer-hub` CLI alias (suggested: 2.0.0, announced one minor release earlier).
- Register `labelyard.dev` as well (`labelyard.app` is registered; `labelyard.com` is for sale) — only if it is to redirect to `labelyard.app`.
- Run a proper DPMA/EUIPO register search for "Labelyard" in classes 9 and 42 (the 2026-11-09 check was a web search, not a register search) before investing in a domain or logo rollout beyond the repo.

Deployment follow-ups (internal, done by the operator, no details in this repo):
- [ ] Every compose file that pins `label-printer-hub-backend` → `labelyard:1.6.0`, including the stack that serves the label hub to the inventory app.
- [ ] Update-automation pins (Watchtower scope, Renovate rules) for the new image name.
- [ ] Client integrations (inventory app, scripts): base URL unchanged, header unchanged; rename visible labels "Print-Hub"/"Label Printer Hub" to "Labelyard" where they show the product name.
- [ ] Reverse-proxy/tunnel resource: rename the **display name** only, keep the resource key.
- [ ] Container-management stack: keep the stack name (renaming creates a new stack directory); rename the container only if desired.
- [ ] Internal documentation, runbooks and the operator's agent skill for the hub: new name, new image, `labelyard admin create-key`.
- [ ] Monitoring/uptime check names.
- [ ] Website hosting: none to run — the site is on GitHub Pages (Task 9, Task 13 "GitHub Pages and DNS"). Remove any older self-hosting idea for `labelyard.app` from internal notes.
