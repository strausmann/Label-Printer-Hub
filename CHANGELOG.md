# Changelog

All notable changes to this project will be documented in this file.

This project adheres to [Semantic Versioning](https://semver.org/) and uses [Conventional Commits](https://www.conventionalcommits.org/) via [semantic-release](https://github.com/semantic-release/semantic-release).

## 0.3.0 (2026-05-12)

* feat(config): pydantic-settings module with env-driven runtime configuration (#45) ([878e9e0](https://github.com/strausmann/label-printer-hub/commit/878e9e0)), closes [#45](https://github.com/strausmann/label-printer-hub/issues/45)
* feat(integrations): AppLookupService aggregator — Phase 3 complete (#53) ([222bef4](https://github.com/strausmann/label-printer-hub/commit/222bef4)), closes [#53](https://github.com/strausmann/label-printer-hub/issues/53)
* feat(integrations): Grocy + Spoolman lookup clients with shared NotFoundError base (#52) ([b1c9c3c](https://github.com/strausmann/label-printer-hub/commit/b1c9c3c)), closes [#52](https://github.com/strausmann/label-printer-hub/issues/52)
* feat(integrations): LabelData schema + Snipe-IT lookup client (#51) ([3bc180f](https://github.com/strausmann/label-printer-hub/commit/3bc180f)), closes [#51](https://github.com/strausmann/label-printer-hub/issues/51)
* feat(label-renderer): Template schema + Pillow/qrcode renderer for 1-bit label bitmaps (#54) ([fb77028](https://github.com/strausmann/label-printer-hub/commit/fb77028)), closes [#54](https://github.com/strausmann/label-printer-hub/issues/54)
* feat(printer-models): Brother PT-Series TapeRegistry with TZe and heat-shrink specs (#47) ([7526019](https://github.com/strausmann/label-printer-hub/commit/7526019)), closes [#47](https://github.com/strausmann/label-printer-hub/issues/47)
* feat(printer-models): Job lifecycle FSM with explicit state machine (#49) ([1a8c40e](https://github.com/strausmann/label-printer-hub/commit/1a8c40e)), closes [#49](https://github.com/strausmann/label-printer-hub/issues/49)
* feat(printer-models): PrinterModel Protocol + ModelRegistry for plugin discovery (#48) ([2ae0e09](https://github.com/strausmann/label-printer-hub/commit/2ae0e09)), closes [#48](https://github.com/strausmann/label-printer-hub/issues/48)
* feat(printer-models): PrintQueue worker with pause/resume/cancel/retry (#50) ([dfdf6fe](https://github.com/strausmann/label-printer-hub/commit/dfdf6fe)), closes [#50](https://github.com/strausmann/label-printer-hub/issues/50)

## <small>0.2.1 (2026-05-11)</small>

* fix(ci): emit GHCR package description as index annotation (#39) ([12c6b6c](https://github.com/strausmann/label-printer-hub/commit/12c6b6c)), closes [#39](https://github.com/strausmann/label-printer-hub/issues/39)
* fix(ci): lowercase image ref before push-by-digest (#41) ([9dd954e](https://github.com/strausmann/label-printer-hub/commit/9dd954e)), closes [#41](https://github.com/strausmann/label-printer-hub/issues/41)
* fix(ci): repair docker-publish.yml startup failure (#37) ([fb7cb59](https://github.com/strausmann/label-printer-hub/commit/fb7cb59)), closes [#37](https://github.com/strausmann/label-printer-hub/issues/37)
* fix(ci): repair Verify multi-arch manifest step + drop fail-fast (#38) ([5d2ff7d](https://github.com/strausmann/label-printer-hub/commit/5d2ff7d)), closes [#38](https://github.com/strausmann/label-printer-hub/issues/38)
* refactor(ci): split docker-publish into native-arch matrix + manifest merge (#40) ([8cd824d](https://github.com/strausmann/label-printer-hub/commit/8cd824d)), closes [#40](https://github.com/strausmann/label-printer-hub/issues/40)
* chore(deps): bump github.com/go-chi/chi/v5 from 5.1.0 to 5.2.2 in /frontend (#36) ([a5971b9](https://github.com/strausmann/label-printer-hub/commit/a5971b9)), closes [#36](https://github.com/strausmann/label-printer-hub/issues/36)

## 0.2.0 (2026-05-10)

* feat(backend): FastAPI app skeleton + /healthz endpoint + Dockerfile (#34) ([0efbb0c](https://github.com/strausmann/label-printer-hub/commit/0efbb0c)), closes [#34](https://github.com/strausmann/label-printer-hub/issues/34) [#34](https://github.com/strausmann/label-printer-hub/issues/34) [#34](https://github.com/strausmann/label-printer-hub/issues/34) [#34](https://github.com/strausmann/label-printer-hub/issues/34)
* feat(frontend): Go web server skeleton with /healthz + Dockerfile (#35) ([0b3ed6b](https://github.com/strausmann/label-printer-hub/commit/0b3ed6b)), closes [#35](https://github.com/strausmann/label-printer-hub/issues/35)

## 0.1.0 (2026-05-10)

* docs: refactor — ADRs in docs/decisions/, policies in docs/policies/, slim CLAUDE.md ([51c2cf1](https://github.com/strausmann/label-printer-hub/commit/51c2cf1)), closes [#1](https://github.com/strausmann/label-printer-hub/issues/1)
* docs(ci): document mypy as hard gate; clarify CI gate policy in CONTRIBUTING (#31) ([e1e6f18](https://github.com/strausmann/label-printer-hub/commit/e1e6f18)), closes [#31](https://github.com/strausmann/label-printer-hub/issues/31) [#30](https://github.com/strausmann/label-printer-hub/issues/30) [#30](https://github.com/strausmann/label-printer-hub/issues/30) [#30](https://github.com/strausmann/label-printer-hub/issues/30)
* docs(decisions): ADR 0006 — PT vs QL ESC i S behaviour from Phase-0 hardware test ([0d12c63](https://github.com/strausmann/label-printer-hub/commit/0d12c63)), closes [#12](https://github.com/strausmann/label-printer-hub/issues/12) [#11](https://github.com/strausmann/label-printer-hub/issues/11)
* docs(decisions): ADR 0012 — layout management; clarify integration push/pull capabilities ([effcbdf](https://github.com/strausmann/label-printer-hub/commit/effcbdf)), closes [#17](https://github.com/strausmann/label-printer-hub/issues/17) [#19](https://github.com/strausmann/label-printer-hub/issues/19)
* docs(decisions): ADR 0013 + cart UI spec + AI-review workflow ([c72dc85](https://github.com/strausmann/label-printer-hub/commit/c72dc85)), closes [#26](https://github.com/strausmann/label-printer-hub/issues/26) [#27](https://github.com/strausmann/label-printer-hub/issues/27) [#28](https://github.com/strausmann/label-printer-hub/issues/28)
* docs(docker): document image tag scheme (latest, 1.0.0, 1.0, 1) ([1f72396](https://github.com/strausmann/label-printer-hub/commit/1f72396))
* docs(examples): sample compose files for standalone/Traefik/Pangolin/Caddy ([a2f6f3d](https://github.com/strausmann/label-printer-hub/commit/a2f6f3d))
* docs(learnings): add code-review-patterns + reference from CLAUDE/CONTRIBUTING/AI configs (#33) ([0fc61d2](https://github.com/strausmann/label-printer-hub/commit/0fc61d2)), closes [#33](https://github.com/strausmann/label-printer-hub/issues/33) [#29](https://github.com/strausmann/label-printer-hub/issues/29) [#30](https://github.com/strausmann/label-printer-hub/issues/30) [#32](https://github.com/strausmann/label-printer-hub/issues/32) [#6](https://github.com/strausmann/label-printer-hub/issues/6)
* ci: make Python lint/test job branch-tolerant for dependabot PRs (#30) ([6ee8e16](https://github.com/strausmann/label-printer-hub/commit/6ee8e16)), closes [#30](https://github.com/strausmann/label-printer-hub/issues/30) [2-#9](https://github.com/2-/issues/9) [#2](https://github.com/strausmann/label-printer-hub/issues/2) [#3](https://github.com/strausmann/label-printer-hub/issues/3) [#4](https://github.com/strausmann/label-printer-hub/issues/4) [#6](https://github.com/strausmann/label-printer-hub/issues/6) [#7](https://github.com/strausmann/label-printer-hub/issues/7) [#8](https://github.com/strausmann/label-printer-hub/issues/8) [#9](https://github.com/strausmann/label-printer-hub/issues/9)
* ci(deps): bump the actions-all group across 1 directory with 14 updates (#9) ([a88a027](https://github.com/strausmann/label-printer-hub/commit/a88a027)), closes [#9](https://github.com/strausmann/label-printer-hub/issues/9)
* ci(release): trigger releases via cron + workflow_dispatch only (#32) ([9941958](https://github.com/strausmann/label-printer-hub/commit/9941958)), closes [#32](https://github.com/strausmann/label-printer-hub/issues/32) [#32](https://github.com/strausmann/label-printer-hub/issues/32) [#32](https://github.com/strausmann/label-printer-hub/issues/32)
* chore(deps-dev): bump @commitlint/cli from 19.8.1 to 21.0.0 (#3) ([2642b26](https://github.com/strausmann/label-printer-hub/commit/2642b26)), closes [#3](https://github.com/strausmann/label-printer-hub/issues/3)
* chore(deps-dev): bump @commitlint/config-conventional (#4) ([44be5f9](https://github.com/strausmann/label-printer-hub/commit/44be5f9)), closes [#4](https://github.com/strausmann/label-printer-hub/issues/4)
* chore(deps-dev): bump @semantic-release/exec from 6.0.3 to 7.1.0 (#2) ([a8097b0](https://github.com/strausmann/label-printer-hub/commit/a8097b0)), closes [#2](https://github.com/strausmann/label-printer-hub/issues/2)
* chore(deps-dev): bump @semantic-release/github from 11.0.6 to 12.0.8 (#8) ([098e766](https://github.com/strausmann/label-printer-hub/commit/098e766)), closes [#8](https://github.com/strausmann/label-printer-hub/issues/8)
* chore(deps-dev): bump conventional-changelog-conventionalcommits (#7) ([9f5370f](https://github.com/strausmann/label-printer-hub/commit/9f5370f)), closes [#7](https://github.com/strausmann/label-printer-hub/issues/7)
* chore(deps-dev): bump semantic-release from 24.2.9 to 25.0.3 (#6) ([306010f](https://github.com/strausmann/label-printer-hub/commit/306010f)), closes [#6](https://github.com/strausmann/label-printer-hub/issues/6)
* chore(release): 1.0.0 ([15abeb3](https://github.com/strausmann/label-printer-hub/commit/15abeb3))
* feat(status): add Brother 32-byte status block parser (#29) ([ced0ff8](https://github.com/strausmann/label-printer-hub/commit/ced0ff8)), closes [#29](https://github.com/strausmann/label-printer-hub/issues/29) [#11](https://github.com/strausmann/label-printer-hub/issues/11) [#19](https://github.com/strausmann/label-printer-hub/issues/19) [#29](https://github.com/strausmann/label-printer-hub/issues/29)

## Pre-1.0 development

The project is in active **pre-1.0 development**. The public API (REST endpoints, plugin protocol, configuration shape) may change between minor versions until `1.0.0` ships. Releases on the `0.x.y` track are explicitly *not* covered by SemVer's stable-API contract.

When `1.0.0` ships, that release will mark the first stable, supported version. The expected breaking-change cadence will follow normal SemVer rules from there on.

<!--
semantic-release prepends new release entries directly under the
"# Changelog" title above (newest first). The "## Pre-1.0 development"
section will sink down the file as new releases land — that's expected.
Do not edit release entries by hand; semantic-release regenerates them.
-->
