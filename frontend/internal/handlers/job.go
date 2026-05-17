package handlers

import (
	"errors"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/strausmann/label-printer-hub/frontend/internal/api"
)

// JobDetailData holds the template variables for the job detail page.
type JobDetailData struct {
	TemplateData
	Job        *api.JobRead
	IsTerminal bool // true when state is done / failed / cancelled
}

// JobDetail handles GET /jobs/{id}. It reads the job ID from the chi URL param
// and delegates to JobDetailWithID.
func (h *PageHandler) JobDetail(w http.ResponseWriter, r *http.Request) {
	h.JobDetailWithID(w, r, chi.URLParam(r, "id"))
}

// JobDetailWithID fetches the job from the backend and renders the job detail
// template. Exported so integration tests can supply the ID directly.
func (h *PageHandler) JobDetailWithID(w http.ResponseWriter, r *http.Request, id string) {
	job, err := h.client.GetJob(r.Context(), id)
	if errors.Is(err, api.ErrNotFound) {
		h.renderError(w, r, http.StatusNotFound, "Not Found", "Job not found: "+id)
		return
	}
	if err != nil {
		h.renderError(w, r, http.StatusServiceUnavailable, "Service Unavailable", err.Error())
		return
	}

	isTerminal := job.State == "done" || job.State == "failed" || job.State == "cancelled"

	h.renderPage(w, r, "job", JobDetailData{
		TemplateData: TemplateData{Version: h.version, ActiveNav: "jobs"},
		Job:          job,
		IsTerminal:   isTerminal,
	})
}

// JobRetry handles POST /jobs/{id}/retry. It calls the backend retry endpoint
// and redirects (PRG pattern) to the new job's detail page with 303 See Other.
func (h *PageHandler) JobRetry(w http.ResponseWriter, r *http.Request) {
	h.JobRetryWithID(w, r, chi.URLParam(r, "id"))
}

// JobRetryWithID is the testable implementation of JobRetry.
// It clones the job via the API and issues a 303 redirect to /jobs/{newID}.
func (h *PageHandler) JobRetryWithID(w http.ResponseWriter, r *http.Request, id string) {
	newID, err := h.client.RetryJob(r.Context(), id)
	if errors.Is(err, api.ErrNotFound) {
		h.renderError(w, r, http.StatusNotFound, "Not Found", "Job not found: "+id)
		return
	}
	if err != nil {
		h.renderError(w, r, http.StatusServiceUnavailable, "Service Unavailable", err.Error())
		return
	}
	http.Redirect(w, r, "/jobs/"+newID, http.StatusSeeOther)
}
