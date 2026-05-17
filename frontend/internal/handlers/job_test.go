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

const (
	jobID    = "22222222-0000-0000-0000-000000000002"
	newJobID = "33333333-0000-0000-0000-000000000003"
)

func jobDetailBackend(t *testing.T) *httptest.Server {
	t.Helper()
	now := time.Now().Format(time.RFC3339)
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch {
		case r.Method == http.MethodGet && r.URL.Path == "/api/jobs/"+jobID:
			json.NewEncoder(w).Encode(map[string]any{
				"id": jobID, "printer_id": "aaaaaaaa-0000-0000-0000-000000000001",
				"template_key": "snipeit-asset", "state": "failed",
				"payload": map[string]any{}, "result": nil, "error": "timeout",
				"created_at": now, "updated_at": now, "started_at": nil, "finished_at": nil,
			})
		case r.Method == http.MethodPost && r.URL.Path == "/api/jobs/"+jobID+"/retry":
			w.WriteHeader(http.StatusCreated)
			json.NewEncoder(w).Encode(map[string]any{
				"id": newJobID, "printer_id": "aaaaaaaa-0000-0000-0000-000000000001",
				"template_key": "snipeit-asset", "state": "queued",
				"payload": map[string]any{}, "result": nil, "error": nil,
				"created_at": now, "updated_at": now, "started_at": nil, "finished_at": nil,
			})
		default:
			http.NotFound(w, r)
		}
	}))
}

func TestJobDetailOK(t *testing.T) {
	t.Parallel()
	backend := jobDetailBackend(t)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	// Use HX-Request to render the job-content fragment which contains
	// the expected id ("job-detail") in the stub template.
	req := httptest.NewRequest(http.MethodGet, "/jobs/"+jobID, nil)
	req.Header.Set("HX-Request", "true")
	w := httptest.NewRecorder()
	ph.JobDetailWithID(w, req, jobID)
	if w.Code != http.StatusOK {
		t.Fatalf("status %d, body: %s", w.Code, w.Body.String())
	}
	if !strings.Contains(w.Body.String(), "job-detail") {
		t.Errorf("body missing 'job-detail', got: %s", w.Body.String())
	}
}

func TestJobDetailOKFullPage(t *testing.T) {
	t.Parallel()
	backend := jobDetailBackend(t)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/jobs/"+jobID, nil)
	w := httptest.NewRecorder()
	ph.JobDetailWithID(w, req, jobID)
	if w.Code != http.StatusOK {
		t.Fatalf("status %d, body: %s", w.Code, w.Body.String())
	}
	if !strings.Contains(w.Body.String(), "<!DOCTYPE html>") {
		t.Error("full page must have DOCTYPE")
	}
}

func TestJobDetailNotFound(t *testing.T) {
	t.Parallel()
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.NotFound(w, r) }))
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	w := httptest.NewRecorder()
	ph.JobDetailWithID(w, httptest.NewRequest(http.MethodGet, "/jobs/no-such", nil), "no-such")
	if w.Code != http.StatusNotFound {
		t.Errorf("status %d, want 404", w.Code)
	}
}

func TestJobRetry303(t *testing.T) {
	t.Parallel()
	backend := jobDetailBackend(t)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodPost, "/jobs/"+jobID+"/retry", nil)
	w := httptest.NewRecorder()
	ph.JobRetryWithID(w, req, jobID)
	if w.Code != http.StatusSeeOther {
		t.Errorf("status %d, want 303 See Other", w.Code)
	}
	loc := w.Header().Get("Location")
	if !strings.Contains(loc, newJobID) {
		t.Errorf("Location %q must contain new job ID %s", loc, newJobID)
	}
}
