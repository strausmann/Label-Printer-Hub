---
title: Security model
description: What Labelyard protects, what it does not, how to verify the image signature, and how to report a vulnerability.
---

## What the hub protects

- **Every API call and every page is authenticated** with an API key or a trusted SSO proxy (see [users and SSO](/admin/users-and-sso/)). Scopes (`read`, `print`, `admin`) and per-key printer lists limit what a key can do.
- **Keys are stored as bcrypt hashes.** The plaintext is shown once, when the key is created.
- **Stored secrets are encrypted** with `LABELYARD_SECRET_KEY` (32 bytes), for example the API keys of integrations.
- **Secrets stay out of logs, error messages and pages.** The web UI shows a saved secret as stored, never its value.
- **Browser sessions are guarded against CSRF.** With an `https` public address the session cookies are `Secure` and `__Host-` prefixed; state-changing requests must come from the configured origin.
- **Proxy headers count only with the trust token,** and forwarded client addresses only from the one proxy in `FORWARDED_ALLOW_IPS`.
- **Sign-in attempts are rate limited** per client address, and every API key has its own rate limit.
- **Webhooks need their own key** (`X-API-Key`, at least 32 characters).
- **The container runs as a non-root user** (UID 1000).

## What it does not protect against

- Attackers on the same network as the printers. Label printers accept print data on TCP port 9100 and answer SNMP with the community `public` by design; put them on a network segment you trust.
- A compromised reverse proxy or container host.
- Malicious printer firmware.

## Verify the image signature

From 1.6.0 on, every published image is signed with [cosign](https://docs.sigstore.dev/) without a key: the signature is made with the GitHub Actions token of the project's image workflow and covers the multi-arch index, so the platform images and their SBOM and provenance attestations are covered too. A tag can move, so resolve it to its digest first and verify the digest:

```bash
docker buildx imagetools inspect ghcr.io/strausmann/labelyard:<version> --format '{{ .Manifest.Digest }}'

cosign verify \
  --certificate-identity-regexp '^https://github\.com/strausmann/(Label-Printer-Hu[b]|labelyard)/\.github/workflows/docker-publish\.yml@refs/(heads/main|heads/milestone/[0-9]+\.[0-9]+\.(0|x))$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/strausmann/labelyard@<digest>
```

The identity accepts only the image workflow of this repository (under its current and its former name), run from `main` or a milestone branch. `[b]` in the pattern matches the letter b. The digest is the same on Docker Hub; replace the last line with `docker.io/strausmann/labelyard@<digest>` to check the copy there. `cosign verify` exits with an error when no valid signature matches. The [supply-chain notes](https://github.com/strausmann/labelyard/blob/main/docs/supply-chain.md) cover the exact release identity, the SBOM and the provenance.

## Reporting a vulnerability

Please do not open a public issue. Report it privately through [GitHub's security advisories](https://github.com/strausmann/labelyard/security/advisories/new); the [security policy](https://github.com/strausmann/labelyard/blob/main/SECURITY.md) has the other ways and the response times.
