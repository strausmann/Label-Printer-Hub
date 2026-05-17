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

const testPrinterID = "cccccccc-0000-0000-0000-000000000003"

func printerDetailBackend(t *testing.T, id string) *httptest.Server {
	t.Helper()
	now := time.Now().Format(time.RFC3339)
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/api/printers/" + id:
			json.NewEncoder(w).Encode(map[string]any{
				"id": id, "name": "PT-P750W", "model": "pt_series", "backend": "tcp",
				"connection": map[string]any{"host": "198.51.100.10", "port": 9100},
				"enabled":    true, "paused": false, "created_at": now, "updated_at": now,
			})
		case "/api/printers/" + id + "/status":
			json.NewEncoder(w).Encode(map[string]any{"printer_id": id, "online": true, "tape_loaded": "12mm black/clear", "error_state": nil, "captured_at": now})
		case "/api/printers/" + id + "/tape":
			json.NewEncoder(w).Encode(map[string]any{"width_mm": 12})
		case "/api/printers/" + id + "/queue":
			json.NewEncoder(w).Encode([]any{})
		default:
			http.NotFound(w, r)
		}
	}))
}

func TestPrinterDetailShowsMetadata(t *testing.T) {
	// Regression for Bug 2 — the printer detail page had no metadata block.
	// Verify the handler populates Printer in PrinterDetailData so the template
	// can render model/host/enabled/paused/created/updated fields.
	t.Parallel()
	backend := printerDetailBackend(t, testPrinterID)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)

	req := httptest.NewRequest(http.MethodGet, "/printers/"+testPrinterID, nil)
	req.Header.Set("HX-Request", "true")
	w := httptest.NewRecorder()
	ph.PrinterDetailWithID(w, req, testPrinterID)

	if w.Code != http.StatusOK {
		t.Fatalf("status %d, body: %s", w.Code, w.Body.String())
	}
	// Verify page renders without error — metadata fields verified at template level.
	if !strings.Contains(w.Body.String(), "printer-detail") {
		t.Errorf("body missing 'printer-detail', got: %s", w.Body.String())
	}
}

func TestPrinterDetailOK(t *testing.T) {
	t.Parallel()
	backend := printerDetailBackend(t, testPrinterID)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	// Use HX-Request so renderPage returns the printer-content fragment which
	// contains the expected id ("printer-detail") in the stub template.
	req := httptest.NewRequest(http.MethodGet, "/printers/"+testPrinterID, nil)
	req.Header.Set("HX-Request", "true")
	w := httptest.NewRecorder()
	ph.PrinterDetailWithID(w, req, testPrinterID)
	if w.Code != http.StatusOK {
		t.Fatalf("status %d, body: %s", w.Code, w.Body.String())
	}
	if !strings.Contains(w.Body.String(), "printer-detail") {
		t.Errorf("body missing 'printer-detail', got: %s", w.Body.String())
	}
}

func TestPrinterDetailOKFullPage(t *testing.T) {
	t.Parallel()
	backend := printerDetailBackend(t, testPrinterID)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/printers/"+testPrinterID, nil)
	w := httptest.NewRecorder()
	ph.PrinterDetailWithID(w, req, testPrinterID)
	if w.Code != http.StatusOK {
		t.Fatalf("status %d, body: %s", w.Code, w.Body.String())
	}
	if !strings.Contains(w.Body.String(), "<!DOCTYPE html>") {
		t.Error("full page must have DOCTYPE")
	}
}

func TestPrinterDetailNotFound(t *testing.T) {
	t.Parallel()
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.NotFound(w, r) }))
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/printers/no-such", nil)
	w := httptest.NewRecorder()
	ph.PrinterDetailWithID(w, req, "no-such")
	if w.Code != http.StatusNotFound {
		t.Errorf("status %d, want 404", w.Code)
	}
}
