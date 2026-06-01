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
	Printer   *api.PrinterRead   // metadata from GET /api/printers/{id}
	Status    *api.PrinterStatus
	Tape      map[string]any
	Queue     []map[string]any
}

// PrinterDetail handles GET /printers/{id}. It reads the printer ID from the
// chi URL param and delegates to PrinterDetailWithID.
func (h *PageHandler) PrinterDetail(w http.ResponseWriter, r *http.Request) {
	h.PrinterDetailWithID(w, r, chi.URLParam(r, "id"))
}

// PrinterDetailWithID fetches printer detail, status, tape, and queue in parallel
// using errgroup and renders the printer detail template.
// Exported so integration tests can call it directly with a known ID.
func (h *PageHandler) PrinterDetailWithID(w http.ResponseWriter, r *http.Request, id string) {
	var (
		printer *api.PrinterRead
		status  *api.PrinterStatus
		tape    map[string]any
		queue   []map[string]any
	)

	authClient := h.client.WithAuthFrom(r)
	g, ctx := errgroup.WithContext(r.Context())

	g.Go(func() (err error) {
		printer, err = authClient.GetPrinterDetail(ctx, id)
		return
	})
	g.Go(func() (err error) {
		status, err = authClient.GetPrinterStatus(ctx, id)
		// Status may be a 404 on unknown printer; also non-fatal when just unavailable.
		if errors.Is(err, api.ErrNotFound) {
			status = nil
			err = nil
		}
		return
	})
	g.Go(func() (err error) {
		tape, err = authClient.GetPrinterTape(ctx, id)
		// Tape absent is non-fatal (e.g. not yet measured).
		if errors.Is(err, api.ErrNotFound) {
			tape = nil
			err = nil
		}
		return
	})
	g.Go(func() (err error) {
		queue, err = authClient.GetPrinterQueue(ctx, id)
		// Queue absent is non-fatal.
		if errors.Is(err, api.ErrNotFound) {
			queue = nil
			err = nil
		}
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

	// If the printer detail itself was not found, return 404.
	if printer == nil {
		h.renderError(w, r, http.StatusNotFound, "Not Found", "printer not found: "+id)
		return
	}

	h.renderPage(w, r, "printer", PrinterDetailData{
		TemplateData: TemplateData{Version: h.version, ActiveNav: "dashboard"},
		PrinterID:    id,
		Printer:      printer,
		Status:       status,
		Tape:         tape,
		Queue:        queue,
	})
}
