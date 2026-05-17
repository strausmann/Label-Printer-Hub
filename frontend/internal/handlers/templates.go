package handlers

import (
	"net/http"

	"github.com/strausmann/label-printer-hub/frontend/internal/api"
)

// TemplatesListData holds the template variables for the templates list page.
type TemplatesListData struct {
	TemplateData
	Templates []api.TemplateRead
	AppFilter string
}

// TemplatesList handles GET /templates. It reads the optional ?app= query param
// and delegates to TemplatesListWithApp.
func (h *PageHandler) TemplatesList(w http.ResponseWriter, r *http.Request) {
	h.TemplatesListWithApp(w, r, r.URL.Query().Get("app"))
}

// TemplatesListWithApp fetches templates from the backend, optionally filtered by app,
// and renders the templates list template. Exported so integration tests can supply
// the app filter directly without URL parsing.
func (h *PageHandler) TemplatesListWithApp(w http.ResponseWriter, r *http.Request, app string) {
	templates, err := h.client.ListTemplates(r.Context(), app)
	if err != nil {
		h.renderError(w, r, http.StatusServiceUnavailable, "Service Unavailable", err.Error())
		return
	}

	h.renderPage(w, r, "templates", TemplatesListData{
		TemplateData: TemplateData{Version: h.version, ActiveNav: "templates"},
		Templates:    templates,
		AppFilter:    app,
	})
}
