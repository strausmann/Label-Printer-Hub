# Privacy policy for this repository

This is a public, open-source project. Nothing in this repository may reveal information about the maintainer's private network, infrastructure, or accounts.

This policy is **enforced by CI** (see `.github/workflows/ci.yml` job `privacy-scan`) and **mandatory for every contributor**.

## Forbidden in this repository

The following must not appear in commits, examples, tests, docs, issues, PRs, or wiki pages:

| Category | Examples to avoid | Use instead |
|---|---|---|
| **Internal IPs** | `172.16.50.212`, `192.168.x.x`, `10.x.x.x` from real networks, Tailscale `100.64.0.0/10` | `192.0.2.10`, `198.51.100.10`, `<printer-ip>` (RFC 5737 documentation ranges) |
| **Internal hostnames** | `hhdocker03`, `hhplex01`, real Tailscale machine names | `printer-host`, `docker-host`, generic placeholders |
| **Personal domains** | `*.strausmann.cloud`, `*.strausmann.de`, `*.strausmann.net` and similar | `printerhub.example.com`, `your-domain.example.com` |
| **Personal location/contact** | Real `sysLocation`/`sysContact` values, real serial numbers, real MAC addresses | `Office`, `<your-name>`, `D5G123456` (synthetic), `04:68:74:00:00:00` (locally administered) |
| **Reverse-proxy specifics** | Real Pangolin organisation IDs, real OAuth client IDs, real API keys | Generic Traefik/Caddy/Pangolin placeholders |
| **App-specific tokens** | Real Snipe-IT, Grocy, Spoolman tokens | `<your-snipeit-token>` etc. |
| **MAC-based device names** | Anything resembling a real MAC pattern | `BRW000000000000` (synthetic) |
| **Photos with EXIF metadata** | Photos that reveal location, device, timestamp | Strip EXIF before uploading |

When in doubt, ask: *"Could a stranger doxx the maintainer with this?"* If yes, redact.

## Where private values DO live

In the maintainer's separate `homelab-pangolin-client` repository (private deployment glue). That repo is not mirrored here — the split is intentional.

## Sanitisation checklist for every commit

Before pushing, ensure no commit contains:

- [ ] Real LAN IP addresses
- [ ] Real Tailscale IPs (`100.64.0.0/10`)
- [ ] Real hostnames from any private infrastructure
- [ ] Real `*.strausmann.*` domains (or any real personal domain)
- [ ] Real serial numbers, MAC addresses, or printer-discovered identifiers
- [ ] Real API keys, tokens, OAuth credentials
- [ ] Real photos with EXIF metadata revealing location

## Enforcement

If a contributor accidentally includes any of the above:

1. The maintainer will not merge the PR
2. The contributor must amend the commit history with sanitised content
3. If already merged, the maintainer will force-push a sanitised history within 24 hours

CI rejects pushes that match known-bad patterns (`privacy-scan` job in `ci.yml`). If the CI scanner ever lets something private through, treat it as a bug and add the pattern.

## Relationship to security policy

This policy is **about maintainer privacy** — protecting the operator's network from being traceable through this repository. Vulnerability disclosure for security bugs in the code belongs in [`SECURITY.md`](../../SECURITY.md).
