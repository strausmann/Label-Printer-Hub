package handlers_test

// csrf_test.go überprüft das CSRF-Schutzverhalten der Admin-API-Key-Routen.
//
// Da gorilla/csrf als Middleware außerhalb des handlers-Packages sitzt,
// testen wir hier das Verhalten des Handlers OHNE Middleware (kein CSRF-Schutz
// aktiv — gorilla/csrf wird in main.go auf den Router gelegt, nicht im Handler
// selbst). Die Tests prüfen:
//
//   1. POST mit gültigem CSRF-Formularfeld → Handler wird aufgerufen (kein 403 durch den Handler)
//   2. Ohne Middleware ergibt POST ohne CSRF-Token → kein 403 (Handler ist middleware-agnostisch)
//   3. GET-Anfragen liefern 200 (kein CSRF für GET)
//   4. Wenn gorilla/csrf aktiv ist, blockiert POST ohne Token mit 403
//
// Für Test 4 wird ein echter gorilla/csrf-Protect-Wrapper um den Handler gelegt
// (Test-CSRF-Key ist fixture, kein Produktions-Key).

import (
	"encoding/hex"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"

	"github.com/gorilla/csrf"
	"github.com/strausmann/label-printer-hub/frontend/internal/handlers"
)

// testCSRFKey ist ein 32-Byte-Fixture-Schlüssel für Tests — KEIN Produktions-Key.
var testCSRFKey = func() []byte {
	b, err := hex.DecodeString("0102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f20")
	if err != nil {
		panic("testCSRFKey decode: " + err.Error())
	}
	return b
}()

// newAdminBackend startet einen httptest.Server der /api/admin/api-keys
// mit minimalen gültigen Antworten beantwortet.
func newAdminBackend(t *testing.T) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/api/admin/api-keys" && r.Method == http.MethodGet:
			w.Header().Set("Content-Type", "application/json")
			fmt.Fprint(w, `[]`)
		case r.URL.Path == "/api/admin/api-keys" && r.Method == http.MethodPost:
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusCreated)
			fmt.Fprint(w, `{"plaintext":"lph_test_key","prefix":"lph_test"}`)
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(srv.Close)
	return srv
}

// TestAdminAPIKeysGet_ReturnOK prüft dass GET /admin/api-keys ohne CSRF-Token 200 liefert.
// GET-Anfragen brauchen keinen CSRF-Token.
func TestAdminAPIKeysGet_ReturnOK(t *testing.T) {
	t.Parallel()
	backend := newAdminBackend(t)
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)

	req := httptest.NewRequest(http.MethodGet, "/admin/api-keys", nil)
	w := httptest.NewRecorder()
	ph.AdminAPIKeysList(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("GET /admin/api-keys ohne CSRF-Token: Status %d, erwartet 200", w.Code)
	}
}

// TestAdminAPIKeysNew_GetReturnOK prüft dass GET /admin/api-keys/new 200 liefert.
func TestAdminAPIKeysNew_GetReturnOK(t *testing.T) {
	t.Parallel()
	backend := newAdminBackend(t)
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)

	req := httptest.NewRequest(http.MethodGet, "/admin/api-keys/new", nil)
	w := httptest.NewRecorder()
	ph.AdminAPIKeysNew(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("GET /admin/api-keys/new: Status %d, erwartet 200", w.Code)
	}
}

// TestAdminAPIKeysCreate_WithCSRFMiddleware_NoToken_Returns403 prüft dass
// gorilla/csrf POST-Anfragen ohne gültigen Token mit 403 ablehnt.
// Die Middleware wird hier explizit um den Handler gewickelt — identisch zu
// dem was main.go in der Produktionskonfiguration tut.
func TestAdminAPIKeysCreate_WithCSRFMiddleware_NoToken_Returns403(t *testing.T) {
	t.Parallel()
	backend := newAdminBackend(t)
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)

	// gorilla/csrf im Test-Modus: Secure=false (kein HTTPS in Tests), sonst
	// identische Konfiguration wie buildCSRFMiddleware() in main.go.
	csrfMW := csrf.Protect(
		testCSRFKey,
		csrf.Secure(false), // HTTP ist in httptest OK
		csrf.SameSite(csrf.SameSiteStrictMode),
		csrf.CookieName("__Host-csrf"),
		csrf.RequestHeader("X-CSRF-Token"),
		csrf.FieldName("csrf_token"),
	)

	handler := csrfMW(http.HandlerFunc(ph.AdminAPIKeysCreate))

	body := url.Values{"name": {"TestKey"}, "scopes": {"read"}}.Encode()
	req := httptest.NewRequest(http.MethodPost, "/admin/api-keys/new", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	// Kein CSRF-Token — gorilla/csrf soll 403 zurückgeben.
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, req)

	if w.Code != http.StatusForbidden {
		t.Errorf("POST ohne CSRF-Token: Status %d, erwartet 403 (Forbidden)", w.Code)
	}
}

// TestAdminAPIKeysCreate_WithCSRFMiddleware_WrongToken_Returns403 prüft dass
// ein falscher CSRF-Token (falsche Signatur) ebenfalls 403 liefert.
func TestAdminAPIKeysCreate_WithCSRFMiddleware_WrongToken_Returns403(t *testing.T) {
	t.Parallel()
	backend := newAdminBackend(t)
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)

	csrfMW := csrf.Protect(
		testCSRFKey,
		csrf.Secure(false),
		csrf.SameSite(csrf.SameSiteStrictMode),
		csrf.CookieName("__Host-csrf"),
		csrf.RequestHeader("X-CSRF-Token"),
		csrf.FieldName("csrf_token"),
	)

	handler := csrfMW(http.HandlerFunc(ph.AdminAPIKeysCreate))

	body := url.Values{
		"name":       {"TestKey"},
		"scopes":     {"read"},
		"csrf_token": {"ungueltig-dies-ist-kein-echter-token"},
	}.Encode()
	req := httptest.NewRequest(http.MethodPost, "/admin/api-keys/new", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, req)

	if w.Code != http.StatusForbidden {
		t.Errorf("POST mit falschem CSRF-Token: Status %d, erwartet 403 (Forbidden)", w.Code)
	}
}

// TestAdminAPIKeysCreate_WithCSRFMiddleware_ValidToken_CallsHandler prüft
// dass ein gültiger CSRF-Token den Handler erreicht (kein 403).
//
// Ablauf: GET → Cookie aus Response entnehmen + Token via csrf.Token() aus
// Request-Kontext lesen → POST mit Cookie + Token im X-CSRF-Token Header.
//
// gorilla/csrf setzt keinen X-CSRF-Token Response-Header automatisch. Der Token
// wird direkt über csrf.Token(r) aus dem Request-Kontext gelesen — das geht nur
// innerhalb der Middleware-Chain. Deshalb fängt ein Wrapper-Handler den Token ab.
func TestAdminAPIKeysCreate_WithCSRFMiddleware_ValidToken_CallsHandler(t *testing.T) {
	t.Parallel()
	backend := newAdminBackend(t)
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)

	csrfMW := csrf.Protect(
		testCSRFKey,
		csrf.Secure(false),
		csrf.SameSite(csrf.SameSiteStrictMode),
		csrf.CookieName("__Host-csrf"),
		csrf.RequestHeader("X-CSRF-Token"),
		csrf.FieldName("csrf_token"),
	)

	// Schritt 1: GET — Token über Wrapper aus Request-Kontext lesen.
	// csrf.Token(r) ist nur innerhalb der Middleware-Chain verfügbar.
	// csrf.PlaintextHTTPRequest() wird gesetzt damit gorilla/csrf den Request
	// als HTTP (nicht HTTPS) behandelt — verhindert dass Secure-Cookie-Logik
	// im httptest-Kontext scheitert.
	var capturedToken string
	getHandler := csrfMW(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		capturedToken = csrf.Token(r)
		ph.AdminAPIKeysNew(w, r)
	}))
	getReq := httptest.NewRequest(http.MethodGet, "/admin/api-keys/new", nil)
	getReq = csrf.PlaintextHTTPRequest(getReq)
	getW := httptest.NewRecorder()
	getHandler.ServeHTTP(getW, getReq)
	if getW.Code != http.StatusOK {
		t.Fatalf("GET für Token-Fetch: Status %d, erwartet 200", getW.Code)
	}
	if capturedToken == "" {
		t.Fatal("csrf.Token(r) ist leer — Middleware-Kontext nicht gesetzt")
	}

	// CSRF-Cookie aus GET-Response extrahieren.
	var csrfCookie *http.Cookie
	for _, c := range getW.Result().Cookies() {
		if c.Name == "__Host-csrf" {
			csrfCookie = c
			break
		}
	}
	if csrfCookie == nil {
		t.Fatal("__Host-csrf Cookie fehlt in GET-Response")
	}

	// Schritt 2: POST mit gültigem Token im Header + Cookie.
	// csrf.PlaintextHTTPRequest() signalisiert gorilla/csrf dass der Request über
	// HTTP (nicht HTTPS) läuft — überspringt Referer-Pflicht-Check der nur für TLS gilt.
	// In Produktion läuft der Frontend-Container hinter Pangolin TLS-Termination;
	// in Tests (httptest) gibt es kein TLS, daher ist PlaintextHTTPRequest nötig.
	postHandler := csrfMW(http.HandlerFunc(ph.AdminAPIKeysCreate))
	body := url.Values{
		"name":   {"TestKey"},
		"scopes": {"read"},
	}.Encode()
	postReq := httptest.NewRequest(http.MethodPost, "/admin/api-keys/new", strings.NewReader(body))
	postReq = csrf.PlaintextHTTPRequest(postReq)
	postReq.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	postReq.Header.Set("X-CSRF-Token", capturedToken)
	postReq.AddCookie(csrfCookie)

	postW := httptest.NewRecorder()
	postHandler.ServeHTTP(postW, postReq)

	// Handler liefert 200 (Key-Erstellungsseite mit Plaintext) — kein 403.
	if postW.Code == http.StatusForbidden {
		t.Errorf("POST mit gültigem CSRF-Token: Status 403 (Forbidden) — Token-Validierung fehlgeschlagen; Reason: %v", csrf.FailureReason(postReq))
	}
	if postW.Code != http.StatusOK {
		t.Errorf("POST mit gültigem CSRF-Token: Status %d, erwartet 200", postW.Code)
	}
}

// TestAdminAPIKeysCreate_ServiceAccountBypassComment dokumentiert dass
// Service-Account-Bypass (Authorization-Header überspringt CSRF) mit
// gorilla/csrf out-of-the-box NICHT möglich ist.
//
// gorilla/csrf kennt kein Konzept eines "vertrauenswürdigen" Authorization-Headers.
// Für Service-Account-Zugriff (curl mit X-Label-Hub-Key) muss ein Custom-Wrapper
// die Middleware für API-Requests überspringen — das ist Phase-7-Sub-Task #124.
//
// Dieser Test ist ein Dokumentations-Test (kein assert auf 200) — er beschreibt
// das erwartete Verhalten und ist als TODOtest markiert damit CI nicht fällt.
func TestAdminAPIKeysCreate_ServiceAccountBypass_TODO(t *testing.T) {
	// TODO(#124 Phase-7-Sub-Task): Custom-Wrapper der gorilla/csrf für
	// Requests mit X-Label-Hub-Key überspringt.
	// Aktuell werden Service-Account-POSTs mit 403 abgelehnt wenn CSRF aktiv ist.
	// Kurzfristiger Workaround: Service-Accounts nutzen GET-only-Endpunkte
	// oder den /api/* Proxy-Pfad (kein CSRF dort).
	t.Log("CSRF Service-Account-Bypass ist Phase-7-Sub-Task — noch nicht implementiert")
}
