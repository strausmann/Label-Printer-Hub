package handlers_test

// admin_printers_test.go testet die Admin-Drucker-Handler.
//
// Das Pattern folgt csrf_test.go: ein httptest.Server simuliert das Backend,
// NewPageHandlerFromURL erzeugt einen Handler mit Stub-Templates und echtem
// HTTP-Client der auf den Mock-Backend zeigt.
//
// Für Handlers die chi-URL-Parameter nutzen, werden die *WithSlug-Varianten
// direkt aufgerufen (analog zu PrinterDetailWithID in printer_test.go).

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"

	"github.com/go-chi/chi/v5"
	"github.com/strausmann/label-printer-hub/frontend/internal/handlers"
)

// printerJSON ist ein minimaler gültiger Drucker-JSON für Mock-Antworten.
const printerJSON = `{
	"id": "00000000-0000-0000-0000-000000000001",
	"name": "Bürodrucker Nord",
	"slug": "buero-nord",
	"model": "QL-810W",
	"backend": "brother_ql",
	"connection": {"host": "192.0.2.10", "port": 9100},
	"queue": {"timeout_s": 30},
	"cut_defaults": {"half_cut": false},
	"enabled": true,
	"created_at": "2026-01-01T00:00:00",
	"updated_at": "2026-01-01T00:00:00"
}`

const printerJSON2 = `{
	"id": "00000000-0000-0000-0000-000000000002",
	"name": "Lagerdrucker Süd",
	"slug": "lager-sued",
	"model": "PT-P710BT",
	"backend": "ptouch",
	"connection": {"host": "192.0.2.11", "port": 9101},
	"queue": {"timeout_s": 60},
	"cut_defaults": {"half_cut": true},
	"enabled": false,
	"created_at": "2026-01-02T00:00:00",
	"updated_at": "2026-01-02T00:00:00"
}`

// withChiParam setzt einen chi-URL-Parameter im Request-Kontext.
// Wird benötigt weil httptest.NewRequest keinen chi-Router durchläuft.
func withChiParam(r *http.Request, key, value string) *http.Request {
	rctx := chi.NewRouteContext()
	rctx.URLParams.Add(key, value)
	return r.WithContext(context.WithValue(r.Context(), chi.RouteCtxKey, rctx))
}

// newPrinterBackend erstellt einen httptest.Server der /api/v1/admin/printers
// mit minimalen gültigen Antworten beantwortet.
func newPrinterBackend(t *testing.T) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch {
		// Liste aller Drucker
		case r.URL.Path == "/api/v1/admin/printers" && r.Method == http.MethodGet:
			fmt.Fprintf(w, `[%s, %s]`, printerJSON, printerJSON2)

		// Drucker anlegen
		case r.URL.Path == "/api/v1/admin/printers" && r.Method == http.MethodPost:
			w.WriteHeader(http.StatusCreated)
			fmt.Fprint(w, printerJSON)

		// Einzelner Drucker per Slug
		case r.URL.Path == "/api/v1/admin/printers/buero-nord" && r.Method == http.MethodGet:
			fmt.Fprint(w, printerJSON)

		// Drucker aktualisieren
		case r.URL.Path == "/api/v1/admin/printers/buero-nord" && r.Method == http.MethodPut:
			fmt.Fprint(w, printerJSON)

		// Drucker deaktivieren
		case r.URL.Path == "/api/v1/admin/printers/buero-nord/disable" && r.Method == http.MethodPost:
			disabledJSON := strings.Replace(printerJSON, `"enabled": true`, `"enabled": false`, 1)
			fmt.Fprint(w, disabledJSON)

		// Drucker aktivieren
		case r.URL.Path == "/api/v1/admin/printers/lager-sued/enable" && r.Method == http.MethodPost:
			enabledJSON := strings.Replace(printerJSON2, `"enabled": false`, `"enabled": true`, 1)
			fmt.Fprint(w, enabledJSON)

		// Nicht-gefundener Drucker
		case r.URL.Path == "/api/v1/admin/printers/nicht-vorhanden" && r.Method == http.MethodGet:
			w.WriteHeader(http.StatusNotFound)
			fmt.Fprint(w, `{"detail": "not found"}`)

		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(srv.Close)
	return srv
}

// newPrinterBackendConflict erstellt einen Backend-Mock der beim POST 409 zurückgibt.
func newPrinterBackendConflict(t *testing.T) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.URL.Path == "/api/v1/admin/printers" && r.Method == http.MethodPost {
			w.WriteHeader(http.StatusConflict)
			fmt.Fprint(w, `{"detail": {"error_code": "duplicate_slug", "error_message": "Slug bereits vergeben."}}`)
			return
		}
		http.NotFound(w, r)
	}))
	t.Cleanup(srv.Close)
	return srv
}

// ---------------------------------------------------------------------------
// ListPrintersPage
// ---------------------------------------------------------------------------

// TestListPrintersPage_RendertTabelleMitZweiDruckern prüft dass die Liste
// mit zwei Druckern korrekt gerendert wird.
func TestListPrintersPage_RendertTabelleMitZweiDruckern(t *testing.T) {
	t.Parallel()
	backend := newPrinterBackend(t)
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)

	req := httptest.NewRequest(http.MethodGet, "/admin/printers", nil)
	w := httptest.NewRecorder()
	ph.ListPrintersPage(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("ListPrintersPage: Status %d, erwartet 200", w.Code)
	}
}

// TestListPrintersPage_InkludiertDisabled prüft den include_disabled Query-Parameter.
func TestListPrintersPage_InkludiertDisabled(t *testing.T) {
	t.Parallel()

	var capturedQuery string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/admin/printers" {
			capturedQuery = r.URL.RawQuery
			w.Header().Set("Content-Type", "application/json")
			fmt.Fprintf(w, `[%s]`, printerJSON2)
		} else {
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(srv.Close)

	ph := handlers.NewPageHandlerFromURL(t, srv.URL)
	req := httptest.NewRequest(http.MethodGet, "/admin/printers?include_disabled=true", nil)
	w := httptest.NewRecorder()
	ph.ListPrintersPage(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("ListPrintersPage?include_disabled: Status %d, erwartet 200", w.Code)
	}
	if !strings.Contains(capturedQuery, "include_disabled=true") {
		t.Errorf("Backend-Request hat include_disabled nicht weitergeleitet, Query: %q", capturedQuery)
	}
}

// ---------------------------------------------------------------------------
// NewPrinterPage
// ---------------------------------------------------------------------------

// TestNewPrinterPage_RendertFormular prüft dass GET /admin/printers/new 200 liefert.
func TestNewPrinterPage_RendertFormular(t *testing.T) {
	t.Parallel()
	ph := handlers.NewPageHandlerForTest(t)

	req := httptest.NewRequest(http.MethodGet, "/admin/printers/new", nil)
	w := httptest.NewRecorder()
	ph.NewPrinterPage(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("NewPrinterPage: Status %d, erwartet 200", w.Code)
	}
}

// ---------------------------------------------------------------------------
// CreatePrinter
// ---------------------------------------------------------------------------

// TestCreatePrinter_HappyPath_Redirect303 prüft dass ein gültiger POST
// zu einem Redirect auf die Detail-Seite führt.
func TestCreatePrinter_HappyPath_Redirect303(t *testing.T) {
	t.Parallel()
	backend := newPrinterBackend(t)
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)

	form := url.Values{
		"name":                  {"Bürodrucker Nord"},
		"slug":                  {"buero-nord"},
		"model":                 {"QL-810W"},
		"backend":               {"brother_ql"},
		"host":                  {"192.0.2.10"},
		"port":                  {"9100"},
		"queue_timeout_s":       {"30"},
		"cut_defaults_half_cut": {""},
		"snmp_discover":         {""},
		"snmp_community":        {"public"},
	}
	req := httptest.NewRequest(http.MethodPost, "/admin/printers/new", strings.NewReader(form.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	w := httptest.NewRecorder()
	ph.CreatePrinter(w, req)

	if w.Code != http.StatusSeeOther {
		t.Errorf("CreatePrinter Happy-Path: Status %d, erwartet 303", w.Code)
	}
	loc := w.Header().Get("Location")
	if !strings.Contains(loc, "/admin/printers/buero-nord") {
		t.Errorf("CreatePrinter Redirect-Ziel: %q, erwartet /admin/printers/buero-nord", loc)
	}
}

// TestCreatePrinter_ValidationError_NameLeer prüft dass bei fehlenden
// Pflichtfeldern (name leer) das Formular mit Fehlermeldung zurückgerendert wird.
func TestCreatePrinter_ValidationError_NameLeer(t *testing.T) {
	t.Parallel()
	ph := handlers.NewPageHandlerForTest(t)

	form := url.Values{
		"name":    {""}, // Pflichtfeld leer
		"slug":    {"buero-nord"},
		"model":   {"QL-810W"},
		"backend": {"brother_ql"},
		"host":    {"192.0.2.10"},
		"port":    {"9100"},
	}
	req := httptest.NewRequest(http.MethodPost, "/admin/printers/new", strings.NewReader(form.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	w := httptest.NewRecorder()
	ph.CreatePrinter(w, req)

	// Formular wird erneut gerendert (200) — kein Redirect
	if w.Code == http.StatusSeeOther {
		t.Error("CreatePrinter bei leerem name: darf keinen Redirect (303) liefern")
	}
	if w.Code != http.StatusOK {
		t.Errorf("CreatePrinter Validation-Error: Status %d, erwartet 200", w.Code)
	}
}

// TestCreatePrinter_ValidationError_InvalidQueueTimeout prüft Ablehnung bei Timeout=0.
func TestCreatePrinter_ValidationError_InvalidQueueTimeout(t *testing.T) {
	t.Parallel()
	ph := handlers.NewPageHandlerForTest(t)

	form := url.Values{
		"name":            {"Testdrucker"},
		"slug":            {"testdrucker"},
		"model":           {"QL-810W"},
		"backend":         {"brother_ql"},
		"host":            {"192.0.2.10"},
		"port":            {"9100"},
		"queue_timeout_s": {"0"}, // Ungültig: muss 1-3600 sein
	}
	req := httptest.NewRequest(http.MethodPost, "/admin/printers/new", strings.NewReader(form.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	w := httptest.NewRecorder()
	ph.CreatePrinter(w, req)

	if w.Code == http.StatusSeeOther {
		t.Error("CreatePrinter bei queue_timeout_s=0: darf keinen Redirect liefern")
	}
}

// TestCreatePrinter_ValidationError_InvalidPort prüft Ablehnung bei Port=0.
func TestCreatePrinter_ValidationError_InvalidPort(t *testing.T) {
	t.Parallel()
	ph := handlers.NewPageHandlerForTest(t)

	form := url.Values{
		"name":    {"Testdrucker"},
		"slug":    {"testdrucker"},
		"model":   {"QL-810W"},
		"backend": {"brother_ql"},
		"host":    {"192.0.2.10"},
		"port":    {"0"}, // Ungültig: muss 1-65535 sein
	}
	req := httptest.NewRequest(http.MethodPost, "/admin/printers/new", strings.NewReader(form.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	w := httptest.NewRecorder()
	ph.CreatePrinter(w, req)

	if w.Code == http.StatusSeeOther {
		t.Error("CreatePrinter bei Port=0: darf keinen Redirect liefern")
	}
}

// TestCreatePrinter_BackendConflict_FormRerender prüft dass ein 409 vom Backend
// (Slug bereits vergeben) das Formular mit Fehlermeldung zurückrendert.
func TestCreatePrinter_BackendConflict_FormRerender(t *testing.T) {
	t.Parallel()
	backend := newPrinterBackendConflict(t)
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)

	form := url.Values{
		"name":    {"Duplikat"},
		"slug":    {"buero-nord"},
		"model":   {"QL-810W"},
		"backend": {"brother_ql"},
		"host":    {"192.0.2.10"},
		"port":    {"9100"},
	}
	req := httptest.NewRequest(http.MethodPost, "/admin/printers/new", strings.NewReader(form.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	w := httptest.NewRecorder()
	ph.CreatePrinter(w, req)

	// Formular mit Fehlermeldung, kein Redirect
	if w.Code == http.StatusSeeOther {
		t.Error("CreatePrinter bei 409: darf keinen Redirect liefern")
	}
}

// ---------------------------------------------------------------------------
// PrinterDetailPage
// ---------------------------------------------------------------------------

// TestPrinterDetailAdminPage_HappyPath prüft dass die Admin-Detail-Seite für einen
// vorhandenen Drucker korrekt gerendert wird.
func TestPrinterDetailAdminPage_HappyPath(t *testing.T) {
	t.Parallel()
	backend := newPrinterBackend(t)
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)

	req := httptest.NewRequest(http.MethodGet, "/admin/printers/buero-nord", nil)
	w := httptest.NewRecorder()
	ph.PrinterDetailPageWithSlug(w, req, "buero-nord")

	if w.Code != http.StatusOK {
		t.Errorf("PrinterDetailPage: Status %d, erwartet 200", w.Code)
	}
}

// TestPrinterDetailAdminPage_NotFound prüft dass ein 404 vom Backend auch
// als 404 an den Client weitergeleitet wird.
func TestPrinterDetailAdminPage_NotFound(t *testing.T) {
	t.Parallel()
	backend := newPrinterBackend(t)
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)

	req := httptest.NewRequest(http.MethodGet, "/admin/printers/nicht-vorhanden", nil)
	w := httptest.NewRecorder()
	ph.PrinterDetailPageWithSlug(w, req, "nicht-vorhanden")

	if w.Code != http.StatusNotFound {
		t.Errorf("PrinterDetailPage 404: Status %d, erwartet 404", w.Code)
	}
}

// ---------------------------------------------------------------------------
// EditPrinterPage
// ---------------------------------------------------------------------------

// TestEditPrinterPage_NotFound prüft 404 bei fehlendem Drucker.
func TestEditPrinterPage_NotFound(t *testing.T) {
	t.Parallel()
	backend := newPrinterBackend(t)
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)

	req := httptest.NewRequest(http.MethodGet, "/admin/printers/nicht-vorhanden/edit", nil)
	w := httptest.NewRecorder()
	ph.EditPrinterPageWithSlug(w, req, "nicht-vorhanden")

	if w.Code != http.StatusNotFound {
		t.Errorf("EditPrinterPage nicht-vorhanden: Status %d, erwartet 404", w.Code)
	}
}

// TestEditPrinterPage_HappyPath prüft dass GET /admin/printers/{id}/edit 200 liefert.
func TestEditPrinterPage_HappyPath(t *testing.T) {
	t.Parallel()
	backend := newPrinterBackend(t)
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)

	req := httptest.NewRequest(http.MethodGet, "/admin/printers/buero-nord/edit", nil)
	w := httptest.NewRecorder()
	ph.EditPrinterPageWithSlug(w, req, "buero-nord")

	if w.Code != http.StatusOK {
		t.Errorf("EditPrinterPage: Status %d, erwartet 200", w.Code)
	}
}

// ---------------------------------------------------------------------------
// UpdatePrinter
// ---------------------------------------------------------------------------

// TestUpdatePrinter_HappyPath_Redirect prüft Redirect nach erfolgreichem PUT.
func TestUpdatePrinter_HappyPath_Redirect(t *testing.T) {
	t.Parallel()
	backend := newPrinterBackend(t)
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)

	form := url.Values{
		"name":                  {"Bürodrucker Nord Neu"},
		"host":                  {"192.0.2.10"},
		"port":                  {"9100"},
		"queue_timeout_s":       {"30"},
		"cut_defaults_half_cut": {""},
	}
	req := httptest.NewRequest(http.MethodPost, "/admin/printers/buero-nord/edit", strings.NewReader(form.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	w := httptest.NewRecorder()
	ph.UpdatePrinterWithSlug(w, req, "buero-nord")

	if w.Code != http.StatusSeeOther {
		t.Errorf("UpdatePrinter Happy-Path: Status %d, erwartet 303", w.Code)
	}
	loc := w.Header().Get("Location")
	if !strings.Contains(loc, "buero-nord") {
		t.Errorf("UpdatePrinter Redirect: %q enthält nicht 'buero-nord'", loc)
	}
}

// TestUpdatePrinter_BackendFehler_FormRerender prüft Formular-Rerender bei Backend-Fehler.
func TestUpdatePrinter_BackendFehler_FormRerender(t *testing.T) {
	t.Parallel()

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
		fmt.Fprint(w, `{"detail": "not found"}`)
	}))
	t.Cleanup(srv.Close)

	ph := handlers.NewPageHandlerFromURL(t, srv.URL)
	form := url.Values{
		"name": {"Drucker"},
		"host": {"192.0.2.10"},
		"port": {"9100"},
	}
	req := httptest.NewRequest(http.MethodPost, "/admin/printers/nicht-vorhanden/edit", strings.NewReader(form.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	w := httptest.NewRecorder()
	ph.UpdatePrinterWithSlug(w, req, "nicht-vorhanden")

	if w.Code == http.StatusSeeOther {
		t.Error("UpdatePrinter bei Backend-Fehler: darf keinen Redirect liefern")
	}
}

// TestUpdatePrinter_ValidationError_PortZuGross prüft Formular-Rerender
// bei ungültigem Port > 65535.
func TestUpdatePrinter_ValidationError_PortZuGross(t *testing.T) {
	t.Parallel()
	ph := handlers.NewPageHandlerForTest(t)

	form := url.Values{
		"name": {"Drucker"},
		"host": {"192.0.2.10"},
		"port": {"99999"}, // Ungültig: > 65535
	}
	req := httptest.NewRequest(http.MethodPost, "/admin/printers/buero-nord/edit", strings.NewReader(form.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	w := httptest.NewRecorder()
	ph.UpdatePrinterWithSlug(w, req, "buero-nord")

	if w.Code == http.StatusSeeOther {
		t.Error("UpdatePrinter bei Port=99999: darf keinen Redirect liefern")
	}
}

// ---------------------------------------------------------------------------
// DisablePrinterConfirmPage + DisablePrinter
// ---------------------------------------------------------------------------

// TestDisablePrinterConfirmPage_RendertBestaetigungsseite prüft GET /admin/printers/{id}/disable.
func TestDisablePrinterConfirmPage_RendertBestaetigungsseite(t *testing.T) {
	t.Parallel()
	backend := newPrinterBackend(t)
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)

	req := httptest.NewRequest(http.MethodGet, "/admin/printers/buero-nord/disable", nil)
	w := httptest.NewRecorder()
	ph.DisablePrinterConfirmPageWithSlug(w, req, "buero-nord")

	if w.Code != http.StatusOK {
		t.Errorf("DisablePrinterConfirmPage: Status %d, erwartet 200", w.Code)
	}
}

// TestDisablePrinter_CallsBackendUndRedirect prüft POST disable → Backend-Aufruf → Redirect zur Liste.
func TestDisablePrinter_CallsBackendUndRedirect(t *testing.T) {
	t.Parallel()

	var disableCalled bool
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.URL.Path == "/api/v1/admin/printers/buero-nord/disable" && r.Method == http.MethodPost {
			disableCalled = true
			disabledJSON := strings.Replace(printerJSON, `"enabled": true`, `"enabled": false`, 1)
			fmt.Fprint(w, disabledJSON)
			return
		}
		http.NotFound(w, r)
	}))
	t.Cleanup(srv.Close)

	ph := handlers.NewPageHandlerFromURL(t, srv.URL)
	req := httptest.NewRequest(http.MethodPost, "/admin/printers/buero-nord/disable", nil)
	w := httptest.NewRecorder()
	ph.DisablePrinterWithSlug(w, req, "buero-nord")

	if !disableCalled {
		t.Error("DisablePrinter: Backend-Endpunkt /disable wurde nicht aufgerufen")
	}
	if w.Code != http.StatusSeeOther {
		t.Errorf("DisablePrinter: Status %d, erwartet 303", w.Code)
	}
	loc := w.Header().Get("Location")
	if loc != "/admin/printers" {
		t.Errorf("DisablePrinter Redirect: %q, erwartet /admin/printers", loc)
	}
}

// ---------------------------------------------------------------------------
// EnablePrinter
// ---------------------------------------------------------------------------

// TestDisablePrinterConfirmPage_NotFound prüft 404-Fehler wenn Drucker nicht gefunden.
func TestDisablePrinterConfirmPage_NotFound(t *testing.T) {
	t.Parallel()
	backend := newPrinterBackend(t)
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)

	req := httptest.NewRequest(http.MethodGet, "/admin/printers/nicht-vorhanden/disable", nil)
	w := httptest.NewRecorder()
	ph.DisablePrinterConfirmPageWithSlug(w, req, "nicht-vorhanden")

	if w.Code != http.StatusNotFound {
		t.Errorf("DisablePrinterConfirmPage nicht-vorhanden: Status %d, erwartet 404", w.Code)
	}
}

// TestDisablePrinter_BackendFehler_RendertError prüft Fehlerseite bei Backend-Fehler.
func TestDisablePrinter_BackendFehler_RendertError(t *testing.T) {
	t.Parallel()

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusConflict)
		fmt.Fprint(w, `{"detail": "already_disabled"}`)
	}))
	t.Cleanup(srv.Close)

	ph := handlers.NewPageHandlerFromURL(t, srv.URL)
	req := httptest.NewRequest(http.MethodPost, "/admin/printers/buero-nord/disable", nil)
	w := httptest.NewRecorder()
	ph.DisablePrinterWithSlug(w, req, "buero-nord")

	// Kein Redirect bei Fehler
	if w.Code == http.StatusSeeOther {
		t.Error("DisablePrinter bei Backend-Fehler: darf keinen Redirect liefern")
	}
}

// TestEnablePrinter_BackendFehler_RendertError prüft Fehlerseite bei Backend-Fehler.
func TestEnablePrinter_BackendFehler_RendertError(t *testing.T) {
	t.Parallel()

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusConflict)
		fmt.Fprint(w, `{"detail": "already_enabled"}`)
	}))
	t.Cleanup(srv.Close)

	ph := handlers.NewPageHandlerFromURL(t, srv.URL)
	req := httptest.NewRequest(http.MethodPost, "/admin/printers/buero-nord/enable", nil)
	w := httptest.NewRecorder()
	ph.EnablePrinterWithSlug(w, req, "buero-nord")

	// Kein Redirect bei Fehler
	if w.Code == http.StatusSeeOther {
		t.Error("EnablePrinter bei Backend-Fehler: darf keinen Redirect liefern")
	}
}

// TestListPrintersPage_BackendFehler_RendertError prüft Fehlerseite bei Backend-Ausfall.
func TestListPrintersPage_BackendFehler_RendertError(t *testing.T) {
	t.Parallel()

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		fmt.Fprint(w, `{"error": "internal"}`)
	}))
	t.Cleanup(srv.Close)

	ph := handlers.NewPageHandlerFromURL(t, srv.URL)
	req := httptest.NewRequest(http.MethodGet, "/admin/printers", nil)
	w := httptest.NewRecorder()
	ph.ListPrintersPage(w, req)

	if w.Code != http.StatusServiceUnavailable {
		t.Errorf("ListPrintersPage Backend-Fehler: Status %d, erwartet 503", w.Code)
	}
}

// TestEnablePrinter_CallsBackendUndRedirectZuDetail prüft POST enable → Backend → Redirect zum Detail.
func TestEnablePrinter_CallsBackendUndRedirectZuDetail(t *testing.T) {
	t.Parallel()

	var enableCalled bool
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.URL.Path == "/api/v1/admin/printers/lager-sued/enable" && r.Method == http.MethodPost {
			enableCalled = true
			enabledJSON := strings.Replace(printerJSON2, `"enabled": false`, `"enabled": true`, 1)
			fmt.Fprint(w, enabledJSON)
			return
		}
		http.NotFound(w, r)
	}))
	t.Cleanup(srv.Close)

	ph := handlers.NewPageHandlerFromURL(t, srv.URL)
	req := httptest.NewRequest(http.MethodPost, "/admin/printers/lager-sued/enable", nil)
	w := httptest.NewRecorder()
	ph.EnablePrinterWithSlug(w, req, "lager-sued")

	if !enableCalled {
		t.Error("EnablePrinter: Backend-Endpunkt /enable wurde nicht aufgerufen")
	}
	if w.Code != http.StatusSeeOther {
		t.Errorf("EnablePrinter: Status %d, erwartet 303", w.Code)
	}
	loc := w.Header().Get("Location")
	if !strings.Contains(loc, "lager-sued") {
		t.Errorf("EnablePrinter Redirect: %q enthält nicht 'lager-sued'", loc)
	}
}
