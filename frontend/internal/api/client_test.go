package api_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/strausmann/label-printer-hub/frontend/internal/api"
)

// TestPrinterReadPausedFalseDecodesAsBoolFalse verifies that a JSON response
// with "paused": false decodes to PrinterRead.Paused == false (not a non-nil
// pointer to false, which would be truthy in Go template {{if .Paused}}).
//
// This is the regression test for Bug 1: oapi-codegen generated Paused *bool
// (omitempty) from the OpenAPI schema that listed paused as optional-with-default.
// A non-nil *bool(&false) evaluates as truthy in html/template {{if .Paused}},
// causing every printer to show the "Paused" badge.
// After the fix: paused is required in the schema → Paused bool → false is falsy.
func TestPrinterReadPausedFalseDecodesAsBoolFalse(t *testing.T) {
	t.Parallel()
	now := time.Now().Format(time.RFC3339)
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/printers" {
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode([]map[string]any{
				{"id": "aaaaaaaa-0000-0000-0000-000000000001", "name": "PT-P750W",
					"model": "pt_series", "backend": "tcp",
					"connection": map[string]any{"host": "198.51.100.10", "port": 9100},
					"enabled":    true, "paused": false, "created_at": now, "updated_at": now},
			})
		} else {
			http.NotFound(w, r)
		}
	}))
	defer backend.Close()

	printers, err := api.NewHubClient(backend.URL).ListPrinters(context.Background())
	if err != nil {
		t.Fatalf("ListPrinters: %v", err)
	}
	if len(printers) != 1 {
		t.Fatalf("expected 1 printer, got %d", len(printers))
	}
	// Paused must be a plain bool false — NOT a non-nil *bool(&false).
	// A *bool is truthy in html/template {{if .Paused}} even when it points to false.
	if printers[0].Paused != false {
		t.Errorf("Paused = %v, want false (plain bool, not pointer-to-false)", printers[0].Paused)
	}
}

func TestListPrintersHitsCorrectPath(t *testing.T) {
	t.Parallel()
	called := false
	now := time.Now().Format(time.RFC3339)
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/printers" {
			called = true
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode([]map[string]any{
				{"id": "aaaaaaaa-0000-0000-0000-000000000001", "name": "PT-P750W",
					"model": "pt_series", "backend": "tcp",
					"connection": map[string]any{"host": "198.51.100.10", "port": 9100},
					"enabled":    true, "paused": false, "created_at": now, "updated_at": now},
			})
		} else {
			http.NotFound(w, r)
		}
	}))
	defer backend.Close()

	printers, err := api.NewHubClient(backend.URL).ListPrinters(context.Background())
	if err != nil {
		t.Fatalf("ListPrinters: %v", err)
	}
	if !called {
		t.Error("GET /api/printers not called")
	}
	if len(printers) != 1 || printers[0].Name != "PT-P750W" {
		t.Errorf("unexpected result: %+v", printers)
	}
}

func TestGetJobReturnsErrNotFound(t *testing.T) {
	t.Parallel()
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.NotFound(w, r)
	}))
	defer backend.Close()
	_, err := api.NewHubClient(backend.URL).GetJob(context.Background(), "no-such-job")
	if err != api.ErrNotFound {
		t.Errorf("err = %v, want ErrNotFound", err)
	}
}

// TestListTemplatesReturnsErrNotImplemented verifies that ListTemplates returns
// ErrNotImplemented now that GET /api/templates has been removed from the
// backend in Phase 1k.1a (Issue #103). A follow-up task will remove the
// template routes and handler code entirely.
func TestListTemplatesReturnsErrNotImplemented(t *testing.T) {
	t.Parallel()
	// No backend needed — the stub returns immediately without any HTTP call.
	_, err := api.NewHubClient("http://localhost:0").ListTemplates(context.Background(), "snipeit")
	if err != api.ErrNotImplemented {
		t.Errorf("ListTemplates err = %v, want ErrNotImplemented", err)
	}
}

func TestLookupEntityReturnsErrUnsupportedApp(t *testing.T) {
	t.Parallel()
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, `{"detail":"unprocessable"}`, http.StatusUnprocessableEntity)
	}))
	defer backend.Close()
	_, err := api.NewHubClient(backend.URL).LookupEntity(context.Background(), "badapp", "123")
	if err != api.ErrUnsupportedApp {
		t.Errorf("err = %v, want ErrUnsupportedApp", err)
	}
}

// TestListPrintersForwards401AsError verifies that when the backend returns 401
// (because the frontend sends no auth header), ListPrinters returns an error
// that causes the dashboard to render 503.
//
// This is the regression test for the Phase 7c auth bug: after PR #88 added
// backend API-key auth, the frontend HubClient did not forward the
// X-Pangolin-User / X-Label-Hub-Key headers from the incoming browser request
// to the outgoing backend call, causing every dashboard load to receive 401
// and render a 503 Service Unavailable page.
func TestListPrintersForwards401AsError(t *testing.T) {
	t.Parallel()
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/printers" {
			http.Error(w, `{"error_code":"missing_credentials"}`, http.StatusUnauthorized)
			return
		}
		http.NotFound(w, r)
	}))
	defer backend.Close()

	_, err := api.NewHubClient(backend.URL).ListPrinters(context.Background())
	if err == nil {
		t.Fatal("ListPrinters: expected error on 401 from backend, got nil")
	}
}

// TestWithAuthFromForwardsPangolinHeader verifies that WithAuthFrom propagates
// the X-Pangolin-User header from the incoming browser request to the backend
// call, allowing authenticated dashboard loads.
func TestWithAuthFromForwardsPangolinHeader(t *testing.T) {
	t.Parallel()
	var receivedHeader string
	now := time.Now().Format(time.RFC3339)
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/printers" {
			receivedHeader = r.Header.Get("X-Pangolin-User")
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode([]map[string]any{
				{"id": "aaaaaaaa-0000-0000-0000-000000000001", "name": "PT-P750W",
					"model": "pt_series", "backend": "tcp",
					"connection": map[string]any{"host": "198.51.100.10", "port": 9100},
					"enabled": true, "paused": false,
					"created_at": now, "updated_at": now},
			})
			return
		}
		http.NotFound(w, r)
	}))
	defer backend.Close()

	// Simulate an incoming browser request with Pangolin SSO header set.
	incomingReq := httptest.NewRequest(http.MethodGet, "/", nil)
	incomingReq.Header.Set("X-Pangolin-User", "strausmann")

	client := api.NewHubClient(backend.URL).WithAuthFrom(incomingReq)
	printers, err := client.ListPrinters(context.Background())
	if err != nil {
		t.Fatalf("ListPrinters: %v", err)
	}
	if receivedHeader != "strausmann" {
		t.Errorf("X-Pangolin-User forwarded as %q, want %q", receivedHeader, "strausmann")
	}
	if len(printers) != 1 {
		t.Errorf("expected 1 printer, got %d", len(printers))
	}
}

// TestWithAuthFromForwardsAPIKeyHeader verifies that WithAuthFrom propagates
// the X-Label-Hub-Key header from the incoming browser request to the backend.
func TestWithAuthFromForwardsAPIKeyHeader(t *testing.T) {
	t.Parallel()
	var receivedKey string
	now := time.Now().Format(time.RFC3339)
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/printers" {
			receivedKey = r.Header.Get("X-Label-Hub-Key")
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode([]map[string]any{
				{"id": "aaaaaaaa-0000-0000-0000-000000000001", "name": "PT-P750W",
					"model": "pt_series", "backend": "tcp",
					"connection": map[string]any{"host": "198.51.100.10", "port": 9100},
					"enabled": true, "paused": false,
					"created_at": now, "updated_at": now},
			})
			return
		}
		http.NotFound(w, r)
	}))
	defer backend.Close()

	incomingReq := httptest.NewRequest(http.MethodGet, "/", nil)
	incomingReq.Header.Set("X-Label-Hub-Key", "lh_testapikey1234567890")

	client := api.NewHubClient(backend.URL).WithAuthFrom(incomingReq)
	_, err := client.ListPrinters(context.Background())
	if err != nil {
		t.Fatalf("ListPrinters: %v", err)
	}
	if receivedKey != "lh_testapikey1234567890" {
		t.Errorf("X-Label-Hub-Key forwarded as %q, want %q", receivedKey, "lh_testapikey1234567890")
	}
}

// TestWithAuthFromForwardsPangolinTokenHeader verifies that WithAuthFrom
// propagates the X-Pangolin-Token header from the incoming browser request
// to the backend. Pangolin Resources can be configured with a custom upstream
// header (via Pangolin Header-Auth) that injects a static trust token into
// every request reaching the frontend container. The backend accepts this
// token as a Phase 7c SSO-trust signal (sso_trust_header). Without this
// forwarding, browser users without an SSO session see a 503 on every route
// that needs backend data (Dashboard, Jobs, Templates, /admin/*).
func TestWithAuthFromForwardsPangolinTokenHeader(t *testing.T) {
	t.Parallel()
	var receivedToken string
	now := time.Now().Format(time.RFC3339)
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/printers" {
			receivedToken = r.Header.Get("X-Pangolin-Token")
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode([]map[string]any{
				{"id": "aaaaaaaa-0000-0000-0000-000000000001", "name": "PT-P750W",
					"model": "pt_series", "backend": "tcp",
					"connection": map[string]any{"host": "198.51.100.10", "port": 9100},
					"enabled": true, "paused": false,
					"created_at": now, "updated_at": now},
			})
			return
		}
		http.NotFound(w, r)
	}))
	defer backend.Close()

	incomingReq := httptest.NewRequest(http.MethodGet, "/", nil)
	incomingReq.Header.Set("X-Pangolin-Token", "pangolin-trust-token-abc123")

	client := api.NewHubClient(backend.URL).WithAuthFrom(incomingReq)
	_, err := client.ListPrinters(context.Background())
	if err != nil {
		t.Fatalf("ListPrinters: %v", err)
	}
	if receivedToken != "pangolin-trust-token-abc123" {
		t.Errorf("X-Pangolin-Token forwarded as %q, want %q", receivedToken, "pangolin-trust-token-abc123")
	}
}
