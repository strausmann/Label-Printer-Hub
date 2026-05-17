package handlers

import (
	"net/http"
	"time"

	openapi_types "github.com/oapi-codegen/runtime/types"
	"github.com/strausmann/label-printer-hub/frontend/internal/api"
)

// JobsListData holds the template variables for the jobs list page.
type JobsListData struct {
	TemplateData
	Jobs          []api.JobRead
	StateFilter   string
	PrinterFilter string
	NextCursor    string
}

// JobsList handles GET /jobs — paginated list with state and printer filters.
func (h *PageHandler) JobsList(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	stateFilter := q.Get("state")
	// printer_id is accepted as a URL query parameter (?printer_id=<uuid>) for
	// programmatic / bookmarked use. The jobs UI only exposes the state filter;
	// a printer-id dropdown is deferred to a later phase because it requires
	// fetching the printer list on the jobs page — adding an extra backend call.
	printerFilter := q.Get("printer_id")
	sinceRaw := q.Get("since")

	const pageSize = 50
	limit := pageSize
	params := &api.ListJobsApiJobsGetParams{Limit: &limit}

	if stateFilter != "" {
		sf := stateFilter
		params.State = &sf
	}
	if printerFilter != "" {
		var uid openapi_types.UUID
		if err := uid.UnmarshalText([]byte(printerFilter)); err == nil {
			params.PrinterId = &uid
		}
		// Ignore unparseable UUIDs — backend will return all jobs.
	}
	if sinceRaw != "" {
		if t, err := time.Parse(time.RFC3339, sinceRaw); err == nil {
			params.Since = &t
		}
	}

	jobs, err := h.client.ListJobs(r.Context(), params)
	if err != nil {
		h.renderError(w, r, http.StatusServiceUnavailable, "Service Unavailable", err.Error())
		return
	}

	// Cursor pagination: if we received a full page, the last job's
	// created_at becomes the ?since= cursor for the next page.
	var nextCursor string
	if len(jobs) == pageSize {
		nextCursor = jobs[len(jobs)-1].CreatedAt.UTC().Format(time.RFC3339)
	}

	h.renderPage(w, r, "jobs", JobsListData{
		TemplateData:  TemplateData{Version: h.version, ActiveNav: "jobs"},
		Jobs:          jobs,
		StateFilter:   stateFilter,
		PrinterFilter: printerFilter,
		NextCursor:    nextCursor,
	})
}
