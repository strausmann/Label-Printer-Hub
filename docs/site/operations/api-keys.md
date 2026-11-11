# API Key Management

Label Printer Hub Phase 7c introduces app-side API key authentication.
All external callers (Plex, SnipeIT, Hangar, curl scripts) should use
a dedicated `X-Label-Hub-Key` header instead of the Pangolin `claude-automation`
Basic-Auth bypass.

## Scope Model

| Scope | Access | Use for |
|-------|--------|---------|
| `read` | GET endpoints only | monitoring, status checks |
| `print` | Read + submit print jobs | Plex, SnipeIT, Hangar, curl |
| `admin` | Everything + manage API keys | Claude tooling, bootstrap only |

`admin` supersumes `print` which supersumes `read`.

## Creating a Key

1. Open `/admin/api-keys` in your browser (requires Pangolin SSO login)
2. Click **New Key**
3. Set name, scopes, and rate limit
4. Copy the plaintext key shown after creation — **it will not be shown again**

The key starts with `lh_` (Label Hub prefix, ~43 URL-safe chars).

## Using a Key

```bash
# List printers
curl -H "X-Label-Hub-Key: lh_abc..." https://your-hub/api/v1/printers

# Submit a print job
curl -X POST \
  -H "X-Label-Hub-Key: lh_abc..." \
  -H "Content-Type: application/json" \
  -d '{"content_type": "qr_two_lines", "data": {"primary_id": "ASSET-123", "title": "Asset 123", "qr_payload": "https://snipe.example/assets/123"}}' \
  https://your-hub/api/v1/print
```

## Rate Limits

Default: 60 requests/minute per key. Adjustable in the UI (1-10,000/min).

When exceeded, the response is `HTTP 429` with a `Retry-After` header and body:
```json
{
  "error_code": "rate_limit_exceeded",
  "error_message": "Key 'Plex Print' exceeded 60 prints/minute. Retry after 12 seconds.",
  "retry_after_seconds": 12
}
```

## Batch and preview limits

Tape batches (`POST /api/v1/print/{printer}/batch`) are limited per printer and per key:

| Limit | Default | Setting |
|---|---|---|
| Tape runs a printer has queued or printing | 5 (at least 5) | `PRINTER_HUB_MAX_QUEUED_RUNS_PER_PRINTER` |
| Tape runs of one key, over all printers, held runs included | 20 | `PRINTER_HUB_MAX_QUEUED_RUNS_PER_KEY` |
| Held runs per printer (stopped, or waiting for `/continue`) | 5 | fixed |
| Held runs of one key on one printer | 2 | fixed |

Over a queued-run limit the batch answers `HTTP 429` with `error_code`
`too-many-queued-runs`, in the shape shown above. A key's third held run on a printer
discards that key's own oldest held run (`run_discarded_limit`), never another key's.
While a printer's five held places are taken, a batch of more than 50 labels from a key
without a held run there is refused with 429; smaller batches are always taken.

Only the key that submitted a batch may `continue`, `reprint` or `discard` its run, and
`GET /api/v1/batches/runs/held` shows a key only its own runs. For any other key the batch
answers 404. Browser sessions, SSO users and admin keys may act on all runs.

A sheet preview (`POST /api/v1/print/{printer}/sheet/preview`) runs once per key at a
time; a second one answers 429 `too-many-previews`.

At most two pages are drawn at once in the hub (sheet previews and page jobs together). A
page that takes longer than `PRINTER_HUB_RENDER_TIMEOUT_S` (default 60 seconds) to draw
ends the preview with `HTTP 504` `render-timeout` (the key may preview again at once) and
fails a page job with `render_timeout`. Its drawing thread cannot be stopped and keeps its
slot until it ends; `GET /readiness` shows such stuck renders in the check `render_slots`
(failing when every slot is stuck). `/healthz` does not, so restart the hub by hand then.

All callers without a key (browser sessions, SSO users) count as **one** key for the
held-run limits: one UI user's held run lets every UI user pass the held-places check, and
a UI user's further held run can discard another UI user's oldest one. For previews they
are told apart by source, user and address.

## Printer ACL

A key can be restricted to specific printers via `allowed_printer_ids`.
An empty list means all printers are allowed.

## Transition from Pangolin Bypass

The Pangolin `Authorization: Basic` bypass is **off by default**. It only
authenticates when `PRINTER_HUB_TRUST_PANGOLIN_BASIC_BYPASS=true` is set, and its
state-changing requests need an `Origin` equal to `PRINTER_HUB_PUBLIC_URL`. While it
is enabled, limit it to `read` scope with:

```env
PRINTER_HUB_PANGOLIN_BYPASS_SCOPE_DOWNGRADE=true
```

Prefer dedicated API keys for every caller and leave the bypass disabled.

## First Admin Key (Bootstrap)

A fresh install has no API key. The migrations create none and print none.

1. Set a one-time key of at least 32 characters, for example
   `PRINTER_HUB_BOOTSTRAP_ADMIN_KEY=$(openssl rand -hex 32)`, and start the hub.
2. Sign in to the web UI with that key. The bootstrap session can only create
   the first real admin key, and the key is shown once.
3. Sign in with the new admin key and remove `PRINTER_HUB_BOOTSTRAP_ADMIN_KEY`.
   Once any enabled admin key exists, the bootstrap key is rejected.

Without the web UI, create the first key inside the container instead:

```bash
docker compose exec backend printer-hub admin create-key --scope admin --name first-admin
```

## Recovery

If every admin key is lost, create a new one with the same command inside the
container. It prints the plaintext key once on stdout:

```bash
docker compose exec backend printer-hub admin create-key --scope admin --name recovery
```

Whoever can run commands in the container already controls the hub, so this adds
no new attack surface. Revoke the lost keys afterwards via `/api/v1/admin/api-keys`.
