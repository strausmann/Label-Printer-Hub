// Package handlers implements the HTTP handlers for the frontend web UI.
//
// All page handlers are methods on PageHandler, which holds the parsed
// template sets and the typed backend API client. The renderPage helper
// detects HX-Request to choose between a full-page layout render and a
// content-fragment-only render from the same URL.
//
// # Template organisation
//
// Each page file (dashboard.html, jobs.html, …) defines three blocks:
//
//   - {{define "title"}}…{{end}}        — page-specific <title>
//   - {{define "content"}}…{{end}}      — delegates to the unique content block
//   - {{define "PAGENAME-content"}}…{{end}} — the actual page body
//
// Because multiple files define {{define "content"}} and {{define "title"}},
// they cannot all be parsed into a single *template.Template set — the last
// definition would silently win, causing every full-page render to produce
// the same page's content (whichever file sorts last alphabetically).
//
// To avoid this, PageHandler stores a map from page name (e.g. "dashboard")
// to a *template.Template that was parsed from exactly two files:
// layout.html and the corresponding page file. Each per-page set has exactly
// one "content" and one "title" definition, so {{block "content" .}} inside
// layout resolves correctly.
//
// HTMX fragment responses (HX-Request: true) use the per-page set and execute
// the uniquely-named "PAGENAME-content" template directly — bypassing layout.
//
// Error pages and the shared error-content template use a dedicated error set
// (layout.html + error.html) to avoid the same redefinition problem.
package handlers

import (
	"fmt"
	"html/template"
	"io/fs"
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
	// pages maps a page name (e.g. "dashboard") to a *template.Template
	// parsed from layout.html + the corresponding page file only. This
	// ensures each set has exactly one "content" and "title" definition.
	pages map[string]*template.Template
	// errTmpl is the template set for error pages (layout.html + error.html).
	errTmpl *template.Template
	client  *api.HubClient
	version string
}

// pageNames is the canonical list of page template names. Each entry must
// have a corresponding {name}.html file in web/templates/.
var pageNames = []string{
	"admin_api_keys",
	"admin_api_keys_create",
	"admin_api_keys_detail",
	"dashboard",
	"printer",
	"jobs",
	"job",
	"templates",
	"template",
	"lookup",
}

// ParsePageTemplates parses the per-page template sets from the given fs.FS.
// tmplFS must be rooted so that "web/templates/layout.html" is a valid path.
//
// Returns a map from page name to its template set and the error template set.
// Returns an error if any template file fails to parse.
func ParsePageTemplates(tmplFS fs.FS) (map[string]*template.Template, *template.Template, error) {
	pages := make(map[string]*template.Template, len(pageNames))
	for _, name := range pageNames {
		t, err := template.ParseFS(tmplFS,
			"web/templates/layout.html",
			fmt.Sprintf("web/templates/%s.html", name),
		)
		if err != nil {
			return nil, nil, fmt.Errorf("parse template %q: %w", name, err)
		}
		pages[name] = t
	}
	errTmpl, err := template.ParseFS(tmplFS,
		"web/templates/layout.html",
		"web/templates/error.html",
	)
	if err != nil {
		return nil, nil, fmt.Errorf("parse error template: %w", err)
	}
	return pages, errTmpl, nil
}

// NewPageHandler is called from main.go at startup with the per-page template
// map (from ParsePageTemplates) and a real backend client.
func NewPageHandler(pages map[string]*template.Template, errTmpl *template.Template, client *api.HubClient, version string) *PageHandler {
	return &PageHandler{pages: pages, errTmpl: errTmpl, client: client, version: version}
}

// renderPage writes a full-page or fragment response.
//
// Full page (no HX-Request header): looks up the per-page template set for
// the given name and executes "layout". Each per-page set has exactly one
// "content" definition, so {{block "content" .}} in layout.html resolves
// to the correct page's content — not to whichever page file was parsed last.
//
// Fragment (HX-Request: true): executes only "<name>-content" from the same
// per-page set — no layout wrapper, no <html>/<head>/<body> — so HTMX can
// swap it into the page without replacing the surrounding shell.
func (h *PageHandler) renderPage(w http.ResponseWriter, r *http.Request, name string, data any) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")

	t, ok := h.pages[name]
	if !ok {
		http.Error(w, "unknown page: "+name, http.StatusInternalServerError)
		return
	}

	tplName := "layout"
	if r.Header.Get("HX-Request") == "true" {
		tplName = name + "-content"
	}
	if err := t.ExecuteTemplate(w, tplName, data); err != nil {
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
	_ = h.errTmpl.ExecuteTemplate(w, "error-content", errData{
		TemplateData: TemplateData{Version: h.version, Error: detail},
		StatusCode:   code,
		StatusText:   text,
	})
}

// --- test helpers (compiled into the test binary only) ---

// stubLayoutAndError is the shared layout + error fragment used by all per-page
// stub template sets. Includes the CSS link so tests can verify asset wiring.
const stubLayoutAndError = `
{{define "layout"}}<!DOCTYPE html><html><head><link rel="stylesheet" href="/static/app.css"></head><body>{{block "content" .}}{{end}}</body></html>{{end}}
{{define "error-content"}}<div class="error">{{.StatusCode}} {{.Error}}</div>{{end}}
`

// stubPageContent maps each page name to its stub fragment templates.
//
// The split between {{define "content"}} and {{define "NAME-content"}} is
// intentional:
//
//   - {{define "content"}} is invoked by the layout's {{block "content" .}} on
//     full-page renders. It must work with ANY data type passed by renderPage
//     unit tests (which use TemplateData, not page-specific structs). The stub
//     version renders a safe static placeholder with the page's well-known ID.
//
//   - {{define "NAME-content"}} is the HTMX fragment executed directly by
//     renderPage when HX-Request is true. Integration tests that pass real
//     page-specific data (DashboardData, JobsListData, etc.) hit this path, so
//     these definitions may access page-specific fields.
//
// This two-level split mirrors the real template structure and avoids type
// errors when base_test.go passes TemplateData{} to renderPage for dashboard.
var stubPageContent = map[string]string{
	"dashboard": `{{define "content"}}<div id="printer-grid"></div>{{end}}
{{define "dashboard-content"}}<div id="printer-grid">{{range .Printers}}<span>{{.Name}}</span>{{end}}</div>{{end}}`,
	"printer": `{{define "content"}}<div id="printer-detail">printer</div>{{end}}
{{define "printer-content"}}<div id="printer-detail">printer</div>{{end}}`,
	"jobs": `{{define "content"}}<div id="jobs-table-container"></div>{{end}}
{{define "jobs-content"}}<div id="jobs-table-container">{{range .Jobs}}<span class="badge-{{.State}}">{{.State}}</span>{{end}}</div>{{end}}`,
	"job": `{{define "content"}}<div id="job-detail">job</div>{{end}}
{{define "job-content"}}<div id="job-detail">job</div>{{end}}`,
	"templates": `{{define "content"}}<div id="templates-grid">templates</div>{{end}}
{{define "templates-content"}}<div id="templates-grid">templates</div>{{end}}`,
	"template": `{{define "content"}}<div id="template-detail">template</div>{{end}}
{{define "template-content"}}<div id="template-detail">template</div>{{end}}`,
	"lookup": `{{define "content"}}<div id="lookup-result">lookup</div>{{end}}
{{define "lookup-content"}}<div id="lookup-result">lookup</div>{{end}}`,
	"admin_api_keys": `{{define "content"}}<div id="api-keys-list"></div>{{end}}
{{define "admin_api_keys-content"}}<div id="api-keys-list">{{range .Keys}}<span>{{.Name}}</span>{{end}}</div>{{end}}`,
	"admin_api_keys_create": `{{define "content"}}<div id="api-key-create"></div>{{end}}
{{define "admin_api_keys_create-content"}}<div id="api-key-create">{{.Plaintext}}</div>{{end}}`,
	"admin_api_keys_detail": `{{define "content"}}<div id="api-key-detail"></div>{{end}}
{{define "admin_api_keys_detail-content"}}<div id="api-key-detail">{{.Key.Name}}</div>{{end}}`,
}

// newStubPageHandler builds a PageHandler backed by minimal stub templates for
// tests. Each page name gets its own *template.Template (layout + page-specific
// content) so renderPage can look up by name — matching the production pattern.
func newStubPageHandler(version string, client *api.HubClient) *PageHandler {
	pages := make(map[string]*template.Template, len(pageNames))
	for _, name := range pageNames {
		src := stubLayoutAndError + stubPageContent[name]
		pages[name] = template.Must(template.New("stub-" + name).Parse(src))
	}
	errTmpl := template.Must(template.New("stub-error").Parse(stubLayoutAndError))
	return &PageHandler{pages: pages, errTmpl: errTmpl, client: client, version: version}
}

// NewPageHandlerForTest returns a PageHandler backed by minimal stub
// templates and no real API client. Safe for unit tests that exercise
// renderPage/renderError without calling the backend.
func NewPageHandlerForTest(t *testing.T) *PageHandler {
	t.Helper()
	return newStubPageHandler("0.0.0-test", nil)
}

// NewPageHandlerFromURL returns a PageHandler with stub templates and a real
// API client pointed at backendURL. Used for integration tests that spin up
// a mock backend via httptest.NewServer.
func NewPageHandlerFromURL(t *testing.T, backendURL string) *PageHandler {
	t.Helper()
	return newStubPageHandler("0.0.0-test", api.NewHubClient(backendURL))
}

// RenderTestPage exposes the unexported renderPage for use in external test
// packages (package handlers_test). It is a thin pass-through.
func (h *PageHandler) RenderTestPage(w http.ResponseWriter, r *http.Request, name string, data any) {
	h.renderPage(w, r, name, data)
}
