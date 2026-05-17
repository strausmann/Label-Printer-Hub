package handlers

import (
	"context"
	"encoding/base64"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/strausmann/label-printer-hub/frontend/internal/api"
)

// TemplateDetailData holds the template variables for the template detail page.
type TemplateDetailData struct {
	TemplateData
	Template   *api.TemplateRead
	PreviewURI string // base64 data URI or /static/preview-placeholder.svg
	YAMLSource string // raw YAML source for display in <pre>
}

// TemplateDetail handles GET /templates/{id}. It reads the template key from
// the chi URL param and delegates to TemplateDetailWithKey.
func (h *PageHandler) TemplateDetail(w http.ResponseWriter, r *http.Request) {
	h.TemplateDetailWithKey(w, r, chi.URLParam(r, "id"))
}

// TemplateDetailWithKey fetches the template from the backend by key (filtering
// from the full list) and renders the template detail page with YAML source and
// a base64-embedded preview image. Exported so integration tests can supply
// the key directly.
func (h *PageHandler) TemplateDetailWithKey(w http.ResponseWriter, r *http.Request, key string) {
	if key == "" {
		h.renderError(w, r, http.StatusBadRequest, "Bad Request", "template key is required")
		return
	}

	// Fetch all templates and filter by key (the backend list endpoint supports
	// key-based filtering via ?app= but not ?key=; we fetch all and filter
	// client-side. Template lists are small — typically < 100 entries).
	templates, err := h.client.ListTemplates(r.Context(), "")
	if err != nil {
		h.renderError(w, r, http.StatusServiceUnavailable, "Service Unavailable", err.Error())
		return
	}

	var found *api.TemplateRead
	for i := range templates {
		if templates[i].Key == key {
			found = &templates[i]
			break
		}
	}
	if found == nil {
		h.renderError(w, r, http.StatusNotFound, "Not Found", "Template not found: "+key)
		return
	}

	// Request a preview PNG from the backend's render endpoint.
	// A 2-second sub-context timeout prevents a slow render from blocking the page.
	previewURI := "/static/preview-placeholder.svg"
	previewCtx, previewCancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer previewCancel()
	previewBytes, previewErr := h.client.RenderPreview(previewCtx, key)
	if previewErr == nil && len(previewBytes) > 0 {
		previewURI = "data:image/png;base64," + base64.StdEncoding.EncodeToString(previewBytes)
	}

	h.renderPage(w, r, "template", TemplateDetailData{
		TemplateData: TemplateData{Version: h.version, ActiveNav: "templates"},
		Template:     found,
		PreviewURI:   previewURI,
		YAMLSource:   found.Source,
	})
}
