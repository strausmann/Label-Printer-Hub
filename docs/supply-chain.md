<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Supply chain: SBOM, provenance and licence lists

This page says how to find out what is inside a Labelyard image, where it came from, and under which licences
its parts are distributed. It covers the published container image only. Not legal advice.

Some of the artefacts below arrive with later steps of release 1.6.0. Each section says which. A statement
without such a note describes what the repository does today.

Image references on this page:

| Registry | Reference |
|---|---|
| GitHub Container Registry | `ghcr.io/strausmann/labelyard:<version>` |
| Docker Hub | `docker.io/<user>/labelyard:<version>` |

`<version>` is the exact version tag (for example `1.6.0`), not a floating tag such as `latest`. Both registries
receive the same multi-arch image (`linux/amd64`, `linux/arm64`).

## What exists, and since when

| Artefact | What it is | Where | Status |
|---|---|---|---|
| Web licence list | Every package the web app ships, with licence and text | `/licenses/frontend.json` of the running app; `/opt/app/web/licenses/frontend.json` in the image; About page | on the branch |
| Web SBOM | CycloneDX document of the web bundle | `frontend.cdx.json` in the image (`/opt/app/web/frontend.cdx.json`) | on the branch |
| Backend licence list | Python packages and bundled fonts, with licence and text | `/licenses/backend.json` of the running app; About page | generated at build time; the About page says the list is missing in builds without it |
| BuildKit SBOM (SPDX) | Attached to each platform image by the build | registry, read without pulling | published today; see the note on its limits below |
| BuildKit provenance | How and where the image was built | registry, read without pulling | published today, with `mode=max` content by the build action's default; the attestation step (B5) makes it explicit |
| Image SBOM as a release asset | CycloneDX document of the whole image, `labelyard-<version>.cdx.json` | the GitHub release | lands with the release SBOM step (B6); the first release that carries it is 1.6.0 |
| SPDX headers in every own file | `reuse lint` clean | repository | lands with the header sweep (B9) |
| Image signature | Keyless cosign signature of the image index | registry, next to the image | from release 1.6.0 and its previews; see "Verify the signature" |

## Read the SBOM and provenance without pulling the image

The build attaches an SBOM and a provenance attestation to the image index in the registry. Docker Buildx reads
them without pulling the layers:

```bash
# Which manifests belong to the tag: two platform images and their attestations.
docker buildx imagetools inspect ghcr.io/strausmann/labelyard:<version>

# Which platforms have an SBOM: the keys of the map.
docker buildx imagetools inspect ghcr.io/strausmann/labelyard:<version> \
  --format '{{ json .SBOM }}'

# The SBOM (SPDX) of one platform; repeat with "linux/arm64".
docker buildx imagetools inspect ghcr.io/strausmann/labelyard:<version> \
  --format '{{ json (index .SBOM "linux/amd64").SPDX }}'

# The provenance (SLSA) of one platform; repeat with "linux/arm64".
docker buildx imagetools inspect ghcr.io/strausmann/labelyard:<version> \
  --format '{{ json (index .Provenance "linux/amd64").SLSA }}'
```

On a multi-platform image, `.SBOM` and `.Provenance` are maps keyed by platform. The short forms
`{{ json .SBOM.SPDX }}` and `{{ json .Provenance }}` work only on a single-platform image; on this image
`.SBOM.SPDX` prints `null`, which does **not** mean the image has no attestation. The commands were run
read-only against the 1.5.0 image of the predecessor name: `{{ json .SBOM }}` has the keys `linux/amd64` and
`linux/arm64`, and the indexed forms print the SPDX document and the SLSA provenance.

The same commands work on Docker Hub with `docker.io/<user>/labelyard:<version>` for a release version.
Pre-release previews (`<version>-rc.N`) stay off Docker Hub until the rename step (Task 4) publishes them
there; before that, check a preview on GHCR only. If the platform-indexed command prints `null` or an error for a
platform that `{{ json .SBOM }}` lists, report it; do not assume the image is clean.

Two limits you should know before relying on the BuildKit SBOM:

- It describes what a scan of the final image layers finds. It does **not** list the packages bundled into the
  web app by the Vite build. Measured on 2026-11-11 on the 1.5.0 image: the SPDX document has no `react`. The
  web bundle is therefore covered by the embedded document in the next section.
- The provenance records the build arguments, the build steps and the source of the build. On the 1.5.0 image it
  already carries the `mode=max` content (`buildkit_metadata` with layer information): the build action's
  default for a public repository. The attestation step (B5) sets `mode=max` explicitly so that it no longer
  depends on that default. It contains no secrets by design (the workflow passes none as build arguments), but
  read it before you share it.

## Verify the signature

Every image the image workflow publishes is signed with [cosign](https://docs.sigstore.dev/) without a key.
The workflow signs with its GitHub OIDC token, and the certificate names the workflow file of this repository as
the signer. What is signed is the digest of the multi-arch index, once on each registry. The index contains the
platform images and the BuildKit attestation manifests (SBOM and provenance), so one signature covers them too.
A tag is never signed, because a tag can move.

Resolve the tag to its digest first, then verify the digest:

```bash
docker buildx imagetools inspect ghcr.io/strausmann/labelyard:<version> --format '{{ .Manifest.Digest }}'

cosign verify \
  --certificate-identity-regexp '^https://github\.com/strausmann/(Label-Printer-Hu[b]|labelyard)/\.github/workflows/docker-publish\.yml@refs/(heads/main|heads/milestone/[0-9]+\.[0-9]+\.(0|x))$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/strausmann/labelyard@<digest>

cosign verify \
  --certificate-identity-regexp '^https://github\.com/strausmann/(Label-Printer-Hu[b]|labelyard)/\.github/workflows/docker-publish\.yml@refs/(heads/main|heads/milestone/[0-9]+\.[0-9]+\.(0|x))$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  docker.io/<user>/labelyard@<digest>
```

The digest is the same on both registries. `--certificate-oidc-issuer` requires a certificate issued for a GitHub
Actions token. The identity accepts `docker-publish.yml` of this repository only, and only on the refs the
workflow signs from:

| Ref | Images signed from it |
|---|---|
| `refs/heads/main` | releases, `dev`, previews built on main |
| `refs/heads/milestone/<x.y.0>`, `refs/heads/milestone/<x.y.x>` | previews of a milestone |

A release is signed from `refs/heads/main`: the release workflow runs on main and calls the image workflow, and
the certificate carries the caller's ref. Tags are not a publishing ref: images from a tag or from any other
branch are published unsigned. The identity
allows the current and the former repository name, because previews built before the rename carry the former
name in their certificate. `[b]` in the pattern matches the letter b.

For a release after the rename, you can verify against the exact identity instead of the pattern:

```bash
cosign verify \
  --certificate-identity https://github.com/strausmann/labelyard/.github/workflows/docker-publish.yml@refs/heads/main \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/strausmann/labelyard@<digest>
```

With the pattern, `--certificate-github-workflow-ref refs/heads/main` also pins the ref, but it reads a deprecated
certificate extension; the exact identity is the sturdier pin. `cosign verify` exits with an error when no valid
signature matches; a successful run prints the verified signature payload.

Where the signature is stored differs per registry. Docker Hub keeps it as an OCI referrer of the index, without a
tag. GHCR has no referrers support, so cosign stores it under a tag `sha256-<index digest>`. That tag is not an
image; the registry cleanup treats it as part of its image and removes it only together with the image.

## The web bundle: `frontend.cdx.json`

The image contains a CycloneDX 1.6 document of everything the web app ships, generated by the build from the
same package set as `/licenses/frontend.json`. Get it from a running container or a stopped one:

```bash
docker create --name labelyard-sbom ghcr.io/strausmann/labelyard:<version>
docker cp labelyard-sbom:/opt/app/web/frontend.cdx.json .
docker rm labelyard-sbom
```

`metadata.component.name` is the name from `frontend/package.json`, and its version is the image version the
build was given. The document is deterministic: no serial number and no timestamp, components sorted by
package URL.

### Why a scanner must be told to read it

A scanner that works on the image filesystem does not find an SBOM file that is not part of an installed
package. Syft ships a cataloger for embedded CycloneDX and SPDX documents, but it is not part of the default
selection for images. To make it read the document, select it explicitly:

```bash
syft scan ghcr.io/strausmann/labelyard:<version> --select-catalogers +sbom-cataloger -o cyclonedx-json
```

Without `+sbom-cataloger` the result is expected to lack the web packages, in line with the BuildKit SBOM
above. Status: Syft 1.55.0 accepts the flag (run against the 1.5.0 image, which has no embedded document yet);
that it picks up `frontend.cdx.json` is verified in B8 against the milestone preview.

### What is in it, and what is over-approximated

- Every package of the web bundle, with its licence. The build fails when one is outside
  `licence-policy.yml` (see "The policy" below).
- Two kinds of content that a bundler hides from a normal scan are added on purpose: the barcode reader
  `zxing-cpp` (compiled into a WebAssembly module, with its own licence text kept under `frontend/licenses/`)
  and the self-hosted fonts (`@fontsource/*`: CSS and font files, no JavaScript module). A test asserts that
  every dependency declared in `frontend/package.json` appears in the list.
- The API reference page (`/docs`) is served by the standalone Scalar bundle, which is copied into the image
  as one file. Its dependencies are not individually visible in that file. The document therefore lists the
  **whole production dependency subtree** of `@scalar/api-reference`, which is an over-approximation: it may
  name a package that is not in the bundle, never the other way round.
- The build tools (the licence plugin and the packages it depends on) are not shipped and are not listed. Two
  of them carry a licence that is not on the allow-list (SPDX licence-list data, build time only); the policy
  file excepts them with that reason, and a test asserts they are not in the built output.

### Build note

`pnpm install` in the `web-builder` stage needs the network. The build step after it was run once with the
network switched off and succeeded: the licence texts are read from `node_modules` and nothing is downloaded.
Where a package ships no text, one kept under `frontend/licenses/` is used (the Scalar packages and
`zxing-cpp`). The build fails, and no image is produced, when a package is outside `licence-policy.yml`.

## The release asset

From release 1.6.0 on, every GitHub release has one asset, `labelyard-<version>.cdx.json`: a CycloneDX
document of the image of that release, generated from the published image. It is built by the image workflow
and uploaded by the release workflow, so an asset exists only for a published version. A preview build
(`<version>-rc.N`) has no release and therefore no asset; use the registry commands above for it (GHCR only, see above).

Until the release SBOM step has landed, no release has this asset.

## The lists at `/about`

The About page of the running app shows the web list and, once the backend list has landed, the Python list: package,
version, licence and the licence text on demand. The same data is available as `/licenses/frontend.json` and
`/licenses/backend.json` (the app serves the files of its web directory, `/opt/app/web/licenses/` in the image;
that the running app answers these URLs is confirmed in B8). A list that is missing in an image (for example an API-only build) is reported as
missing; the page keeps the project's own licence and source link either way.

Both lists exclude the project itself. The backend list reads the name from `backend/pyproject.toml`. The backend list is generated at build time with `--require-texts`, so the build stops when a package has no licence text; see [A licence text is missing](../CONTRIBUTING.md#a-licence-text-is-missing).

## Operating system packages

The Python and web lists do not cover the Debian packages of the base image and the few the runtime stage
installs. For those the licence information is the one the distribution ships inside the image:

```bash
docker run --rm --entrypoint sh ghcr.io/strausmann/labelyard:<version> \
  -c 'ls /usr/share/doc/*/copyright'
```

Some of them are copyleft (for example GPL-2.0-or-later scripts in `ca-certificates`). Their source is
available from Debian (`sources.debian.org`, or `apt source <package>`). The packages the Dockerfile installs
by name are listed in `THIRD_PARTY_NOTICES.md`. The BuildKit SBOM lists the operating system packages found in
the image layers.

## The policy

`licence-policy.yml` at the repository root is the single policy. It is read by:

- the dependency review on pull requests (`allow-licenses`, `allow-dependencies-licenses`),
- the backend licence check (`licence-backend.yml`, `backend/scripts/licence_report.py`),
- the web build (a package outside the policy stops the build).

An unacceptable licence means the check fails. Nothing is waived silently. A package that is judged wrongly (for
example because its metadata is wrong or missing) gets an entry in `x-licence-exceptions` with its package URL,
the licence it actually carries and the reason. Such an entry is a decision that appears in review, not a
default. See `CONTRIBUTING.md` for the steps.

## SPDX headers

Every file the project owns carries an SPDX header (`SPDX-FileCopyrightText` and `SPDX-License-Identifier:
AGPL-3.0-or-later`), checked in CI with `reuse lint`. Files that cannot carry a comment (data files, binaries,
generated files) are covered by `REUSE.toml`. This lands with the header sweep (B9) at the end of milestone 1.6.0;
until then not every file has a header.

## What is not provided

- **VEX.** There is no VEX statement (no machine-readable "this vulnerability does not affect this image").
  A vulnerability scanner will report findings in the base image that do not affect Labelyard, and this release
  cannot say which. A follow-up issue is planned.
- **Legal advice.** The lists and documents are generated from package metadata. They are as good as that
  metadata; the exceptions in the policy mark the known gaps.
