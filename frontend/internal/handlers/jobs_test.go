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

func jobsBackend(t *testing.T) *httptest.Server {
	t.Helper()
	now := time.Now().Format(time.RFC3339)
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/jobs" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode([]map[string]any{
			{"id": "11111111-0000-0000-0000-000000000001",
				"printer_id":   "aaaaaaaa-0000-0000-0000-000000000001",
				"template_key": "snipeit-asset", "state": "done",
				"payload": map[string]any{}, "result": nil, "error": nil,
				"created_at": now, "updated_at": now,
				"started_at": now, "finished_at": now},
		})
	}))
}

func TestJobsListOK(t *testing.T) {
	t.Parallel()
	backend := jobsBackend(t)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	// Use HX-Request so renderPage returns the jobs-content fragment which
	// contains the expected ids in the stub template.
	req := httptest.NewRequest(http.MethodGet, "/jobs", nil)
	req.Header.Set("HX-Request", "true")
	w := httptest.NewRecorder()
	ph.JobsList(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("status %d, body: %s", w.Code, w.Body.String())
	}
	for _, want := range []string{"jobs-table-container", "done"} {
		if !strings.Contains(w.Body.String(), want) {
			t.Errorf("body missing %q, got: %s", want, w.Body.String())
		}
	}
}

func TestJobsListFullPage(t *testing.T) {
	t.Parallel()
	backend := jobsBackend(t)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/jobs", nil)
	w := httptest.NewRecorder()
	ph.JobsList(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("status %d", w.Code)
	}
	if !strings.Contains(w.Body.String(), "<!DOCTYPE html>") {
		t.Error("full page must have DOCTYPE")
	}
}

func TestJobsListFilter(t *testing.T) {
	t.Parallel()
	backend := jobsBackend(t)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/jobs?state=done", nil)
	req.Header.Set("HX-Request", "true")
	w := httptest.NewRecorder()
	ph.JobsList(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("status %d", w.Code)
	}
}
