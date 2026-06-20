package handlers_test

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/strausmann/label-printer-hub/frontend/internal/handlers"
)

// TestTemplatesListReturns503 verifies that GET /templates returns 503 Service
// Unavailable now that the backend endpoint GET /api/templates has been removed
// in Phase 1k.1a (Issue #103). The frontend stub (ListTemplates) always returns
// ErrNotImplemented, which the handler maps to 503.
//
// A follow-up task (#103) will remove the template routes and handlers.
func TestTemplatesListReturns503(t *testing.T) {
	t.Parallel()
	// Any backend will do — the client never reaches it.
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.NotFound(w, r)
	}))
	defer backend.Close()

	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/templates", nil)
	w := httptest.NewRecorder()
	ph.TemplatesList(w, req)
	if w.Code != http.StatusServiceUnavailable {
		t.Errorf("status %d, want 503 (templates endpoint removed)", w.Code)
	}
}

// TestTemplatesListWithAppReturns503 verifies that TemplatesListWithApp also
// returns 503 after the backend endpoint was removed.
func TestTemplatesListWithAppReturns503(t *testing.T) {
	t.Parallel()
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.NotFound(w, r)
	}))
	defer backend.Close()

	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/templates?app=snipeit", nil)
	w := httptest.NewRecorder()
	ph.TemplatesListWithApp(w, req, "snipeit")
	if w.Code != http.StatusServiceUnavailable {
		t.Errorf("status %d, want 503 (templates endpoint removed)", w.Code)
	}
}
