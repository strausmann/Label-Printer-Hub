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

const templateKey = "snipeit/asset"

// templateDetailBackend returns a mock backend serving /api/templates and
// optionally a /api/render/preview endpoint.
func templateDetailBackend(t *testing.T, servePreview bool) *httptest.Server {
	t.Helper()
	now := time.Now().Format(time.RFC3339)
	tpls := []map[string]any{
		{
			"id": "aaaaaaaa-0000-0000-0000-000000000001", "key": templateKey,
			"name": "Snipe-IT Asset", "app": "snipeit", "printer_model": "pt_series",
			"tape_width_mm": 12, "schema_version": 1,
			"source":     "name: Snipe-IT Asset\nwidth: 12\n",
			"definition": map[string]any{}, "created_at": now, "updated_at": now,
		},
	}
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/api/templates":
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(tpls)
		case r.URL.Path == "/api/render/preview" && servePreview:
			// Return a minimal 1×1 PNG so the base64 embed path is exercised.
			// Smallest valid PNG: 67 bytes.
			w.Header().Set("Content-Type", "image/png")
			w.Write(minimalPNG())
		default:
			http.NotFound(w, r)
		}
	}))
}

// minimalPNG returns the bytes of a 1×1 transparent PNG for preview testing.
func minimalPNG() []byte {
	// Minimal valid PNG (1×1 pixel, RGBA, generated offline).
	return []byte{
		0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, // PNG signature
		0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52, // IHDR chunk
		0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
		0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
		0xde, 0x00, 0x00, 0x00, 0x0c, 0x49, 0x44, 0x41, // IDAT chunk
		0x54, 0x08, 0xd7, 0x63, 0xf8, 0xcf, 0xc0, 0x00,
		0x00, 0x00, 0x02, 0x00, 0x01, 0xe2, 0x21, 0xbc,
		0x33, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4e, // IEND chunk
		0x44, 0xae, 0x42, 0x60, 0x82,
	}
}

func TestTemplateDetailOK(t *testing.T) {
	t.Parallel()
	backend := templateDetailBackend(t, false)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/templates/"+templateKey, nil)
	req.Header.Set("HX-Request", "true")
	w := httptest.NewRecorder()
	ph.TemplateDetailWithKey(w, req, templateKey)
	if w.Code != http.StatusOK {
		t.Fatalf("status %d, body: %s", w.Code, w.Body.String())
	}
	if !strings.Contains(w.Body.String(), "template-detail") {
		t.Errorf("body missing 'template-detail', got: %s", w.Body.String())
	}
}

func TestTemplateDetailFullPage(t *testing.T) {
	t.Parallel()
	backend := templateDetailBackend(t, false)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/templates/"+templateKey, nil)
	w := httptest.NewRecorder()
	ph.TemplateDetailWithKey(w, req, templateKey)
	if w.Code != http.StatusOK {
		t.Fatalf("status %d, body: %s", w.Code, w.Body.String())
	}
	if !strings.Contains(w.Body.String(), "<!DOCTYPE html>") {
		t.Error("full page must have DOCTYPE")
	}
}

func TestTemplateDetailNotFound(t *testing.T) {
	t.Parallel()
	backend := templateDetailBackend(t, false)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	w := httptest.NewRecorder()
	ph.TemplateDetailWithKey(w, httptest.NewRequest(http.MethodGet, "/templates/no-such", nil), "no-such")
	if w.Code != http.StatusNotFound {
		t.Errorf("status %d, want 404", w.Code)
	}
}

func TestTemplateDetailPreviewTimeout(t *testing.T) {
	t.Parallel()
	// Backend serves templates but render/preview is missing → placeholder used.
	backend := templateDetailBackend(t, false)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/templates/"+templateKey, nil)
	req.Header.Set("HX-Request", "true")
	w := httptest.NewRecorder()
	ph.TemplateDetailWithKey(w, req, templateKey)
	// Should still return 200 — placeholder is used on preview failure.
	if w.Code != http.StatusOK {
		t.Fatalf("status %d, body: %s", w.Code, w.Body.String())
	}
}

// TestTemplateDetailPreviewDataURLNotEscaped is the regression test for
// issue #87: html/template was escaping the `data:image/png;base64,...` URL
// in src= attributes to `#ZgotmplZ` because PreviewURI was typed `string`
// (default url-sanitisation kicks in). After the fix PreviewURI is
// template.URL, marking it as already-safe so it round-trips through the
// rendered HTML unmodified.
func TestTemplateDetailPreviewDataURLNotEscaped(t *testing.T) {
	t.Parallel()
	backend := templateDetailBackend(t, true) // serve preview PNG
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/templates/"+templateKey, nil)
	req.Header.Set("HX-Request", "true")
	w := httptest.NewRecorder()
	ph.TemplateDetailWithKey(w, req, templateKey)
	if w.Code != http.StatusOK {
		t.Fatalf("status %d, body: %s", w.Code, w.Body.String())
	}
	body := w.Body.String()
	if !strings.Contains(body, "data:image/png;base64,") {
		t.Errorf("preview src must contain data:image/png;base64 URL, got: %s", body)
	}
	if strings.Contains(body, "ZgotmplZ") {
		t.Errorf("preview src is html-template-escaped (ZgotmplZ marker); PreviewURI must use template.URL type, got: %s", body)
	}
}

func TestTemplateDetailBackendError(t *testing.T) {
	t.Parallel()
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "internal", http.StatusInternalServerError)
	}))
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	w := httptest.NewRecorder()
	ph.TemplateDetailWithKey(w, httptest.NewRequest(http.MethodGet, "/templates/x", nil), "x")
	if w.Code != http.StatusServiceUnavailable {
		t.Errorf("status %d, want 503", w.Code)
	}
}
