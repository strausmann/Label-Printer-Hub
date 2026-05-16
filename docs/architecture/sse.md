# SSE Reverse-Proxy Compatibility

The `/api/events` endpoint streams `text/event-stream` responses. All modern
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
traefik.http.routers.printer-hub-sse.rule=PathPrefix(`/api/events`)
traefik.http.routers.printer-hub-sse.middlewares=sse-flush@docker
```

The `customResponseHeaders` middleware overrides the header on the downstream
response, ensuring even older Traefik v2 releases pass bytes through without
buffering.

---

## Caddy

```caddyfile
@sse path /api/events*
handle @sse {
    reverse_proxy backend:8090 {
        flush_interval -1
    }
}
```

`flush_interval -1` instructs Caddy to flush on every write. The default
`flush_interval 0` means Caddy chooses the interval, which may buffer small
SSE events. The `examples/compose.caddy.yml` example file should use this
block for the `/api/events` path.

---

## Nginx / nginx-proxy

```nginx
location /api/events {
    proxy_pass http://backend:8090;
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

**Note for `examples/compose.pangolin.yml` maintainer:** document that SSE
works without extra config when `X-Accel-Buffering: no` is set on the response,
and remind operators to set their Pangolin idle-timeout above
`PRINTER_HUB_SSE_IDLE_TIMEOUT_S`.

---

## Verification

After deploying, verify SSE is working end-to-end:

```bash
# Replace <host> and <printer-id> with real values
curl -N -H "Accept: text/event-stream" \
  "https://<host>/api/events?printer_id=<printer-id>"
# You should see ": keepalive" comment lines every 30 seconds.
```

If the connection returns immediately with no output, or only produces output
after a long delay, the proxy is buffering. Check the `X-Accel-Buffering`
header in the response:

```bash
curl -sI "https://<host>/api/events?printer_id=<printer-id>" | grep -i buffering
# Expected: X-Accel-Buffering: no
```

If the header is missing, check that the backend container is reachable and
that the proxy is forwarding headers from the upstream response.
