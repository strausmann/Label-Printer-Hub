package api_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/strausmann/label-printer-hub/frontend/internal/api"
)

func TestListPrintersHitsCorrectPath(t *testing.T) {
	t.Parallel()
	called := false
	now := time.Now().Format(time.RFC3339)
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/printers" {
			called = true
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode([]map[string]any{
				{"id": "aaaaaaaa-0000-0000-0000-000000000001", "name": "PT-P750W",
					"model": "pt_series", "backend": "tcp",
					"connection": map[string]any{"host": "198.51.100.10", "port": 9100},
					"enabled":    true, "paused": false, "created_at": now, "updated_at": now},
			})
		} else {
			http.NotFound(w, r)
		}
	}))
	defer backend.Close()

	printers, err := api.NewHubClient(backend.URL).ListPrinters(context.Background())
	if err != nil {
		t.Fatalf("ListPrinters: %v", err)
	}
	if !called {
		t.Error("GET /api/printers not called")
	}
	if len(printers) != 1 || printers[0].Name != "PT-P750W" {
		t.Errorf("unexpected result: %+v", printers)
	}
}

func TestGetJobReturnsErrNotFound(t *testing.T) {
	t.Parallel()
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.NotFound(w, r)
	}))
	defer backend.Close()
	_, err := api.NewHubClient(backend.URL).GetJob(context.Background(), "no-such-job")
	if err != api.ErrNotFound {
		t.Errorf("err = %v, want ErrNotFound", err)
	}
}

func TestListTemplatesFiltersByApp(t *testing.T) {
	t.Parallel()
	now := time.Now().Format(time.RFC3339)
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/templates" {
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode([]map[string]any{
				{"id": "cccccccc-0000-0000-0000-000000000001", "key": "snipeit_asset",
					"name": "Asset Label", "app": "snipeit", "printer_model": "pt_series",
					"tape_width_mm": 12, "schema_version": 1,
					"definition": map[string]any{}, "source": "",
					"created_at": now, "updated_at": now},
			})
		} else {
			http.NotFound(w, r)
		}
	}))
	defer backend.Close()

	templates, err := api.NewHubClient(backend.URL).ListTemplates(context.Background(), "snipeit")
	if err != nil {
		t.Fatalf("ListTemplates: %v", err)
	}
	if len(templates) != 1 || templates[0].Name != "Asset Label" {
		t.Errorf("unexpected result: %+v", templates)
	}
}

func TestLookupEntityReturnsErrUnsupportedApp(t *testing.T) {
	t.Parallel()
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, `{"detail":"unprocessable"}`, http.StatusUnprocessableEntity)
	}))
	defer backend.Close()
	_, err := api.NewHubClient(backend.URL).LookupEntity(context.Background(), "badapp", "123")
	if err != api.ErrUnsupportedApp {
		t.Errorf("err = %v, want ErrUnsupportedApp", err)
	}
}
