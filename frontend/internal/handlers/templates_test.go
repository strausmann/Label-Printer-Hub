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

// templatesBackend returns a mock backend that serves /api/templates.
// If appFilter is non-empty it only returns templates matching that app.
func templatesBackend(t *testing.T) *httptest.Server {
	t.Helper()
	now := time.Now().Format(time.RFC3339)
	tpls := []map[string]any{
		{
			"id": "aaaaaaaa-0000-0000-0000-000000000001", "key": "snipeit/asset",
			"name": "Snipe-IT Asset", "app": "snipeit", "printer_model": "pt_series",
			"tape_width_mm": 12, "schema_version": 1, "source": "name: Snipe-IT Asset\n",
			"definition": map[string]any{}, "created_at": now, "updated_at": now,
		},
		{
			"id": "bbbbbbbb-0000-0000-0000-000000000002", "key": "grocy/product",
			"name": "Grocy Product", "app": "grocy", "printer_model": "ql_series",
			"tape_width_mm": 29, "schema_version": 1, "source": "name: Grocy Product\n",
			"definition": map[string]any{}, "created_at": now, "updated_at": now,
		},
	}
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/templates" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		app := r.URL.Query().Get("app")
		if app == "" {
			json.NewEncoder(w).Encode(tpls)
			return
		}
		// Return only templates matching the app filter.
		var filtered []map[string]any
		for _, tpl := range tpls {
			if tpl["app"] == app {
				filtered = append(filtered, tpl)
			}
		}
		if filtered == nil {
			filtered = []map[string]any{}
		}
		json.NewEncoder(w).Encode(filtered)
	}))
}

func TestTemplatesListOK(t *testing.T) {
	t.Parallel()
	backend := templatesBackend(t)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/templates", nil)
	req.Header.Set("HX-Request", "true")
	w := httptest.NewRecorder()
	ph.TemplatesList(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("status %d, body: %s", w.Code, w.Body.String())
	}
	body := w.Body.String()
	if !strings.Contains(body, "templates-grid") {
		t.Errorf("body missing 'templates-grid', got: %s", body)
	}
}

func TestTemplatesListFullPage(t *testing.T) {
	t.Parallel()
	backend := templatesBackend(t)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/templates", nil)
	w := httptest.NewRecorder()
	ph.TemplatesList(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("status %d, body: %s", w.Code, w.Body.String())
	}
	if !strings.Contains(w.Body.String(), "<!DOCTYPE html>") {
		t.Error("full page must have DOCTYPE")
	}
}

func TestTemplatesListAppFilter(t *testing.T) {
	t.Parallel()
	backend := templatesBackend(t)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/templates?app=snipeit", nil)
	req.Header.Set("HX-Request", "true")
	w := httptest.NewRecorder()
	ph.TemplatesListWithApp(w, req, "snipeit")
	if w.Code != http.StatusOK {
		t.Fatalf("status %d, body: %s", w.Code, w.Body.String())
	}
}

func TestTemplatesListBackendError(t *testing.T) {
	t.Parallel()
	// Backend returns 500 for all requests.
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "internal error", http.StatusInternalServerError)
	}))
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	w := httptest.NewRecorder()
	ph.TemplatesListWithApp(w, httptest.NewRequest(http.MethodGet, "/templates", nil), "")
	if w.Code != http.StatusServiceUnavailable {
		t.Errorf("status %d, want 503", w.Code)
	}
}
