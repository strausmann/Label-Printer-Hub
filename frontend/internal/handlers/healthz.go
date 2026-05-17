// Package handlers — healthz endpoint with backend reachability probe.
package handlers

import (
	"context"
	"encoding/json"
	"net/http"
	"time"
)

// HealthzResponse is the JSON shape returned by GET /healthz.
//
// It extends the build-info fields (Version, Repository) with a live
// backend-reachability probe so container orchestrators and monitoring tools
// can distinguish "frontend up, backend down" from "frontend up, backend ok".
type HealthzResponse struct {
	Status           string `json:"status"`
	Version          string `json:"version"`
	Repository       string `json:"repository"`
	BackendReachable bool   `json:"backend_reachable"`
	BackendLatencyMs int64  `json:"backend_latency_ms,omitempty"`
	BackendError     string `json:"backend_error,omitempty"`
}

// Healthz handles GET /healthz.
//
// It always returns 200 — the frontend itself is healthy if it can serve this
// response. The backend_reachable field tells callers whether the backend was
// reachable at the time of the probe. A 3-second timeout prevents this probe
// from blocking normal health-check cadences.
func (h *PageHandler) Healthz(w http.ResponseWriter, r *http.Request) {
	resp := HealthzResponse{
		Status:     "ok",
		Version:    h.version,
		Repository: "https://github.com/strausmann/label-printer-hub",
	}

	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
	defer cancel()

	start := time.Now()
	if h.client != nil {
		if err := h.client.CheckHealth(ctx); err == nil {
			resp.BackendReachable = true
			resp.BackendLatencyMs = time.Since(start).Milliseconds()
		} else {
			resp.BackendError = err.Error()
		}
	}

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(resp); err != nil {
		// Encoding a fixed-shape struct should never fail.
		// If it does the connection is dead — nothing useful we can write.
		_ = err
	}
}
