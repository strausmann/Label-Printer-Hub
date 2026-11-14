---
title: Security model
description: What Labelyard protects, what it does not, and how to report a vulnerability.
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

## Reporting a vulnerability

Please do not open a public issue. Report it privately through [GitHub's security advisories](https://github.com/strausmann/labelyard/security/advisories/new); the [security policy](https://github.com/strausmann/labelyard/blob/main/SECURITY.md) has the other ways and the response times.
