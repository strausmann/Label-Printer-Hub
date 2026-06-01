package handlers

import (
	"errors"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/strausmann/label-printer-hub/frontend/internal/api"
)

// LookupDisplayData holds the template variables for the lookup display page.
type LookupDisplayData struct {
	TemplateData
	Result *api.LookupResult
	App    string
	ID     string
}

// LookupDisplay handles GET /lookup/{app}/{id}. It reads the app and entity ID
// from the chi URL params and delegates to LookupDisplayWithParams.
func (h *PageHandler) LookupDisplay(w http.ResponseWriter, r *http.Request) {
	h.LookupDisplayWithParams(w, r, chi.URLParam(r, "app"), chi.URLParam(r, "id"))
}

// LookupDisplayWithParams resolves the entity via the backend API and renders
// the lookup display page. Exported so integration tests can supply params
// directly without URL parsing.
func (h *PageHandler) LookupDisplayWithParams(w http.ResponseWriter, r *http.Request, app, id string) {
	result, err := h.client.WithAuthFrom(r).LookupEntity(r.Context(), app, id)
	switch {
	case errors.Is(err, api.ErrNotFound):
		h.renderError(w, r, http.StatusNotFound, "Not Found",
			"Entity not found: "+app+"/"+id)
		return
	case errors.Is(err, api.ErrUnsupportedApp):
		h.renderError(w, r, http.StatusUnprocessableEntity, "Unprocessable Entity",
			"Unknown integration: "+app)
		return
	case err != nil:
		h.renderError(w, r, http.StatusServiceUnavailable, "Service Unavailable", err.Error())
		return
	}

	h.renderPage(w, r, "lookup", LookupDisplayData{
		TemplateData: TemplateData{Version: h.version, ActiveNav: ""},
		Result:       result,
		App:          app,
		ID:           id,
	})
}
