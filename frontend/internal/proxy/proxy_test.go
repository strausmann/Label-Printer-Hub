package proxy_test

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/strausmann/label-printer-hub/frontend/internal/proxy"
)

func TestProxyForwards(t *testing.T) {
	t.Parallel()
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, `{"ok":true}`)
	}))
	defer backend.Close()
	w := httptest.NewRecorder()
	proxy.New(backend.URL).ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/api/printers", nil))
	if w.Code != http.StatusOK {
		t.Fatalf("status %d", w.Code)
	}
	if !strings.Contains(w.Body.String(), `"ok":true`) {
		t.Error("body not forwarded")
	}
}

func TestProxyPassesSSEContentType(t *testing.T) {
	t.Parallel()
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		io.WriteString(w, "data: hello\n\n")
		w.(http.Flusher).Flush()
	}))
	defer backend.Close()
	w := httptest.NewRecorder()
	proxy.New(backend.URL).ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/api/events", nil))
	if !strings.HasPrefix(w.Header().Get("Content-Type"), "text/event-stream") {
		t.Errorf("Content-Type = %q", w.Header().Get("Content-Type"))
	}
}

func TestProxyReturns502WhenDown(t *testing.T) {
	t.Parallel()
	// Use a server that listens but immediately closes the connection,
	// simulating a backend that rejects connections.
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Hijack the connection and close it to force a connection error.
		hj, ok := w.(http.Hijacker)
		if !ok {
			http.Error(w, "no hijack", 500)
			return
		}
		conn, _, _ := hj.Hijack()
		conn.Close()
	}))
	defer backend.Close()

	w := httptest.NewRecorder()
	proxy.New(backend.URL).ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/", nil))
	if w.Code != http.StatusBadGateway {
		t.Errorf("status %d, want 502", w.Code)
	}
}
