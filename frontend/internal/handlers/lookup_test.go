package handlers_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/strausmann/label-printer-hub/frontend/internal/handlers"
)

const (
	lookupApp = "snipeit"
	lookupID  = "42"
)

// lookupBackend returns a mock backend for /api/lookup/{app}/{id}.
// It handles snipeit/42 as found, snipeit/999 as 404, and
// badapp/anything as 422 (unknown integration).
func lookupBackend(t *testing.T) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/api/lookup/snipeit/42":
			json.NewEncoder(w).Encode(map[string]any{
				"app":  "snipeit",
				"id":   "42",
				"name": "Test Asset #42",
				"url":  "https://snipeit.example.com/hardware/42",
			})
		case "/api/lookup/snipeit/999":
			w.WriteHeader(http.StatusNotFound)
			json.NewEncoder(w).Encode(map[string]any{"detail": "not found"})
		case "/api/lookup/badapp/1":
			w.WriteHeader(http.StatusUnprocessableEntity)
			json.NewEncoder(w).Encode(map[string]any{"detail": "unknown app"})
		default:
			http.NotFound(w, r)
		}
	}))
}

func TestLookupDisplayOK(t *testing.T) {
	t.Parallel()
	backend := lookupBackend(t)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/lookup/snipeit/42", nil)
	req.Header.Set("HX-Request", "true")
	w := httptest.NewRecorder()
	ph.LookupDisplayWithParams(w, req, lookupApp, lookupID)
	if w.Code != http.StatusOK {
		t.Fatalf("status %d, body: %s", w.Code, w.Body.String())
	}
	if w.Body.String() == "" {
		t.Error("body must not be empty")
	}
}

func TestLookupDisplayFullPage(t *testing.T) {
	t.Parallel()
	backend := lookupBackend(t)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/lookup/snipeit/42", nil)
	w := httptest.NewRecorder()
	ph.LookupDisplayWithParams(w, req, lookupApp, lookupID)
	if w.Code != http.StatusOK {
		t.Fatalf("status %d, body: %s", w.Code, w.Body.String())
	}
	body := w.Body.String()
	if body == "" {
		t.Error("body must not be empty for full page")
	}
}

func TestLookupDisplayNotFound(t *testing.T) {
	t.Parallel()
	backend := lookupBackend(t)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	w := httptest.NewRecorder()
	ph.LookupDisplayWithParams(w, httptest.NewRequest(http.MethodGet, "/lookup/snipeit/999", nil), "snipeit", "999")
	if w.Code != http.StatusNotFound {
		t.Errorf("status %d, want 404", w.Code)
	}
}

func TestLookupDisplayInvalidApp(t *testing.T) {
	t.Parallel()
	backend := lookupBackend(t)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	w := httptest.NewRecorder()
	ph.LookupDisplayWithParams(w, httptest.NewRequest(http.MethodGet, "/lookup/badapp/1", nil), "badapp", "1")
	if w.Code != http.StatusUnprocessableEntity {
		t.Errorf("status %d, want 422", w.Code)
	}
}

func TestLookupDisplayBackendError(t *testing.T) {
	t.Parallel()
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "internal", http.StatusInternalServerError)
	}))
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	w := httptest.NewRecorder()
	ph.LookupDisplayWithParams(w, httptest.NewRequest(http.MethodGet, "/lookup/snipeit/1", nil), "snipeit", "1")
	if w.Code != http.StatusServiceUnavailable {
		t.Errorf("status %d, want 503", w.Code)
	}
}
