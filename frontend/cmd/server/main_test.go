package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestHealthz_ReturnsOK(t *testing.T) {
	t.Parallel()
	r := newRouter()
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", w.Code)
	}
}

func TestHealthz_BodyShape(t *testing.T) {
	t.Parallel()
	r := newRouter()
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
	r := newRouter()
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
	r := newRouter()
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
	r := newRouter()
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
	t.Parallel()
	t.Setenv("FRONTEND_TEST_KEY", "expected")
	got := envDefault("FRONTEND_TEST_KEY", "fallback")
	if got != "expected" {
		t.Errorf("envDefault returned %q, want expected", got)
	}
}

func TestEnvDefault_UsesFallbackWhenEmpty(t *testing.T) {
	t.Parallel()
	t.Setenv("FRONTEND_EMPTY_KEY", "")
	got := envDefault("FRONTEND_EMPTY_KEY", "fallback")
	if got != "fallback" {
		t.Errorf("envDefault with empty env returned %q, want fallback", got)
	}
}
