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
curl -H "X-Label-Hub-Key: lh_abc..." https://your-hub/api/printers

# Submit a print job
curl -X POST \
  -H "X-Label-Hub-Key: lh_abc..." \
  -H "Content-Type: application/json" \
  -d '{"template_id": "snipeit-12mm", "data": {...}}' \
  https://your-hub/print
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

## Printer ACL

A key can be restricted to specific printers via `allowed_printer_ids`.
An empty list means all printers are allowed.

## Transition from Pangolin Bypass

After creating dedicated keys for all callers, the Pangolin `claude-automation`
bypass is downgraded to `read` scope by setting:

```env
PRINTER_HUB_PANGOLIN_BYPASS_SCOPE_DOWNGRADE=true
```

**Default is `false`** — no breakage on deploy. Flip this after confirming
all consumers have migrated to app keys.

## Bootstrap Key

On first migration, a `bootstrap-admin` key is seeded and its plaintext
is printed to the container startup log. Copy it and create your permanent
keys, then revoke the bootstrap key.

```bash
# Find the bootstrap key in container logs
docker logs label-printer-hub-backend 2>&1 | grep "BOOTSTRAP API KEY"
```

## Recovery

If all keys are lost:

1. The `claude-automation` Pangolin bypass still works for `read`-scoped endpoints
2. Use `/readiness` to verify the backend is up
3. Connect to the backend DB directly and re-seed a key, or restart the backend
   (a second bootstrap key is only seeded when the table is empty)
