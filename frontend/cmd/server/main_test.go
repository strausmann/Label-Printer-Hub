package main

import (
	"encoding/json"
	"fmt"
	"io/fs"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"github.com/strausmann/label-printer-hub/frontend/internal/api"
	"github.com/strausmann/label-printer-hub/frontend/internal/handlers"
	"github.com/strausmann/label-printer-hub/frontend/internal/proxy"
)

// initBuildInfoForTests loads the package-level buildInfo from the current
// env. Tests that exercise /healthz must call this — main() is what loads
// buildInfo in production, and that does not run during `go test`.
//
// sync.Once makes this safe for `t.Parallel()` tests: many goroutines may
// call it concurrently, but the write to the global `buildInfo` only
// happens once. Without this, `go test -race` (which CI runs) fails.
var initBuildInfoOnce sync.Once

func initBuildInfoForTests(t *testing.T) {
	t.Helper()
	initBuildInfoOnce.Do(func() {
		buildInfo = loadBuildInfo()
	})
}

// minimalBackend starts an httptest.Server that answers /healthz and
// /api/printers with minimal valid JSON, and 404 for everything else.
func minimalBackend(t *testing.T) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/healthz":
			w.Header().Set("Content-Type", "application/json")
			fmt.Fprint(w, `{"status":"ok"}`)
		case "/api/printers":
			w.Header().Set("Content-Type", "application/json")
			fmt.Fprint(w, `[]`)
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(srv.Close)
	return srv
}

// testRouterWithBackend builds a minimal router for unit tests that need to
// hit route handlers. It uses the handlers package stub templates to avoid
// parsing the full web/templates set in each test.
func testRouterWithBackend(t *testing.T, backendURL string) http.Handler {
	t.Helper()
	initBuildInfoForTests(t)
	ph := handlers.NewPageHandlerFromURL(t, backendURL)
	prx := proxy.New(backendURL)
	sub, err := fs.Sub(staticFS, "web/static")
	if err != nil {
		t.Fatalf("fs.Sub: %v", err)
	}
	return newRouter(ph, prx, sub)
}

func TestHealthz_ReturnsOK(t *testing.T) {
	t.Parallel()
	backend := minimalBackend(t)
	r := testRouterWithBackend(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", w.Code)
	}
}

func TestHealthz_BodyShape(t *testing.T) {
	t.Parallel()
	backend := minimalBackend(t)
	r := testRouterWithBackend(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	var body handlers.HealthzResponse
	if err := json.NewDecoder(w.Body).Decode(&body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body.Status != "ok" {
		t.Errorf("status = %q, want %q", body.Status, "ok")
	}
	if body.Version == "" {
		t.Error("version must not be empty")
	}
	if !strings.Contains(body.Repository, "github.com/strausmann/label-printer-hub") {
		t.Errorf("repository = %q, must point at the project repo", body.Repository)
	}
}

func TestHealthz_BackendReachable(t *testing.T) {
	t.Parallel()
	backend := minimalBackend(t)
	r := testRouterWithBackend(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	var body handlers.HealthzResponse
	if err := json.NewDecoder(w.Body).Decode(&body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if !body.BackendReachable {
		t.Errorf("backend_reachable = false with a live mock backend; backend_error = %q", body.BackendError)
	}
}

func TestHealthz_BackendUnreachable(t *testing.T) {
	t.Parallel()
	// Point at a port that is definitely not listening.
	r := testRouterWithBackend(t, "http://127.0.0.1:19998")
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 even when backend unreachable", w.Code)
	}
	var body handlers.HealthzResponse
	if err := json.NewDecoder(w.Body).Decode(&body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body.BackendReachable {
		t.Error("backend_reachable must be false when backend is down")
	}
	if body.BackendError == "" {
		t.Error("backend_error must be non-empty when backend is unreachable")
	}
}

func TestHealthz_ContentTypeJSON(t *testing.T) {
	t.Parallel()
	backend := minimalBackend(t)
	r := testRouterWithBackend(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	ct := w.Header().Get("Content-Type")
	if !strings.HasPrefix(ct, "application/json") {
		t.Errorf("Content-Type = %q, want application/json prefix", ct)
	}
}

func TestHealthz_NoAuthRequired(t *testing.T) {
	t.Parallel()
	backend := minimalBackend(t)
	r := testRouterWithBackend(t, backend.URL)
	// No Authorization header — container orchestrators probe healthz without credentials.
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 even without auth", w.Code)
	}
}

func TestHealthz_DoesNotLeakSecrets(t *testing.T) {
	t.Parallel()
	backend := minimalBackend(t)
	r := testRouterWithBackend(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	body := strings.ToLower(w.Body.String())
	for _, needle := range []string{"password", "token", "api_key", "secret", "snipeit", "grocy"} {
		if strings.Contains(body, needle) {
			t.Errorf("healthz body must not contain %q (potential secret leak)", needle)
		}
	}
}

func TestEnvDefault_UsesFallbackWhenUnset(t *testing.T) {
	t.Parallel()
	// Use a key extremely unlikely to be set so this test is hermetic.
	got := envDefault("DEFINITELY_NOT_A_REAL_ENVVAR_FOR_FRONTEND_TESTS", "fallback")
	if got != "fallback" {
		t.Errorf("envDefault returned %q, want fallback", got)
	}
}

func TestEnvDefault_UsesEnvWhenSet(t *testing.T) {
	// t.Setenv is incompatible with t.Parallel — Go's testing package
	// panics if both are used on the same test.
	t.Setenv("FRONTEND_TEST_KEY", "expected")
	got := envDefault("FRONTEND_TEST_KEY", "fallback")
	if got != "expected" {
		t.Errorf("envDefault returned %q, want expected", got)
	}
}

func TestEnvDefault_UsesFallbackWhenEmpty(t *testing.T) {
	t.Setenv("FRONTEND_EMPTY_KEY", "")
	got := envDefault("FRONTEND_EMPTY_KEY", "fallback")
	if got != "fallback" {
		t.Errorf("envDefault with empty env returned %q, want fallback", got)
	}
}

func TestLoadBuildInfo_AppliesEnvOverrides(t *testing.T) {
	// Confirms the startup-cache path actually reads env. t.Setenv prevents
	// parallel execution, which is fine — this is a small synchronous check.
	t.Setenv("HUB_VERSION", "9.9.9")
	t.Setenv("HUB_REVISION", "deadbeef")
	t.Setenv("HUB_BUILD_DATE", "2099-12-31T23:59:59Z")
	t.Setenv("HUB_REPO_URL", "https://example.invalid/fork")

	got := loadBuildInfo()
	if got.Version != "9.9.9" {
		t.Errorf("Version = %q, want %q", got.Version, "9.9.9")
	}
	if got.Revision != "deadbeef" {
		t.Errorf("Revision = %q, want %q", got.Revision, "deadbeef")
	}
	if got.BuildDate != "2099-12-31T23:59:59Z" {
		t.Errorf("BuildDate = %q, want %q", got.BuildDate, "2099-12-31T23:59:59Z")
	}
	if got.Repository != "https://example.invalid/fork" {
		t.Errorf("Repository = %q, want override URL", got.Repository)
	}
}

func TestLoadBuildInfo_UsesDefaultsWhenUnset(t *testing.T) {
	t.Setenv("HUB_VERSION", "")
	t.Setenv("HUB_REVISION", "")
	t.Setenv("HUB_BUILD_DATE", "")
	t.Setenv("HUB_REPO_URL", "")

	got := loadBuildInfo()
	if got.Status != "ok" {
		t.Errorf("Status = %q, want %q", got.Status, "ok")
	}
	if got.Version != "0.0.0-dev" {
		t.Errorf("Version = %q, want default %q", got.Version, "0.0.0-dev")
	}
	if got.Repository != defaultRepoURL {
		t.Errorf("Repository = %q, want default %q", got.Repository, defaultRepoURL)
	}
}

// TestRoutesDashboard is the routing integration test.
// It spins up a full router backed by a mock backend and hits every wired
// route, asserting the expected HTTP status codes.
func TestRoutesDashboard(t *testing.T) {
	// Note: not parallel — uses initBuildInfoForTests which has a sync.Once.
	// Multiple non-parallel tests that call initBuildInfoForTests are safe
	// because sync.Once ensures only one write to the global.
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/api/printers":
			fmt.Fprint(w, `[]`)
		case "/healthz":
			fmt.Fprint(w, `{"status":"ok"}`)
		default:
			http.NotFound(w, r)
		}
	}))
	defer backend.Close()

	initBuildInfoForTests(t)
	// Use the real embedded templates (ParsePageTemplates) so this test
	// exercises the full per-page template render path.
	pages, errTmpl, err := handlers.ParsePageTemplates(templateFS)
	if err != nil {
		t.Fatalf("ParsePageTemplates: %v", err)
	}
	ph := handlers.NewPageHandler(pages, errTmpl, api.NewHubClient(backend.URL), "0.0.0-test")
	prx := proxy.New(backend.URL)
	sub, err := fs.Sub(staticFS, "web/static")
	if err != nil {
		t.Fatalf("fs.Sub: %v", err)
	}
	r := newRouter(ph, prx, sub)

	tests := []struct {
		method string
		path   string
		want   int
	}{
		{http.MethodGet, "/", http.StatusOK},
		{http.MethodGet, "/healthz", http.StatusOK},
		{http.MethodGet, "/static/app.css", http.StatusOK},
	}

	for _, tc := range tests {
		req := httptest.NewRequest(tc.method, tc.path, nil)
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)
		if w.Code != tc.want {
			t.Errorf("%s %s = %d, want %d (body: %s)", tc.method, tc.path, w.Code, tc.want, w.Body.String()[:min(200, w.Body.Len())])
		}
	}
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// TestProxyMountsBackendDocRoutes verifies that /docs, /openapi.json and /redoc
// are forwarded to the backend (Phase 7b Cluster 3).
// Without the three r.Handle lines in newRouter, the chi router returns 404 for
// each of these paths.
func TestProxyMountsBackendDocRoutes(t *testing.T) {
	// Not parallel at the outer level: we need initBuildInfoForTests to run
	// (sync.Once write) before the parallel subtests read the global.
	initBuildInfoForTests(t)

	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/docs":
			w.Header().Set("Content-Type", "text/html")
			fmt.Fprint(w, "<html>Swagger UI</html>")
		case "/openapi.json":
			w.Header().Set("Content-Type", "application/json")
			fmt.Fprint(w, `{"openapi":"3.1.0"}`)
		case "/redoc":
			w.Header().Set("Content-Type", "text/html")
			fmt.Fprint(w, "ReDoc")
		case "/readiness":
			w.Header().Set("Content-Type", "application/json")
			fmt.Fprint(w, `{"status":"ready","checks":{}}`)
		default:
			http.NotFound(w, r)
		}
	}))
	// t.Cleanup (not defer) ensures the server stays up until all parallel
	// subtests have finished — defer fires when the outer function returns,
	// which is before t.Parallel subtests execute.
	t.Cleanup(backend.Close)

	// Build the router directly against our mock backend so all three doc
	// paths are proxied to the server that actually answers them.
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	prx := proxy.New(backend.URL)
	sub, err := fs.Sub(staticFS, "web/static")
	if err != nil {
		t.Fatalf("fs.Sub: %v", err)
	}
	r := newRouter(ph, prx, sub)

	for path, want := range map[string]string{
		"/docs":         "Swagger UI",
		"/openapi.json": `"openapi":"3.1.0"`,
		"/redoc":        "ReDoc",
		"/readiness":    `"status":"ready"`,
	} {
		path, want := path, want // capture loop variables
		t.Run(path, func(t *testing.T) {
			t.Parallel()
			rec := httptest.NewRecorder()
			r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
			if rec.Code != http.StatusOK {
				t.Fatalf("GET %s: got status %d, want 200 (body: %q)", path, rec.Code, rec.Body.String())
			}
			if !strings.Contains(rec.Body.String(), want) {
				t.Errorf("GET %s: body = %q, want substring %q", path, rec.Body.String(), want)
			}
		})
	}
}

// TestProxyMountsLegacyFirstPrintRoutes verifies that POST /print is
// forwarded to the backend (Phase 7 legacy smoke path).
//
// Before Phase 7 the smoke test called the backend container:8000/print
// directly (container port was public). Phase 7 placed a Go frontend proxy in
// front and closed the public port, but missed wiring /print to the
// backend. This test locks in the fix so the ad-hoc curl workflow
// (POST /print) works through Pangolin with the claude-automation
// Basic-Auth header.
//
// /jobs/{id} is intentionally NOT proxied — that path is served by the
// r.Get("/jobs/{id}", ph.JobDetail) page handler which renders the HTML
// job-detail page for browser users. Scripts that need JSON for a
// specific job id should use the typed /api/* routes instead.
func TestProxyMountsLegacyFirstPrintRoutes(t *testing.T) {
	// Not parallel at the outer level: initBuildInfoForTests must run (sync.Once
	// write) before any parallel subtest reads the global.
	initBuildInfoForTests(t)

	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/print" && r.Method == http.MethodPost:
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusAccepted)
			fmt.Fprint(w, `{"job_id":"abc-123","status":"queued"}`)
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(backend.Close)

	r := testRouterWithBackend(t, backend.URL)

	t.Run("POST /print returns 202 with job_id", func(t *testing.T) {
		t.Parallel()
		rec := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodPost, "/print",
			strings.NewReader(`{"template_id":"qr-only-12mm","data":{"title":"T","primary_id":"P","qr_payload":"https://example.com"}}`))
		req.Header.Set("Content-Type", "application/json")
		r.ServeHTTP(rec, req)
		if rec.Code != http.StatusAccepted {
			t.Fatalf("got %d, want 202 (body: %q)", rec.Code, rec.Body.String())
		}
		if !strings.Contains(rec.Body.String(), `"job_id":"abc-123"`) {
			t.Errorf("body = %q, expected job_id field", rec.Body.String())
		}
	})
}

// TestRealTemplatesPerPageContent verifies that each page renders its own
// content when using the real embedded templates — not the content of whatever
// page file happens to be parsed last.
//
// When all template files are parsed into a single *template.Template set with
// template.ParseFS, multiple files define {{define "content"}} (one per page).
// Go's html/template resolves the last definition, so every call to
// ExecuteTemplate(w, "layout", data) produces the content of the last-parsed
// page. This test catches that regression: it expects the dashboard to produce
// "printer-grid" and the templates list to produce "templates-grid".
func TestRealTemplatesPerPageContent(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/api/printers":
			fmt.Fprint(w, `[]`)
		case "/api/templates":
			fmt.Fprint(w, `[]`)
		case "/healthz":
			fmt.Fprint(w, `{"status":"ok"}`)
		default:
			http.NotFound(w, r)
		}
	}))
	defer backend.Close()

	initBuildInfoForTests(t)
	pages, errTmpl, err := handlers.ParsePageTemplates(templateFS)
	if err != nil {
		t.Fatalf("ParsePageTemplates: %v", err)
	}
	ph := handlers.NewPageHandler(pages, errTmpl, api.NewHubClient(backend.URL), "0.0.0-test")
	prx := proxy.New(backend.URL)
	sub, err := fs.Sub(staticFS, "web/static")
	if err != nil {
		t.Fatalf("fs.Sub: %v", err)
	}
	r := newRouter(ph, prx, sub)

	t.Run("dashboard_renders_printer_grid", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)
		if w.Code != http.StatusOK {
			t.Fatalf("status %d, body: %s", w.Code, w.Body.String())
		}
		if !strings.Contains(w.Body.String(), "printer-grid") {
			t.Errorf("dashboard full-page response must contain 'printer-grid'; got content starting with: %q",
				w.Body.String()[:min(400, w.Body.Len())])
		}
		if strings.Contains(w.Body.String(), "templates-grid") {
			t.Error("dashboard must NOT render templates-grid (template block clash: last 'content' definition wins)")
		}
	})

	t.Run("templates_page_renders_templates_grid", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodGet, "/templates", nil)
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)
		if w.Code != http.StatusOK {
			t.Fatalf("status %d, body: %s", w.Code, w.Body.String())
		}
		if !strings.Contains(w.Body.String(), "templates-grid") {
			t.Errorf("templates page must contain 'templates-grid'; got: %q",
				w.Body.String()[:min(400, w.Body.Len())])
		}
	})
}

// TestQRLandingPrefixPreserved verifies that the QR-landing proxy routes
// (/loc, /asset, /spool, /product) forward the FULL path to the backend,
// including the prefix.
//
// chi.Mount strips the mount prefix before calling the handler, so
// r.Mount("/loc", proxy) causes the backend to see "/" instead of "/loc/abc".
// The correct pattern is r.Handle("/loc/*", proxy) which preserves the prefix.
func TestQRLandingPrefixPreserved(t *testing.T) {
	t.Parallel()
	// Record the path the backend actually receives.
	var receivedPath string
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedPath = r.URL.Path
		// Return 200 so the proxy does not emit a 502.
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"ok":true}`)
	}))
	defer backend.Close()

	r := testRouterWithBackend(t, backend.URL)

	cases := []struct {
		path string
	}{
		{"/loc/abc123"},
		{"/asset/def456"},
		{"/spool/ghi789"},
		{"/product/jkl012"},
	}

	for _, tc := range cases {
		receivedPath = ""
		req := httptest.NewRequest(http.MethodGet, tc.path, nil)
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)

		if w.Code != http.StatusOK {
			t.Errorf("GET %s: status %d, want 200", tc.path, w.Code)
			continue
		}
		if receivedPath != tc.path {
			t.Errorf("GET %s: backend received path %q, want %q (chi.Mount strips prefix; use r.Handle instead)",
				tc.path, receivedPath, tc.path)
		}
	}
}
