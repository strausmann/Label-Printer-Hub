package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
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

func TestHealthz_ReturnsOK(t *testing.T) {
	t.Parallel()
	initBuildInfoForTests(t)
	r := newRouter(nil, "")
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", w.Code)
	}
}

func TestHealthz_BodyShape(t *testing.T) {
	t.Parallel()
	initBuildInfoForTests(t)
	r := newRouter(nil, "")
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	var body BuildInfo
	if err := json.NewDecoder(w.Body).Decode(&body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body.Status != "ok" {
		t.Errorf("status = %q, want %q", body.Status, "ok")
	}
	if body.Version == "" {
		t.Error("version must not be empty")
	}
	if body.Revision == "" {
		t.Error("revision must not be empty")
	}
	if body.BuildDate == "" {
		t.Error("build_date must not be empty")
	}
	if !strings.Contains(body.Repository, "github.com/strausmann/label-printer-hub") {
		t.Errorf("repository = %q, must point at the project repo", body.Repository)
	}
}

func TestHealthz_ContentTypeJSON(t *testing.T) {
	t.Parallel()
	initBuildInfoForTests(t)
	r := newRouter(nil, "")
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
	initBuildInfoForTests(t)
	r := newRouter(nil, "")
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
	initBuildInfoForTests(t)
	r := newRouter(nil, "")
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
