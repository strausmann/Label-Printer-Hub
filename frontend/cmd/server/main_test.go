package main

import (
	"encoding/json"
	"fmt"
	"html/template"
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
// hit route handlers. It uses stub templates to avoid parsing the full
// web/templates glob in each test.
func testRouterWithBackend(t *testing.T, backendURL string) http.Handler {
	t.Helper()
	initBuildInfoForTests(t)
	// Use a stub template set that defines all required named blocks so the
	// handlers can render without the full Tailwind HTML.
	const stubTmpl = `
{{define "layout"}}<!DOCTYPE html><html><body>{{block "content" .}}{{end}}</body></html>{{end}}
{{define "error-content"}}<div class="error">{{.StatusCode}} {{.Error}}</div>{{end}}
{{define "dashboard-content"}}<div id="printer-grid"></div>{{end}}
{{define "printer-content"}}<div id="printer-detail"></div>{{end}}
{{define "jobs-content"}}<div id="jobs-table-container"></div>{{end}}
{{define "job-content"}}<div id="job-detail"></div>{{end}}
{{define "templates-content"}}<div id="templates-grid"></div>{{end}}
{{define "template-content"}}<div id="template-detail"></div>{{end}}
{{define "lookup-content"}}<div id="lookup-result"></div>{{end}}
`
	tmpl := template.Must(template.New("stub").Parse(stubTmpl))
	ph := handlers.NewPageHandler(tmpl, api.NewHubClient(backendURL), buildInfo.Version)
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
	// Use the real embedded templates so this test exercises the full render path.
	tmpl, err := template.ParseFS(templateFS, "web/templates/*.html")
	if err != nil {
		t.Fatalf("template.ParseFS: %v", err)
	}
	ph := handlers.NewPageHandler(tmpl, api.NewHubClient(backend.URL), "0.0.0-test")
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
