<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Security Policy

We work to keep Labelyard secure, but issues can still slip through. If you believe you have
found a security issue, please tell us. We want to work with you to resolve it promptly.

## Reporting a Vulnerability

**Please do not open a public issue for security problems.** That exposes users before a fix
exists.

Use one of these private channels:

- **GitHub private vulnerability reporting:** the "Report a vulnerability" button on the
  repository's Security tab (public repositories only).
- **Email:** **security@strausmann.ch**. This inbox exists for security reports only.

If the report is sensitive, please encrypt it (see below). We support coordinated disclosure and
will credit you if you wish.

## Encryption (PGP)

Encrypt sensitive reports to our security key:

- **Fingerprint:** `3EE0 4713 5125 2BF2 C6BE FB1B BB40 F221 7A21 F210`
- **Address:** `security@strausmann.ch`
- **Get the key** from this repository at [`.well-known/security.asc`](.well-known/security.asc),
  or from one of these public key servers:
  - [keys.openpgp.org](https://keys.openpgp.org/search?q=security%40strausmann.ch)
  - [keys.mailvelope.com](https://keys.mailvelope.com/pks/lookup?op=get&search=security%40strausmann.ch)
  - [pgpkeys.eu](https://pgpkeys.eu/pks/lookup?search=0x3EE0471351252BF2C6BEFB1BBB40F2217A21F210&fingerprint=on&op=index)
  - [keyserver.ubuntu.com](https://keyserver.ubuntu.com/pks/lookup?search=0x3EE0471351252BF2C6BEFB1BBB40F2217A21F210&fingerprint=on&op=index)

Always compare the fingerprint before you use a key. If you have your own key, include your public
key or its fingerprint so we can reply encrypted.

## What to include

To help us reproduce and fix quickly:

- A clear description of the flaw and its impact.
- Step-by-step reproduction.
- The affected version(s) or commit.
- The environment where it occurs.
- Any suggested fix or workaround.

## Disclosure policy

- Tell us as soon as possible after you discover a potential issue. We will make every effort to
  resolve it quickly.
- Give us a reasonable amount of time to fix the issue before you disclose it to the public or a
  third party. We may disclose an issue before it is fixed when that protects users.
- Make a good-faith effort to avoid privacy violations, destruction of data, and interruption or
  degradation of any service. Only interact with accounts and data you own, or with the explicit
  permission of the owner.

## Our commitment

Once you report, we will:

- Confirm receipt within a couple of business days.
- Investigate and verify the issue.
- Develop and release a fix as quickly as is practical.
- Keep you informed throughout and coordinate the disclosure timing with you.
- Publish a GitHub security advisory for confirmed issues, request a CVE where appropriate, and
  mark the fix in the release notes.

## Scope

**In scope:** security issues in the current release and the default branch of Labelyard
(https://github.com/strausmann/labelyard).

**Out of scope:**

- Issues already reported in the issue tracker.
- Issues in third-party dependencies that are already reported to their maintainers. Report new
  ones to the maintainers directly.
- Attackers on the same network segment as the printers: Brother printers expose TCP/9100 and SNMP
  `public` by design, and the hub cannot change that.
- A compromised reverse proxy, container host or printer firmware.
- The infrastructure this project may be deployed on.
- Attacks that require physical access to a user's device.
- Vulnerabilities in outdated versions.
- Missing best practices that do not lead to a vulnerability. You may still report them as a
  normal issue.

While researching, please do not:

- run denial-of-service attacks,
- send spam,
- use social engineering (including phishing) against maintainers, contributors or users.

## What the hub protects

- Authentication and authorization of the web UI and the API (API keys with scopes and printer
  restrictions, sessions with CSRF protection, trusted SSO headers only with a shared token).
- The webhook endpoints (Spoolman, Grocy) with their own key and rate limit.
- Credentials and tokens never appear in logs, error messages or pages; stored integration keys
  are encrypted with `LABELYARD_SECRET_KEY`.
- The container runs as a non-root user (UID 1000); dependencies are kept current by Dependabot.

## Trademarks

See [README.md](README.md#trademarks-and-disclaimer) for trademark notices and disclaimers.

Thank you for helping keep Labelyard and its users safe.
