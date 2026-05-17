# Phase 7a — Frontend-Basis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the read-only web UI for the frontend container: Dashboard, Printer Detail (live SSE), Jobs list/detail (with retry PRG), Templates list/detail (YAML + base64 preview), and Lookup display — server-side rendered in Go with Tailwind v4 and HTMX.

**Architecture:** A single Go binary embeds Tailwind-compiled CSS and `html/template` files via `//go:embed`. `PageHandler` wraps an `oapi-codegen`-generated typed client. `httputil.ReverseProxy` with `FlushInterval: -1` proxies `/api/*` (REST + SSE) and QR landing paths to the backend. Page handlers detect `HX-Request` to return full-page or fragment from the same URL. Generated `client.gen.go` is committed so `go build` works without a live backend.

**Tech Stack:** Go 1.23, chi v5, `html/template` (stdlib), `oapi-codegen v2`, Tailwind v4.1.5 Standalone CLI, HTMX 2.0.4 + htmx-ext-sse 2.2.3 (vendored), `golang.org/x/sync/errgroup`.

**Tracking:** Issue #22 (every commit ends with `Refs #22`).

---

## Conventions

- Conventional Commits — valid scopes: `ui`, `ci`, `docs`, `docker`, `deps`, `api`, `integration` (from `commitlint.config.cjs`).
- Header max 120 chars. No `Co-Authored-By: Claude` anywhere.
- TDD-strict: failing test → RED → implement → GREEN → commit.
- All `go test` runs use `-race`. Coverage ≥ 70% on `frontend/internal/`.
- Subagents do NOT push. Orchestrator handles push + PR.
- Run commands from `frontend/` unless stated otherwise.
- Every commit: `git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" commit`

---

## File Structure (target state)

```
frontend/
├── cmd/server/
│   ├── main.go          MODIFY — embed vars, newRouter with all routes
│   └── main_test.go     MODIFY — routing integration test
├── internal/
│   ├── api/
│   │   ├── client.gen.go   CREATE — oapi-codegen output (committed)
│   │   └── client.go       CREATE — NewClient wrapper + typed helpers + ErrNotFound/ErrUnsupportedApp
│   ├── handlers/
│   │   ├── base.go         CREATE — TemplateData, PageHandler{tmpl,client,version}, renderPage, renderError, test helpers
│   │   ├── dashboard.go    CREATE — GET /
│   │   ├── printer.go      CREATE — GET /printers/{id} (errgroup parallel)
│   │   ├── jobs.go         CREATE — GET /jobs (filter + cursor pagination)
│   │   ├── job.go          CREATE — GET /jobs/{id}, POST /jobs/{id}/retry (303 See Other)
│   │   ├── templates.go    CREATE — GET /templates
│   │   ├── template.go     CREATE — GET /templates/{id} (base64 preview, 2s timeout)
│   │   ├── lookup.go       CREATE — GET /lookup/{app}/{id}
│   │   └── healthz.go      CREATE — /healthz extended with backend_reachable
│   └── proxy/
│       └── proxy.go        CREATE — FlushInterval=-1 reverse proxy
├── web/
│   ├── styles/app.css      CREATE — @import tailwindcss + @theme tokens
│   ├── static/             CREATE — htmx.min.js, htmx-ext-sse.min.js, app.css (docker-built),
│   │                                preview-placeholder.svg, favicon.ico, VERSIONS.txt
│   └── templates/          CREATE — layout.html, error.html, dashboard.html, printer.html,
│                                    jobs.html, job.html, templates.html, template.html, lookup.html
├── oapi-codegen.yaml       CREATE
├── tools.go                CREATE — //go:build tools; pin oapi-codegen version in go.mod
├── Makefile                CREATE — gen-client, dev-css, dev-go, test targets
└── Dockerfile              MODIFY — add Stage 0 (Tailwind), update Stage 1 (copy CSS + ldflags)
```

---

## Task 0: Dockerfile multi-stage + Tailwind input CSS + Makefile

**Files:** Modify `Dockerfile`; create `web/styles/app.css`, `Makefile`

- [ ] **Step 1: Create `web/styles/app.css`** (full @theme token block)

```css
@import "tailwindcss";

@theme {
  --color-primary:           oklch(55% 0.20 250);
  --color-primary-hover:     oklch(48% 0.20 250);
  --color-primary-fg:        oklch(98% 0.00 0);
  --color-surface:           oklch(98% 0.00 0);
  --color-surface-raised:    oklch(100% 0.00 0);
  --color-surface-border:    oklch(88% 0.00 0);
  --color-content:           oklch(20% 0.00 0);
  --color-content-secondary: oklch(50% 0.00 0);
  --color-status-online:     oklch(55% 0.18 145);
  --color-status-offline:    oklch(50% 0.15 25);
  --color-status-paused:     oklch(65% 0.16 80);
  --color-state-queued:      oklch(65% 0.16 80);
  --color-state-printing:    oklch(55% 0.18 250);
  --color-state-done:        oklch(55% 0.18 145);
  --color-state-failed:      oklch(50% 0.15 25);
  --color-state-cancelled:   oklch(50% 0.00 0);
}

@layer components {
  .nav-link        { @apply text-sm text-content-secondary hover:text-content transition-colors; }
  .nav-link-active { @apply text-content font-medium; }
  .badge           { @apply inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium; }
  .badge-online    { @apply bg-status-online/15 text-status-online; }
  .badge-offline   { @apply bg-status-offline/15 text-status-offline; }
  .badge-paused    { @apply bg-status-paused/15 text-status-paused; }
  .badge-printing  { @apply bg-state-printing/15 text-state-printing; }
  .badge-queued    { @apply bg-state-queued/15 text-state-queued; }
  .badge-done      { @apply bg-state-done/15 text-state-done; }
  .badge-failed    { @apply bg-state-failed/15 text-state-failed; }
  .badge-cancelled { @apply bg-state-cancelled/15 text-state-cancelled; }
}
```

- [ ] **Step 2: Prepend Stage 0 to `Dockerfile`** (before the existing `builder` stage)

```dockerfile
# Note: use debian:bookworm-slim, NOT alpine. The Tailwind v4 standalone
# binary is a glibc ELF; alpine (musl libc) cannot execute it.
FROM debian:bookworm-slim AS tailwind-builder
ARG TAILWIND_VERSION=v4.1.5
ARG TARGETARCH
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    ARCH_SUFFIX=$([ "$TARGETARCH" = "arm64" ] && echo "arm64" || echo "x64") && \
    curl -fsSL \
      "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-${ARCH_SUFFIX}" \
      -o /usr/local/bin/tailwindcss && chmod +x /usr/local/bin/tailwindcss
WORKDIR /src
COPY web/styles/ ./web/styles/
COPY web/templates/ ./web/templates/
RUN tailwindcss --input web/styles/app.css --output web/static/app.css --minify
```

In the existing `builder` stage, after `COPY . ./`:

```dockerfile
COPY --from=tailwind-builder /src/web/static/app.css ./web/static/app.css
ARG VERSION=0.0.0-dev
ARG REVISION=unknown
ARG BUILD_DATE=1970-01-01T00:00:00Z
```

Update the `go build` command to pass `ldflags`:

```dockerfile
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath \
      -ldflags="-s -w -X main.version=${VERSION} -X main.revision=${REVISION} -X main.buildDate=${BUILD_DATE}" \
      -o /out/server ./cmd/server
```

- [ ] **Step 3: Create `Makefile`**

```makefile
.PHONY: dev-css dev-go gen-client test lint
TAILWIND_BIN ?= ./tailwindcss
BACKEND_URL  ?= http://localhost:8000
dev-css:
	$(TAILWIND_BIN) -i web/styles/app.css -o web/static/app.css --watch
dev-go:
	BACKEND_URL=$(BACKEND_URL) go run ./cmd/server
gen-client:
	go run github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen \
	  --config oapi-codegen.yaml ../backend/openapi.json
test:
	go test -race ./...
lint:
	go vet ./...
```

- [ ] **Step 4: Create `web/static/` and `web/templates/` directories; add local CSS stub**

```bash
mkdir -p web/static web/templates
echo "/* local stub — overwritten by docker build */" > web/static/app.css
```

- [ ] **Step 5: Verify Docker build with a stub layout template**

```bash
echo '<!-- stub -->' > web/templates/layout.html
docker build --platform linux/amd64 . -t lph:t0
# Expected: exit 0, image created
```

- [ ] **Step 6: Commit**

```bash
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "build(docker): add Tailwind v4 standalone CLI stage to frontend Dockerfile

Refs #22"
```

---

## Task 1: Vendor static assets + base layout + error templates

**Files:** `web/static/{htmx.min.js,htmx-ext-sse.min.js,preview-placeholder.svg,favicon.ico,VERSIONS.txt}`, `web/templates/{layout.html,error.html}`

- [ ] **Step 1: Download vendored JS assets**

```bash
curl -fsSL https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js  -o web/static/htmx.min.js
curl -fsSL https://unpkg.com/htmx-ext-sse@2.2.3/sse.js         -o web/static/htmx-ext-sse.min.js
cat > web/static/VERSIONS.txt <<'EOF'
htmx          2.0.4   https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js
htmx-ext-sse  2.2.3   https://unpkg.com/htmx-ext-sse@2.2.3/sse.js
tailwindcss   v4.1.5  https://github.com/tailwindlabs/tailwindcss/releases/tag/v4.1.5
EOF
cat > web/static/preview-placeholder.svg <<'EOF'
<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 200 100">
  <rect width="200" height="100" fill="#f0f0f0" rx="4"/>
  <text x="100" y="54" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#888">Preview unavailable</text>
</svg>
EOF
printf 'AAABAAEAEBAAAAEAIABoBAAAFgAAACgAAAAQAAAAIAAAAAEAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==' \
  | base64 -d > web/static/favicon.ico
```

- [ ] **Step 2: Create `web/templates/layout.html`**

```html
{{define "layout"}}
<!DOCTYPE html>
<html lang="en" class="h-full">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{block "title" .}}Label Printer Hub{{end}}</title>
  <link rel="stylesheet" href="/static/app.css">
  <link rel="icon" href="/static/favicon.ico">
  <script src="/static/htmx.min.js" defer></script>
  <script src="/static/htmx-ext-sse.min.js" defer></script>
</head>
<body class="bg-surface min-h-full flex flex-col">
  <nav class="bg-surface-raised border-b border-surface-border">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center h-14 gap-6">
      <a href="/" class="font-semibold text-primary">Label Printer Hub</a>
      <a href="/"          class="nav-link {{if eq .ActiveNav "dashboard"}}nav-link-active{{end}}">Dashboard</a>
      <a href="/jobs"      class="nav-link {{if eq .ActiveNav "jobs"}}nav-link-active{{end}}">Jobs</a>
      <a href="/templates" class="nav-link {{if eq .ActiveNav "templates"}}nav-link-active{{end}}">Templates</a>
    </div>
  </nav>
  <main class="flex-1 max-w-7xl mx-auto w-full px-4 py-6 sm:px-6 lg:px-8">
    {{block "content" .}}{{end}}
  </main>
  <footer class="border-t border-surface-border py-3 text-center text-xs text-content-secondary">
    v{{.Version}} &mdash; <a href="https://github.com/strausmann/label-printer-hub" class="hover:underline">GitHub</a>
  </footer>
</body>
</html>
{{end}}
```

- [ ] **Step 3: Create `web/templates/error.html`**

```html
{{define "error-content"}}
<div class="flex flex-col items-center justify-center py-24 gap-4">
  <h1 class="text-2xl font-semibold text-content">{{.StatusCode}} &mdash; {{.StatusText}}</h1>
  <p class="text-content-secondary">{{.Error}}</p>
  <a href="/" class="text-primary hover:underline">Back to Dashboard</a>
</div>
{{end}}
```

- [ ] **Step 4: Verify templates parse**

```bash
go run -mod=mod - <<'EOF'
package main
import ("fmt";"html/template";"os")
func main() {
  if _, err := template.ParseGlob("web/templates/*.html"); err != nil {
    fmt.Fprintln(os.Stderr, err); os.Exit(1)
  }
  fmt.Println("OK")
}
EOF
# Expected: OK
```

- [ ] **Step 5: Commit**

```bash
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "feat(ui): vendor HTMX 2.0.4+SSE 2.2.3, add base layout and error templates

Refs #22"
```

---

## Task 2: `internal/handlers/base.go` — shared types + `//go:embed`

**Files:** Create `internal/handlers/base.go`, `base_test.go`; modify `cmd/server/main.go`

- [ ] **Step 1: Write failing test**

```go
// frontend/internal/handlers/base_test.go
package handlers_test

import (
	"net/http"; "net/http/httptest"; "strings"; "testing"
	"github.com/strausmann/label-printer-hub/frontend/internal/handlers"
)

func TestRenderPageFullLayout(t *testing.T) {
	t.Parallel()
	ph := handlers.NewPageHandlerForTest(t)
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	w   := httptest.NewRecorder()
	ph.RenderTestPage(w, req, "dashboard", handlers.TemplateData{Version: "0.0.0-test", ActiveNav: "dashboard"})
	if w.Code != http.StatusOK { t.Fatalf("status %d", w.Code) }
	if !strings.Contains(w.Body.String(), "<!DOCTYPE html>") { t.Error("full page must have DOCTYPE") }
}

func TestRenderPageHTMXFragment(t *testing.T) {
	t.Parallel()
	ph := handlers.NewPageHandlerForTest(t)
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set("HX-Request", "true")
	w := httptest.NewRecorder()
	ph.RenderTestPage(w, req, "dashboard", handlers.TemplateData{Version: "0.0.0-test"})
	if strings.Contains(w.Body.String(), "<!DOCTYPE html>") { t.Error("fragment must NOT have DOCTYPE") }
}
```

- [ ] **Step 2: Run — expect RED (package undefined)**

```bash
go test -race ./internal/handlers/... 2>&1 | head -5
```

- [ ] **Step 3: Create `internal/handlers/base.go`**

```go
package handlers

import (
	"html/template"; "net/http"; "testing"
	"github.com/strausmann/label-printer-hub/frontend/internal/api"
)

type TemplateData struct {
	Version   string
	ActiveNav string
	Error     string
}

type PageHandler struct {
	tmpl    *template.Template
	client  *api.Client
	version string
}

func NewPageHandler(tmpl *template.Template, client *api.Client, version string) *PageHandler {
	return &PageHandler{tmpl: tmpl, client: client, version: version}
}

func (h *PageHandler) renderPage(w http.ResponseWriter, r *http.Request, name string, data any) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	tpl := "layout"
	if r.Header.Get("HX-Request") == "true" { tpl = name + "-content" }
	if err := h.tmpl.ExecuteTemplate(w, tpl, data); err != nil {
		http.Error(w, "template error: "+err.Error(), http.StatusInternalServerError)
	}
}

func (h *PageHandler) renderError(w http.ResponseWriter, r *http.Request, code int, text, detail string) {
	type errData struct { TemplateData; StatusCode int; StatusText string }
	w.WriteHeader(code)
	_ = h.tmpl.ExecuteTemplate(w, "error-content", errData{
		TemplateData: TemplateData{Version: h.version, Error: detail},
		StatusCode: code, StatusText: text,
	})
}

// stubTemplates is used by both test helpers below; keep definitions in sync with all page handlers.
const stubTemplates = `
{{define "layout"}}<!DOCTYPE html><html><body>{{block "content" .}}{{end}}</body></html>{{end}}
{{define "error-content"}}<div class="error">{{.StatusCode}} {{.Error}}</div>{{end}}
{{define "dashboard-content"}}<div id="printer-grid">{{range .Printers}}<span>{{.Name}}</span>{{end}}</div>{{end}}
{{define "printer-content"}}<div id="printer-detail"></div>{{end}}
{{define "jobs-content"}}<div id="jobs-table-container">{{range .Jobs}}<span class="badge-{{.State}}">{{.State}}</span>{{end}}</div>{{end}}
{{define "job-content"}}<div id="job-detail">{{if .Job}}state:{{.Job.State}}{{end}}</div>{{end}}
{{define "templates-content"}}<div id="templates-grid">{{range .Templates}}<span>{{.Name}}</span>{{end}}</div>{{end}}
{{define "template-content"}}<div id="template-detail">{{if .Template}}{{.Template.Key}}{{end}}</div>{{end}}
{{define "lookup-content"}}<div id="lookup-result">{{if .Result}}{{.Result.Name}}{{end}}</div>{{end}}
`

// NewPageHandlerForTest returns a handler with stub templates and no API client (for base tests).
func NewPageHandlerForTest(t *testing.T) *PageHandler {
	t.Helper()
	return &PageHandler{tmpl: template.Must(template.New("test").Parse(stubTemplates)), version: "0.0.0-test"}
}

// NewPageHandlerFromURL returns a handler with stub templates and a real API client (for handler integration tests).
func NewPageHandlerFromURL(t *testing.T, backendURL string) *PageHandler {
	t.Helper()
	return &PageHandler{
		tmpl:    template.Must(template.New("test").Parse(stubTemplates)),
		client:  api.NewClient(backendURL),
		version: "0.0.0-test",
	}
}

// RenderTestPage exposes renderPage for tests.
func (h *PageHandler) RenderTestPage(w http.ResponseWriter, r *http.Request, name string, data any) {
	h.renderPage(w, r, name, data)
}
```

- [ ] **Step 4: Add `//go:embed` to `cmd/server/main.go`**

```go
import "embed"

//go:embed web/static
var staticFS embed.FS

//go:embed web/templates
var templateFS embed.FS
```

- [ ] **Step 5: Run — GREEN**

```bash
go test -race ./internal/handlers/... -run TestRenderPage -v 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "feat(ui): handlers base (TemplateData, PageHandler, renderPage) + go:embed

Refs #22"
```

---

## Task 3: `oapi-codegen` typed backend client

**Files:** `oapi-codegen.yaml`, `tools.go`, `internal/api/client.go`, `internal/api/client.gen.go`, `internal/api/client_test.go`

- [ ] **Step 1: Create config and tool pin**

```bash
cat > oapi-codegen.yaml <<'EOF'
package: api
generate:
  models: true
  client: true
  strict-server: false
output: internal/api/client.gen.go
EOF

cat > tools.go <<'EOF'
//go:build tools
package tools
import _ "github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen"
EOF

go get github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen
go get github.com/oapi-codegen/runtime
go mod tidy
```

- [ ] **Step 2: Export OpenAPI spec and generate client**

```bash
# If backend is running:
curl -s http://localhost:8000/openapi.json > /tmp/openapi.json
# Or from the FastAPI app directly:
# cd ../backend && python -c "from app.main import app; import json; print(json.dumps(app.openapi()))" > /tmp/openapi.json

cd frontend
go run github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen \
  --config oapi-codegen.yaml /tmp/openapi.json

head -3 internal/api/client.gen.go  # must start with "// Code generated by oapi-codegen"
go build ./internal/api/...         # must succeed
```

- [ ] **Step 3: Write failing test**

```go
// frontend/internal/api/client_test.go
package api_test

import (
	"context"; "encoding/json"; "net/http"; "net/http/httptest"; "testing"; "time"
	"github.com/strausmann/label-printer-hub/frontend/internal/api"
)

func TestListPrintersHitsCorrectPath(t *testing.T) {
	t.Parallel()
	called := false
	now := time.Now().Format(time.RFC3339)
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/printers" {
			called = true
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode([]map[string]any{
				{"id": "aaaaaaaa-0000-0000-0000-000000000001", "name": "PT-P750W",
				 "model": "pt_series", "backend": "tcp",
				 "connection": map[string]any{"host": "198.51.100.10", "port": 9100},
				 "enabled": true, "paused": false, "created_at": now, "updated_at": now},
			})
		} else { http.NotFound(w, r) }
	}))
	defer backend.Close()

	printers, err := api.NewClient(backend.URL).ListPrinters(context.Background())
	if err != nil { t.Fatalf("ListPrinters: %v", err) }
	if !called { t.Error("GET /api/printers not called") }
	if len(printers) != 1 || printers[0].Name != "PT-P750W" { t.Errorf("unexpected result: %+v", printers) }
}

func TestGetJobReturnsErrNotFound(t *testing.T) {
	t.Parallel()
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.NotFound(w, r) }))
	defer backend.Close()
	_, err := api.NewClient(backend.URL).GetJob(context.Background(), "no-such-job")
	if err != api.ErrNotFound { t.Errorf("err = %v, want ErrNotFound", err) }
}
```

- [ ] **Step 4: Run — RED**

```bash
go test -race ./internal/api/... 2>&1 | head -5
# Expected: build error — api.NewClient undefined
```

- [ ] **Step 5: Create `internal/api/client.go`**

Implement all methods shown below. The generated method names depend on the actual spec; after generation verify them in `client.gen.go` and adjust. Pattern: `<HTTPVerb><PathCamelCase>WithResponse`.

```go
package api

import (
	"context"; "fmt"; "log/slog"; "net/http"; "time"
)

type Client struct { gen *ClientWithResponses; baseURL string }

var (
	ErrNotFound       = fmt.Errorf("not found")
	ErrUnsupportedApp = fmt.Errorf("unsupported app")
)

func NewClient(baseURL string) *Client {
	hc := &http.Client{Timeout: 10 * time.Second}
	gen, err := NewClientWithResponses(baseURL, WithHTTPClient(hc))
	if err != nil { panic("api.NewClient: " + err.Error()) }
	return &Client{gen: gen, baseURL: baseURL}
}

func logCall(op string, start time.Time, err error) {
	slog.Debug("backend call", "op", op, "ms", time.Since(start).Milliseconds(), "err", err)
}

func (c *Client) ListPrinters(ctx context.Context) ([]PrinterRead, error) {
	start := time.Now()
	resp, err := c.gen.GetApiPrintersWithResponse(ctx)
	logCall("ListPrinters", start, err)
	if err != nil { return nil, err }
	if resp.JSON200 == nil { return nil, fmt.Errorf("ListPrinters: status %d", resp.StatusCode()) }
	return *resp.JSON200, nil
}

func (c *Client) GetPrinterStatus(ctx context.Context, id string) (*PrinterStatus, error) {
	start := time.Now()
	resp, err := c.gen.GetApiPrintersPrinterIdStatusWithResponse(ctx, id)
	logCall("GetPrinterStatus", start, err)
	if err != nil { return nil, err }
	if resp.StatusCode() == http.StatusNotFound { return nil, ErrNotFound }
	if resp.JSON200 == nil { return nil, fmt.Errorf("GetPrinterStatus: status %d", resp.StatusCode()) }
	return resp.JSON200, nil
}

func (c *Client) GetPrinterTape(ctx context.Context, id string) (map[string]any, error) {
	start := time.Now()
	resp, err := c.gen.GetApiPrintersPrinterIdTapeWithResponse(ctx, id)
	logCall("GetPrinterTape", start, err)
	if err != nil { return nil, err }
	if resp.StatusCode() == http.StatusNotFound { return nil, ErrNotFound }
	if resp.JSON200 == nil { return nil, fmt.Errorf("GetPrinterTape: status %d", resp.StatusCode()) }
	return *resp.JSON200, nil
}

func (c *Client) GetPrinterQueue(ctx context.Context, id string) ([]map[string]any, error) {
	start := time.Now()
	resp, err := c.gen.GetApiPrintersPrinterIdQueueWithResponse(ctx, id)
	logCall("GetPrinterQueue", start, err)
	if err != nil { return nil, err }
	if resp.JSON200 == nil { return nil, fmt.Errorf("GetPrinterQueue: status %d", resp.StatusCode()) }
	return *resp.JSON200, nil
}

func (c *Client) ListJobs(ctx context.Context, params *GetApiJobsParams) ([]JobRead, error) {
	start := time.Now()
	resp, err := c.gen.GetApiJobsWithResponse(ctx, params)
	logCall("ListJobs", start, err)
	if err != nil { return nil, err }
	if resp.JSON200 == nil { return nil, fmt.Errorf("ListJobs: status %d", resp.StatusCode()) }
	return *resp.JSON200, nil
}

func (c *Client) GetJob(ctx context.Context, id string) (*JobRead, error) {
	start := time.Now()
	resp, err := c.gen.GetApiJobsJobIdWithResponse(ctx, id)
	logCall("GetJob", start, err)
	if err != nil { return nil, err }
	if resp.StatusCode() == http.StatusNotFound { return nil, ErrNotFound }
	if resp.JSON200 == nil { return nil, fmt.Errorf("GetJob: status %d", resp.StatusCode()) }
	return resp.JSON200, nil
}

func (c *Client) RetryJob(ctx context.Context, id string) (string, error) {
	start := time.Now()
	resp, err := c.gen.PostApiJobsJobIdRetryWithResponse(ctx, id)
	logCall("RetryJob", start, err)
	if err != nil { return "", err }
	if resp.StatusCode() == http.StatusNotFound { return "", ErrNotFound }
	if resp.JSON201 == nil { return "", fmt.Errorf("RetryJob: status %d", resp.StatusCode()) }
	return resp.JSON201.Id.String(), nil
}

func (c *Client) ListTemplates(ctx context.Context, app string) ([]TemplateRead, error) {
	start := time.Now()
	var params *GetApiTemplatesParams
	if app != "" { params = &GetApiTemplatesParams{App: &app} }
	resp, err := c.gen.GetApiTemplatesWithResponse(ctx, params)
	logCall("ListTemplates", start, err)
	if err != nil { return nil, err }
	if resp.JSON200 == nil { return nil, fmt.Errorf("ListTemplates: status %d", resp.StatusCode()) }
	return *resp.JSON200, nil
}

func (c *Client) RenderPreview(ctx context.Context, key string) ([]byte, error) {
	start := time.Now()
	resp, err := c.gen.PostApiRenderPreviewWithResponse(ctx, PostApiRenderPreviewJSONRequestBody{TemplateKey: key})
	logCall("RenderPreview", start, err)
	if err != nil { return nil, err }
	if resp.StatusCode() == http.StatusNotFound { return nil, ErrNotFound }
	if resp.StatusCode() != http.StatusOK { return nil, fmt.Errorf("RenderPreview: status %d", resp.StatusCode()) }
	return resp.Body, nil
}

func (c *Client) LookupEntity(ctx context.Context, app, id string) (*LookupResult, error) {
	start := time.Now()
	resp, err := c.gen.GetApiLookupAppEntityIdWithResponse(ctx, app, id)
	logCall("LookupEntity", start, err)
	if err != nil { return nil, err }
	if resp.StatusCode() == http.StatusNotFound { return nil, ErrNotFound }
	if resp.StatusCode() == http.StatusUnprocessableEntity { return nil, ErrUnsupportedApp }
	if resp.JSON200 == nil { return nil, fmt.Errorf("LookupEntity: status %d", resp.StatusCode()) }
	return resp.JSON200, nil
}

func (c *Client) CheckHealth(ctx context.Context) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.baseURL+"/healthz", nil)
	if err != nil { return err }
	resp, err := http.DefaultClient.Do(req)
	if err != nil { return err }
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK { return fmt.Errorf("backend healthz: %d", resp.StatusCode) }
	return nil
}
```

- [ ] **Step 6: Run — GREEN**

```bash
go test -race ./internal/api/... -v 2>&1 | tail -5
```

- [ ] **Step 7: Commit**

```bash
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "feat(api): add oapi-codegen config, generate typed client, add wrapper with logging

Refs #22"
```

---

## Task 4: Reverse proxy (`internal/proxy/proxy.go`)

**Files:** `internal/proxy/proxy.go`, `proxy_test.go`

- [ ] **Step 1: Write failing tests**

```go
// frontend/internal/proxy/proxy_test.go
package proxy_test

import (
	"io"; "net/http"; "net/http/httptest"; "strings"; "testing"
	"github.com/strausmann/label-printer-hub/frontend/internal/proxy"
)

func TestProxyForwards(t *testing.T) {
	t.Parallel()
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, `{"ok":true}`)
	}))
	defer backend.Close()
	w := httptest.NewRecorder()
	proxy.New(backend.URL).ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/api/printers", nil))
	if w.Code != http.StatusOK { t.Fatalf("status %d", w.Code) }
	if !strings.Contains(w.Body.String(), `"ok":true`) { t.Error("body not forwarded") }
}

func TestProxyPassesSSEContentType(t *testing.T) {
	t.Parallel()
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		io.WriteString(w, "data: hello\n\n")
		w.(http.Flusher).Flush()
	}))
	defer backend.Close()
	w := httptest.NewRecorder()
	proxy.New(backend.URL).ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/api/events", nil))
	if !strings.HasPrefix(w.Header().Get("Content-Type"), "text/event-stream") {
		t.Errorf("Content-Type = %q", w.Header().Get("Content-Type"))
	}
}

func TestProxyReturns502WhenDown(t *testing.T) {
	t.Parallel()
	w := httptest.NewRecorder()
	proxy.New("http://198.51.100.1:19999").ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/", nil))
	if w.Code != http.StatusBadGateway { t.Errorf("status %d, want 502", w.Code) }
}
```

- [ ] **Step 2: Run — RED**

```bash
go test -race ./internal/proxy/... 2>&1 | head -5
```

- [ ] **Step 3: Create `internal/proxy/proxy.go`**

```go
package proxy

import (
	"log/slog"; "net/http"; "net/http/httputil"; "net/url"
)

// New returns a reverse proxy to backendURL with FlushInterval=-1 (required for SSE).
func New(backendURL string) http.Handler {
	target, err := url.Parse(backendURL)
	if err != nil { panic("proxy.New: " + err.Error()) }
	return &httputil.ReverseProxy{
		Director: func(req *http.Request) {
			req.URL.Scheme = target.Scheme
			req.URL.Host   = target.Host
			req.Host       = target.Host
			req.Header.Del("X-Forwarded-For")
		},
		FlushInterval: -1,
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			slog.Error("proxy error", "path", r.URL.Path, "err", err)
			http.Error(w, "backend unavailable", http.StatusBadGateway)
		},
	}
}
```

- [ ] **Step 4: Run — GREEN + commit**

```bash
go test -race ./internal/proxy/... -v 2>&1 | tail -5
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "feat(ui): add reverse proxy with FlushInterval=-1 for SSE pass-through

Refs #22"
```

---

## Task 5: Dashboard handler + template

**Files:** `handlers/dashboard.go`, `dashboard_test.go`, `web/templates/dashboard.html`

- [ ] **Step 1: Write failing test**

```go
// frontend/internal/handlers/dashboard_test.go
package handlers_test

import (
	"encoding/json"; "net/http"; "net/http/httptest"; "strings"; "testing"; "time"
	"github.com/strausmann/label-printer-hub/frontend/internal/handlers"
)

func printersBackend(t *testing.T) *httptest.Server {
	t.Helper()
	now := time.Now().Format(time.RFC3339)
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/printers" { http.NotFound(w, r); return }
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode([]map[string]any{
			{"id": "aaaaaaaa-0000-0000-0000-000000000001", "name": "PT-P750W",
			 "model": "pt_series", "backend": "tcp",
			 "connection": map[string]any{"host": "198.51.100.10", "port": 9100},
			 "enabled": true, "paused": false, "created_at": now, "updated_at": now},
			{"id": "bbbbbbbb-0000-0000-0000-000000000002", "name": "QL-800",
			 "model": "ql_series", "backend": "tcp",
			 "connection": map[string]any{"host": "198.51.100.11", "port": 9100},
			 "enabled": true, "paused": true, "created_at": now, "updated_at": now},
		})
	}))
}

func TestDashboardOK(t *testing.T) {
	t.Parallel()
	backend := printersBackend(t)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	w   := httptest.NewRecorder()
	ph.Dashboard(w, req)
	if w.Code != http.StatusOK { t.Fatalf("status %d", w.Code) }
	for _, want := range []string{"PT-P750W", "QL-800", "printer-grid"} {
		if !strings.Contains(w.Body.String(), want) { t.Errorf("body missing %q", want) }
	}
}

func TestDashboard503WhenBackendDown(t *testing.T) {
	t.Parallel()
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "gone", http.StatusServiceUnavailable)
	}))
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	w   := httptest.NewRecorder()
	ph.Dashboard(w, req)
	if w.Code != http.StatusServiceUnavailable { t.Errorf("status %d, want 503", w.Code) }
}
```

- [ ] **Step 2: Run — RED**

```bash
go test -race ./internal/handlers/... -run TestDashboard 2>&1 | head -5
```

- [ ] **Step 3: Create `handlers/dashboard.go`**

```go
package handlers

import (
	"net/http"
	"github.com/strausmann/label-printer-hub/frontend/internal/api"
)

type DashboardData struct {
	TemplateData
	Printers []api.PrinterRead
}

func (h *PageHandler) Dashboard(w http.ResponseWriter, r *http.Request) {
	printers, err := h.client.ListPrinters(r.Context())
	if err != nil {
		h.renderError(w, r, http.StatusServiceUnavailable, "Service Unavailable", "Could not reach backend: "+err.Error())
		return
	}
	h.renderPage(w, r, "dashboard", DashboardData{
		TemplateData: TemplateData{Version: h.version, ActiveNav: "dashboard"},
		Printers: printers,
	})
}
```

- [ ] **Step 4: Create `web/templates/dashboard.html`**

```html
{{template "layout" .}}
{{define "title"}}Dashboard — Label Printer Hub{{end}}
{{define "content"}}{{template "dashboard-content" .}}{{end}}

{{define "dashboard-content"}}
<div class="space-y-4">
  <h1 class="text-xl font-semibold text-content">Printers</h1>
  <div id="printer-grid" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
       hx-get="/" hx-trigger="every 30s" hx-select="#printer-grid" hx-target="this" hx-swap="outerHTML">
    {{range .Printers}}
    <div class="rounded-lg border border-surface-border bg-surface-raised p-4 flex flex-col gap-2">
      <div class="flex items-center justify-between">
        <a href="/printers/{{.Id}}" class="font-semibold text-content hover:text-primary">{{.Name}}</a>
        {{if .Paused}}<span class="badge badge-paused">Paused</span>
        {{else if .Enabled}}<span class="badge badge-online">Online</span>
        {{else}}<span class="badge badge-offline">Disabled</span>{{end}}
      </div>
      <p class="text-sm text-content-secondary">{{.Model}} &middot; {{index .Connection "host"}}:{{index .Connection "port"}}</p>
    </div>
    {{else}}<p class="text-content-secondary col-span-full">No printers configured.</p>{{end}}
  </div>
</div>
{{end}}
```

- [ ] **Step 5: Run — GREEN + commit**

```bash
go test -race ./internal/handlers/... -run TestDashboard -v 2>&1 | tail -5
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "feat(ui): dashboard handler and template with 30s HTMX polling

Refs #22"
```

---

## Task 6: Printer detail handler + template + SSE hookup

**Files:** `handlers/printer.go`, `printer_test.go`, `web/templates/printer.html`

- [ ] **Step 1: Add `golang.org/x/sync` + write failing test**

```bash
go get golang.org/x/sync && go mod tidy
```

```go
// frontend/internal/handlers/printer_test.go
package handlers_test

import (
	"encoding/json"; "net/http"; "net/http/httptest"; "strings"; "testing"; "time"
	"github.com/strausmann/label-printer-hub/frontend/internal/handlers"
)

const testPrinterID = "cccccccc-0000-0000-0000-000000000003"

func printerDetailBackend(t *testing.T, id string) *httptest.Server {
	t.Helper()
	now := time.Now().Format(time.RFC3339)
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/api/printers/" + id + "/status":
			json.NewEncoder(w).Encode(map[string]any{"printer_id": id, "online": true, "tape_loaded": "12mm black/clear", "error_state": nil, "captured_at": now})
		case "/api/printers/" + id + "/tape":
			json.NewEncoder(w).Encode(map[string]any{"width_mm": 12})
		case "/api/printers/" + id + "/queue":
			json.NewEncoder(w).Encode([]any{})
		default:
			http.NotFound(w, r)
		}
	}))
}

func TestPrinterDetailOK(t *testing.T) {
	t.Parallel()
	backend := printerDetailBackend(t, testPrinterID)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/printers/"+testPrinterID, nil)
	w   := httptest.NewRecorder()
	ph.PrinterDetailWithID(w, req, testPrinterID)
	if w.Code != http.StatusOK { t.Fatalf("status %d", w.Code) }
	if !strings.Contains(w.Body.String(), "printer-detail") { t.Error("missing printer-detail") }
}

func TestPrinterDetailNotFound(t *testing.T) {
	t.Parallel()
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.NotFound(w, r) }))
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	req := httptest.NewRequest(http.MethodGet, "/printers/no-such", nil)
	w   := httptest.NewRecorder()
	ph.PrinterDetailWithID(w, req, "no-such")
	if w.Code != http.StatusNotFound { t.Errorf("status %d, want 404", w.Code) }
}
```

- [ ] **Step 2: Run — RED**

```bash
go test -race ./internal/handlers/... -run TestPrinterDetail 2>&1 | head -5
```

- [ ] **Step 3: Create `handlers/printer.go`**

```go
package handlers

import (
	"net/http"
	"github.com/go-chi/chi/v5"
	"golang.org/x/sync/errgroup"
	"github.com/strausmann/label-printer-hub/frontend/internal/api"
)

type PrinterDetailData struct {
	TemplateData
	PrinterID string
	Status    *api.PrinterStatus
	Tape      map[string]any
	Queue     []map[string]any
}

func (h *PageHandler) PrinterDetail(w http.ResponseWriter, r *http.Request) {
	h.PrinterDetailWithID(w, r, chi.URLParam(r, "id"))
}

func (h *PageHandler) PrinterDetailWithID(w http.ResponseWriter, r *http.Request, id string) {
	var status *api.PrinterStatus
	var tape   map[string]any
	var queue  []map[string]any
	g, ctx := errgroup.WithContext(r.Context())
	g.Go(func() (err error) { status, err = h.client.GetPrinterStatus(ctx, id); return })
	g.Go(func() (err error) {
		tape, err = h.client.GetPrinterTape(ctx, id)
		if err == api.ErrNotFound { tape = nil; err = nil }
		return
	})
	g.Go(func() (err error) { queue, err = h.client.GetPrinterQueue(ctx, id); return })
	if err := g.Wait(); err != nil {
		code := http.StatusServiceUnavailable
		if err == api.ErrNotFound { code = http.StatusNotFound }
		h.renderError(w, r, code, http.StatusText(code), err.Error())
		return
	}
	h.renderPage(w, r, "printer", PrinterDetailData{
		TemplateData: TemplateData{Version: h.version},
		PrinterID: id, Status: status, Tape: tape, Queue: queue,
	})
}
```

- [ ] **Step 4: Create `web/templates/printer.html`**

```html
{{template "layout" .}}
{{define "title"}}Printer — Label Printer Hub{{end}}
{{define "content"}}{{template "printer-content" .}}{{end}}

{{define "printer-content"}}
<div id="sse-root" hx-ext="sse" sse-connect="/api/events?printer_id={{.PrinterID}}">
  <div class="space-y-6">
    <div id="printer-status-panel" sse-swap="printer.status" hx-swap="innerHTML"
         class="rounded-lg border border-surface-border bg-surface-raised p-4">
      {{if .Status}}
      <div class="flex items-center justify-between">
        <h1 class="text-xl font-semibold text-content">Printer {{.PrinterID}}</h1>
        {{if .Status.Online}}<span class="badge badge-online">Online</span>
        {{else}}<span class="badge badge-offline">Offline</span>{{end}}
      </div>
      {{if .Status.TapeLoaded}}<p class="mt-2 text-sm text-content-secondary">Tape: {{.Status.TapeLoaded}}</p>{{end}}
      {{if .Status.ErrorState}}<p class="mt-1 text-sm text-state-failed">Error: {{.Status.ErrorState}}</p>{{end}}
      {{else}}<p class="text-content-secondary">Status unavailable.</p>{{end}}
    </div>
    <div id="job-queue-panel" sse-swap="job.state_changed" hx-swap="innerHTML"
         class="rounded-lg border border-surface-border bg-surface-raised p-4">
      <h2 class="font-medium text-content mb-3">Active Jobs</h2>
      {{if .Queue}}
      <ul class="space-y-1">{{range .Queue}}
        <li class="flex items-center gap-2 text-sm">
          <span class="badge badge-{{index . "state"}}">{{index . "state"}}</span>
          <a href="/jobs/{{index . "id"}}" class="text-primary hover:underline">{{index . "template_key"}}</a>
        </li>{{end}}
      </ul>
      {{else}}<p class="text-sm text-content-secondary">No active jobs.</p>{{end}}
    </div>
    <div id="tape-panel" sse-swap="printer.tape_changed" hx-swap="innerHTML"></div>
  </div>
</div>
{{end}}
```

- [ ] **Step 5: Run — GREEN + commit**

```bash
go test -race ./internal/handlers/... -run TestPrinterDetail -v 2>&1 | tail -5
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "feat(ui): printer detail handler with errgroup parallel fetch and SSE wiring

Refs #22"
```

---

## Task 7: Jobs list + Task 8: Job detail/retry — implement together

These two tasks share the same mock-backend pattern. Implement them sequentially in one sitting.

### Task 7 — Jobs list

**Files:** `handlers/jobs.go`, `jobs_test.go`, `web/templates/jobs.html`

- [ ] **Step 1: Write failing test**

```go
// frontend/internal/handlers/jobs_test.go
package handlers_test

import (
	"encoding/json"; "net/http"; "net/http/httptest"; "strings"; "testing"; "time"
	"github.com/strausmann/label-printer-hub/frontend/internal/handlers"
)

func jobsBackend(t *testing.T) *httptest.Server {
	t.Helper()
	now := time.Now().Format(time.RFC3339)
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/jobs" { http.NotFound(w, r); return }
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode([]map[string]any{
			{"id": "11111111-0000-0000-0000-000000000001", "printer_id": "aaaaaaaa-0000-0000-0000-000000000001",
			 "template_key": "snipeit-asset", "state": "done", "payload": map[string]any{},
			 "result": nil, "error": nil, "created_at": now, "updated_at": now, "started_at": now, "finished_at": now},
		})
	}))
}

func TestJobsListOK(t *testing.T) {
	t.Parallel()
	backend := jobsBackend(t)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	w  := httptest.NewRecorder()
	ph.JobsList(w, httptest.NewRequest(http.MethodGet, "/jobs", nil))
	if w.Code != http.StatusOK { t.Fatalf("status %d", w.Code) }
	for _, want := range []string{"jobs-table-container", "done"} {
		if !strings.Contains(w.Body.String(), want) { t.Errorf("body missing %q", want) }
	}
}
```

- [ ] **Step 2: Run RED → implement `handlers/jobs.go`**

```go
package handlers

import (
	"net/http"
	"github.com/strausmann/label-printer-hub/frontend/internal/api"
)

type JobsListData struct {
	TemplateData
	Jobs []api.JobRead
	StateFilter, PrinterFilter, NextCursor string
}

func (h *PageHandler) JobsList(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	sf, pf, since := q.Get("state"), q.Get("printer_id"), q.Get("since")
	limit := 50
	params := &api.GetApiJobsParams{Limit: &limit}
	if sf != ""    { params.State     = &sf }
	if pf != ""    { params.PrinterId = &pf }
	if since != "" { params.Since     = &since }
	jobs, err := h.client.ListJobs(r.Context(), params)
	if err != nil { h.renderError(w, r, http.StatusServiceUnavailable, "Service Unavailable", err.Error()); return }
	var next string
	if len(jobs) == limit { next = jobs[len(jobs)-1].CreatedAt.Format("2006-01-02T15:04:05Z07:00") }
	h.renderPage(w, r, "jobs", JobsListData{
		TemplateData: TemplateData{Version: h.version, ActiveNav: "jobs"},
		Jobs: jobs, StateFilter: sf, PrinterFilter: pf, NextCursor: next,
	})
}
```

- [ ] **Step 3: Create `web/templates/jobs.html`**

```html
{{template "layout" .}}
{{define "title"}}Jobs — Label Printer Hub{{end}}
{{define "content"}}{{template "jobs-content" .}}{{end}}

{{define "jobs-content"}}
<div class="space-y-4">
  <div class="flex items-center justify-between">
    <h1 class="text-xl font-semibold text-content">Jobs</h1>
    <form hx-get="/jobs" hx-push-url="true" hx-target="#jobs-table-container" class="flex gap-2">
      <select name="state" class="rounded border border-surface-border px-2 py-1 text-sm">
        <option value="">All states</option>
        <option value="queued"    {{if eq .StateFilter "queued"}}selected{{end}}>Queued</option>
        <option value="printing"  {{if eq .StateFilter "printing"}}selected{{end}}>Printing</option>
        <option value="done"      {{if eq .StateFilter "done"}}selected{{end}}>Done</option>
        <option value="failed"    {{if eq .StateFilter "failed"}}selected{{end}}>Failed</option>
        <option value="cancelled" {{if eq .StateFilter "cancelled"}}selected{{end}}>Cancelled</option>
      </select>
      <button type="submit" class="rounded bg-primary px-3 py-1 text-sm text-primary-fg">Filter</button>
    </form>
  </div>
  <div id="jobs-table-container"
       hx-get="/jobs" hx-trigger="every 30s"
       hx-select="#jobs-table-container" hx-target="this" hx-swap="outerHTML">
    <table class="w-full text-sm border-collapse">
      <thead><tr class="border-b border-surface-border text-left text-content-secondary">
        <th class="py-2 pr-4">State</th><th class="py-2 pr-4">Template</th>
        <th class="py-2 pr-4">Printer</th><th class="py-2">Created</th>
      </tr></thead>
      <tbody>
        {{range .Jobs}}
        <tr class="border-b border-surface-border hover:bg-surface">
          <td class="py-2 pr-4"><span class="badge badge-{{.State}}">{{.State}}</span></td>
          <td class="py-2 pr-4"><a href="/jobs/{{.Id}}" class="text-primary hover:underline">{{.TemplateKey}}</a></td>
          <td class="py-2 pr-4 text-content-secondary font-mono text-xs">{{.PrinterId}}</td>
          <td class="py-2 text-content-secondary">{{.CreatedAt.Format "2006-01-02 15:04"}}</td>
        </tr>
        {{else}}<tr><td colspan="4" class="py-6 text-center text-content-secondary">No jobs found.</td></tr>{{end}}
      </tbody>
    </table>
    {{if .NextCursor}}
    <div class="mt-4">
      <a href="/jobs?since={{.NextCursor}}{{if .StateFilter}}&state={{.StateFilter}}{{end}}"
         class="text-primary hover:underline text-sm">Next page &rarr;</a>
    </div>
    {{end}}
  </div>
</div>
{{end}}
```

- [ ] **Step 4: Run GREEN + commit**

```bash
go test -race ./internal/handlers/... -run TestJobsList -v 2>&1 | tail -5
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "feat(ui): jobs list handler with filter form and cursor-based pagination

Refs #22"
```

### Task 8 — Job detail + retry PRG

**Files:** `handlers/job.go`, `job_test.go`, `web/templates/job.html`

- [ ] **Step 5: Write failing test**

```go
// frontend/internal/handlers/job_test.go
package handlers_test

import (
	"encoding/json"; "net/http"; "net/http/httptest"; "strings"; "testing"; "time"
	"github.com/strausmann/label-printer-hub/frontend/internal/handlers"
)

const (
	jobID    = "22222222-0000-0000-0000-000000000002"
	newJobID = "33333333-0000-0000-0000-000000000003"
)

func jobDetailBackend(t *testing.T) *httptest.Server {
	t.Helper()
	now := time.Now().Format(time.RFC3339)
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch {
		case r.Method == http.MethodGet && r.URL.Path == "/api/jobs/"+jobID:
			json.NewEncoder(w).Encode(map[string]any{
				"id": jobID, "printer_id": "aaaaaaaa-0000-0000-0000-000000000001",
				"template_key": "snipeit-asset", "state": "failed",
				"payload": map[string]any{}, "result": nil, "error": "timeout",
				"created_at": now, "updated_at": now, "started_at": nil, "finished_at": nil,
			})
		case r.Method == http.MethodPost && r.URL.Path == "/api/jobs/"+jobID+"/retry":
			w.WriteHeader(http.StatusCreated)
			json.NewEncoder(w).Encode(map[string]any{
				"id": newJobID, "printer_id": "aaaaaaaa-0000-0000-0000-000000000001",
				"template_key": "snipeit-asset", "state": "queued",
				"payload": map[string]any{}, "result": nil, "error": nil,
				"created_at": now, "updated_at": now, "started_at": nil, "finished_at": nil,
			})
		default:
			http.NotFound(w, r)
		}
	}))
}

func TestJobDetailOK(t *testing.T) {
	t.Parallel()
	backend := jobDetailBackend(t)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	w  := httptest.NewRecorder()
	ph.JobDetailWithID(w, httptest.NewRequest(http.MethodGet, "/jobs/"+jobID, nil), jobID)
	if w.Code != http.StatusOK { t.Fatalf("status %d", w.Code) }
	if !strings.Contains(w.Body.String(), "job-detail") { t.Error("missing job-detail") }
}

func TestJobRetry303(t *testing.T) {
	t.Parallel()
	backend := jobDetailBackend(t)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	w  := httptest.NewRecorder()
	ph.JobRetryWithID(w, httptest.NewRequest(http.MethodPost, "/jobs/"+jobID+"/retry", nil), jobID)
	if w.Code != http.StatusSeeOther { t.Errorf("status %d, want 303", w.Code) }
	if !strings.Contains(w.Header().Get("Location"), newJobID) {
		t.Errorf("Location %q must contain new job ID", w.Header().Get("Location"))
	}
}
```

- [ ] **Step 6: Run RED → implement `handlers/job.go`**

```go
package handlers

import (
	"net/http"
	"github.com/go-chi/chi/v5"
	"github.com/strausmann/label-printer-hub/frontend/internal/api"
)

type JobDetailData struct {
	TemplateData
	Job        *api.JobRead
	IsTerminal bool
}

func (h *PageHandler) JobDetail(w http.ResponseWriter, r *http.Request) {
	h.JobDetailWithID(w, r, chi.URLParam(r, "id"))
}

func (h *PageHandler) JobDetailWithID(w http.ResponseWriter, r *http.Request, id string) {
	job, err := h.client.GetJob(r.Context(), id)
	if err == api.ErrNotFound { h.renderError(w, r, http.StatusNotFound, "Not Found", "Job not found: "+id); return }
	if err != nil { h.renderError(w, r, http.StatusServiceUnavailable, "Service Unavailable", err.Error()); return }
	h.renderPage(w, r, "job", JobDetailData{
		TemplateData: TemplateData{Version: h.version, ActiveNav: "jobs"},
		Job: job,
		IsTerminal: job.State == "done" || job.State == "failed" || job.State == "cancelled",
	})
}

func (h *PageHandler) JobRetry(w http.ResponseWriter, r *http.Request) {
	h.JobRetryWithID(w, r, chi.URLParam(r, "id"))
}

func (h *PageHandler) JobRetryWithID(w http.ResponseWriter, r *http.Request, id string) {
	newID, err := h.client.RetryJob(r.Context(), id)
	if err == api.ErrNotFound { h.renderError(w, r, http.StatusNotFound, "Not Found", "Job not found: "+id); return }
	if err != nil { h.renderError(w, r, http.StatusServiceUnavailable, "Service Unavailable", err.Error()); return }
	http.Redirect(w, r, "/jobs/"+newID, http.StatusSeeOther)
}
```

- [ ] **Step 7: Create `web/templates/job.html`**

```html
{{template "layout" .}}
{{define "title"}}Job — Label Printer Hub{{end}}
{{define "content"}}{{template "job-content" .}}{{end}}

{{define "job-content"}}
{{if .Job}}
<div class="space-y-6">
  <div class="flex items-center justify-between">
    <h1 class="text-xl font-semibold text-content">Job {{.Job.Id}}</h1>
    <span class="badge badge-{{.Job.State}}">{{.Job.State}}</span>
  </div>
  {{if not .IsTerminal}}
  <div id="job-status-row"
       hx-get="/jobs/{{.Job.Id}}" hx-trigger="every 10s"
       hx-select="#job-status-row" hx-target="this" hx-swap="outerHTML">
    <p class="text-sm text-content-secondary">Auto-refreshing&hellip;</p>
  </div>
  {{end}}
  <dl class="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
    <dt class="text-content-secondary">Template</dt>
    <dd><a href="/templates/{{.Job.TemplateKey}}" class="text-primary hover:underline">{{.Job.TemplateKey}}</a></dd>
    <dt class="text-content-secondary">Printer</dt>
    <dd><a href="/printers/{{.Job.PrinterId}}" class="text-primary hover:underline">{{.Job.PrinterId}}</a></dd>
    <dt class="text-content-secondary">Created</dt>
    <dd>{{.Job.CreatedAt.Format "2006-01-02 15:04:05 UTC"}}</dd>
    {{if .Job.Error}}<dt class="text-content-secondary">Error</dt>
    <dd class="text-state-failed">{{.Job.Error}}</dd>{{end}}
  </dl>
  {{if or (eq .Job.State "failed") (eq .Job.State "cancelled")}}
  <form method="post" action="/jobs/{{.Job.Id}}/retry">
    <button type="submit" class="rounded bg-primary px-4 py-2 text-sm text-primary-fg hover:bg-primary-hover">
      Retry Job
    </button>
  </form>
  {{end}}
</div>
{{end}}
{{end}}
```

- [ ] **Step 8: Run GREEN + commit both tasks**

```bash
go test -race ./internal/handlers/... -run "TestJobsList|TestJobDetail|TestJobRetry" -v 2>&1 | tail -5
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "feat(ui): job detail handler with retry PRG (303 See Other to new job)

Refs #22"
```

---

## Task 9: Templates list handler + template

**Files:** `handlers/templates.go`, `templates_test.go`, `web/templates/templates.html`

- [ ] **Step 1: Write failing test → run RED**

```go
// frontend/internal/handlers/templates_test.go
package handlers_test

import (
	"encoding/json"; "net/http"; "net/http/httptest"; "strings"; "testing"; "time"
	"github.com/strausmann/label-printer-hub/frontend/internal/handlers"
)

func templatesBackend(t *testing.T) *httptest.Server {
	t.Helper()
	now := time.Now().Format(time.RFC3339)
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/templates" { http.NotFound(w, r); return }
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode([]map[string]any{
			{"id": "dddddddd-0000-0000-0000-000000000004", "key": "snipeit-asset",
			 "name": "Snipe-IT Asset Label", "app": "snipeit", "printer_model": "pt_series",
			 "tape_width_mm": 12, "schema_version": 1, "definition": map[string]any{},
			 "source": "key: snipeit-asset\n", "created_at": now, "updated_at": now},
		})
	}))
}

func TestTemplatesListOK(t *testing.T) {
	t.Parallel()
	backend := templatesBackend(t)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	w  := httptest.NewRecorder()
	ph.TemplatesList(w, httptest.NewRequest(http.MethodGet, "/templates", nil))
	if w.Code != http.StatusOK { t.Fatalf("status %d", w.Code) }
	for _, want := range []string{"templates-grid", "Snipe-IT Asset Label"} {
		if !strings.Contains(w.Body.String(), want) { t.Errorf("body missing %q", want) }
	}
}
```

- [ ] **Step 2: Implement `handlers/templates.go`**

```go
package handlers

import (
	"net/http"
	"github.com/strausmann/label-printer-hub/frontend/internal/api"
)

type TemplatesListData struct {
	TemplateData
	Templates []api.TemplateRead
	AppFilter string
}

func (h *PageHandler) TemplatesList(w http.ResponseWriter, r *http.Request) {
	app := r.URL.Query().Get("app")
	templates, err := h.client.ListTemplates(r.Context(), app)
	if err != nil { h.renderError(w, r, http.StatusServiceUnavailable, "Service Unavailable", err.Error()); return }
	h.renderPage(w, r, "templates", TemplatesListData{
		TemplateData: TemplateData{Version: h.version, ActiveNav: "templates"},
		Templates: templates, AppFilter: app,
	})
}
```

- [ ] **Step 3: Create `web/templates/templates.html`**

```html
{{template "layout" .}}
{{define "title"}}Templates — Label Printer Hub{{end}}
{{define "content"}}{{template "templates-content" .}}{{end}}

{{define "templates-content"}}
<div class="space-y-4">
  <div class="flex items-center justify-between">
    <h1 class="text-xl font-semibold text-content">Templates</h1>
    <form hx-get="/templates" hx-push-url="true" hx-target="#templates-grid" class="flex gap-2">
      <select name="app" class="rounded border border-surface-border px-2 py-1 text-sm">
        <option value="">All apps</option>
        <option value="snipeit"  {{if eq .AppFilter "snipeit"}}selected{{end}}>Snipe-IT</option>
        <option value="grocy"    {{if eq .AppFilter "grocy"}}selected{{end}}>Grocy</option>
        <option value="spoolman" {{if eq .AppFilter "spoolman"}}selected{{end}}>Spoolman</option>
      </select>
      <button type="submit" class="rounded bg-primary px-3 py-1 text-sm text-primary-fg">Filter</button>
    </form>
  </div>
  <div id="templates-grid" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
       hx-get="/templates" hx-trigger="every 60s"
       hx-select="#templates-grid" hx-target="this" hx-swap="outerHTML">
    {{range .Templates}}
    <a href="/templates/{{.Key}}"
       class="rounded-lg border border-surface-border bg-surface-raised p-4 flex flex-col gap-1 hover:border-primary">
      <div class="flex items-center justify-between">
        <span class="font-medium text-content">{{.Name}}</span>
        {{if .App}}<span class="badge badge-online">{{.App}}</span>{{end}}
      </div>
      <p class="text-sm text-content-secondary">{{.TapeWidthMm}} mm &middot; {{.PrinterModel}}</p>
    </a>
    {{else}}<p class="text-content-secondary col-span-full">No templates found.</p>{{end}}
  </div>
</div>
{{end}}
```

- [ ] **Step 4: Run GREEN + commit**

```bash
go test -race ./internal/handlers/... -run TestTemplatesList -v 2>&1 | tail -5
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "feat(ui): templates list handler with 60s polling and tile grid

Refs #22"
```

---

## Task 10: Template detail handler + template (YAML + base64 preview)

**Files:** `handlers/template.go`, `template_test.go`, `web/templates/template.html`

- [ ] **Step 1: Write failing test → run RED**

```go
// frontend/internal/handlers/template_test.go
package handlers_test

import (
	"encoding/json"; "net/http"; "net/http/httptest"; "strings"; "testing"; "time"
	"github.com/strausmann/label-printer-hub/frontend/internal/handlers"
)

const testTplKey = "snipeit-asset"

func templateDetailBackend(t *testing.T, previewOK bool) *httptest.Server {
	t.Helper()
	now := time.Now().Format(time.RFC3339)
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == http.MethodGet && r.URL.Path == "/api/templates":
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode([]map[string]any{
				{"id": "dddddddd-0000-0000-0000-000000000004", "key": testTplKey,
				 "name": "Snipe-IT Asset Label", "app": "snipeit", "printer_model": "pt_series",
				 "tape_width_mm": 12, "schema_version": 1, "definition": map[string]any{},
				 "source": "key: snipeit-asset\napp: snipeit\n", "created_at": now, "updated_at": now},
			})
		case r.Method == http.MethodPost && r.URL.Path == "/api/render/preview":
			if previewOK { w.Header().Set("Content-Type", "image/png"); w.Write([]byte("\x89PNG\r\n\x1a\n")) } else { http.Error(w, "err", 500) }
		default:
			http.NotFound(w, r)
		}
	}))
}

func TestTemplateDetailOK(t *testing.T) {
	t.Parallel()
	backend := templateDetailBackend(t, true)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	w  := httptest.NewRecorder()
	ph.TemplateDetailWithKey(w, httptest.NewRequest(http.MethodGet, "/templates/"+testTplKey, nil), testTplKey)
	if w.Code != http.StatusOK { t.Fatalf("status %d", w.Code) }
	if !strings.Contains(w.Body.String(), "template-detail") { t.Error("missing template-detail") }
}

func TestTemplateDetailPreviewFallback(t *testing.T) {
	t.Parallel()
	backend := templateDetailBackend(t, false)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	w  := httptest.NewRecorder()
	ph.TemplateDetailWithKey(w, httptest.NewRequest(http.MethodGet, "/templates/"+testTplKey, nil), testTplKey)
	if w.Code != http.StatusOK { t.Fatalf("status %d, want 200 even with failed preview", w.Code) }
}
```

- [ ] **Step 2: Implement `handlers/template.go`**

```go
package handlers

import (
	"context"; "encoding/base64"; "net/http"; "time"
	"github.com/go-chi/chi/v5"
	"github.com/strausmann/label-printer-hub/frontend/internal/api"
)

type TemplateDetailData struct {
	TemplateData
	Template       *api.TemplateRead
	PreviewDataURI string
}

func (h *PageHandler) TemplateDetail(w http.ResponseWriter, r *http.Request) {
	h.TemplateDetailWithKey(w, r, chi.URLParam(r, "id"))
}

func (h *PageHandler) TemplateDetailWithKey(w http.ResponseWriter, r *http.Request, key string) {
	templates, err := h.client.ListTemplates(r.Context(), "")
	if err != nil { h.renderError(w, r, http.StatusServiceUnavailable, "Service Unavailable", err.Error()); return }
	var tmpl *api.TemplateRead
	for i := range templates {
		if templates[i].Key == key { tmpl = &templates[i]; break }
	}
	if tmpl == nil { h.renderError(w, r, http.StatusNotFound, "Not Found", "Template not found: "+key); return }

	previewURI := "/static/preview-placeholder.svg"
	pCtx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if png, err := h.client.RenderPreview(pCtx, key); err == nil && len(png) > 0 {
		previewURI = "data:image/png;base64," + base64.StdEncoding.EncodeToString(png)
	}

	h.renderPage(w, r, "template", TemplateDetailData{
		TemplateData: TemplateData{Version: h.version, ActiveNav: "templates"},
		Template: tmpl, PreviewDataURI: previewURI,
	})
}
```

- [ ] **Step 3: Create `web/templates/template.html`**

```html
{{template "layout" .}}
{{define "title"}}{{if .Template}}{{.Template.Name}}{{else}}Template{{end}} — Label Printer Hub{{end}}
{{define "content"}}{{template "template-content" .}}{{end}}

{{define "template-content"}}
{{if .Template}}
<div id="template-detail" class="space-y-6">
  <div class="flex items-center justify-between">
    <h1 class="text-xl font-semibold text-content">{{.Template.Name}}</h1>
    {{if .Template.App}}<span class="badge badge-online">{{.Template.App}}</span>{{end}}
  </div>
  <dl class="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
    <dt class="text-content-secondary">Key</dt>     <dd class="font-mono">{{.Template.Key}}</dd>
    <dt class="text-content-secondary">Model</dt>   <dd>{{.Template.PrinterModel}}</dd>
    <dt class="text-content-secondary">Tape</dt>    <dd>{{.Template.TapeWidthMm}} mm</dd>
    <dt class="text-content-secondary">Updated</dt> <dd>{{.Template.UpdatedAt.Format "2006-01-02"}}</dd>
  </dl>
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
    <div>
      <h2 class="font-medium text-content mb-2">YAML Source</h2>
      <pre class="rounded bg-surface border border-surface-border p-4 text-xs overflow-x-auto font-mono">{{.Template.Source}}</pre>
    </div>
    <div>
      <h2 class="font-medium text-content mb-2">Preview</h2>
      <img src="{{.PreviewDataURI}}" alt="Label preview" class="rounded border border-surface-border max-w-full">
    </div>
  </div>
</div>
{{end}}
{{end}}
```

- [ ] **Step 4: Run GREEN + commit**

```bash
go test -race ./internal/handlers/... -run TestTemplateDetail -v 2>&1 | tail -5
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "feat(ui): template detail with YAML source and base64 PNG preview (2s timeout)

Refs #22"
```

---

## Task 11: Lookup display handler + template

**Files:** `handlers/lookup.go`, `lookup_test.go`, `web/templates/lookup.html`

- [ ] **Step 1: Write failing test → run RED**

```go
// frontend/internal/handlers/lookup_test.go
package handlers_test

import (
	"encoding/json"; "net/http"; "net/http/httptest"; "strings"; "testing"
	"github.com/strausmann/label-printer-hub/frontend/internal/handlers"
)

func lookupBackend(t *testing.T, app, id string, code int) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/lookup/"+app+"/"+id { http.NotFound(w, r); return }
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(code)
		if code == http.StatusOK {
			json.NewEncoder(w).Encode(map[string]any{"app": app, "id": id, "name": "Test Asset",
				"url": "https://snipeit.example.invalid/hardware/42", "extra": map[string]any{}})
		} else {
			json.NewEncoder(w).Encode(map[string]any{"detail": "not found"})
		}
	}))
}

func TestLookupOK(t *testing.T) {
	t.Parallel()
	backend := lookupBackend(t, "snipeit", "42", http.StatusOK)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	w  := httptest.NewRecorder()
	ph.LookupDisplayWithParams(w, httptest.NewRequest(http.MethodGet, "/lookup/snipeit/42", nil), "snipeit", "42")
	if w.Code != http.StatusOK { t.Fatalf("status %d", w.Code) }
	if !strings.Contains(w.Body.String(), "lookup-result") { t.Error("missing lookup-result") }
}

func TestLookupNotFound(t *testing.T) {
	t.Parallel()
	backend := lookupBackend(t, "snipeit", "999", http.StatusNotFound)
	defer backend.Close()
	ph := handlers.NewPageHandlerFromURL(t, backend.URL)
	w  := httptest.NewRecorder()
	ph.LookupDisplayWithParams(w, httptest.NewRequest(http.MethodGet, "/lookup/snipeit/999", nil), "snipeit", "999")
	if w.Code != http.StatusNotFound { t.Errorf("status %d, want 404", w.Code) }
	if strings.Contains(w.Body.String(), `"detail"`) { t.Error("must not expose raw JSON") }
}
```

- [ ] **Step 2: Implement `handlers/lookup.go`**

```go
package handlers

import (
	"net/http"
	"github.com/go-chi/chi/v5"
	"github.com/strausmann/label-printer-hub/frontend/internal/api"
)

type LookupDisplayData struct {
	TemplateData
	Result *api.LookupResult
	App, ID string
}

func (h *PageHandler) LookupDisplay(w http.ResponseWriter, r *http.Request) {
	h.LookupDisplayWithParams(w, r, chi.URLParam(r, "app"), chi.URLParam(r, "id"))
}

func (h *PageHandler) LookupDisplayWithParams(w http.ResponseWriter, r *http.Request, app, id string) {
	result, err := h.client.LookupEntity(r.Context(), app, id)
	switch err {
	case api.ErrNotFound:
		h.renderError(w, r, http.StatusNotFound, "Not Found", "No entity found for "+app+"/"+id)
	case api.ErrUnsupportedApp:
		h.renderError(w, r, http.StatusUnprocessableEntity, "Unknown Integration", app+" is not supported")
	case nil:
		h.renderPage(w, r, "lookup", LookupDisplayData{
			TemplateData: TemplateData{Version: h.version},
			Result: result, App: app, ID: id,
		})
	default:
		h.renderError(w, r, http.StatusServiceUnavailable, "Service Unavailable", err.Error())
	}
}
```

- [ ] **Step 3: Create `web/templates/lookup.html`**

```html
{{template "layout" .}}
{{define "title"}}Lookup — Label Printer Hub{{end}}
{{define "content"}}{{template "lookup-content" .}}{{end}}

{{define "lookup-content"}}
<div id="lookup-result" class="max-w-lg space-y-4">
  {{if .Result}}
  <div class="rounded-lg border border-surface-border bg-surface-raised p-6 space-y-3">
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-semibold text-content">{{.Result.Name}}</h1>
      <span class="badge badge-online">{{.Result.App}}</span>
    </div>
    <p class="text-sm text-content-secondary">ID: {{.Result.Id}}</p>
    <a href="{{.Result.Url}}" target="_blank" rel="noopener noreferrer"
       class="text-primary hover:underline text-sm">Open in {{.Result.App}} &nearr;</a>
    {{if .Result.Extra}}
    <table class="w-full text-sm border-collapse mt-2"><tbody>
      {{range $k, $v := .Result.Extra}}
      <tr class="border-b border-surface-border">
        <td class="py-1 pr-4 text-content-secondary">{{$k}}</td>
        <td class="py-1 font-mono text-xs">{{$v}}</td>
      </tr>{{end}}
    </tbody></table>
    {{end}}
  </div>
  {{end}}
</div>
{{end}}
```

- [ ] **Step 4: Run GREEN + commit**

```bash
go test -race ./internal/handlers/... -run TestLookup -v 2>&1 | tail -5
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "feat(ui): lookup display handler with styled 404 (no raw JSON)

Refs #22"
```

---

## Task 12: Extended healthz + wire all routes in `main.go`

**Files:** `handlers/healthz.go`; modify `cmd/server/main.go`, `cmd/server/main_test.go`

- [ ] **Step 1: Create `handlers/healthz.go`**

```go
package handlers

import (
	"context"; "encoding/json"; "net/http"; "time"
)

type HealthzResponse struct {
	Status           string `json:"status"`
	Version          string `json:"version"`
	Repository       string `json:"repository"`
	BackendReachable bool   `json:"backend_reachable"`
	BackendLatencyMs int64  `json:"backend_latency_ms,omitempty"`
	BackendError     string `json:"backend_error,omitempty"`
}

func (h *PageHandler) Healthz(w http.ResponseWriter, r *http.Request) {
	resp := HealthzResponse{Status: "ok", Version: h.version, Repository: "https://github.com/strausmann/label-printer-hub"}
	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
	defer cancel()
	start := time.Now()
	if err := h.client.CheckHealth(ctx); err == nil {
		resp.BackendReachable = true
		resp.BackendLatencyMs = time.Since(start).Milliseconds()
	} else {
		resp.BackendError = err.Error()
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}
```

- [ ] **Step 2: Replace `newRouter` and update `main()` in `cmd/server/main.go`**

Replace the existing `newRouter` with:

```go
func newRouter(ph *handlers.PageHandler, prx http.Handler, staticSubFS fs.FS) *chi.Mux {
	r := chi.NewRouter()
	r.Use(middleware.RequestID, middleware.RealIP, middleware.Recoverer, slogRequestLogger)

	r.Handle("/static/*", http.StripPrefix("/static/", http.FileServer(http.FS(staticSubFS))))
	r.Get("/",                  ph.Dashboard)
	r.Get("/printers/{id}",     ph.PrinterDetail)
	r.Get("/jobs",              ph.JobsList)
	r.Get("/jobs/{id}",         ph.JobDetail)
	r.Post("/jobs/{id}/retry",  ph.JobRetry)
	r.Get("/templates",         ph.TemplatesList)
	r.Get("/templates/{id}",    ph.TemplateDetail)
	r.Get("/lookup/{app}/{id}", ph.LookupDisplay)
	r.Get("/healthz",           ph.Healthz)

	r.Mount("/api",     http.StripPrefix("/api", prx))
	r.Mount("/loc",     prx)
	r.Mount("/asset",   prx)
	r.Mount("/spool",   prx)
	r.Mount("/product", prx)
	return r
}
```

Update `main()` startup:

```go
func main() {
	buildInfo = loadBuildInfo()
	backendURL := envDefault("BACKEND_URL", "http://backend:8000")

	tmpl, err := template.ParseFS(templateFS, "web/templates/*.html")
	if err != nil { slog.Error("templates", "err", err); os.Exit(1) }

	client         := api.NewClient(backendURL)
	ph             := handlers.NewPageHandler(tmpl, client, buildInfo.Version)
	prx            := proxy.New(backendURL)
	staticSubFS, _ := fs.Sub(staticFS, "web/static")
	r := newRouter(ph, prx, staticSubFS)
	// ... rest of main unchanged (srv, signals, ListenAndServe)
}
```

Add imports: `"html/template"`, `"io/fs"`, and packages for `api`, `handlers`, `proxy`.
Remove the old standalone `healthzHandler` function.

- [ ] **Step 3: Add routing integration test to `main_test.go`**

```go
func TestRoutesDashboard(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/api/printers": fmt.Fprint(w, `[]`)
		case "/healthz":      fmt.Fprint(w, `{"status":"ok"}`)
		default:              http.NotFound(w, r)
		}
	}))
	defer backend.Close()

	buildInfo = loadBuildInfo()
	tmpl, _ := template.ParseFS(templateFS, "web/templates/*.html")
	ph       := handlers.NewPageHandler(tmpl, api.NewClient(backend.URL), "0.0.0-test")
	prx      := proxy.New(backend.URL)
	sub, _   := fs.Sub(staticFS, "web/static")
	r        := newRouter(ph, prx, sub)

	for _, path := range []string{"/", "/healthz"} {
		req := httptest.NewRequest(http.MethodGet, path, nil)
		w   := httptest.NewRecorder()
		r.ServeHTTP(w, req)
		if w.Code != http.StatusOK { t.Errorf("GET %s = %d, want 200", path, w.Code) }
	}
}
```

- [ ] **Step 4: Run full test suite**

```bash
go test -race ./... 2>&1 | tail -10
# Expected: all PASS
```

- [ ] **Step 5: Commit**

```bash
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "feat(ui): wire all routes in main.go + extended /healthz with backend_reachable

Refs #22"
```

---

## Task 13: Final verify + CI drift check + PR prep

**Files:** Modify `.github/workflows/ci.yml`, `frontend/README.md`

- [ ] **Step 1: Docker builds both architectures**

```bash
docker build --platform linux/amd64 . -t lph-frontend:phase7a-amd64
docker build --platform linux/arm64 . -t lph-frontend:phase7a-arm64
docker run --rm -d -p 18080:8080 --name lph-test lph-frontend:phase7a-amd64
sleep 2
curl -sf http://localhost:18080/healthz
# Expected: {"status":"ok","backend_reachable":false,...}
docker stop lph-test
```

- [ ] **Step 2: Coverage check**

```bash
go test -race -coverprofile=coverage.out ./...
go tool cover -func coverage.out | grep "total:"
# Expected: ≥ 70%
```

- [ ] **Step 3: Static analysis**

```bash
go vet ./...
# Expected: no output
```

- [ ] **Step 4: Add `oapi-codegen-drift` CI job to `.github/workflows/ci.yml`**

```yaml
  oapi-codegen-drift:
    name: Check oapi-codegen output is up to date
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with:
          go-version-file: frontend/go.mod
      - name: Regenerate client
        working-directory: frontend
        run: make gen-client
      - name: Fail if generated file differs
        run: git diff --exit-code frontend/internal/api/client.gen.go
```

- [ ] **Step 5: Placeholder scan**

```bash
git diff main..HEAD -- '*.go' '*.html' '*.css' '*.yaml' '*.yml' \
  | grep -iE "TBD|similar to|implement later|implement appropriately" \
  && echo "FOUND — fix before PR" || echo "clean"
```

- [ ] **Step 6: Final commit**

```bash
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "ci: add oapi-codegen drift check; docs: add local dev guide to frontend README

Refs #22"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §3.1 pages (7 routes) | T5–T11 |
| §4.1 layout.html | T1 |
| §4.2 @theme tokens | T0 |
| §5.1 base.go | T2 |
| §5.2 proxy.go | T4 |
| §5.3 route registration | T12 |
| §6 Tailwind Dockerfile | T0 |
| §6.5 vendored JS assets | T1 |
| §7 HTMX wiring (polling + SSE) | T5–T11 templates |
| §8 SSE proxy semantics | T4 |
| §9.2 `//go:embed` | T2 |
| §9.4 `oapi-codegen` CI drift | T13 |
| §10 tests | T2–T12 |
| §11.1 extended /healthz | T12 |
| §11.2 structured logging | T3 (`logCall`) |

**Placeholder scan:** No "TBD", "similar to", "implement later", or "implement appropriately" in this plan.

**Type consistency:**
- `TemplateData` defined T2, embedded in all data structs T5–T12.
- `PageHandler{tmpl, client, version}` established in T2; `client` field available from the start.
- `api.ErrNotFound` / `api.ErrUnsupportedApp` defined T3, used in T6, T8, T11.
- `*WithID` / `*WithKey` / `*WithParams` testable variants defined per handler, chi methods delegate to them.
- `stubTemplates` in `base.go` includes all `<name>-content` defines for T5–T11.

**Generated client note:** Method names in `client.go` (e.g. `GetApiPrintersWithResponse`) are derived from the OpenAPI spec at generation time. After `make gen-client`, verify each name in `client.gen.go` and adjust `client.go` if they differ.
