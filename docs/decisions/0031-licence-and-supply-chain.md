<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# 0031 — The hub is AGPL-3.0-or-later and every image says what it contains and who built it

- **Status:** Accepted
- **Accepted:** 2026-11-21 — shipped in 1.6.0 (#154, #311); written down after the fact by the ADR audit of 2026-11-21
- **Date:** 2026-11-21
- **Deciders:** maintainer
- **Decision labels:** D20, D23
- **Related:** [0007](0007-docker-image-tag-scheme.md) (the image and its tags), [0026](0026-rename-to-labelyard.md) (image name)

## Context

Labelyard is run by people who did not build it, often as a container image pulled from a registry and placed next to other services on a home server. Two questions follow from that, and until 1.6.0 neither had a recorded answer:

- **Under which terms may people use, change and run it, and what do they get back?** The hub is a network service; under a permissive licence a modified hub can be offered to others without its source. The project wants changes to a running hub to stay open.
- **What is inside an image, and is it the one the project built?** An image bundles a Python environment, a web bundle and an operating-system layer, each with their own licences. People need to read those licences without unpacking the image, and to check that an image came from this repository's workflow and not from somewhere else.

The register carried the answers as D20 (licence and source link) and D23 (licence lists), but no ADR held the reasoning.

## Decision

**The hub is licensed under AGPL-3.0-or-later, links to the source of the running build, fails its build on a dependency licence outside the policy, ships its licence lists, and publishes every image with an SBOM, a provenance attestation and a keyless cosign signature.**

- **Licence (D20).** Project code is AGPL-3.0-or-later (`LICENSE`; `backend/pyproject.toml:9`; `package.json`; `PROJECT_LICENSE` in `backend/app/build_info.py:17`). Every own file carries an SPDX header, and `reuse lint` runs on every pull request (`.github/workflows/ci.yml:453-461`). Contributions come in under the CLA (`CLA.md`).
- **Source of the running build (D20, AGPL section 13).** The hub derives a public source link from its build values (`source_url`, `backend/app/build_info.py:53`) and the web UI shows it on the About page (`frontend/src/features/about/SourceLink.tsx:12-20`).
- **One licence policy, enforced at build time.** `licence-policy.yml` lists the allowed licences. The web build fails on a package outside it (`backend/Dockerfile:41-43`, `frontend/vite.config.ts:55-58`); the image build checks the Python packages it has just installed against the same file and fails on a violation or a missing licence text (`backend/Dockerfile:110-121`). Every pull request also runs GitHub's dependency review against the same file (`.github/workflows/licence-gate.yml:28-32`).
- **Licence lists in the image (D23).** The same build steps write the lists the image serves: `/licenses/frontend.json` and the web bundle's CycloneDX document, and `/licenses/backend.json` for the Python environment and bundled fonts (`backend/Dockerfile:41-43,115-116`; served file-first by `backend/app/web/spa.py:36-41`). Operating-system packages are covered by the image SBOM and their own copyright files, not by these lists.
- **SBOM and provenance.** The image build attaches a BuildKit SBOM (SPDX) and a provenance attestation with `mode=max` to each platform image (`.github/workflows/docker-publish.yml:298-299`). The release additionally gets a CycloneDX SBOM of the whole image as a release asset (`docker-publish.yml:625-692`).
- **Keyless signature.** Every published image index is signed with cosign using the workflow's OIDC identity, without a long-lived key (`docker-publish.yml:332,570-621`). `docs/supply-chain.md` says how to verify it and how to read the SBOM and provenance without pulling the image.

## Options considered

### Option A — AGPL-3.0-or-later with build-time licence lists, SBOM, provenance and keyless signature (chosen)
- Pros: changes to a hub offered over a network stay open; licences can be read in the running app; a licence problem stops the build instead of reaching users; anyone can check where an image came from with public tools and no key exchange.
- Cons: AGPL keeps some companies from contributing or embedding the hub; every dependency change has to pass the policy; the build carries the licence tooling and the signing steps.

### Option B — a permissive licence (MIT or Apache-2.0), no supply-chain metadata
- Pros: no licence obligations for users who change the hub; simpler build.
- Cons: a modified hub can be run for others without its source; people cannot tell what an image contains or who built it.

### Option C — keep the licence, sign with a long-lived key
- Pros: verification does not depend on Sigstore's transparency log.
- Cons: a private key to store, rotate and protect in CI; verifiers have to fetch and trust a public key; a leaked key signs anything.

## Consequences

- The relicence to AGPL-3.0-or-later was a breaking change of 1.6.0 (#154).
- A new dependency whose licence is not in `licence-policy.yml` fails the build; adding a licence to the policy is a decision of its own, made in the pull request that needs it.
- A build without the licence step (for example a local stub build) has no backend list; the About page says so instead of showing an empty list.
- Images published before 1.6.0 carry no signature and no release SBOM (`docs/supply-chain.md`).
- ADR 0007 still decides the tags; this ADR decides what travels with every tagged image.
- Register labels D20 and D23 now point here.

## References

- Issues: #154 (relicence, licence tracking, SBOM), #311 (cosign signing)
- Docs: [`docs/supply-chain.md`](../supply-chain.md), [`CLA.md`](../../CLA.md), [`licence-policy.yml`](../../licence-policy.yml)
- Workflows: [`docker-publish.yml`](../../.github/workflows/docker-publish.yml), [`licence-gate.yml`](../../.github/workflows/licence-gate.yml), [`ci.yml`](../../.github/workflows/ci.yml) (`reuse lint`)
- Related ADRs: [0007](0007-docker-image-tag-scheme.md), [0026](0026-rename-to-labelyard.md)
