# 0027 — A print-scope key in the URL authenticates the Grocy label webhook

- **Status:** Proposed
- **Date:** 2026-11-14
- **Deciders:** maintainer

## Context

Grocy can print labels for products, stock entries, chores, batteries and recipes by calling a "label printer webhook" (#281). Grocy's `helpers/WebhookRunner.php` POSTs to one fixed URL from its `config.php` (`LABEL_PRINTER_WEBHOOK`) with a 2.0 s timeout. It sends **no headers of its own**: the only place a credential can travel is the URL.

Everywhere else the hub takes an API key in the `X-Label-Hub-Key` header and never in a URL. A URL is less private than a header:

- Grocy writes every webhook URL **and body** to its stderr, so the key ends up in Grocy's container log.
- When the hub answers with an error, or does not answer within 2 s, Grocy shows the URL — with the key — to the Grocy user who pressed "print".
- uvicorn writes the full request line, query string included, to its access log, and the hub keeps recent warnings in its own log buffer for the System page.
- A reverse proxy in front of the hub usually logs the full URL too.

A key in a URL is therefore a key that several people and several logs can see. The question is how to accept it while keeping the damage of a leak small.

## Decision

We accept an **API key with the effective scope `print`** as the value of a literal `token=` query parameter, on the Grocy label webhook route only, and refuse any other scope.

- The token is the value of a literal `token=` parameter of the raw query string; only the value is percent-decoded, so a percent-encoded parameter name is not a token. The `X-Label-Hub-Key` header is accepted on the same route and wins over the query.
- A `read` key answers 403 `insufficient_scope`; an **`admin` key answers 403 `token_scope_too_wide`**. An admin key must never sit in Grocy's configuration and log. It is refused before it uses a slot of its rate limit and before it is marked as used, so the key list never shows a refused admin key as used by the webhook.
- Every failure of the token itself — missing, malformed, longer than 128 characters, unknown, disabled, expired, wrong — answers the same **401 `invalid_token`** with one fixed message, because Grocy forwards the answer to its user. A token over 128 characters is refused before the key is looked up.
- The key's own rate limit applies (429 with `Retry-After`).
- A logging filter on `uvicorn.access` and `uvicorn.error` replaces the value of every `token=` parameter with `***` in the record's message and arguments before any handler sees it; the app installs it at start. The filter covers a superset of what the reader accepts: besides the literal `token=` it hides every look-alike the reader refuses (any case, `;` as separator, a percent-encoded name such as `%74oken=`) and any value in the shape of a hub key (`lh_pat_…`) anywhere in the line. A token the hub accepts is a token it hides, and so is every look-alike it refuses.

The dependency is `require_print_token` (`backend/app/api/dependencies/token_auth.py`), the filter `install_query_token_redaction` (`backend/app/observability/redact_query.py`).

## Options considered

### Option A — print-scope API key as URL token, admin refused (picked)
- Pros: uses the existing keys, their scopes, printer restrictions, expiry, rate limit and revocation; a leaked token can only print, and only on the printers the key allows; the operator revokes it in Settings > Access keys like any other key.
- Cons: the token lives in Grocy's config and log, and is shown to Grocy users on an error.

### Option B — a separate shared webhook secret (like `LABELYARD_WEBHOOK_API_KEY`)
- Pros: independent of the key store.
- Cons: one global secret with no scope, no printer restriction, no expiry and no per-key audit; rotating it breaks every caller at once.

### Option C — accept any key scope in the URL
- Pros: simplest for the operator.
- Cons: an admin key pasted into Grocy would leak full control of the hub to everybody who can read Grocy's log or sees its error message.

### Option D — signed request (HMAC of the body)
- Pros: nothing reusable in the URL.
- Cons: Grocy cannot sign requests; it would need a proxy in between, which defeats the point of a built-in integration.

## Consequences

- The token lives in Grocy's `config.php` and in Grocy's log, and Grocy shows it to its user when the hub refuses a label or does not answer in time. The hub keeps that exposure low by accepting **print-scope tokens only**, by **answering within 1.5 s** (validate, record the job, answer 202; the printer work runs afterwards), and by answering **content errors with 202 and a failed job** instead of an error status, so Grocy has no reason to show the URL for a malformed label.
- The settings page that shows the ready-to-copy Grocy configuration warns that the key should have the print scope, be restricted to the label printer, and that Grocy logs and shows the address with the key.
- **A reverse proxy's access log is outside the hub.** The filter covers the hub's own uvicorn loggers only; an operator who logs full URLs at the proxy must redact there or accept the token in that log.
- The existing debug line for an unknown key prefix (`backend/app/auth/dependencies.py`) logs the first 16 characters of a presented key. For `lh_` keys that prefix is the stored, displayed key prefix and not secret, so it stays.
- The route auth guardrail (`backend/tests/unit/api/test_route_auth_coverage_guardrail.py`) recognises `require_print_token` as an auth dependency.
- This ADR becomes `Accepted` in the PR that ships the webhook route (#281, part 2).

## References

- Issue: #281
- Spec: `docs/superpowers/specs/2026-11-14-milestone-1-7-0-design.md`, section 6 (R-281-1, R-281-2, R-281-11)
- Related ADRs: [0019](0019-proxy-headers-need-trust-token.md) (header trust), [0017](0017-settings-in-database-env-locks-encrypted-secrets.md)
