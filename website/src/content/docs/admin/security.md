---
title: Security model
description: What Labelyard protects, what it does not, the access log for CrowdSec, how to verify the image signature, and how to report a vulnerability.
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

From 1.6.0 on, every release, preview and `dev` image is signed with [cosign](https://docs.sigstore.dev/) without a key: the signature is made with the GitHub Actions token of the project's image workflow and covers the multi-arch index, so the platform images and their SBOM and provenance attestations are covered too. A tag can move, so resolve it to its digest first and verify the digest:

```bash
docker buildx imagetools inspect ghcr.io/strausmann/labelyard:<version> --format '{{ .Manifest.Digest }}'

cosign verify \
  --certificate-identity-regexp '^https://github\.com/strausmann/(Label-Printer-Hub|labelyard)/\.github/workflows/docker-publish\.yml@refs/(heads/main|heads/milestone/[0-9]+\.[0-9]+\.(0|x))$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/strausmann/labelyard@<digest>
```

The identity accepts only the image workflow of this repository (under its current and its former name), run from `main` or a milestone branch. `[b]` in the pattern matches the letter b. The digest is the same on Docker Hub; replace the last line with `docker.io/bstrausmann/labelyard@<digest>` to check the copy there. `cosign verify` exits with an error when no valid signature matches. The [supply-chain notes](https://github.com/strausmann/labelyard/blob/main/docs/supply-chain.md) cover the exact release identity, the SBOM and the provenance.

## Access log

The hub writes one line per HTTP request to its container output (stdout), in the format nginx calls `combined`:

```text
198.51.100.7 - - [15/Nov/2026:17:40:00 +0000] "POST /api/v1/webhook/grocy/label?token=lh_pat_AbCdEfGhI*** HTTP/1.1" 401 52 "-" "Grocy/4.0"
198.51.100.7 - lh_pat_AbCdEfGhI [15/Nov/2026:17:40:01 +0000] "POST /api/v1/print HTTP/1.1" 403 85 "-" "curl/8.5.0"
```

Log tools that read nginx logs read it as is, CrowdSec among them. The access log is kept apart from the application log: no level, no logger name, and it never reaches the System page.

- **Client address.** The first field is the address the hub's rate limits use. Behind a reverse proxy that is the real client only when the proxy is trusted with `FORWARDED_ALLOW_IPS` (see [reverse proxy](/install/reverse-proxy/)); otherwise every line shows the proxy.
- **Key prefix, never a key.** A key in the URL `token` (Grocy's webhook) shows only its public prefix, the first 16 characters, followed by `***`. A key in the `X-Label-Hub-Key` header shows the same prefix in the user field. That prefix is the one in the key list under **Settings > Access and keys**, so you can match a refused call to a key. The prefix is taken from the value as sent: an unknown or guessed key shows its prefix too. A value that is not in key format shows `***` (in the URL) or `-` (in the user field). Every other parameter whose name looks like a key, token, secret or password shows `***`. No other header is written except the referer and the user agent.
- **Honest status codes.** Refusals keep the status the hub answered: `401` for a missing or wrong key, `403` for a key without the right scope, `429` past a rate limit.
- **No forged lines.** Quotes, backslashes and control characters in the request, the referer and the user agent are written as `\xHH`, as nginx does, so a client cannot start a second line.
- **Health checks are left out**, so probes do not flood the log.

Two settings control it (see [configuration](/reference/configuration/)):

| Variable | Default | Effect |
|---|---|---|
| `LABELYARD_ACCESS_LOG` | `true` | `false` turns the access log off completely |
| `LABELYARD_ACCESS_LOG_PROBES` | `false` | `true` also logs `/healthz` and `/readiness` |

### Read it with CrowdSec

CrowdSec can read the hub's container log with its stock nginx parser. With label-based Docker acquisition you only label the Labelyard service.

1. Install the [nginx collection](https://github.com/crowdsecurity/hub/blob/master/collections/crowdsecurity/nginx.yaml) on the CrowdSec agent. It brings the parser `crowdsecurity/nginx-logs` and the HTTP scenarios:

   ```bash
   cscli collections install crowdsecurity/nginx
   ```

2. Let CrowdSec pick containers by label, in its `acquis.yaml` (or a file under `acquis.d/`). The agent needs the Docker socket:

   ```yaml
   source: docker
   use_container_labels: true
   ```

3. Label the Labelyard service in your compose file:

   ```yaml
   services:
     labelyard:
       image: ghcr.io/strausmann/labelyard:latest
       environment:
         FORWARDED_ALLOW_IPS: ${PROXY_IP}
       labels:
         - "crowdsec.enable=true"
         - "crowdsec.labels.type=nginx"
   ```

4. Never ban your own networks. Callers inside the Docker network (Grocy calling the webhook directly) or over your VPN must not be blocked by a mistyped key. Add a whitelist to the agent, for example `/etc/crowdsec/parsers/s02-enrich/labelyard-whitelist.yaml`, with your own ranges in place of the example ones:

   ```yaml
   name: local/labelyard-whitelist
   description: "Never ban internal callers of Labelyard"
   whitelist:
     reason: "internal Docker and VPN networks"
     cidr:
       - "192.0.2.0/24"     # your Docker network
       - "198.51.100.0/24"  # your VPN range
   ```

   Then reload CrowdSec. `cscli explain --log '<a line>' --type nginx` shows how a line is parsed and which scenarios it reaches.

### Scenarios that react

What the stock scenarios of the collection count (checked against `crowdsecurity/nginx` 0.2 and `crowdsecurity/base-http-scenarios` 1.2 on CrowdSec 1.7.3):

| Scenario | Counts | Triggers |
|---|---|---|
| [`LePresidente/http-generic-401-bf`](https://github.com/crowdsecurity/hub/blob/master/scenarios/crowdsecurity/http-generic-bf.yaml) | `POST` answered `401` (wrong or missing key at the webhook, the sign-in or the API) | more than 5 per address within about 10 seconds |
| [`LePresidente/http-generic-403-bf`](https://github.com/crowdsecurity/hub/blob/master/scenarios/crowdsecurity/http-generic-bf.yaml) | `POST` answered `403` (key without the right scope) | more than 5 per address within about 10 seconds |
| [`crowdsecurity/http-probing`](https://github.com/crowdsecurity/hub/blob/master/scenarios/crowdsecurity/http-probing.yaml) | `400`, `403` or `404` for pages that are not static files | more than 10 per address within about 10 seconds |
| [`crowdsecurity/http-sensitive-files`](https://github.com/crowdsecurity/hub/blob/master/scenarios/crowdsecurity/http-sensitive-files.yaml) | requests for files such as `.env` or backups, any status | more than 4 within a few seconds |
| [`crowdsecurity/http-crawl-non_statics`](https://github.com/crowdsecurity/hub/blob/master/scenarios/crowdsecurity/http-crawl-non_statics.yaml) | many `GET`/`HEAD` requests for pages that are not static files | a burst of more than 40 |
| [`crowdsecurity/http-bad-user-agent`](https://github.com/crowdsecurity/hub/blob/master/scenarios/crowdsecurity/http-bad-user-agent.yaml) | user agents of known scanners | the second such request within a minute |

The two brute-force scenarios are defined in the [`http-generic-bf` file](https://github.com/crowdsecurity/hub/blob/master/scenarios/crowdsecurity/http-generic-bf.yaml) of the [`base-http-scenarios` collection](https://github.com/crowdsecurity/hub/blob/master/collections/crowdsecurity/base-http-scenarios.yaml); they count `POST` only. A refused `GET` counts in `http-probing` when it is answered `403`, and not at all when it is answered `401`. No stock scenario counts `429`: the hub's own rate limits stay the answer to too many calls. The collection's `crowdsecurity/nginx-req-limit-exceeded` reads nginx's error log, not this access log, and does not apply.

## Reporting a vulnerability

Please do not open a public issue. Report it privately through [GitHub's security advisories](https://github.com/strausmann/labelyard/security/advisories/new); the [security policy](https://github.com/strausmann/labelyard/blob/main/SECURITY.md) has the other ways and the response times.
