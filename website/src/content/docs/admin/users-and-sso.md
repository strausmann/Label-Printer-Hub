---
title: Users and SSO
description: How people sign in to Labelyard, with an API key or through an SSO reverse proxy.
sidebar:
  label: Users and SSO
---

Labelyard has no user accounts and no passwords of its own. A person signs in in one of two ways.

## With an API key

The sign-in page takes an API key with `print` or `admin` scope; a `read` key cannot sign in. The browser then holds a session cookie. Give each person their own key, so revoking it ends their sessions and nobody else's.

## Through an SSO proxy

When the hub runs behind a proxy that does single sign-on (Pangolin, or Traefik or Caddy with a forward-auth service such as Authelia), the proxy can tell the hub who is signed in:

- The proxy sends the user in the `Remote-User` header (`LABELYARD_SSO_USER_HEADER`).
- It also sends a shared secret in `X-Pangolin-Token` (`LABELYARD_SSO_TRUST_HEADER`) whose value equals `LABELYARD_SSO_TRUST_TOKEN`.

The user header counts **only** together with the matching trust token. Without the token set, sign-in through the proxy is off and a neighbouring container cannot pose as a user by sending the header. Generate the token with `openssl rand -hex 32` and configure the same value in the proxy (see the Pangolin example under [reverse proxy](/install/reverse-proxy/)).

## Legacy paths, off by default

Two older Pangolin paths exist for existing setups and are off unless you opt in:

| Variable | What it allows |
|---|---|
| `LABELYARD_TRUST_LEGACY_PANGOLIN_USER` | the `X-Pangolin-User` header without a trust token |
| `LABELYARD_TRUST_PANGOLIN_BASIC_BYPASS` | Pangolin's `Authorization: Basic` bypass credential |

Neither creates a browser session. State-changing requests over the Basic bypass need an `Origin` equal to `LABELYARD_PUBLIC_URL`, and `LABELYARD_PANGOLIN_BYPASS_SCOPE_DOWNGRADE=true` limits it to `read`. Prefer API keys and leave both off.
