package handlers_test

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/strausmann/label-printer-hub/frontend/internal/handlers"
)

// TestTemplateDetailReturns503 verifies that GET /templates/{key} returns 503
// now that the backend endpoint GET /api/templates has been removed in Phase
// 1k.1a (Issue #103). The frontend stub (ListTemplates) always returns
// ErrNotImplemented, which the template detail handler maps to 503.
//
// A follow-up task (#103) will remove the template routes and handlers.
func TestTemplateDetailReturns503(t *testing.T) {
	t.Parallel()
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.NotFound(w, r)
	}))
	defer backend.Close()

	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/templates/snipeit/asset", nil)
	req.Header.Set("HX-Request", "true")
	w := httptest.NewRecorder()
	ph.TemplateDetailWithKey(w, req, "snipeit/asset")
	if w.Code != http.StatusServiceUnavailable {
		t.Errorf("status %d, want 503 (templates endpoint removed)", w.Code)
	}
}

// TestTemplateDetailEmptyKeyReturns400 verifies that a missing key still
// returns 400 Bad Request before any backend call is made.
func TestTemplateDetailEmptyKeyReturns400(t *testing.T) {
	t.Parallel()
	ph := handlers.NewPageHandlerFromURL(t, "http://localhost:0")
	w := httptest.NewRecorder()
	ph.TemplateDetailWithKey(w, httptest.NewRequest(http.MethodGet, "/templates/", nil), "")
	if w.Code != http.StatusBadRequest {
		t.Errorf("status %d, want 400", w.Code)
	}
}

// TestTemplateDetailBackendUnreachable verifies that a network error (backend
// server returns 500) maps to 503 Service Unavailable. This tests the general
// error path in the handler, which is still exercised via ErrNotImplemented.
func TestTemplateDetailBackendUnreachable(t *testing.T) {
	t.Parallel()
	// The stub always returns ErrNotImplemented — no backend call happens.
	ph := handlers.NewPageHandlerFromURL(t, "http://localhost:0")
	w := httptest.NewRecorder()
	ph.TemplateDetailWithKey(w, httptest.NewRequest(http.MethodGet, "/templates/x", nil), "x")
	if w.Code != http.StatusServiceUnavailable {
		t.Errorf("status %d, want 503", w.Code)
	}
}
