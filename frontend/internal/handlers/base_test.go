package handlers_test

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/strausmann/label-printer-hub/frontend/internal/handlers"
)

func TestRenderPageFullLayout(t *testing.T) {
	t.Parallel()
	ph := handlers.NewPageHandlerForTest(t)
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	w := httptest.NewRecorder()
	ph.RenderTestPage(w, req, "dashboard", handlers.TemplateData{Version: "0.0.0-test", ActiveNav: "dashboard"})
	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", w.Code)
	}
	if !strings.Contains(w.Body.String(), "<!DOCTYPE html>") {
		t.Error("full page must contain DOCTYPE")
	}
}

func TestRenderPageHTMXFragment(t *testing.T) {
	t.Parallel()
	ph := handlers.NewPageHandlerForTest(t)
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set("HX-Request", "true")
	w := httptest.NewRecorder()
	ph.RenderTestPage(w, req, "dashboard", handlers.TemplateData{Version: "0.0.0-test"})
	if strings.Contains(w.Body.String(), "<!DOCTYPE html>") {
		t.Error("HTMX fragment must NOT contain DOCTYPE")
	}
}

func TestRenderPageSetsContentType(t *testing.T) {
	t.Parallel()
	ph := handlers.NewPageHandlerForTest(t)
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	w := httptest.NewRecorder()
	ph.RenderTestPage(w, req, "dashboard", handlers.TemplateData{Version: "0.0.0-test"})
	ct := w.Header().Get("Content-Type")
	if !strings.HasPrefix(ct, "text/html") {
		t.Errorf("Content-Type = %q, want text/html prefix", ct)
	}
}

func TestRenderPageHTMXFragmentContainsContent(t *testing.T) {
	t.Parallel()
	ph := handlers.NewPageHandlerForTest(t)
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set("HX-Request", "true")
	w := httptest.NewRecorder()
	ph.RenderTestPage(w, req, "dashboard", handlers.TemplateData{Version: "0.0.0-test"})
	// The dashboard-content stub emits a div with id printer-grid
	if !strings.Contains(w.Body.String(), "printer-grid") {
		t.Errorf("HTMX fragment must contain content, got: %q", w.Body.String())
	}
}

func TestRenderPageNavLinkInLayout(t *testing.T) {
	t.Parallel()
	ph := handlers.NewPageHandlerForTest(t)
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	w := httptest.NewRecorder()
	ph.RenderTestPage(w, req, "dashboard", handlers.TemplateData{Version: "0.0.0-test", ActiveNav: "dashboard"})
	body := w.Body.String()
	if !strings.Contains(body, "/static/app.css") {
		t.Error("layout must link to /static/app.css")
	}
}
