package handlers

import (
	"errors"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/strausmann/label-printer-hub/frontend/internal/api"
	"golang.org/x/sync/errgroup"
)

// PrinterDetailData holds the template variables for the printer detail page.
type PrinterDetailData struct {
	TemplateData
	PrinterID string
	Status    *api.PrinterStatus
	Tape      map[string]any
	Queue     []map[string]any
}

// PrinterDetail handles GET /printers/{id}. It reads the printer ID from the
// chi URL param and delegates to PrinterDetailWithID.
func (h *PageHandler) PrinterDetail(w http.ResponseWriter, r *http.Request) {
	h.PrinterDetailWithID(w, r, chi.URLParam(r, "id"))
}

// PrinterDetailWithID fetches printer status, tape, and queue in parallel using
// errgroup and renders the printer detail template.
// Exported so integration tests can call it directly with a known ID.
func (h *PageHandler) PrinterDetailWithID(w http.ResponseWriter, r *http.Request, id string) {
	var (
		status *api.PrinterStatus
		tape   map[string]any
		queue  []map[string]any
	)

	g, ctx := errgroup.WithContext(r.Context())

	g.Go(func() (err error) {
		status, err = h.client.GetPrinterStatus(ctx, id)
		return
	})
	g.Go(func() (err error) {
		tape, err = h.client.GetPrinterTape(ctx, id)
		// Tape absent is non-fatal (e.g. not yet measured).
		if errors.Is(err, api.ErrNotFound) {
			tape = nil
			err = nil
		}
		return
	})
	g.Go(func() (err error) {
		queue, err = h.client.GetPrinterQueue(ctx, id)
		return
	})

	if err := g.Wait(); err != nil {
		code := http.StatusServiceUnavailable
		if errors.Is(err, api.ErrNotFound) {
			code = http.StatusNotFound
		}
		h.renderError(w, r, code, http.StatusText(code), err.Error())
		return
	}

	h.renderPage(w, r, "printer", PrinterDetailData{
		TemplateData: TemplateData{Version: h.version},
		PrinterID:    id,
		Status:       status,
		Tape:         tape,
		Queue:        queue,
	})
}
