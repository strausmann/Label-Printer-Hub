# SSE Reverse-Proxy Compatibility

The `/api/v1/events` endpoint streams `text/event-stream` responses. The backend serves it directly to the browser (one process, ADR 0015), so these settings apply to the reverse proxy in front of the hub. All modern
reverse proxies buffer responses by default — this breaks SSE because the
client receives nothing until the buffer flushes or the connection closes.

The backend sets `X-Accel-Buffering: no` on every SSE response. Proxies that
honour this header (Traefik v3, Nginx with the `ngx_http_proxy` module) will
flush immediately without extra configuration. For proxies that do not honour
it, the explicit configuration below is required.

**Why does buffering break SSE?**
SSE is a long-lived HTTP response. Each event is a small chunk sent as soon as
it occurs. A buffering proxy holds those chunks until its write buffer is full
or the TCP connection closes — at which point the client receives either a burst
of all events at once or nothing at all. Disabling buffering forces the proxy to
pass each write through to the client immediately, which is the only way SSE can
work in real time.

**Why does idle-timeout matter?**
The backend closes idle SSE connections after 300 seconds (configurable via
`PRINTER_HUB_SSE_IDLE_TIMEOUT_S`). If the reverse proxy has a shorter
read-timeout on idle connections it will close the connection first, causing
the browser's EventSource to reconnect. Set any proxy read-timeout to at least
`PRINTER_HUB_SSE_IDLE_TIMEOUT_S + 60` seconds to avoid spurious reconnects.

---

## Traefik v3

Traefik v3 respects `X-Accel-Buffering: no` when `passHostHeader` is enabled
(the default). The header set by the backend is sufficient — no extra Traefik
configuration is needed. To be explicit, or if you are running Traefik v2, add
a dedicated middleware:

```yaml
# In Docker Compose labels or a static Traefik middleware file
traefik.http.middlewares.sse-flush.headers.customResponseHeaders.X-Accel-Buffering=no
traefik.http.routers.printer-hub-sse.rule=PathPrefix(`/api/v1/events`)
traefik.http.routers.printer-hub-sse.middlewares=sse-flush@docker
```

The `customResponseHeaders` middleware overrides the header on the downstream
response, ensuring even older Traefik v2 releases pass bytes through without
buffering.

---

## Caddy

```caddyfile
@sse path /api/v1/events*
handle @sse {
    reverse_proxy backend:8000 {
        flush_interval -1
    }
}
```

`flush_interval -1` instructs Caddy to flush on every write. The default
`flush_interval 0` means Caddy chooses the interval, which may buffer small
SSE events. `examples/compose.caddy.yml` sets `flush_interval -1` for the whole
site, which covers the event path.

---

## Nginx / nginx-proxy

```nginx
location /api/v1/events {
    proxy_pass http://backend:8000;
    proxy_buffering off;
    proxy_cache off;
    add_header X-Accel-Buffering no;
    proxy_set_header Connection '';
    proxy_http_version 1.1;
    chunked_transfer_encoding on;
}
```

Key directives:

| Directive | Why it is needed |
|---|---|
| `proxy_buffering off` | Disables Nginx's default response buffer; bytes pass through immediately |
| `proxy_cache off` | Prevents the cache module from intercepting the long-lived response |
| `proxy_http_version 1.1` | SSE relies on HTTP/1.1 persistent connections; the default `1.0` closes after each response |
| `proxy_set_header Connection ''` | Clears the `Connection: close` header that HTTP/1.0 mode sets, keeping the connection alive |
| `chunked_transfer_encoding on` | Allows the server to send chunked responses without a known `Content-Length` |

---

## Pangolin (HomeLab deployment)

Pangolin tunnels sit in front of Traefik. The `X-Accel-Buffering: no` header
set by the backend propagates through the tunnel chain to the browser. No
Pangolin-specific configuration is required beyond the Traefik settings above.

This pattern is verified to work with Gotify (also SSE-based) behind the same
Pangolin + Traefik v3 stack. The header passes through the Pangolin newt client
→ Traefik → browser path unchanged.

SSE works without extra Pangolin configuration while `X-Accel-Buffering: no` is
set on the response. Set the Pangolin idle timeout above
`PRINTER_HUB_SSE_IDLE_TIMEOUT_S`.

---

## Verification

After deploying, verify SSE is working end-to-end:

```bash
# Replace <host> with the hub address; use any API key with read scope
# (the key is read from the environment, never typed into the command line).
curl -N -H "Accept: text/event-stream" -K - <<EOF2
header = "X-Label-Hub-Key: $HUB_API_KEY"
url = "https://<host>/api/v1/events"
EOF2
# You should see ": connected", a snapshot per printer, then ": keepalive"
# comment lines every 30 seconds.
```

If the connection returns immediately with no output, or only produces output
after a long delay, the proxy is buffering. Check the `X-Accel-Buffering`
header in the response:

```bash
curl -s -D - -o /dev/null -m 3 -K - <<EOF2 | grep -i buffering
header = "X-Label-Hub-Key: $HUB_API_KEY"
url = "https://<host>/api/v1/events"
EOF2
# Expected: X-Accel-Buffering: no
```

If the header is missing, check that the backend container is reachable and
that the proxy is forwarding headers from the upstream response.

---

## Web UI stream: `GET /api/v1/events`

The web UI opens **one** `EventSource` on `/api/v1/events` (optional
`?printer_id=<uuid>`). It authenticates like every `read` route, so the session
cookie of a signed-in browser is enough. The proxy settings above apply unchanged.

| Frame | Meaning |
|-------|---------|
| `: connected` | subscriptions are in place |
| `id: 0` + snapshot events | current state per visible printer (`printer.status`, `printer.tape_changed`, active `job.state_changed`) |
| `id: N` / `event: <type>` / `data: <json>` | live event; `N` counts per channel |
| `: keepalive` | every `PRINTER_HUB_SSE_HEARTBEAT_S` seconds |
| `event: auth.expired` | the session or key is no longer valid (or its printer restriction changed); the stream closes |

`data` is always `{"channel": str, "printer_id": str | null, "type": str, "ts": ISO-8601, "data": {...}}`.

The stream subscribes to the `hub` channel, to the `sheets` channel and to
`printer:{id}:{queue,state,tape}` of every enabled printer the credentials may see. Printers outside `allowed_printer_ids` are never
subscribed. Without a `printer_id` filter, printers that are created or enabled later are
picked up on the fly.

`sheet.updated` (channel `sheets`) is published after every committed change to a sheet's
cells: a reservation, a release, the outcome of a page job (`used`, `unconfirmed` or freed), the
startup sweep, a resolve of unconfirmed cells and a manual edit. Its `data` is
`{"code": str, "free": int, "total": int, "changed": [int], "state": str}`, where `changed`
lists the cell numbers touched and `state` is the sheet's state. Sheets carry no printer
restriction (OC-11), so every stream receives this channel regardless of
`allowed_printer_ids` and of a `printer_id` filter. A client reacts by reading the sheet.

`run.state_changed` (channel `printer:{id}:queue`) is published when a tape run (#277) enters or
leaves the held list, which no job event tells a client: it starts waiting for a confirmation,
stops, is confirmed, reprinted or discarded. Its `data` is
`{"run_id": str, "printer_id": str, "state": str}`, where `state` is the run's state
(`awaiting_confirmation`, `stopped`, `printing`) or `discarded` / `finished` once the run is gone.
It is sent after the state is set, so a client that reads the run on the event sees it. It carries
no label content. A client reacts by reading the held runs again.

`hub.printers_changed` (channel `hub`) is published by the admin printer API with
`{"printer_id": str, "change": "created" | "updated" | "disabled" | "enabled"}`.

On every heartbeat the stream re-checks its credentials in a short database session (it holds
none for its lifetime). The cap `PRINTER_HUB_SSE_MAX_SUBSCRIBERS` applies to the number of open
event streams; one more gets `429`. Replay via `Last-Event-ID` is not implemented: after a
reconnect the client gets a fresh snapshot.
