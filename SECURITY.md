# Security Policy

## Supported versions

This project is in early development. Only the latest released version receives security updates.

| Version | Supported |
|---|---|
| `latest` (semver tracked) | ✅ |
| anything else | ❌ |

## Reporting a vulnerability

**Please do not open public GitHub Issues for security vulnerabilities.**

Instead, report them privately via GitHub's [Security Advisory feature](https://github.com/strausmann/label-printer-hub/security/advisories/new) or by email to **strausmannservices@googlemail.com**.

Include:
- Description of the vulnerability
- Steps to reproduce
- Affected version(s)
- Potential impact
- (Optional) Suggested fix

You will receive an acknowledgement within 7 days. We aim to release a fix within 30 days for high-severity issues.

## Threat model

Things this project explicitly does **not** protect against:
- Network attackers on the same LAN as the printers (Brother printers expose TCP/9100 + SNMP `public` by design)
- Compromised reverse proxy or container host
- Malicious printer firmware

Things this project **does** care about:
- Authentication/authorization on the hub's web UI and API
- API-Key authenticity for webhook endpoints (Spoolman/Grocy push-mode)
- No exposure of credentials or tokens in logs, error messages, or HTML output
- Container runs as non-root user (UID 1000)
- Dependencies are kept current (Dependabot)

## Trademarks

See [README.md](README.md#trademarks-and-disclaimer) for trademark notices and disclaimers.
