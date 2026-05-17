// Package handlers implements the HTTP handlers for the frontend web UI.
//
// All page handlers are methods on PageHandler, which holds the parsed
// template set and the typed backend API client. The renderPage helper
// detects HX-Request to choose between a full-page layout render and a
// content-fragment-only render from the same URL.
package handlers

import (
	"html/template"
	"net/http"
	"testing"

	"github.com/strausmann/label-printer-hub/frontend/internal/api"
)

// TemplateData is the base type embedded by all page-specific data structs.
// Every page template receives at minimum these fields.
type TemplateData struct {
	Version   string // build version from env (e.g. "1.2.3")
	ActiveNav string // "dashboard" | "jobs" | "templates" | ""
	Error     string // non-empty on error pages
}

// PageHandler holds shared state for all page handlers.
// Instantiated once at startup and shared across all request goroutines.
type PageHandler struct {
	tmpl    *template.Template
	client  *api.HubClient
	version string
}

// NewPageHandler is called from main.go at startup with the parsed template
// set and a real backend client.
func NewPageHandler(tmpl *template.Template, client *api.HubClient, version string) *PageHandler {
	return &PageHandler{tmpl: tmpl, client: client, version: version}
}

// renderPage writes a full-page or fragment response.
//
// Full page (no HX-Request header): executes the "layout" template which
// wraps every page's "content" block.
//
// Fragment (HX-Request: true): executes only "<name>-content" — no layout
// wrapper, no <html>/<head>/<body> — so HTMX can swap it into the page
// without replacing the surrounding shell.
func (h *PageHandler) renderPage(w http.ResponseWriter, r *http.Request, name string, data any) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	tplName := "layout"
	if r.Header.Get("HX-Request") == "true" {
		tplName = name + "-content"
	}
	if err := h.tmpl.ExecuteTemplate(w, tplName, data); err != nil {
		http.Error(w, "template error: "+err.Error(), http.StatusInternalServerError)
	}
}

// renderError renders the shared error page with an HTTP status code.
// code is written as the HTTP status; text is the human-readable status text;
// detail is the error message shown in the body.
func (h *PageHandler) renderError(w http.ResponseWriter, r *http.Request, code int, text, detail string) {
	type errData struct {
		TemplateData
		StatusCode int
		StatusText string
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(code)
	_ = h.tmpl.ExecuteTemplate(w, "error-content", errData{
		TemplateData: TemplateData{Version: h.version, Error: detail},
		StatusCode:   code,
		StatusText:   text,
	})
}

// --- test helpers (compiled into the test binary only) ---

// stubTemplates is a minimal in-process template set used by unit tests.
// It mirrors the structure of the real templates (layout + <page>-content
// named blocks) without the full HTML. The layout includes the CSS link so
// tests can verify asset wiring.
const stubTemplates = `
{{define "layout"}}<!DOCTYPE html><html><head><link rel="stylesheet" href="/static/app.css"></head><body>{{block "content" .}}{{end}}</body></html>{{end}}
{{define "error-content"}}<div class="error">{{.StatusCode}} {{.Error}}</div>{{end}}
{{define "dashboard-content"}}<div id="printer-grid">{{range .Printers}}<span>{{.Name}}</span>{{end}}</div>{{end}}
{{define "printer-content"}}<div id="printer-detail">printer</div>{{end}}
{{define "jobs-content"}}<div id="jobs-table-container">{{range .Jobs}}<span class="badge-{{.State}}">{{.State}}</span>{{end}}</div>{{end}}
{{define "job-content"}}<div id="job-detail">job</div>{{end}}
{{define "templates-content"}}<div id="templates-grid">templates</div>{{end}}
{{define "template-content"}}<div id="template-detail">template</div>{{end}}
{{define "lookup-content"}}<div id="lookup-result">lookup</div>{{end}}
`

// NewPageHandlerForTest returns a PageHandler backed by minimal stub
// templates and no real API client. Safe for unit tests that exercise
// renderPage/renderError without calling the backend.
func NewPageHandlerForTest(t *testing.T) *PageHandler {
	t.Helper()
	tmpl := template.Must(template.New("test").Parse(stubTemplates))
	return &PageHandler{tmpl: tmpl, version: "0.0.0-test"}
}

// NewPageHandlerFromURL returns a PageHandler with stub templates and a real
// API client pointed at backendURL. Used for integration tests that spin up
// a mock backend via httptest.NewServer.
func NewPageHandlerFromURL(t *testing.T, backendURL string) *PageHandler {
	t.Helper()
	tmpl := template.Must(template.New("test").Parse(stubTemplates))
	return &PageHandler{
		tmpl:    tmpl,
		client:  api.NewHubClient(backendURL),
		version: "0.0.0-test",
	}
}

// RenderTestPage exposes the unexported renderPage for use in external test
// packages (package handlers_test). It is a thin pass-through.
func (h *PageHandler) RenderTestPage(w http.ResponseWriter, r *http.Request, name string, data any) {
	h.renderPage(w, r, name, data)
}
