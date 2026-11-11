# Licence Part B for 1.6.0 — Licence Lists, Embedded SBOM, Provenance, Release SBOM and SPDX Headers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The first Labelyard image (1.6.0) lists every shipped third-party licence on the About page, carries a CycloneDX SBOM of its web bundle, has BuildKit SBOM and `mode=max` provenance attestations on GHCR and Docker Hub, every release from 1.6.0 on has a CycloneDX SBOM of the image attached, and every own file of the repository carries an SPDX header checked by `reuse lint`.

**Architecture:** Every task commits directly on `milestone/1.6.0` (maintainer rule: milestone work has no feature branch and no PR into the milestone). The joint order of Part B and rename tasks is the table in the rename plan; this plan fixes only its constraints (section "Ordering with the rename"). Nothing Part B adds spells a product or image name: the backend list excludes the project by the name in `backend/pyproject.toml`, the CycloneDX component takes its name from `frontend/package.json`, and the SBOM job takes the image reference from the `merge` job of `docker-publish.yml`. So when the rename changes those three sources, Part B's output says `labelyard` without a second edit. The SBOM is produced inside the image workflow (read-only), the upload to the GitHub release happens in `release.yml` (the only place with `contents: write`).

**Tech Stack:** FastAPI/Pydantic, React 19 + TanStack Query + Lingui, Vite 8 + `rollup-license-plugin` 3.2.1 (MIT, build-time), `pip-licenses` 5.5.5 (MIT, tool venv only), Docker Buildx/BuildKit attestations via `docker/build-push-action` v7, Syft v1.55.0 via `anchore/sbom-action/download-syft@v0.24.3`, GitHub Actions.

**Spec:** https://github.com/strausmann/Label-Printer-Hub/issues/154 sections C and D, the SPDX item of section A (moved into Part B by the maintainer on 2026-11-11, header text decided the same day) and the acceptance criteria. Input, not repeated here: Part B of `docs/superpowers/plans/2026-11-05-agpl-relicense-licences-sbom.md` (written for 1.2.0, never executed) and its unmerged revision of 2026-11-09 on branch `feat/agpl-part-b` (rulings R-a…R-g, adopted below where still true). The rename plan this one is ordered against: `docs/superpowers/plans/2026-11-09-labelyard-rename.md` on branch `docs/labelyard-rename-plan` (not changed by this plan). Not legal advice.

## Global Constraints

- Release **1.6.0** = rename (#280) + this plan. Minor release: `feat` is allowed; **no commit and no PR title with `!`, no `BREAKING CHANGE:`/`BREAKING-CHANGE:` footer** — semantic-release would compute 2.0.0. Issue #154's own title is `feat!: …`; no commit and not the milestone → `main` PR title is taken from it.
- Only B3 is a `feat` (`feat(ui)`); every other commit is `build`, `ci` or `docs` (none of them releases, `.releaserc.json` `releaseRules`).
- Commit scopes from `commitlint.config.cjs` only (`docker`, `web`, `ui`, `ci`, `release`, `docs`, `license`). Commits use the maintainer's git identity. No AI attribution, no internal host names (public repo, `ci.yml` privacy scan).
- Prose English; UI copy en + de, German in informal "du" (maintainer decision 2026-11-09), British "licence" as the noun, SPDX ids unchanged.
- **No old-name literal in any line Part B adds**: none of `label-printer-hub`, `Label Printer Hub`, `PRINTER_HUB_`, `printer-hub` (except `printer-hub.db`), `PrintHub`, `printerhub` — the rename's `scripts/brand_guard.py` rules. Names that are needed are read from `backend/pyproject.toml`, `frontend/package.json` or the `merge` job output. Where a document must name the published image (README, notices), it uses the final name `labelyard` (these files first go public with 1.6.0).
- No new runtime dependency. Build-time only: `rollup-license-plugin@3.2.1` (exact pin, `frontend` devDependencies), `pip-licenses==5.5.5` (tool venvs only, never `/opt/venv`).
- Actions added to `docker-publish.yml`, `release.yml` and `ci.yml` are pinned by full commit SHA with the version as comment (`test_actions_are_pinned_to_full_commit_shas`). Values resolved on 2026-11-11, re-resolve at implementation: `anchore/sbom-action/download-syft` `v0.24.3` = `66cbf4bc1f1c0d2edc94016e65bc221b6bb0ad6c`; Syft `v1.55.0` (2026-10-19; v1.57.1 is two days old and not taken). `actions/download-artifact` and `actions/upload-artifact` reuse the SHAs already in `docker-publish.yml`.
- `test_actions_are_pinned_to_full_commit_shas` covers `release.yml`, `docker-publish.yml`, `licence-gate.yml` and `licence-backend.yml`, **not `ci.yml`** (whose existing steps use major tags). The new `ci.yml` steps (Syft in B5, REUSE in B9) are pinned by SHA anyway, and their own tests (`test_ci_image_check`, `test_reuse_job`) assert the SHA. `fsfe/reuse-action` `v6.0.0` = `676e2d560c9a403aa252096d99fcab3e1132b0f5` (commit behind the annotated tag, 2025-10-06).
- SPDX header (maintainer decision 2026-11-11, final), in every own file in the file type's comment syntax:
  `SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors`
  `SPDX-License-Identifier: AGPL-3.0-or-later`
  The year is the creation year and is not bumped. A contributor may add an own line `SPDX-FileCopyrightText: <year> <name>` (voluntary). The CLA stays unchanged. Headers are added in one sweep by B9, the last code task of the milestone; earlier tasks (Part B and rename) create files without them. "Labelyard" in this line is the new name and therefore no brand-guard hit.
- Workflow inputs and job outputs reach `run:` only through `env:`.
- `test_image_labels_and_licence_file` counts `licenses=AGPL-3.0-or-later` exactly twice in `docker-publish.yml`: add no further `licenses=` text there.
- Image stays non-root UID 1000; the CSP in `backend/app/web/spa.py` and the precache globs in `frontend/pwa.config.ts` (no `json`) stay unchanged; `BUILDKIT_SBOM_SCAN_STAGE` stays off.
- Never rebuild or push an already published version. No throwaway release tags: the live check (B8) uses the milestone preview `1.6.0-rc.N` that the rename plan builds anyway.
- Coverage gates stay: backend `--cov-fail-under=80`, web 70 %. UI work loads the design skills (`.claude`-side rule of the operator; named in B3).

## Preconditions

1. **Milestone 1.5.x is released and synced.** Its release `v1.5.Z` (the next free patch number when the milestone PR merges; `<V15>` below) is on `main`, `main` is merged into `milestone/1.6.0` (merge commit), before B1, B5 or B6 starts. Check: `git merge-base --is-ancestor <V15> origin/milestone/1.6.0` → exit 0. Milestone 1.5.x brings, and this plan relies on:
   - PR #270 (1.5.x Task 1): CI, licence gate and backend licence workflow also run on PRs into `milestone/**`; release guard `release_impact.py`; register row **D21** is taken by it.
   - PR #269 (1.5.x Task 1b): `preview-image.yml` (calls `docker-publish.yml` with `tag: x.y.z-rc.N`, `ref`, permissions `contents: read, packages: write, id-token: write`), no branch images, `ghcr-cleanup.yml` that keeps platform children and attestations of kept images.
   - 1.5.x Task 14: a path under `licenses/` is served when the file exists and answers 404 otherwise (`licenses/` in the reserved set of `_is_reserved`, file check first for this prefix; tests `test_unknown_licence_page_is_404`, `test_known_licence_file_is_served`), `licence-text-sha256` in exceptions, `Proprietary` inside a classifier join → `UNKNOWN`.
2. Part B does not touch `spa.py`. B1 relies on 1.5.x Task 14 for the 404 and only adds a test that `licenses/backend.json` is served as `application/json`. If Task 14 has not landed, Part B waits; it does not implement the 404 a second way.
3. **Later patch releases.** If another `1.5.Z` (or a `fix` on `main`) is released before the milestone merges, `main` is merged into `milestone/1.6.0` with a merge commit before the next task starts (1.5.x step R1, rename Task 10); the fast gates run again. A sync after B9 is followed by `reuse lint`; files it brought without a header get one in a `chore(license)` commit.
4. **Which tasks wait:** B1 (1.5.x Task 14's `licenses/` handling and licence tooling), B5 and B6 (#269/#270 change `docker-publish.yml`, `release.yml`, `ci.yml` triggers and the preview permission ceiling) wait for the 1.5.x sync. B9 waits for all other code tasks of the milestone (Part B and rename) and the last sync. B2, B3, B4 and B7 may run before the sync.
5. **Checks on a direct commit.** With #270, `ci.yml` also runs on pushes to `milestone/**`; `Dependency review` and `licence-backend.yml` run on pull requests only, so they judge Part B's dependency changes (B2's devDependency) on the milestone → `main` PR. Each task therefore runs its gates locally before the push.

## Ordering with the rename

**Decision: the joint order is the rename plan's table; Part B adds three constraints to it.**

1. **A Part B task comes before every rename task that touches one of its files** (table below). The rename then edits on top of Part B, never the other way round, so no file is rebuilt twice and the rename's brand guard sweeps Part B's lines once, finding nothing (Global Constraints).
2. **B1, B5 and B6 wait for the 1.5.x sync** (Precondition 4); B2, B3, B4 and B7 may come earlier.
3. **B9 is the last code task of milestone 1.6.0** (coordinator ruling 2026-11-11): after every rename task and after the last sync, directly before the gate, whole-branch review and audit. It sees the final file set, including every file the rename creates, so nothing needs a second pass and no running work conflicts with it. It is one large commit, recorded in `.git-blame-ignore-revs`.

B8 runs after B9 on the preview `1.6.0-rc.N` built from the final tree (rename Task 11 Step 5), and closes #154 **before** the milestone → `main` PR, because the 1.5.x release guard refuses a milestone with open issues. Then release 1.6.0, then the post-release check (section "After the release").

What ends up named `labelyard` and why no file is rebuilt twice:

| Artefact | Source Part B reads | Changed by |
|---|---|---|
| Image ref of SBOM job and release asset name `<image>-<version>.cdx.json` | `needs.merge.outputs.image-ref` (= the `image` step's `ref` in `merge`) | rename Task 4 (ref steps) |
| OCI labels / index annotations | untouched by Part B | rename Tasks 3, 4 |
| Attestation subject | BuildKit derives it from the pushed `name=` of the build step | rename Task 4 (same ref) |
| CycloneDX `metadata.component.name`, excluded own package in the web list | `frontend/package.json` `name` | rename Task 5 |
| Excluded own package in the backend list | `backend/pyproject.toml` `[project].name` | rename Task 3 |
| Local CI image tag | `env.IMAGE: labelyard:ci` in `ci.yml` `docker-build` (B5 replaces today's `label-printer-hub:ci` while it rewrites that job) | — |

Files both plans touch, in this order (Part B first, rename second — except the two B9 rows, where B9 comes last):

| File | Part B | Rename | Agreement |
|---|---|---|---|
| `.github/workflows/docker-publish.yml` | B5 `provenance: mode=max`; B6 `merge.outputs`, new job `sbom` | Task 4: ref steps, Docker Hub ref, annotations | **The rename keeps step id `image` with output `ref` in job `merge`** (B6's `image-ref` output points at it). If the rename renames the step, it updates `merge.outputs.image-ref` in the same commit; guard test `test_sbom_uses_merge_image_ref` fails otherwise. |
| `.github/workflows/ci.yml` | B5 job `docker-build` | Task 11: new job `brand-guard` | separate jobs |
| `backend/Dockerfile` | B1 builder licence `RUN` + runtime `COPY`; B2 `web-builder` lines | Task 3: header comment, `LABEL` block, `HUB_REPO_URL` | Part B does not touch the header comment, `LABEL` or `ENV` blocks of `runtime` |
| `backend/scripts/licence_report.py` (+ test) | B1 removes the `OWN_PACKAGE` literal | Task 3 changes `pyproject.toml` only | after B1 the guard has no hit here |
| `frontend/package.json`, `frontend/pnpm-lock.yaml` | B2 adds the devDependency | Task 5: `name`, lockfile regenerated | rename regenerates on top |
| `frontend/playwright.config.ts` | B3: main `webServer.command` | Task 2/10: `PRINTER_HUB_WEB_DIST_DIR` in `serve()` | Part B does not touch `serve()` |
| `frontend/src/i18n/locales/{en,de}/messages.po` | B3 new strings | Task 5 extract/compile | rename extracts after Part B |
| `THIRD_PARTY_NOTICES.md` | B4: second intro paragraph, two new sections, notes column of the fonts table | Task 6: first intro sentence ("… is licensed under") | Part B keeps the first sentence byte-identical |
| `README.md`, `docs/supply-chain.md` | B7: full text in `docs/supply-chain.md`, README gets a three-line section with the link | Task 6 (hero, links, config), Task 7 (slims the README, moves user docs to the site) | the README keeps only the link, which survives the slimming; if Task 7 moves `docs/supply-chain.md` into the site (en + de), it updates the constant `SUPPLY_CHAIN_DOC` in `test_licence_metadata.py` and leaves a pointer at the old path |
| every own file, lines 1–3 | B9 SPDX header (last) | — (rename tasks run before B9 and need no header) | B9 annotates the final tree in one commit |
| `CONTRIBUTING.md`, `.github/workflows/ci.yml` | B9 (last): section "Licence headers", job `reuse` | Task 6 (names), Task 11 (job `brand-guard`), both earlier | separate sections/jobs |
| `docs/decisions/register.md` | B1 appends one row | Task 6 appends its rows | append-only; Part B takes the next free `D` label on the synced head (expected **D22**, D21 is #270's) |

**Registries and attestations (the GitLab registry concern).** Attestations are stored as extra manifests (`unknown/unknown`, `vnd.docker.reference.type: attestation-manifest`) in the image index (https://docs.docker.com/build/metadata/attestations/). `docker/build-push-action` adds them only when pushing to a registry, not with `load: true` (https://docs.docker.com/build/ci/github-actions/attestations/). GHCR accepts OCI image indexes (https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry, "Docker Image Manifest V2, Schema 2" and "Open Container Initiative (OCI) Specifications"); Docker Hub's Docker Scout reads SBOM attestations from pushed images (https://docs.docker.com/scout/explore/analysis/: "When an image includes an SBOM attestation, Docker Scout uses it"). Neither page names registries for attestations, so it was **measured on 2026-11-11** with today's workflow (`provenance: true`, `sbom: true`, push by digest + `imagetools create`):

- `ghcr.io/strausmann/label-printer-hub-backend:1.5.0` and `docker.io/strausmann/label-printer-hub-backend:1.5.0`: index with `linux/amd64`, `linux/arm64` and one attestation manifest each; `{{json .SBOM}}` returns SPDX-2.3 (232 packages, contains `brother-ql` and `tini`, **not** `react`); `{{json .Provenance}}` returns SLSA provenance with `buildkit_metadata.layers/source/vcs` and `internalParameters.buildConfig` — already `mode=max` content (the action's default for public repositories). B5 makes it explicit so it no longer depends on that default.
- The GHCR cleanup of #269 uses `dataaxiom/ghcr-cleanup-action`, which follows manifest lists and referrers and keeps the children of kept images (its header comment); B8 checks that its dry run does not list the preview's attestation digests.

## What changed against the old Part B

| Old Part B (2026-11-05, rev. 2026-11-09) | Now (v1.5.0 + milestone 1.5.x + rename) |
|---|---|
| Release 1.2.0, then 1.6.0 "after 1.5.0", PR into `main`, rebase merge | 1.6.0 with the rename; direct commits on `milestone/1.6.0`, order per the rename plan's table |
| B1 adds the `licenses/` 404 to `spa.py` | done by 1.5.x Task 14; B1 only adds a test that `backend.json` is served as `application/json` |
| `OWN_PACKAGE = "label-printer-hub-backend"` stays | read from `pyproject.toml` (`--own-project`), so the rename's package name flows through |
| Extra records: DejaVu only | DejaVu, Atkinson Hyperlegible Next, IBM Plex Mono (fonts added in #258) and the gLabels-qt sheet data (MIT) |
| D21 for the decision | D21 taken by #270 → next free label (expected D22) |
| CycloneDX component `label-printer-hub-web`, `excludedPackageTest` literal | name read from `frontend/package.json` |
| B5 "turn provenance to mode=max" + spike S2 | content is already max (measured); B5 pins `mode=max`; S2 answered by measurement (BuildKit SBOM lacks `react` → embedded CycloneDX + `+sbom-cataloger`) |
| B5 CI tag `label-printer-hub:ci`, actions by major tag | `labelyard:ci` via `env.IMAGE`; Syft action SHA-pinned |
| B6 job `release-sbom` in `docker-publish.yml` with `contents: write`, hard-coded `ghcr.io/strausmann/label-printer-hub-backend` and asset name | `docker-publish.yml` job `sbom` is read-only (else the preview workflow, which grants `contents: read`, fails validation); upload moves to `release.yml` job `release-sbom`; ref and asset name from `merge` outputs |
| Live tests with `v0.0.0-ci.<n>` tags and GHCR cleanup | none; B8 checks the milestone preview `1.6.0-rc.N` of the renamed image |
| Docker Hub not checked | B8 checks attestations on Docker Hub too (rename Task 4 pushes previews there) |
| #154 closed after the release | closed before the milestone merge (release guard); only the release-asset check runs afterwards |
| SPDX headers optional, not planned | Task B9 (maintainer, 2026-11-11), `reuse lint` as CI gate |
| README section with the whole supply-chain text | `docs/supply-chain.md` plus a short README link section (rename Task 7 slims the README) |
| CI on PRs into the target branch assumed | CI on `milestone/**` PRs comes with #270 (precondition) |

## Review Focus

(Six items: the SPDX task added one that is likely to bite.)

1. **A preview (`1.6.0-rc.N`) or a Docker Hub-only failure must not break the image workflow.** A preview has no GitHub release; the SBOM job must never write to releases and must pass with `contents: read`. → B6 `test_sbom_job_is_read_only`.
2. **After the rename, the SBOM describes the old image or the asset carries the old name.** → B6 `test_sbom_uses_merge_image_ref` (no registry literal in the job, ref only from `needs.merge.outputs`), B8 asset name check.
3. **Licence data missing, foreign or hostile:** API-only image, Vite dev server, 404, 200 `text/html` app shell, 2 MB list, `<script>` in a text. The About page keeps the project licence and source link, says which list is missing, renders texts as text and mounts a text only when expanded. → B3 tests.
4. **The project lists itself after `pyproject.toml` is renamed.** → B1 `test_own_package_read_from_pyproject`.
5. **A header breaks a file that is parsed as data** (`licence-policy.yml` is JSON read by two gates; JSON fixtures; the web manifest). → B9 `test_json_files_stay_json`.
6. **Accidental 2.0.0.** A `!` in a commit or a `BREAKING CHANGE` footer on the milestone. → "Commits and gates": commitlint on every commit before its push, `scripts/release_impact.py check` on `origin/main..origin/milestone/1.6.0` reports a minor change.

---

## File structure

| File | Responsibility |
|---|---|
| `backend/scripts/licence_report.py` | judge (unchanged) and now also publish the backend list (`LicenceRecord`) |
| `backend/licences/` (create) | canonical texts for packages that ship none (`GPL-3.0-or-later.txt`, more per S3b), `glabels-qt-MIT.txt`, `extra-records.json` |
| `frontend/src/licences/build.ts` (create) | policy check, list and CycloneDX for the web bundle (build time only) |
| `frontend/src/features/about/licences.ts`, `DependencyLicences.tsx` (create) | fetch, parse and show both lists |
| `.github/workflows/docker-publish.yml` | `mode=max`; job `sbom` (read-only) |
| `.github/workflows/release.yml` | job `release-sbom` (upload to the release) |
| `.github/workflows/ci.yml` | `docker-build` checks the image content; job `reuse` |
| `REUSE.toml`, `LICENSES/`, `backend/tests/unit/test_spdx_headers.py` (create) | licensing of every file; inline-header guard |
| `docs/supply-chain.md` (create) | how to get SBOM, provenance and licence lists |

---

### Task B1: Backend licence list in the image

**Files:**
- Create: `backend/licences/GPL-3.0-or-later.txt` (verbatim https://www.gnu.org/licenses/gpl-3.0.txt, sha256 `3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986`), one text per further SPDX id from S3b, `backend/licences/glabels-qt-MIT.txt` (the MIT text quoted in `THIRD_PARTY_NOTICES.md` "Sheet type data"), `backend/licences/extra-records.json`
- Modify: `backend/scripts/licence_report.py`, `backend/tests/unit/scripts/test_licence_report.py`, `backend/Dockerfile` (builder: the licence `RUN`; runtime: next to `COPY … LICENSE /opt/app/web/licenses/agpl-3.0.txt`), `.github/workflows/licence-backend.yml` (add `--own-project pyproject.toml --extra licences/extra-records.json`; no `--output`, no `--require-texts`), `backend/tests/integration/api/test_spa_serving.py`, `docs/decisions/register.md` (row `D<next>` "The licence lists cover the Python environment and the web bundle the image ships, generated at build time; operating-system packages are covered by the image SBOM and their own copyright files", 2026-11-11, Accepted, ADR —)

**Interfaces:**
- Produces:
  - `class LicenceRecord(TypedDict): name: str; version: str; license: str; licenseText: str | None; repository: str | None` — the field names of `rollup-license-plugin`, so B3 parses both lists with one function.
  - `def own_package_name(pyproject: Path) -> str` — `[project].name` via `tomllib`.
  - `def _collect(interpreter: str, own: str) -> list[dict[str, str]]` — adds `--with-urls`; excludes `own` by normalised purl.
  - `def load_extra(path: Path, root: Path) -> list[LicenceRecord]` — entries `{name, version, license, licenseTextFile, repository}`, `licenseTextFile` relative to `root`; a missing file raises `ValueError` naming it. `root` comes from the CLI option `--extra-root <dir>` (default `.`, the working directory).
  - `def to_records(entries, policy: Policy, fallback_dir: Path, extra: Sequence[LicenceRecord] = ()) -> list[LicenceRecord]  # D<next>` — `license` from `classify`; `licenseText` = own `LicenseText` (not `UNKNOWN`), else `fallback_dir/<id>.txt` when the expression is a single id, else `None`; `repository` = pip-licenses `URL` if `http(s)://`, else `None`; `extra` appended unjudged; sorted by `name.lower()`.
  - CLI: `--own-project <pyproject.toml>` (required), `--output <path>` (`json.dumps(records, ensure_ascii=False, indent=2)`, written also when the check fails), `--require-texts` (exit 1, each record without text named on stdout), `--extra <path>`, `--extra-root <dir>` (default `.`), `--fallback-dir <path>` (default `licences`). Exit 1 for any policy offender, as today. The old `classified` output (`allowed` key) goes.
- `extra-records.json`: `DejaVu Sans` 2.37 `Bitstream-Vera` (`app/page_render/fonts/LICENSE-DejaVu.txt`), `Atkinson Hyperlegible Next` `google/fonts@66eef70` `OFL-1.1`, `IBM Plex Mono Bold` `google/fonts@633f320` `OFL-1.1` (their `LICENSE-*-OFL.txt`), `gLabels-qt templates` `37901c1` `MIT` (`licences/glabels-qt-MIT.txt`); repositories as in `THIRD_PARTY_NOTICES.md`.
- Image: `/opt/app/web/licenses/backend.json`, served at `/licenses/backend.json` by the SPA file branch (no new route; `test_route_versioning.py` stays green).

- [ ] **Step 1: Write the failing tests** in `test_licence_report.py`: `test_own_package_read_from_pyproject` (tmp `pyproject.toml` with `name = "some-app"` → `"some-app"`, and `_collect(..., own="some-app")` drops `Some_App`); `test_to_records_shape` (exactly the five keys); `test_to_records_sorted` (`b, A, c` → `A, b, c`); `test_text_fallback_for_brother_ql` (no `LicenseText`, GPLv3+ classifier → text starts `GNU GENERAL PUBLIC LICENSE`); `test_no_fallback_for_compound_expression` (`MIT OR Apache-2.0` → `None`); `test_repository_only_http` (`javascript:x` → `None`); `test_extra_record_appended_unjudged` (`Bitstream-Vera` in the output, exit 0); `test_load_extra_missing_file_names_it`; `test_extra_root_option` (`--extra-root` other than the working directory resolves the texts); `test_require_texts_fails_without_text`; `test_output_round_trip` (`<script>` and `ü` unchanged); `test_main_exit_codes_and_output` changed (offender → exit 1 and `bad (GPL-2.0-only)` on stdout; file = five-key records `{"ok", "bad"}`, no `allowed`). Rename the fixture name in `test_collect_excludes_the_own_package_and_reports_tool_failure` to a neutral one. In `test_spa_serving.py`: `test_backend_licence_list_served` (fixture dist with `licenses/backend.json` → 200, `content-type` starts `application/json`, bytes equal).
- [ ] **Step 2: Run** `cd backend && pytest tests/unit/scripts/test_licence_report.py tests/integration/api/test_spa_serving.py -v`. Expected: new tests FAIL; `test_backend_licence_list_served` may already pass (it pins the file branch; record it).
- [ ] **Step 3: Spike S3b (15 min)** in `docker build -f backend/Dockerfile --target builder -t lyb1-builder .`: list the `.py` files of `brother_ql` and `ptouch` in `/opt/venv/lib/python3.12/site-packages`; run pip-licenses as the Dockerfile does and list every package with empty `LicenseText` (at least `brother-ql`, `packbits`, `ptouch`, `pysnmp`, `qrcode`, `Jinja2`, `pyusb`, `reportlab`, `charset-normalizer`). Each single SPDX id without text gets a verbatim canonical text in `backend/licences/` (URL and sha256 in the commit body); a compound expression without text is resolved by the exception's `licence` being a single id, never by a guessed text. In the runtime stage: `for p in libjpeg62-turbo zlib1g curl tini ca-certificates fonts-dejavu-core; do test -s /usr/share/doc/$p/copyright || echo MISSING $p; done` prints nothing (else stop and report).
- [ ] **Step 4: Implement** the functions and flags; Dockerfile builder: `COPY backend/licences/ /build/licences/` and run with `--own-project /build/pyproject.toml --output /build/backend-licences.json --require-texts --extra /build/licences/extra-records.json --extra-root /build --fallback-dir /build/licences` (the extra font texts are at `/build/app/page_render/fonts/`, already copied); runtime: `COPY --from=builder --chown=hub:hub /build/backend-licences.json /opt/app/web/licenses/backend.json`; the register row.
- [ ] **Step 5: Run** the two test files, `test_route_versioning.py`, `test_decision_register.py`, `ruff check . && ruff format --check . && mypy app`, then `docker build -f backend/Dockerfile -t lyb1 .` and `docker run --rm --entrypoint python lyb1 -c "import json;d=json.load(open('/opt/app/web/licenses/backend.json'));m={r['name']:r for r in d};print(len(d)>30, m['brother-ql']['license'], 'pip' in m, m['DejaVu Sans']['license'], all(r['licenseText'] for r in d))"` → `True GPL-3.0-or-later True Bitstream-Vera True`; `test ! -e /opt/licence-tool && ! /opt/venv/bin/pip show pip-licenses` in the image exits 0. Counter-test: delete `GPL-3.0-or-later.txt` → image build fails at `--require-texts` naming `brother-ql`; set `--own-project` to a copy with another name → the project appears in the list.
- [ ] **Step 6: Commit** `build(docker): ship the backend licence list generated from the runtime venv` (`Refs #154`).

### Task B2: Frontend licence list and CycloneDX SBOM of the web bundle

**Files:**
- Create: `frontend/src/licences/build.ts`, `frontend/src/licences/build.test.ts`
- Modify: `frontend/package.json` (devDependency `"rollup-license-plugin": "3.2.1"`), `frontend/pnpm-lock.yaml`, `frontend/vite.config.ts` (plugin next to `licenseNotices()` and `scalarApiReference()`; both stay, ruling R-d: the four texts keep their URLs), `frontend/src/build.test.ts` (new `it` blocks in the existing `describe.skipIf`), `backend/Dockerfile` `web-builder` (`COPY licence-policy.yml /licence-policy.yml`, `ENV LICENCE_POLICY=/licence-policy.yml`; `ARG VERSION=0.0.0-dev` + `ENV HUB_VERSION=${VERSION}` placed **directly before** `RUN pnpm build`, so the `pnpm install` layer keeps its cache)

**Interfaces:**
- Produces in `build.ts`:
  - `export type Policy = {allowed: ReadonlySet<string>; exceptions: ReadonlyMap<string, string>}`; `export function loadPolicy(path: string): Policy` (JSON.parse; exceptions keyed by purl).
  - `export function expressionAllowed(expr: string, allowed: ReadonlySet<string>): boolean` — same grammar as Python `expression_allowed`, proven by `docs/licence-test-vectors.json`.
  - `export function isUnacceptableLicence(id: string, policy: Policy, purl?: string): boolean` — exception for the purl wins; else `!expressionAllowed`.
  - `export function projectName(): string` — `name` of `frontend/package.json`.
  - `export const EXTRA_RECORDS: readonly PluginPackage[]` — `zxing-cpp`, version from S1, `Apache-2.0`, text from `frontend/licenses/zxing-cpp-Apache-2.0.txt`.
  - `export function toLicenceList(packages, extra): string` — merged, sorted by name, `JSON.stringify(…, null, 2)`, same five keys as B1.
  - `export function toCycloneDx(packages, extra, version: string, name: string): string` — CycloneDX 1.6: `bomFormat: "CycloneDX"`, `specVersion: "1.6"`, `version: 1`, `metadata.component {type: "application", name, version}`, `components[] {type: "library", name, version, purl: "pkg:npm/<name with @ as %40>@<version>" (zxing-cpp: "pkg:github/zxing-cpp/zxing-cpp@<version>"), licenses: [{expression}]}`, sorted by purl, no `serialNumber`, no timestamp.
  - `export async function extraPackagePaths(): Promise<string[]>` — `@scalar/api-reference`'s production tree (`pnpm list @scalar/api-reference --prod --depth Infinity --json`), `zxing-wasm`, `workbox-core`, `workbox-precaching`, `workbox-routing`, `workbox-strategies` resolved from `workbox-build`.
- Plugin options: `outputFilename: false`, `includePackages: extraPackagePaths`, `excludedPackageTest: (n) => n === projectName()`, `unacceptableLicenseTest`, `additionalFiles: {"licenses/frontend.json": …, "frontend.cdx.json": (p) => toCycloneDx(p, EXTRA_RECORDS, process.env.HUB_VERSION ?? "0.0.0-dev", projectName())}`; policy path `process.env.LICENCE_POLICY ?? fileURLToPath(new URL("../licence-policy.yml", import.meta.url))`.

- [ ] **Step 1: Write the failing tests.** `licences/build.test.ts`: every vector of `docs/licence-test-vectors.json` gives the Python result; `isUnacceptableLicence("GPL-2.0-only", policy)` → true; `("AFL-2.1 AND AFL-3.0 AND BSD-3-Clause", policy, "pkg:npm/json-schema@0.4.0")` → false; purl of `@tanstack/react-query@5.105.3` is `pkg:npm/%40tanstack/react-query@5.105.3`; two `toCycloneDx` calls are identical strings; `metadata.component.name` equals the `name` argument. `src/build.test.ts` (versions read from `package.json`, ruling R-g): `dist/licenses/frontend.json` lists `react`, `react-dom`, `@scalar/api-reference`, `zxing-wasm`, `workbox-precaching`, `zxing-cpp`, each with non-empty `licenseText`, and none of `vite`, `vitest`, `typescript`, `eslint`, `@playwright/test`, `yaml`, `rollup-license-plugin`, nor the project itself; `dist/frontend.cdx.json` has `pkg:npm/react@<dependencies.react>`, `pkg:npm/%40scalar/api-reference@<…>` and `metadata.component.name === pkg.name`; `dist/sw.js` contains neither `frontend.json` nor `frontend.cdx.json`.
- [ ] **Step 2: Run** `pnpm exec vitest run src/licences/build.test.ts`, then `pnpm build && REQUIRE_DIST=1 pnpm exec vitest run src/build.test.ts`. Expected: FAIL.
- [ ] **Step 3: Spike S1 (20 min).** Wire the plugin; build the `web-builder` stage once with network (as committed) and once from a scratch copy of the Dockerfile where only the build step is offline: `RUN --network=none pnpm build && …` (`pnpm install` at `Dockerfile:36` needs the network and keeps it; the scratch copy is not committed). Record in the PR: `@react-aria/*` and `@fontsource/*` present without `includePackages`?; `licenseText` from `node_modules` or downloaded?; size of the Scalar subtree; the zxing-cpp version zxing-wasm 3.1.6 bundles. A network fetch is acceptable and goes into B7's build note.
- [ ] **Step 4: Implement** `build.ts`, the plugin and the Dockerfile lines.
- [ ] **Step 5: Run** `pnpm typecheck && pnpm lint && pnpm test:coverage && pnpm build`. Expected: PASS. Counter-test: drop `zxing-wasm` from `extraPackagePaths` → built-output test fails; add `json` to `globPatterns` → `sw.js` test fails; `LICENCE_POLICY` at a copy without `MIT` → `pnpm build` fails naming a package; change `name` in a scratch `package.json` → the CycloneDX test follows it.
- [ ] **Step 6: Commit** `build(web): licence list and CycloneDX SBOM of everything the web app ships` (`Refs #154`).

### Task B3: Dependency licences on the About page

Load before writing UI code: `taste-skill:design-taste-frontend`, `emil-design-eng`, `mobile-native`, `break-ui` (long names, long texts, 400 rows); `impeccable:impeccable` on the About page at the end. Screenshots light/dark, 1280 px and 390 px with the existing `shot()` helper of `e2e/about.spec.ts`, as artefacts. A design skill missing in the session is reported, not skipped.

**Files:**
- Create: `frontend/src/features/about/licences.ts`, `licences.test.ts`, `DependencyLicences.tsx`, `DependencyLicences.test.tsx`, `frontend/e2e/fixtures/backend-licences.json` (three records incl. `brother-ql` with the first lines of B1's GPL text)
- Modify: `frontend/src/features/about/AboutPage.tsx` (the `<section data-section="dependencies" />` slot and its "B3" comment), `AboutPage.test.tsx` ("leaves an empty dependencies section for the licence list" → "renders the dependency licences in the dependencies section"), `frontend/playwright.config.ts` (main `webServer.command` only: `pnpm build && cp e2e/fixtures/backend-licences.json dist/licenses/backend.json && ${serve(…)}`; `serve()` and `playwright.harness.config.ts` unchanged, ruling R-e), `frontend/e2e/about.spec.ts`, `frontend/src/i18n/locales/{en,de}/messages.po`

**Interfaces:**
- Consumes: `/licenses/frontend.json` (B2), `/licenses/backend.json` (B1) — static files, not API paths.
- Produces: `export type LicenceEntry = {name: string; version: string; licence: string; text: string | null; part: "web" | "server"}`; `export function parseLicenceList(raw: unknown, part: LicenceEntry["part"]): LicenceEntry[]` (non-array → `[]`, records without `name`/`version` dropped, `licenseText: ""` → `null`); `export async function fetchLicenceList(url: string, part): Promise<LicenceEntry[] | "missing">` (plain `fetch`, `credentials: "same-origin"`, not `apiFetch`; non-2xx, a `content-type` without `application/json`, or a parse error → `"missing"`); `export function useLicenceLists(): {entries: LicenceEntry[]; missing: Array<"web" | "server">; isPending: boolean}` (react-query, `staleTime: Infinity`, About page only).

**Copy (en → de):**

| English | Context | German |
|---|---|---|
| "Third-party software" | `"heading"` | "Software von Dritten" |
| "{count} packages" (Lingui plural) | — | "{count} Pakete" |
| "Show licence text" | `"action"` | "Lizenztext anzeigen" |
| "Hide licence text" | `"action"` | "Lizenztext ausblenden" |
| "The licence list of the web app is not included in this build." | — | "Die Lizenzliste der Web-App ist in diesem Build nicht enthalten." |
| "The licence list of the server is not included in this build." | — | "Die Lizenzliste des Servers ist in diesem Build nicht enthalten." |
| "Operating system packages of the image are listed in its SBOM; their licence texts are in /usr/share/doc inside the image." | ruling R-a | "Die Betriebssystempakete des Images stehen in seiner SBOM; ihre Lizenztexte liegen im Image unter /usr/share/doc." |

- [ ] **Step 1: Write the failing tests.** `licences.test.ts`: `parseLicenceList({}, "web")` → `[]`; record without `version` dropped; `fetchLicenceList` → `"missing"` for 404, for 200 `text/html`, for malformed JSON. `DependencyLicences.test.tsx` (`fetch` stubbed for the two URLs, any other URL throws): columns package, version, licence, part; rows sorted by name across both parts; no licence text in the DOM until "Show licence text"; `"<script>alert(1)</script>"` shown as literal text and no `script` element created; server list missing → web rows plus the server message; both missing → only the two messages while licence and source link still show; the OS sentence always shown; a 2 MB list renders the count without mounting texts. `AboutPage.test.tsx`: the replaced test. `e2e/about.spec.ts`: the table lists `react` and `brother-ql`; expanding `brother-ql` shows `GNU GENERAL PUBLIC LICENSE`.
- [ ] **Step 2: Run** `pnpm exec vitest run src/features/about`. Expected: FAIL.
- [ ] **Step 3: Implement** the component in the slot, the `webServer.command` copy, the messages (`i18n:extract`, translate, `i18n:compile`).
- [ ] **Step 4: Run** the web gates and `pnpm e2e`. Expected: PASS. Counter-test: `dangerouslySetInnerHTML` → the `<script>` test fails; drop the content-type check → the `text/html` test fails; remove the `cp` → the e2e `brother-ql` check fails.
- [ ] **Step 5: Commit** `feat(ui): list every shipped third-party licence on the about page` (`Refs #154`).

### Task B4: Third-party notices

**Files:** Modify `THIRD_PARTY_NOTICES.md`, `backend/tests/unit/test_licence_metadata.py`

- [ ] **Step 1: Write the failing test** `test_notices_name_copyleft_dependencies`: the file contains `brother_ql`, `GPL-3.0-or-later`, `ptouch`, `LGPL-2.1-or-later`, `/licenses/backend.json`, `/licenses/frontend.json`, `/frontend.cdx.json`, `/opt/app/LICENSE`, `/usr/share/doc`; it no longer contains `is tracked in`.
- [ ] **Step 2: Run** `pytest tests/unit/test_licence_metadata.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** First intro sentence unchanged (the rename owns it). Replace the paragraph "Automatic generation … is tracked in #154 …": the complete generated lists are `/licenses/backend.json` and `/licenses/frontend.json` in the image and on the About page, the CycloneDX SBOM of the web bundle is `/frontend.cdx.json`, the tables below are a hand-kept summary. New section "Copyleft dependencies": brother_ql (GPL-3.0-or-later, upstream URL, `.py` source in the image per S3b, text from `backend/licences/` because the wheel ships none), ptouch (LGPL-2.1-or-later, PyPI URL, same notes), the project's own source of each version linked from the About page (GPLv3 §6(d), AGPL §13). New section "Operating system packages" (ruling R-a, the six runtime packages). Fonts table: notes "also listed in `/licenses/backend.json`" (ruling R-b). All other tables unchanged in content and order.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `docs(docs): name the copyleft dependencies and the generated licence lists` (`Refs #154`).

### Task B9: SPDX headers and REUSE compliance

Placed here in the document after B4; it runs last (see above). Header-only change to existing files plus REUSE metadata; no behaviour change. The last code task of the milestone: after every Part B and rename task and the last sync, before gate, review and audit (Ordering).

**Decisions:**
- **Header text:** the two lines of Global Constraints, in the file's comment syntax (`#` for Python, shell, YAML, TOML, Dockerfile, Makefile, `.gitignore`/`.dockerignore`, `.env.example`, `alembic.ini.runtime`; `//` for TS/TSX/JS/MJS/CJS; `/* */` for CSS; `<!-- -->` for Markdown and HTML). Shebang and encoding lines stay first; Python headers go before the module docstring; `frontend/index.html` puts the comment after `<!doctype html>`.
- **Inline header** in every own file whose format allows comments, including docs, ADRs, plans and the history files (one header, nothing else changed).
- **`REUSE.toml` instead of an inline header** (path annotations) for own files that cannot or must not carry one: JSON of every kind (`licence-policy.yml` is JSON parsed with `json.loads`/`JSON.parse` — a `#` line would break both licence gates), `*.webmanifest`, lockfiles, `frontend/.nvmrc`, generated files (`frontend/src/api/schema.gen.ts`, the SVG samples written by `backend/scripts/generate_template_svgs.py`, `*.po` written by Lingui), `CHANGELOG.md` (written by semantic-release), binary test fixtures (`*.bin`, `*.png`), app icons. Those get the same copyright line and `AGPL-3.0-or-later`.
- **Third-party files keep their own licence** via `REUSE.toml` (`precedence = "override"`) with the copyright as written in the file or its source: the three fonts and their `LICENSE-*` texts in `backend/app/page_render/fonts/`, `frontend/licenses/*.txt`, `backend/licences/*.txt` (B1), `CODE_OF_CONDUCT.md` (Contributor Covenant, CC-BY-4.0), `LICENSE` (the AGPL text, copyright Free Software Foundation), the seed `backend/app/seed/sheet_types.json` (derived from gLabels-qt: MIT with Jaye Evins' line **and** the project line). Spike S4 decides any further file; nothing is guessed.
- **`LICENSES/`** holds one text per used SPDX id (`reuse download --all`); `LICENSE` at the root stays (A5 tests pin it).
- **Generated files stay headed:** `backend/alembic/script.py.mako` emits the header into new migrations (Python part of the template, not a `##` Mako comment).
- **CI:** `ci.yml` job `reuse` runs `fsfe/reuse-action` (SHA in Global Constraints), hard, no `continue-on-error`. A backend guard test enforces the inline header where comments are possible, because `reuse lint` alone would also accept a `REUSE.toml` entry.
- **CONTRIBUTING.md** section "Licence headers": the two standard lines with an example per comment syntax; a contributor may add an own `SPDX-FileCopyrightText: <year> <name>` line (voluntary); the year is not bumped; `reuse lint` must pass. No PR-template checkbox, no extra CI hint job (maintainer, 2026-11-11).
- **One commit** for headers, `REUSE.toml`, `LICENSES/`, the test, the CI job and CONTRIBUTING; then `.git-blame-ignore-revs` with its SHA in a second, one-line commit (a commit cannot name its own SHA).

**Files:**
- Create: `REUSE.toml`, `LICENSES/*.txt`, `backend/tests/unit/test_spdx_headers.py`, `.git-blame-ignore-revs`
- Modify: every own file per the decisions (mechanical, `reuse annotate`), `.github/workflows/ci.yml` (job `reuse`), `CONTRIBUTING.md`, `backend/tests/unit/test_release_workflows.py` (`test_reuse_job`)

**Interfaces:**
- Produces: `HEADER_COPYRIGHT = "SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors"`, `HEADER_LICENCE = "SPDX-License-Identifier: AGPL-3.0-or-later"`, `COMMENTABLE_SUFFIXES` and `REUSE_TOML_ONLY` (path globs, read from `REUSE.toml`, not repeated) in `test_spdx_headers.py`.

- [ ] **Step 1: Write the failing tests.** `test_spdx_headers.py` over `git ls-files`: `test_own_sources_carry_header` (every tracked file with a suffix in `COMMENTABLE_SUFFIXES`, or named `Dockerfile`/`Makefile`, and not matched by a `REUSE.toml` annotation, has `HEADER_COPYRIGHT` and `HEADER_LICENCE` within its first 6 lines; further `SPDX-FileCopyrightText:` lines are allowed); `test_json_files_stay_json` (`licence-policy.yml`, `docs/licence-test-vectors.json`, `frontend/public/manifest.webmanifest`, `backend/licences/extra-records.json` parse with `json.loads`); `test_third_party_files_not_relicensed` (the fonts, `LICENSE`, `CODE_OF_CONDUCT.md` carry no AGPL inline header). `test_reuse_job` (`ci.yml` has job `reuse` with the pinned `fsfe/reuse-action` SHA and no `continue-on-error`). Run: FAIL.
- [ ] **Step 2: Spike S4 (20 min).** `pipx run reuse lint` on the branch: list every file without licensing information, group by type, and classify each group by the decisions above; anything third-party that is not in the list above is recorded with its source and stop-and-report if its licence is unclear.
- [ ] **Step 3: Implement.** `reuse annotate --copyright "Björn Strausmann and Labelyard contributors" --year 2026 --license AGPL-3.0-or-later --skip-unrecognised` on the own commentable files (Markdown with `--style html`), `REUSE.toml` for the rest, `reuse download --all`, the CI job, the CONTRIBUTING section.
- [ ] **Step 4: Run** `reuse lint` (clean), the full backend suite, `pnpm typecheck && pnpm lint && pnpm test:coverage && pnpm build`, `ruff format --check .` (headers above docstrings must not trip the formatter), `docker build -f backend/Dockerfile .` (the licence gate still parses the policy), and `git diff --stat` shows only additions of header lines outside `REUSE.toml`, `LICENSES/`, CONTRIBUTING and `ci.yml` (`git diff -U0 | grep '^-' | grep -v '^---'` empty). Counter-test: remove the header from one `.py` → `test_own_sources_carry_header` names it; put `#` into `licence-policy.yml` → `test_json_files_stay_json` fails; drop one `REUSE.toml` font entry → `reuse lint` fails.
- [ ] **Step 5: Commit** `chore(license): SPDX headers and REUSE metadata for every file` (`Refs #154`), then `chore(license): ignore the header commit in git blame` with `.git-blame-ignore-revs`.

### Task B5: Explicit `mode=max` provenance and an image content check in CI

**Files:** Modify `.github/workflows/docker-publish.yml` (build step: `provenance: true` → `provenance: mode=max`, `sbom: true` stays), `.github/workflows/ci.yml` (job `docker-build`), `backend/tests/unit/test_release_workflows.py`

- [ ] **Step 1: Write the failing guard tests** `test_provenance_max` (build step of `build` has `provenance: mode=max` and `sbom: true`, via `_load`) and `test_ci_image_check` (`ci.yml` `docker-build` has `load: true`, `tags: ${{ env.IMAGE }}`, a `download-syft` step pinned by SHA, and a `run:` containing `+sbom-cataloger`). Run: FAIL.
- [ ] **Step 2: Implement.** `docker-publish.yml`: `provenance: mode=max` (build args are only `VERSION`, `REVISION`, `BUILD_DATE` — nothing secret; `mode=max` also records the event payload, which for these triggers is public repository data). `ci.yml` `docker-build`: job `env: {IMAGE: "labelyard:ci"}`, build with `load: true`, Syft `v1.55.0` via `download-syft` (SHA in Global Constraints), gates:
  - `syft "$IMAGE" --select-catalogers +sbom-cataloger -o json | jq -e '[.artifacts[].name] as $n | ($n|index("react")) and ($n|index("react-dom")) and ($n|index("brother-ql")) and ($n|index("tini"))'`
  - `docker run --rm --entrypoint sh "$IMAGE" -c 'test -s /opt/app/web/licenses/backend.json && test -s /opt/app/web/licenses/frontend.json && test -s /opt/app/web/frontend.cdx.json && test -s /opt/app/LICENSE && test -s /opt/app/web/licenses/agpl-3.0.txt && test -s /usr/share/doc/tini/copyright && test -f /opt/venv/lib/python3.12/site-packages/brother_ql/__init__.py'`
  - informational, never a gate: default-catalogue `index("react")` into the step summary.
- [ ] **Step 3: Run** the guard tests and `actionlint` (report if unavailable, do not skip); run both gate commands locally against `docker build -f backend/Dockerfile -t labelyard:ci .`; push, CI green on the milestone push. Counter-test on a local scratch branch (not pushed; build and run the gate command locally): drop `frontend.cdx.json` from `additionalFiles` → the Syft gate fails. Revert.
- [ ] **Step 4: Commit** `ci(docker): pin max provenance and check the embedded SBOM and licence lists in CI` (`Refs #154`).

### Task B6: CycloneDX SBOM of the image as a release asset

**Files:** Modify `.github/workflows/docker-publish.yml` (`merge.outputs`, new job `sbom`), `.github/workflows/release.yml` (new job `release-sbom`), `backend/tests/unit/test_release_workflows.py` (new tests; `test_release_jobs_declare_minimal_permissions` extended)

**Interfaces:**
- `merge` gains `outputs: {image-ref: ${{ steps.image.outputs.ref }}, tag: ${{ steps.tag.outputs.tag }}}` (validated, `v`-stripped tag; one matrix entry today).
- `docker-publish.yml` job `sbom`: `needs: merge`, `if: inputs.tag != ''`, `permissions: {contents: read, packages: read}`, `outputs: {asset: …}`. Steps: GHCR login (existing pinned action, `GITHUB_TOKEN`; a new package may still be private), `download-syft`, then with `env: {IMAGE_REF: ${{ needs.merge.outputs.image-ref }}, TAG: ${{ needs.merge.outputs.tag }}}`: `asset="${IMAGE_REF##*/}-${TAG}.cdx.json"`; `syft "${IMAGE_REF}:${TAG}" --platform linux/amd64 --select-catalogers +sbom-cataloger -o "cyclonedx-json=${asset}"`; `jq -e '.components | map(.name) | (index("react") and index("brother-ql") and index("tini"))' "$asset"`; upload artifact `release-sbom` (`retention-days: 30`). Runs for releases and previews alike; never writes to a release.
- `release.yml` job `release-sbom`: `needs: [release, images]`, same `if` as `images`, `permissions: {contents: write}`, no checkout, no secret besides `GITHUB_TOKEN`. Steps: download artifact `release-sbom`; `env: {VERSION: ${{ needs.release.outputs.new-release-version }}, GH_REPO: ${{ github.repository }}, GH_TOKEN: ${{ github.token }}}`; validate `VERSION` with the same regex as `docker-publish.yml`; `gh release upload "v${VERSION}" ./*.cdx.json --clobber`; `gh release view "v${VERSION}" --json assets --jq '.assets[].name'` lists exactly one `.cdx.json`.

- [ ] **Step 1: Write the failing guard tests:** `test_sbom_job_is_read_only` (`sbom` permissions `{contents: read, packages: read}`; `docker-publish.yml` contains no `gh release`); `test_sbom_uses_merge_image_ref` (the `sbom` job's text contains `needs.merge.outputs.image-ref` and no `ghcr.io/` or `docker.io/` literal; `merge.outputs.image-ref == "${{ steps.image.outputs.ref }}"` and a step `id: image` exists in `merge`); `test_release_sbom_job` (`needs` ⊇ `images`, `if` equals `images.if`, permissions `{contents: write}`, no `${{ inputs.`/`${{ needs.` inside any `run:`, `GH_REPO` set, no `secrets.` except `github.token`); `test_release_jobs_declare_minimal_permissions` gains the new job. Run: FAIL.
- [ ] **Step 2: Implement** both jobs.
- [ ] **Step 3: Run** the guard tests and `actionlint`; locally `syft labelyard:ci --select-catalogers +sbom-cataloger -o cyclonedx-json=x.cdx.json && jq -e '…' x.cdx.json` with the job's filter. Expected: PASS. Counter-test: give `sbom` `contents: write` → `test_sbom_job_is_read_only` fails; replace the ref with a literal → `test_sbom_uses_merge_image_ref` fails.
- [ ] **Step 4: Commit** `ci(release): attach a CycloneDX SBOM of the image to each release` (`Refs #154`).

Releases 1.1.0–1.5.x keep no SBOM asset; a backfill (read a published image, `gh release upload`) only on the operator's request.

### Task B7: Documentation

**Files:** Create `docs/supply-chain.md` (with the SPDX header as HTML comment); modify `README.md` (section "Supply chain: SBOM and provenance" after "License": two sentences and the link to `docs/supply-chain.md`), `backend/tests/unit/test_licence_metadata.py`

- [ ] **Step 1: Write the failing test** `test_supply_chain_doc` with the module constant `SUPPLY_CHAIN_DOC = "docs/supply-chain.md"`: that file contains `imagetools inspect`, `{{ json .SBOM.SPDX }}`, `{{ json .Provenance }}`, `--select-catalogers +sbom-cataloger`, `frontend.cdx.json`, `.cdx.json`, `licence-policy.yml`, `/usr/share/doc`; `README.md` links `SUPPLY_CHAIN_DOC`. Run: FAIL.
- [ ] **Step 2: Implement** `docs/supply-chain.md` with the final names (`ghcr.io/strausmann/labelyard:<version>`, `docker.io/<user>/labelyard:<version>`, asset `labelyard-<version>.cdx.json`): getting SBOM and provenance without pulling (both registries); the release asset from 1.6.0 on; the embedded `frontend.cdx.json` and why scanners need `+sbom-cataloger` (BuildKit's SBOM does not list the web bundle — measured 2026-11-11: no `react` in the SPDX of 1.5.0); Scalar's subtree as an over-approximation; S1's build note; the lists at `/about`; OS packages (ruling R-a); the policy and its exception mechanism; SPDX headers and `reuse lint` (B9); VEX not provided (follow-up issue).
- [ ] **Step 3: Run.** Expected: PASS; `reuse lint` clean; `python3 scripts/brand_guard.py` is not available yet — instead `git diff origin/milestone/1.6.0...HEAD -U0 | grep '^+' | grep -niE 'label-printer-hub|Label Printer Hub|PRINTER_HUB_|printerhub|PrintHub|printer-hub[^.]'` prints nothing.
- [ ] **Step 4: Commit** `docs(docs): how to get the SBOM, provenance and licence lists of an image` (`Refs #154`).

### Task B8: Live check on the first Labelyard preview, then close #154

Not a code task; runs after the last rename task and rename Task 11 Step 5 has built `1.6.0-rc.N` (`<RC>`), and **before** `milestone/1.6.0` is merged into `main`. Uses that run — no extra image is built.

**Depends on two fixes outside this plan:** the 403 handling of `preview-image.yml` when it reads the package versions (1.5.x Task 1b), and the Docker Hub secrets handed to the preview build (rename Task 4). Without the first the preview run does not start, without the second Step 1 has no Docker Hub image — then Step 1 checks GHCR only and the Docker Hub check moves to the post-release check; that is reported, not skipped silently.

- [ ] **Step 1: Attestations on both registries.** For `ghcr.io/strausmann/labelyard:<RC>` and `docker.io/<DOCKERHUB_USERNAME>/labelyard:<RC>`: `docker buildx imagetools inspect <ref> --raw | jq -r '.manifests[] | [.platform.os,.platform.architecture,(.annotations["vnd.docker.reference.type"]//"-"),(.annotations["vnd.docker.reference.digest"]//"-")] | @tsv'` shows `linux/amd64`, `linux/arm64` and two attestation manifests whose `reference.digest` are exactly the two platform digests (subject); `--format '{{json .SBOM}}'` gives SPDX for both platforms; `--format '{{json .Provenance}}'` shows `buildkit_metadata.layers` (max). A missing attestation is stop-and-report.
- [ ] **Step 2: SBOM artefact.** `gh run download <preview run> -n release-sbom` yields `labelyard-<RC>.cdx.json`; `jq` finds `react`, `brother-ql`, `tini`; the embedded `frontend.cdx.json` in the image names `labelyard-web` as `metadata.component.name`. This file is exactly what `release.yml` uploads at the release.
- [ ] **Step 3: Product.** `docker run` the preview with a scratch volume; signed in, `/about` shows both lists, `brother-ql` expands to the GPL text; `/licenses/backend.json` does not list the project itself.
- [ ] **Step 4: Cleanup safety.** A dry run of the GHCR cleanup (`ghcr-cleanup.yml` or the rename's `registry-cleanup.yml`, `dry_run: true`) does not list any digest of Step 1.
- [ ] **Step 5: Close #154 before the milestone merge.** Tick the boxes of sections A (SPDX headers, via B9), C, D and the acceptance criteria that Steps 1–3 proved; annotate the boxes ruled otherwise (A "major version", the departures below). The criterion "each release has the CycloneDX SBOM attached" is ticked with the evidence of Step 2 plus the guard tests of B6 and the note that the asset itself is checked after the release (section "After the release"). Post ruling R-a, open the VEX follow-up issue (milestone 1.7.0 or Backlog, maintainer's choice), close #154 with a summary. Only then the milestone PR can pass the release guard.

---

## Commits and gates

- Each task commits directly on `milestone/1.6.0` (`git branch --show-current` = `milestone/1.6.0`, `git pull --ff-only` before the task) and pushes when its gates are green. Commit messages are the ones in the tasks; no `!`, no footer.
- **Before each push:** backend `ruff check .`, `ruff format --check .`, `mypy app`, `pytest -m "not slow" --cov=app --cov-fail-under=80` (for backend changes); frontend `pnpm typecheck`, `pnpm lint`, `pnpm test:coverage`, `pnpm build` (+ `pnpm e2e` for B3); `npx commitlint --from origin/milestone/1.6.0`; from B9 on `reuse lint`. Then the CI run of the push is green.
- **Per-task review** in the subagent-driven loop; B5, B6 and B9 with the four lenses (security-relevant workflows and the whole repo).
- **On the milestone → `main` PR** (owned by the milestone, not by this plan): `Dependency review` judges B2's devDependency; `release_impact.py check` reports a minor change; the whole-branch review with the four lenses covers Part B — taint (no build arg or env value reaches `backend.json`, `frontend.json` or a CycloneDX file; `repository` only `http(s)`; provenance `mode=max` records nothing secret), outcome (run the image, open `/about`, count records against `pip list` in the image), unchanged dependencies (`spa.py` licence handling and the route guard, `pwa.config.ts` precache, the `preview-image.yml` permission ceiling, `release.yml` output chain), runtime (`sbom` after `merge`, `release-sbom` after `images`, never in a dry run).
- **Security audit** (`security-audit`, 6 phases) at that PR on Part B's surface (B9's header-only lines excluded): rendering of untrusted licence texts, serving under `licenses/`, workflow values reaching `run:`, token scopes of `sbom`/`release-sbom`. HIGH/CRITICAL block until fixed or accepted by the operator. External bots (Codex, Copilot) before merge; re-review after each fix.
- **B9's `.git-blame-ignore-revs`** names the header commit's SHA on the milestone (no rebase changes it, since nothing is rebased).

## After the release (not part of #154)

Runs once `v1.6.0` is published:

- The release lists exactly one asset `labelyard-1.6.0.cdx.json`; B8 Step 1 holds for `ghcr.io/strausmann/labelyard:1.6.0` (and Docker Hub, if B8 had to skip it); the About page of the running 1.6.0 shows both lists.
- If `release-sbom` failed: `gh run download <release run> -n release-sbom` + `gh release upload v1.6.0 labelyard-1.6.0.cdx.json` (reads the artefact, rebuilds nothing). A defect in the workflow gets its own issue in the next patch milestone (`1.6.x`) with the run link; #154 stays closed.

## Departures from #154 (kept deliberately)

- Backend list generated in the `builder` stage from the venv the runtime receives, not in the final stage (no pip-licenses in the runtime image).
- Web list is `licenses/frontend.json`, not `oss-licenses.json` (one folder for every licence file).
- The release asset is produced by the image workflow and uploaded by `release.yml`, not by semantic-release (the release is published before the image exists).
- `BUILDKIT_SBOM_SCAN_STAGE` stays off; the embedded CycloneDX answers the "frontend packages" item (measured: BuildKit's SBOM has no `react`).
