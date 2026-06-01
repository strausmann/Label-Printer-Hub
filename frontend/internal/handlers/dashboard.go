package handlers

import (
	"net/http"

	"github.com/strausmann/label-printer-hub/frontend/internal/api"
)

// DashboardData holds the template variables for the dashboard page.
type DashboardData struct {
	TemplateData
	// Printers is the current list of registered printers. Each card in the
	// printer grid is rendered from one entry.
	Printers []api.PrinterRead
}

// Dashboard handles GET / — the main dashboard showing all printers.
//
// It fetches the printer list from the backend, renders the "dashboard"
// template (full page on first load, fragment-only on HTMX refresh), and
// returns 503 Service Unavailable if the backend is unreachable.
func (h *PageHandler) Dashboard(w http.ResponseWriter, r *http.Request) {
	printers, err := h.client.WithAuthFrom(r).ListPrinters(r.Context())
	if err != nil {
		h.renderError(w, r,
			http.StatusServiceUnavailable,
			"Service Unavailable",
			"Could not reach backend: "+err.Error(),
		)
		return
	}
	h.renderPage(w, r, "dashboard", DashboardData{
		TemplateData: TemplateData{
			Version:   h.version,
			ActiveNav: "dashboard",
		},
		Printers: printers,
	})
}
