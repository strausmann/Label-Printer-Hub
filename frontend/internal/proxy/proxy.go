// Package proxy provides a reverse-proxy handler that forwards all requests
// to the backend container.
//
// FlushInterval=-1 is essential for SSE: it tells httputil.ReverseProxy to
// flush each write immediately rather than buffering, which means
// text/event-stream chunks are forwarded to the browser without delay.
// Without this the browser never sees events until the connection closes.
package proxy

import (
	"log/slog"
	"net/http"
	"net/http/httputil"
	"net/url"
)

// New returns an http.Handler that reverse-proxies every request to backendURL.
//
// The handler is safe for concurrent use. backendURL must not have a
// trailing slash (e.g. "http://backend:8000").
//
// Key behaviours:
//   - FlushInterval=-1: immediate flush on every write (required for SSE).
//   - Host header is rewritten to the backend host (not the frontend host).
//   - X-Forwarded-For is stripped to avoid leaking client IPs through the
//     internal network; the upstream reverse proxy (Traefik/Pangolin) sets
//     the canonical X-Forwarded-For before the frontend receives the request.
//   - Backend errors (connection refused, DNS failure) return 502 Bad Gateway
//     with a plain-text body; the error is logged via slog.
func New(backendURL string) http.Handler {
	target, err := url.Parse(backendURL)
	if err != nil {
		panic("proxy.New: invalid backend URL: " + err.Error())
	}
	return &httputil.ReverseProxy{
		Director: func(req *http.Request) {
			req.URL.Scheme = target.Scheme
			req.URL.Host = target.Host
			req.Host = target.Host
			// Strip X-Forwarded-For so we don't accumulate hops from the
			// frontend → backend hop on the internal Docker network.
			req.Header.Del("X-Forwarded-For")
		},
		// -1 means flush after every write — mandatory for SSE streams.
		FlushInterval: -1,
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			slog.Error("proxy: backend unreachable",
				"method", r.Method,
				"path", r.URL.Path,
				"err", err,
			)
			http.Error(w, "backend unavailable", http.StatusBadGateway)
		},
	}
}
