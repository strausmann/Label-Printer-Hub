// Package main is the Label Printer Hub frontend entry point.
//
// The frontend container serves the user-facing UI and proxies API + SSE
// requests to the backend (see ADR 0001). This skeleton boots a chi router
// with a single /healthz endpoint so the container becomes deployable and
// release-publishable. Tailwind/HTMX/PWA assets, OpenAPI-generated client,
// and the actual UI routes land in follow-up PRs.
//
// Environment variables (all optional, with safe defaults):
//
//	PORT             internal HTTP port (default: 8080)
//	BACKEND_URL      base URL of the Python backend (default: http://backend:8000)
//	HUB_VERSION      release version  — baked in by Dockerfile build arg
//	HUB_REVISION     git commit SHA   — baked in by Dockerfile build arg
//	HUB_BUILD_DATE   ISO-8601 UTC     — baked in by Dockerfile build arg
//	HUB_REPO_URL     project repo URL — baked in by Dockerfile build arg
package main

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
)

const defaultRepoURL = "https://github.com/strausmann/label-printer-hub"

// BuildInfo is the JSON body returned by /healthz.
//
// It mirrors the shape of the backend's /healthz response so callers can
// treat both endpoints uniformly. Fields are populated from environment
// variables set by the Dockerfile (HUB_VERSION, HUB_REVISION, HUB_BUILD_DATE,
// HUB_REPO_URL); when running outside a built image they fall back to
// placeholders.
type BuildInfo struct {
	Status     string `json:"status"`
	Version    string `json:"version"`
	Revision   string `json:"revision"`
	BuildDate  string `json:"build_date"`
	Repository string `json:"repository"`
}

// buildInfo is captured once at startup so /healthz does not hit os.Getenv
// on every request. The HUB_* values are baked into the image by the
// Dockerfile and never change for a running container — caching them
// removes per-request syscalls on what is meant to be a cheap probe.
var buildInfo BuildInfo

// loadBuildInfo reads HUB_* env vars once and returns the BuildInfo. Kept
// as a separate function so tests can call it explicitly after t.Setenv
// without depending on package-load ordering.
func loadBuildInfo() BuildInfo {
	return BuildInfo{
		Status:     "ok",
		Version:    envDefault("HUB_VERSION", "0.0.0-dev"),
		Revision:   envDefault("HUB_REVISION", "unknown"),
		BuildDate:  envDefault("HUB_BUILD_DATE", "1970-01-01T00:00:00Z"),
		Repository: envDefault("HUB_REPO_URL", defaultRepoURL),
	}
}

// healthzHandler returns 200 with the cached BuildInfo struct. It performs
// no authentication, has no external dependencies, and never blocks —
// matching the contract of the backend's /healthz so the same orchestrator
// probe configuration works against both containers.
func healthzHandler(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(buildInfo); err != nil {
		// Encoding a fixed-shape struct should never fail; if it does the
		// connection is dead anyway. Log and return — no further writes.
		slog.Error("failed to encode healthz response", "err", err)
	}
}

// slogRequestLogger returns a chi middleware that emits one structured log
// line per request using the global slog logger. chi's bundled
// middleware.Logger writes to the legacy stdlib `log` package which bypasses
// our slog handler — that means request lines would not honour the log
// level, format, or destination configured elsewhere. We keep the
// implementation small on purpose; it can grow when we add real routes.
func slogRequestLogger(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		ww := middleware.NewWrapResponseWriter(w, r.ProtoMajor)
		next.ServeHTTP(ww, r)
		slog.Info("http request",
			"method", r.Method,
			"path", r.URL.Path,
			"status", ww.Status(),
			"bytes", ww.BytesWritten(),
			"duration_ms", time.Since(start).Milliseconds(),
			"request_id", middleware.GetReqID(r.Context()),
			"remote_ip", r.RemoteAddr,
		)
	})
}

// newRouter builds the chi router. Kept as a separate function so tests can
// exercise it without spinning up an actual HTTP server.
func newRouter() *chi.Mux {
	r := chi.NewRouter()
	r.Use(middleware.RequestID)
	r.Use(middleware.RealIP)
	r.Use(middleware.Recoverer)
	r.Use(slogRequestLogger)

	r.Get("/healthz", healthzHandler)
	return r
}

func envDefault(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func main() {
	buildInfo = loadBuildInfo()

	port := envDefault("PORT", "8080")
	addr := ":" + port

	r := newRouter()
	srv := &http.Server{
		Addr:              addr,
		Handler:           r,
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       30 * time.Second,
		// WriteTimeout is intentionally 0 (no deadline). The frontend will
		// proxy Server-Sent Events from the backend — a single SSE response
		// can stay open for minutes or hours, and any non-zero WriteTimeout
		// would tear it down mid-stream. Per-route timeouts will be applied
		// to non-SSE routes when they are added.
		WriteTimeout: 0,
		IdleTimeout:  120 * time.Second,
	}

	// Register signal handler BEFORE starting the listener. If we waited
	// until after `go func()` returned its first scheduling slice, a SIGTERM
	// arriving during that window would terminate the process by default
	// instead of triggering graceful shutdown.
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGTERM, syscall.SIGINT)

	idleConnsClosed := make(chan struct{})
	go func() {
		<-sigCh
		slog.Info("shutdown signal received")
		ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		if err := srv.Shutdown(ctx); err != nil {
			slog.Error("graceful shutdown failed", "err", err)
		}
		close(idleConnsClosed)
	}()

	slog.Info("starting frontend",
		"addr", addr,
		"version", buildInfo.Version,
		"revision", buildInfo.Revision)
	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		slog.Error("server stopped with error", "err", err)
		os.Exit(1)
	}
	<-idleConnsClosed
	slog.Info("server stopped cleanly")
}
