# 0019 — Proxy identity headers are trusted only with the trust token

- **Status:** Accepted
- **Date:** 2026-11-04
- **Deciders:** maintainer
- **Supersedes:** ADR-0014
- **Decision label:** D10

## Context

ADR 0014 made Pangolin SSO headers and the Basic-auth bypass trusted for all scopes. That relied on the network path: whoever could reach the backend could also set `X-Pangolin-User`. Once the backend serves the browser directly (ADR 0015) it is the first and only hop, so a client able to reach it, or a misconfigured proxy that forwards client-supplied headers, could impersonate any user by sending a header.

## Decision

Identity headers from a reverse proxy are trusted only when the request also carries the SSO trust token, compared in constant time (`hmac.compare_digest`). Without a matching token the headers are ignored.

- The legacy `X-Pangolin-User` header and the Pangolin Basic-auth bypass are no longer trusted by default. Each is opt-in: `PRINTER_HUB_TRUST_LEGACY_PANGOLIN_USER` and `PRINTER_HUB_TRUST_PANGOLIN_BASIC_BYPASS`.
- The Basic bypass is off by default. If an operator enables it, it grants the scope each endpoint requires, including admin. The scope downgrade is a separate opt-in (`PRINTER_HUB_PANGOLIN_BYPASS_SCOPE_DOWNGRADE`, default false): when set, the bypass is limited to `read`. Without it a leaked bypass secret is as powerful as admin, so enable the bypass only knowingly and consider the downgrade.
- SSO sessions are bound to an HMAC fingerprint of the trust token; rotating the token ends all SSO sessions.
- Cookie-less, header-authenticated requests that change state must pass an Origin check, as must the opt-in Basic bypass, so a cross-site request cannot ride on ambient proxy authentication.

## Options considered

### Option A — trust token required, legacy paths opt-in (picked)
- Pros: spoofed headers are inert; rotation revokes sessions; legacy setups keep a documented migration path.
- Cons: operators must configure the token in the proxy.

### Option B — keep ADR 0014 (trust network position)
- Pros: no configuration.
- Cons: safe only if the backend is never reachable except through the proxy; not true for a single-process deployment.

### Option C — drop proxy authentication entirely
- Pros: simplest.
- Cons: removes single sign-on for existing deployments.

## Consequences

- Existing Pangolin deployments must set the trust token on the proxy or enable the legacy opt-ins knowingly.
- Automation using the Basic bypass must send an `Origin` header on state-changing requests.
- The shared per-IP rate-limit bucket behind a proxy is a known minor limitation, to be documented.

## References

- Supersedes ADR-0014; related ADR-0015, ADR-0017
