// Package main is the Label Printer Hub frontend entry point.
//
// The frontend container serves the user-facing UI and proxies API + SSE
// requests to the backend (see ADR 0001). Tailwind-compiled CSS and all
// html/template sources are embedded into the binary via //go:embed so the
// container is self-contained with no runtime asset filesystem.
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
	"errors"
	"io/fs"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	frontend "github.com/strausmann/label-printer-hub/frontend"
	"github.com/strausmann/label-printer-hub/frontend/internal/api"
	"github.com/strausmann/label-printer-hub/frontend/internal/handlers"
	"github.com/strausmann/label-printer-hub/frontend/internal/proxy"
)

// staticFS and templateFS are defined in frontend/assets.go (the module root
// package). They embed web/static and web/templates respectively via
// //go:embed. The declarations live there because go:embed paths are relative
// to the source file — from cmd/server/ we cannot reach ../../web/.
//
// We alias them as package-level vars here so the rest of this file can use
// short names without the `frontend.` prefix everywhere.
var staticFS = frontend.StaticFS
var templateFS = frontend.TemplateFS

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
//
// ph is the shared PageHandler that handles all UI routes including /healthz.
// prx is the pre-built reverse proxy to the backend (FlushInterval=-1 for SSE).
// staticSubFS is an fs.FS rooted at web/static — pass fs.Sub(staticFS, "web/static").
func newRouter(ph *handlers.PageHandler, prx http.Handler, staticSubFS fs.FS) *chi.Mux {
	r := chi.NewRouter()
	r.Use(middleware.RequestID)
	r.Use(middleware.RealIP)
	r.Use(middleware.Recoverer)
	r.Use(slogRequestLogger)

	// Static assets embedded in the binary (Tailwind CSS, HTMX JS, icons).
	// Served at /static/*. staticSubFS is already rooted at web/static so a
	// request for /static/app.css → strips /static/ prefix → looks up app.css
	// directly in the sub-FS.
	r.Handle("/static/*", http.StripPrefix("/static/", http.FileServer(http.FS(staticSubFS))))

	// All page routes and /healthz are handled by the shared PageHandler.
	r.Get("/healthz", ph.Healthz)

	r.Get("/", ph.Dashboard)
	r.Get("/printers/{id}", ph.PrinterDetail)
	r.Get("/jobs", ph.JobsList)
	r.Get("/jobs/{id}", ph.JobDetail)
	r.Post("/jobs/{id}/retry", ph.JobRetry)
	r.Get("/templates", ph.TemplatesList)
	r.Get("/templates/{id}", ph.TemplateDetail)
	r.Get("/lookup/{app}/{id}", ph.LookupDisplay)

	// Reverse proxy: /api/* and QR-landing paths → backend container.
	// FlushInterval=-1 (set inside proxy.New) ensures SSE frames are forwarded
	// immediately without buffering.
	r.Handle("/api/*", prx)
	r.Mount("/loc", prx)
	r.Mount("/asset", prx)
	r.Mount("/spool", prx)
	r.Mount("/product", prx)

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

	// Parse per-page template sets at startup. Each page gets its own
	// *template.Template containing only layout.html + its own page file,
	// which ensures {{block "content" .}} in the layout resolves to the
	// correct page's content. Parsing all files into one set would cause
	// the last {{define "content"}} to win for every page.
	pages, errTmpl, err := handlers.ParsePageTemplates(templateFS)
	if err != nil {
		slog.Error("failed to parse templates", "err", err)
		os.Exit(1)
	}

	// Instantiate the shared PageHandler with the typed backend client.
	backendURL := envDefault("BACKEND_URL", "http://backend:8000")
	client := api.NewHubClient(backendURL)
	ph := handlers.NewPageHandler(pages, errTmpl, client, buildInfo.Version)

	prx := proxy.New(backendURL)
	staticSubFS, err := fs.Sub(staticFS, "web/static")
	if err != nil {
		slog.Error("static embed misconfigured", "err", err)
		os.Exit(1)
	}
	r := newRouter(ph, prx, staticSubFS)
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
