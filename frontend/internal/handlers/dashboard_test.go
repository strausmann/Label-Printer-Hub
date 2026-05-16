package handlers_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/strausmann/label-printer-hub/frontend/internal/handlers"
)

func printersBackend(t *testing.T) *httptest.Server {
	t.Helper()
	now := time.Now().Format(time.RFC3339)
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/printers" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode([]map[string]any{
			{"id": "aaaaaaaa-0000-0000-0000-000000000001", "name": "PT-P750W",
				"model": "pt_series", "backend": "tcp",
				"connection": map[string]any{"host": "198.51.100.10", "port": 9100},
				"enabled": true, "paused": false, "created_at": now, "updated_at": now},
			{"id": "bbbbbbbb-0000-0000-0000-000000000002", "name": "QL-800",
				"model": "ql_series", "backend": "tcp",
				"connection": map[string]any{"host": "198.51.100.11", "port": 9100},
				"enabled": true, "paused": true, "created_at": now, "updated_at": now},
		})
	}))
}

func TestDashboardOK(t *testing.T) {
	t.Parallel()
	backend := printersBackend(t)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	// Set HX-Request to render the dashboard-content fragment, which contains
	// the printer list. The stub layout's {{block "content"}} is not overridden
	// in the test template set, so we use the fragment path to get the
	// dashboard-content template which iterates .Printers.
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set("HX-Request", "true")
	w := httptest.NewRecorder()
	ph.Dashboard(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("status %d", w.Code)
	}
	for _, want := range []string{"PT-P750W", "QL-800", "printer-grid"} {
		if !strings.Contains(w.Body.String(), want) {
			t.Errorf("body missing %q", want)
		}
	}
}

func TestDashboardOKFullPage(t *testing.T) {
	t.Parallel()
	backend := printersBackend(t)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	// Full-page render (no HX-Request header) — verifies the layout template
	// is executed and returns 200 with a DOCTYPE.
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	w := httptest.NewRecorder()
	ph.Dashboard(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("status %d", w.Code)
	}
	if !strings.Contains(w.Body.String(), "<!DOCTYPE html>") {
		t.Error("full page must have DOCTYPE")
	}
}

func TestDashboard503WhenBackendDown(t *testing.T) {
	t.Parallel()
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "gone", http.StatusServiceUnavailable)
	}))
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	w := httptest.NewRecorder()
	ph.Dashboard(w, req)
	if w.Code != http.StatusServiceUnavailable {
		t.Errorf("status %d, want 503", w.Code)
	}
}
