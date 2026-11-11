# Licence Part B for 1.6.0 — Licence Lists, Embedded SBOM, Provenance and Release SBOM — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The first Labelyard image (1.6.0) lists every shipped third-party licence on the About page, carries a CycloneDX SBOM of its web bundle, has BuildKit SBOM and `mode=max` provenance attestations on GHCR and Docker Hub, and every release from 1.6.0 on has a CycloneDX SBOM of the image attached.

**Architecture:** One feature branch `feat/licence-part-b`, one PR into `milestone/1.6.0`, merged **before** the rename PR (`feat/labelyard-rename`, which is the last PR of the milestone). Nothing Part B adds spells a product or image name: the backend list excludes the project by the name in `backend/pyproject.toml`, the CycloneDX component takes its name from `frontend/package.json`, and the SBOM job takes the image reference from the `merge` job of `docker-publish.yml`. So when the rename changes those three sources, Part B's output says `labelyard` without a second edit. The SBOM is produced inside the image workflow (read-only), the upload to the GitHub release happens in `release.yml` (the only place with `contents: write`).

**Tech Stack:** FastAPI/Pydantic, React 19 + TanStack Query + Lingui, Vite 8 + `rollup-license-plugin` 3.2.1 (MIT, build-time), `pip-licenses` 5.5.5 (MIT, tool venv only), Docker Buildx/BuildKit attestations via `docker/build-push-action` v7, Syft v1.55.0 via `anchore/sbom-action/download-syft@v0.24.3`, GitHub Actions.

**Spec:** https://github.com/strausmann/Label-Printer-Hub/issues/154 sections C and D plus the acceptance criteria. Input, not repeated here: Part B of `docs/superpowers/plans/2026-11-05-agpl-relicense-licences-sbom.md` (written for 1.2.0, never executed) and its unmerged revision of 2026-11-09 on branch `feat/agpl-part-b` (rulings R-a…R-g, adopted below where still true). The rename plan this one is ordered against: `docs/superpowers/plans/2026-11-09-labelyard-rename.md` on branch `docs/labelyard-rename-plan` (not changed by this plan). Not legal advice.

## Global Constraints

- Release **1.6.0** = rename (#280) + this plan. Minor release: `feat` is allowed; **no commit and no PR title with `!`, no `BREAKING CHANGE:`/`BREAKING-CHANGE:` footer** — semantic-release would compute 2.0.0. Issue #154's own title is `feat!: …`; the PR title is **not** taken from it.
- Only B3 is a `feat` (`feat(ui)`); every other commit is `build`, `ci` or `docs` (none of them releases, `.releaserc.json` `releaseRules`).
- Commit scopes from `commitlint.config.cjs` only (`docker`, `web`, `ui`, `ci`, `release`, `docs`, `license`). Author `bjoern@strausmann.net`. No AI attribution, no internal host names (public repo, `ci.yml` privacy scan).
- Prose English; UI copy en + de, German in informal "du" (maintainer decision 2026-11-09), British "licence" as the noun, SPDX ids unchanged.
- **No old-name literal in any line Part B adds**: none of `label-printer-hub`, `Label Printer Hub`, `PRINTER_HUB_`, `printer-hub` (except `printer-hub.db`), `PrintHub`, `printerhub` — the rename's `scripts/brand_guard.py` rules. Names that are needed are read from `backend/pyproject.toml`, `frontend/package.json` or the `merge` job output. Where a document must name the published image (README, notices), it uses the final name `labelyard` (these files first go public with 1.6.0).
- No new runtime dependency. Build-time only: `rollup-license-plugin@3.2.1` (exact pin, `frontend` devDependencies), `pip-licenses==5.5.5` (tool venvs only, never `/opt/venv`).
- Actions added to `docker-publish.yml`, `release.yml` and `ci.yml` are pinned by full commit SHA with the version as comment (`test_actions_are_pinned_to_full_commit_shas`). Values resolved on 2026-11-11, re-resolve at implementation: `anchore/sbom-action/download-syft` `v0.24.3` = `66cbf4bc1f1c0d2edc94016e65bc221b6bb0ad6c`; Syft `v1.55.0` (2026-10-19; v1.57.1 is two days old and not taken). `actions/download-artifact` and `actions/upload-artifact` reuse the SHAs already in `docker-publish.yml`.
- Workflow inputs and job outputs reach `run:` only through `env:`.
- `test_image_labels_and_licence_file` counts `licenses=AGPL-3.0-or-later` exactly twice in `docker-publish.yml`: add no further `licenses=` text there.
- Image stays non-root UID 1000; the CSP in `backend/app/web/spa.py` and the precache globs in `frontend/pwa.config.ts` (no `json`) stay unchanged; `BUILDKIT_SBOM_SCAN_STAGE` stays off.
- Never rebuild or push an already published version. No throwaway release tags: the live check (B8) uses the milestone preview `1.6.0-rc.N` that the rename plan builds anyway.
- Coverage gates stay: backend `--cov-fail-under=80`, web 70 %. UI work loads the design skills (`.claude`-side rule of the operator; named in B3).

## Preconditions

1. **1.5.1 is released and synced.** `v1.5.1` is on `main`, `main` is merged into `milestone/1.6.0` (merge commit), and `feat/licence-part-b` is branched from that head. Check: `git merge-base --is-ancestor v1.5.1 origin/milestone/1.6.0` → exit 0. 1.5.1 brings, and this plan relies on:
   - PR #270 (1.5.1 Task 1): CI, licence gate and backend licence workflow also run on PRs into `milestone/**`; release guard `release_impact.py`; register row **D21** is taken by it.
   - PR #269 (1.5.1 Task 1b): `preview-image.yml` (calls `docker-publish.yml` with `tag: x.y.z-rc.N`, `ref`, permissions `contents: read, packages: write, id-token: write`), no branch images, `ghcr-cleanup.yml` that keeps platform children and attestations of kept images.
   - 1.5.1 Task 14: `GET /licenses/<unknown>` answers 404 (`spa.py`, test `test_unknown_licence_page_is_404`), `licence-text-sha256` in exceptions, `Proprietary` inside a classifier join → `UNKNOWN`.
2. If 1.5.1 Task 14 left the `licenses/` 404 out, B1 adds it (the Part B rule: `full_path.startswith(("assets/", "licenses/"))` in the miss branch, never via `_RESERVED_PREFIXES`); otherwise B1 does not touch `spa.py`.

## Ordering with the rename

**Decision: Part B merges into `milestone/1.6.0` first; the rename PR stays the last PR of the milestone** (as the rename plan rules). Reason: the rename's brand guard sweeps the whole tree after everything else has landed, and Part B is written so that the guard finds nothing in Part B's lines (Global Constraints) — the rename only changes the three name sources, and Part B's outputs follow. Building Part B after the rename would also work, but it would contradict the rename plan's "last PR" rule and make the rename branch rebase over Part B's workflow changes.

Sequence: 1.5.1 released → sync → **B1–B7 PR merged into the milestone** → rename branch syncs the milestone (rename Task 10) → rename PR merged → preview `1.6.0-rc.N` (rename Task 11 Step 5) → **B8 live check on that preview** → milestone → `main` → release 1.6.0 → **B8 close-out**.

What ends up named `labelyard` and why no file is rebuilt twice:

| Artefact | Source Part B reads | Changed by |
|---|---|---|
| Image ref of SBOM job and release asset name `<image>-<version>.cdx.json` | `needs.merge.outputs.image-ref` (= the `image` step's `ref` in `merge`) | rename Task 4 (ref steps) |
| OCI labels / index annotations | untouched by Part B | rename Tasks 3, 4 |
| Attestation subject | BuildKit derives it from the pushed `name=` of the build step | rename Task 4 (same ref) |
| CycloneDX `metadata.component.name`, excluded own package in the web list | `frontend/package.json` `name` | rename Task 5 |
| Excluded own package in the backend list | `backend/pyproject.toml` `[project].name` | rename Task 3 |
| Local CI image tag | `env.IMAGE: labelyard:ci` in `ci.yml` `docker-build` (B5 replaces today's `label-printer-hub:ci` while it rewrites that job) | — |

Files both plans touch, in this order (Part B first, rename second):

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
| `README.md` | B7: new section after "License" | Task 6 (hero, links, config), Task 7 (moves user docs to the site) | B7's section uses final names; if the rename moves it to the website, it moves as a whole |
| `docs/decisions/register.md` | B1 appends one row | Task 6 appends its rows | append-only; Part B takes the next free `D` label on the synced head (expected **D22**, D21 is #270's) |

**Registries and attestations (the GitLab registry concern).** Attestations are stored as extra manifests (`unknown/unknown`, `vnd.docker.reference.type: attestation-manifest`) in the image index (https://docs.docker.com/build/metadata/attestations/). `docker/build-push-action` adds them only when pushing to a registry, not with `load: true` (https://docs.docker.com/build/ci/github-actions/attestations/). GHCR accepts OCI image indexes (https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry, "Docker Image Manifest V2, Schema 2" and "Open Container Initiative (OCI) Specifications"); Docker Hub's Docker Scout reads SBOM attestations from pushed images (https://docs.docker.com/scout/explore/analysis/: "When an image includes an SBOM attestation, Docker Scout uses it"). Neither page names registries for attestations, so it was **measured on 2026-11-11** with today's workflow (`provenance: true`, `sbom: true`, push by digest + `imagetools create`):

- `ghcr.io/strausmann/label-printer-hub-backend:1.5.0` and `docker.io/strausmann/label-printer-hub-backend:1.5.0`: index with `linux/amd64`, `linux/arm64` and one attestation manifest each; `{{json .SBOM}}` returns SPDX-2.3 (232 packages, contains `brother-ql` and `tini`, **not** `react`); `{{json .Provenance}}` returns SLSA provenance with `buildkit_metadata.layers/source/vcs` and `internalParameters.buildConfig` — already `mode=max` content (the action's default for public repositories). B5 makes it explicit so it no longer depends on that default.
- The GHCR cleanup of #269 uses `dataaxiom/ghcr-cleanup-action`, which follows manifest lists and referrers and keeps the children of kept images (its header comment); B8 checks that its dry run does not list the preview's attestation digests.

## What changed against the old Part B

| Old Part B (2026-11-05, rev. 2026-11-09) | Now (v1.5.0 + 1.5.1 + rename) |
|---|---|
| Release 1.2.0, then 1.6.0 "after 1.5.0", PR into `main`, rebase merge | 1.6.0 with the rename; PR `feat/licence-part-b` → `milestone/1.6.0`, before the rename PR |
| B1 adds the `licenses/` 404 to `spa.py` | done by 1.5.1 Task 14; B1 only adds a test that `backend.json` is served as `application/json` |
| `OWN_PACKAGE = "label-printer-hub-backend"` stays | read from `pyproject.toml` (`--own-project`), so the rename's package name flows through |
| Extra records: DejaVu only | DejaVu, Atkinson Hyperlegible Next, IBM Plex Mono (fonts added in #258) and the gLabels-qt sheet data (MIT) |
| D21 for the decision | D21 taken by #270 → next free label (expected D22) |
| CycloneDX component `label-printer-hub-web`, `excludedPackageTest` literal | name read from `frontend/package.json` |
| B5 "turn provenance to mode=max" + spike S2 | content is already max (measured); B5 pins `mode=max`; S2 answered by measurement (BuildKit SBOM lacks `react` → embedded CycloneDX + `+sbom-cataloger`) |
| B5 CI tag `label-printer-hub:ci`, actions by major tag | `labelyard:ci` via `env.IMAGE`; Syft action SHA-pinned |
| B6 job `release-sbom` in `docker-publish.yml` with `contents: write`, hard-coded `ghcr.io/strausmann/label-printer-hub-backend` and asset name | `docker-publish.yml` job `sbom` is read-only (else the preview workflow, which grants `contents: read`, fails validation); upload moves to `release.yml` job `release-sbom`; ref and asset name from `merge` outputs |
| Live tests with `v0.0.0-ci.<n>` tags and GHCR cleanup | none; B8 checks the milestone preview `1.6.0-rc.N` of the renamed image |
| Docker Hub not checked | B8 checks attestations on Docker Hub too (rename Task 4 pushes previews there) |
| CI on PRs into the target branch assumed | CI on `milestone/**` PRs comes with #270 (precondition) |

## Review Focus

1. **A preview (`1.6.0-rc.N`) or a Docker Hub-only failure must not break the image workflow.** A preview has no GitHub release; the SBOM job must never write to releases and must pass with `contents: read`. → B6 `test_sbom_job_is_read_only`.
2. **After the rename, the SBOM describes the old image or the asset carries the old name.** → B6 `test_sbom_uses_merge_image_ref` (no registry literal in the job, ref only from `needs.merge.outputs`), B8 asset name check.
3. **Licence data missing, foreign or hostile:** API-only image, Vite dev server, 404, 200 `text/html` app shell, 2 MB list, `<script>` in a text. The About page keeps the project licence and source link, says which list is missing, renders texts as text and mounts a text only when expanded. → B3 tests.
4. **The project lists itself after `pyproject.toml` is renamed.** → B1 `test_own_package_read_from_pyproject`.
5. **Accidental 2.0.0.** A `!` in a commit or in the PR title (squash or rebase), or a footer. → Merge section: `scripts/release_impact.py check` on the merge result prints `1.6.0`, commitlint on every commit.

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
| `.github/workflows/ci.yml` | `docker-build` checks the image content |

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
  - `def load_extra(path: Path, root: Path) -> list[LicenceRecord]` — entries `{name, version, license, licenseTextFile, repository}`, `licenseTextFile` relative to `root`; a missing file raises `ValueError` naming it.
  - `def to_records(entries, policy: Policy, fallback_dir: Path, extra: Sequence[LicenceRecord] = ()) -> list[LicenceRecord]  # D<next>` — `license` from `classify`; `licenseText` = own `LicenseText` (not `UNKNOWN`), else `fallback_dir/<id>.txt` when the expression is a single id, else `None`; `repository` = pip-licenses `URL` if `http(s)://`, else `None`; `extra` appended unjudged; sorted by `name.lower()`.
  - CLI: `--own-project <pyproject.toml>` (required), `--output <path>` (`json.dumps(records, ensure_ascii=False, indent=2)`, written also when the check fails), `--require-texts` (exit 1, each record without text named on stdout), `--extra <path>`, `--fallback-dir <path>` (default `licences`). Exit 1 for any policy offender, as today. The old `classified` output (`allowed` key) goes.
- `extra-records.json`: `DejaVu Sans` 2.37 `Bitstream-Vera` (`app/page_render/fonts/LICENSE-DejaVu.txt`), `Atkinson Hyperlegible Next` `google/fonts@66eef70` `OFL-1.1`, `IBM Plex Mono Bold` `google/fonts@633f320` `OFL-1.1` (their `LICENSE-*-OFL.txt`), `gLabels-qt templates` `37901c1` `MIT` (`licences/glabels-qt-MIT.txt`); repositories as in `THIRD_PARTY_NOTICES.md`.
- Image: `/opt/app/web/licenses/backend.json`, served at `/licenses/backend.json` by the SPA file branch (no new route; `test_route_versioning.py` stays green).

- [ ] **Step 1: Write the failing tests** in `test_licence_report.py`: `test_own_package_read_from_pyproject` (tmp `pyproject.toml` with `name = "some-app"` → `"some-app"`, and `_collect(..., own="some-app")` drops `Some_App`); `test_to_records_shape` (exactly the five keys); `test_to_records_sorted` (`b, A, c` → `A, b, c`); `test_text_fallback_for_brother_ql` (no `LicenseText`, GPLv3+ classifier → text starts `GNU GENERAL PUBLIC LICENSE`); `test_no_fallback_for_compound_expression` (`MIT OR Apache-2.0` → `None`); `test_repository_only_http` (`javascript:x` → `None`); `test_extra_record_appended_unjudged` (`Bitstream-Vera` in the output, exit 0); `test_load_extra_missing_file_names_it`; `test_require_texts_fails_without_text`; `test_output_round_trip` (`<script>` and `ü` unchanged); `test_main_exit_codes_and_output` changed (offender → exit 1 and `bad (GPL-2.0-only)` on stdout; file = five-key records `{"ok", "bad"}`, no `allowed`). Rename the fixture name in `test_collect_excludes_the_own_package_and_reports_tool_failure` to a neutral one. In `test_spa_serving.py`: `test_backend_licence_list_served` (fixture dist with `licenses/backend.json` → 200, `content-type` starts `application/json`, bytes equal).
- [ ] **Step 2: Run** `cd backend && pytest tests/unit/scripts/test_licence_report.py tests/integration/api/test_spa_serving.py -v`. Expected: new tests FAIL; `test_backend_licence_list_served` may already pass (it pins the file branch; record it).
- [ ] **Step 3: Spike S3b (15 min)** in `docker build -f backend/Dockerfile --target builder -t lyb1-builder .`: list the `.py` files of `brother_ql` and `ptouch` in `/opt/venv/lib/python3.12/site-packages`; run pip-licenses as the Dockerfile does and list every package with empty `LicenseText` (at least `brother-ql`, `packbits`, `ptouch`, `pysnmp`, `qrcode`, `Jinja2`, `pyusb`, `reportlab`, `charset-normalizer`). Each single SPDX id without text gets a verbatim canonical text in `backend/licences/` (URL and sha256 in the commit body); a compound expression without text is resolved by the exception's `licence` being a single id, never by a guessed text. In the runtime stage: `for p in libjpeg62-turbo zlib1g curl tini ca-certificates fonts-dejavu-core; do test -s /usr/share/doc/$p/copyright || echo MISSING $p; done` prints nothing (else stop and report).
- [ ] **Step 4: Implement** the functions and flags; Dockerfile builder: `COPY backend/licences/ /build/licences/` and run from `WORKDIR /build` with `--own-project pyproject.toml --output /build/backend-licences.json --require-texts --extra licences/extra-records.json --fallback-dir licences` (the extra font texts are at `/build/app/page_render/fonts/`, already copied); runtime: `COPY --from=builder --chown=hub:hub /build/backend-licences.json /opt/app/web/licenses/backend.json`; the register row.
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
- [ ] **Step 3: Spike S1 (20 min).** Wire the plugin; build once in `docker build --target web-builder --network none` and once online. Record in the PR: `@react-aria/*` and `@fontsource/*` present without `includePackages`?; `licenseText` from `node_modules` or downloaded?; size of the Scalar subtree; the zxing-cpp version zxing-wasm 3.1.6 bundles. A network fetch is acceptable and goes into B7's build note.
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

### Task B5: Explicit `mode=max` provenance and an image content check in CI

**Files:** Modify `.github/workflows/docker-publish.yml` (build step: `provenance: true` → `provenance: mode=max`, `sbom: true` stays), `.github/workflows/ci.yml` (job `docker-build`), `backend/tests/unit/test_release_workflows.py`

- [ ] **Step 1: Write the failing guard tests** `test_provenance_max` (build step of `build` has `provenance: mode=max` and `sbom: true`, via `_load`) and `test_ci_image_check` (`ci.yml` `docker-build` has `load: true`, `tags: ${{ env.IMAGE }}`, a `download-syft` step pinned by SHA, and a `run:` containing `+sbom-cataloger`). Run: FAIL.
- [ ] **Step 2: Implement.** `docker-publish.yml`: `provenance: mode=max` (build args are only `VERSION`, `REVISION`, `BUILD_DATE` — nothing secret; `mode=max` also records the event payload, which for these triggers is public repository data). `ci.yml` `docker-build`: job `env: {IMAGE: "labelyard:ci"}`, build with `load: true`, Syft `v1.55.0` via `download-syft` (SHA in Global Constraints), gates:
  - `syft "$IMAGE" --select-catalogers +sbom-cataloger -o json | jq -e '[.artifacts[].name] as $n | ($n|index("react")) and ($n|index("react-dom")) and ($n|index("brother-ql")) and ($n|index("tini"))'`
  - `docker run --rm --entrypoint sh "$IMAGE" -c 'test -s /opt/app/web/licenses/backend.json && test -s /opt/app/web/licenses/frontend.json && test -s /opt/app/web/frontend.cdx.json && test -s /opt/app/LICENSE && test -s /opt/app/web/licenses/agpl-3.0.txt && test -s /usr/share/doc/tini/copyright && test -f /opt/venv/lib/python3.12/site-packages/brother_ql/__init__.py'`
  - informational, never a gate: default-catalogue `index("react")` into the step summary.
- [ ] **Step 3: Run** the guard tests and `actionlint` (report if unavailable, do not skip); run both gate commands locally against `docker build -f backend/Dockerfile -t labelyard:ci .`; push, CI green on the PR. Counter-test on a scratch commit: drop `frontend.cdx.json` from `additionalFiles` → the Syft gate fails. Revert.
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

**Files:** Modify `README.md` (new section "Supply chain: SBOM and provenance" after "License"), `backend/tests/unit/test_licence_metadata.py`

- [ ] **Step 1: Write the failing test** `test_readme_supply_chain`: README contains `imagetools inspect`, `{{ json .SBOM.SPDX }}`, `{{ json .Provenance }}`, `--select-catalogers +sbom-cataloger`, `frontend.cdx.json`, `.cdx.json`, `licence-policy.yml`, `/usr/share/doc`. Run: FAIL.
- [ ] **Step 2: Implement.** With the final names (`ghcr.io/strausmann/labelyard:<version>`, `docker.io/<user>/labelyard:<version>`, asset `labelyard-<version>.cdx.json`): getting SBOM and provenance without pulling (both registries); the release asset from 1.6.0 on; the embedded `frontend.cdx.json` and why scanners need `+sbom-cataloger` (BuildKit's SBOM does not list the web bundle — measured 2026-11-11: no `react` in the SPDX of 1.5.0); Scalar's subtree as an over-approximation; S1's build note; the lists at `/about`; OS packages (ruling R-a); the policy and its exception mechanism; VEX not provided (follow-up issue).
- [ ] **Step 3: Run.** Expected: PASS; `python3 scripts/brand_guard.py` is not available yet — instead `git diff origin/milestone/1.6.0...HEAD -U0 | grep '^+' | grep -niE 'label-printer-hub|Label Printer Hub|PRINTER_HUB_|printerhub|PrintHub|printer-hub[^.]'` prints nothing.
- [ ] **Step 4: Commit** `docs(docs): how to get the SBOM, provenance and licence lists of an image` (`Refs #154`).

### Task B8: Live check on the first Labelyard preview, close-out after 1.6.0

Not a code task; runs after the rename PR is merged and rename Task 11 Step 5 has built `1.6.0-rc.N` (`<RC>`). Uses that run — no extra image is built.

- [ ] **Step 1: Attestations on both registries.** For `ghcr.io/strausmann/labelyard:<RC>` and `docker.io/<DOCKERHUB_USERNAME>/labelyard:<RC>`: `docker buildx imagetools inspect <ref> --raw | jq -r '.manifests[] | [.platform.os,.platform.architecture,(.annotations["vnd.docker.reference.type"]//"-"),(.annotations["vnd.docker.reference.digest"]//"-")] | @tsv'` shows `linux/amd64`, `linux/arm64` and two attestation manifests whose `reference.digest` are exactly the two platform digests (subject); `--format '{{json .SBOM}}'` gives SPDX for both platforms; `--format '{{json .Provenance}}'` shows `buildkit_metadata.layers` (max). A missing attestation on one registry is stop-and-report.
- [ ] **Step 2: SBOM artefact.** `gh run download <preview run> -n release-sbom` yields `labelyard-<RC>.cdx.json`; `jq` finds `react`, `brother-ql`, `tini`; `metadata` of the embedded `frontend.cdx.json` in the image names `labelyard-web`.
- [ ] **Step 3: Product.** `docker run` the preview with a scratch volume; signed in, `/about` shows both lists, `brother-ql` expands to the GPL text; `/licenses/backend.json` excludes the project (`labelyard` not in the names).
- [ ] **Step 4: Cleanup safety.** Dry run of the GHCR cleanup (`ghcr-cleanup.yml`/`registry-cleanup.yml`, `dry_run: true`) does not list any digest of Step 1.
- [ ] **Step 5: Close-out after 1.6.0.** The release has exactly `labelyard-1.6.0.cdx.json`; Step 1 holds for `1.6.0`; the About page of the running 1.6.0 shows both lists. If `release-sbom` failed: `gh run download <release run> -n release-sbom` + `gh release upload v1.6.0 …` (no rebuild). Tick #154's boxes (C, D, acceptance criteria; annotate the A boxes ruled otherwise), post ruling R-a, open the VEX follow-up issue, close #154 with a summary.

---

## Merge and release

- **PR** `feat/licence-part-b` → `milestone/1.6.0`, title `feat(ui): licence lists, embedded SBOM and release SBOM (#154)` (no `!`), body with `Refs #154`, spike results S1/S3b and the counter-test results. Merged with **"Rebase and merge"** after review fix-ups are folded in with `git rebase -i --autosquash`, so B1–B7 stay seven commits.
- **Before opening and before merging:** backend `ruff check .`, `ruff format --check .`, `mypy app`, `pytest -m "not slow" --cov=app --cov-fail-under=80`; frontend `pnpm typecheck`, `pnpm lint`, `pnpm test:coverage`, `pnpm build`, `pnpm e2e`; `npx commitlint --from origin/milestone/1.6.0`; `python3 scripts/release_impact.py check` (from #270) on `origin/milestone/1.6.0..HEAD` reports a minor change; the CI run of the PR (incl. `Dependency review` for `rollup-license-plugin`, licence backend workflow, `docker-build`) is green.
- **Whole-branch review** with the four lenses: taint (no build arg or env value reaches `backend.json`, `frontend.json` or a CycloneDX file; `repository` only `http(s)`; provenance `mode=max` records nothing secret), outcome (run the image, open `/about`, count records against `pip list` in the image), unchanged dependencies (`spa.py` file branch and the route guard, `pwa.config.ts` precache, the `preview-image.yml` permission ceiling, `release.yml` output chain), runtime (`sbom` after `merge`, `release-sbom` after `images`, never in a dry run).
- **Security audit** (`security-audit`, 6 phases) on the changed surface before the PR opens and after any rebase that touches it: rendering of untrusted licence texts, serving under `licenses/`, workflow values reaching `run:`, token scopes of `sbom`/`release-sbom`. HIGH/CRITICAL block until fixed or accepted by the operator.
- **External bots** (Codex, Copilot) before merge; re-review after each fix.
- Then the rename PR (rename plan Task 10 syncs the milestone, so it sees Part B).

## Departures from #154 (kept deliberately)

- Backend list generated in the `builder` stage from the venv the runtime receives, not in the final stage (no pip-licenses in the runtime image).
- Web list is `licenses/frontend.json`, not `oss-licenses.json` (one folder for every licence file).
- The release asset is produced by the image workflow and uploaded by `release.yml`, not by semantic-release (the release is published before the image exists).
- `BUILDKIT_SBOM_SCAN_STAGE` stays off; the embedded CycloneDX answers the "frontend packages" item (measured: BuildKit's SBOM has no `react`).
