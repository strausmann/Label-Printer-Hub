package handlers

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"

	"github.com/go-chi/chi/v5"
)

// AdminAPIKeyListData holds variables for the /admin/api-keys list page.
type AdminAPIKeyListData struct {
	TemplateData
	Keys []APIKeyMeta
}

// AdminAPIKeyCreateData holds variables for the /admin/api-keys/new page.
type AdminAPIKeyCreateData struct {
	TemplateData
	Plaintext string
	Prefix    string
	Error     string
}

// AdminAPIKeyDetailData holds variables for the /admin/api-keys/{id} page.
type AdminAPIKeyDetailData struct {
	TemplateData
	Key APIKeyMeta
}

// APIKeyMeta is the front-end representation of an API key (no hash/plaintext).
type APIKeyMeta struct {
	Id                 string
	Name               string
	KeyPrefix          string
	Scopes             []string
	AllowedPrinterIds  []string
	RateLimitPerMinute int
	Enabled            bool
	CreatedAt          string
	LastUsedAt         *string
	LastUsedIp         *string
	ExpiresAt          *string
	Notes              *string
}

// AdminAPIKeysList handles GET /admin/api-keys — Auflistung aller Keys.
func (h *PageHandler) AdminAPIKeysList(w http.ResponseWriter, r *http.Request) {
	keys, err := h.listAPIKeys(r)
	if err != nil {
		h.renderError(w, r, http.StatusServiceUnavailable, "Service Unavailable", err.Error())
		return
	}
	h.renderPage(w, r, "admin_api_keys", AdminAPIKeyListData{
		TemplateData: h.baseData(r, "admin-api-keys"),
		Keys:         keys,
	})
}

// AdminAPIKeysNew handles GET /admin/api-keys/new — Erstell-Formular anzeigen.
func (h *PageHandler) AdminAPIKeysNew(w http.ResponseWriter, r *http.Request) {
	h.renderPage(w, r, "admin_api_keys_create", AdminAPIKeyCreateData{
		TemplateData: h.baseData(r, "admin-api-keys"),
	})
}

// AdminAPIKeysCreate handles POST /admin/api-keys/new — neuen Key erstellen.
// CSRF-Token wird von gorilla/csrf vor dem Handler-Aufruf validiert.
func (h *PageHandler) AdminAPIKeysCreate(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseForm(); err != nil {
		h.renderError(w, r, http.StatusBadRequest, "Bad Request", err.Error())
		return
	}

	name := r.FormValue("name")
	scopes := r.Form["scopes"]
	rateLimitStr := r.FormValue("rate_limit_per_minute")
	notes := r.FormValue("notes")

	if len(scopes) == 0 {
		scopes = []string{"read"}
	}
	rateLimit := 60
	if _, err := fmt.Sscanf(rateLimitStr, "%d", &rateLimit); err != nil || rateLimit < 1 {
		rateLimit = 60
	}

	payload := map[string]interface{}{
		"name":                  name,
		"scopes":                scopes,
		"allowed_printer_ids":   []string{},
		"rate_limit_per_minute": rateLimit,
	}
	if notes != "" {
		payload["notes"] = notes
	}

	plaintext, prefix, apiErr := h.createAPIKey(r, payload)
	if apiErr != nil {
		h.renderPage(w, r, "admin_api_keys_create", AdminAPIKeyCreateData{
			TemplateData: h.baseData(r, "admin-api-keys"),
			Error:        apiErr.Error(),
		})
		return
	}

	h.renderPage(w, r, "admin_api_keys_create", AdminAPIKeyCreateData{
		TemplateData: h.baseData(r, "admin-api-keys"),
		Plaintext:    plaintext,
		Prefix:       prefix,
	})
}

// AdminAPIKeyDetail handles GET /admin/api-keys/{id} — Key-Detailansicht.
func (h *PageHandler) AdminAPIKeyDetail(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	key, err := h.getAPIKey(r, id)
	if err != nil {
		h.renderError(w, r, http.StatusNotFound, "Not Found", err.Error())
		return
	}
	h.renderPage(w, r, "admin_api_keys_detail", AdminAPIKeyDetailData{
		TemplateData: h.baseData(r, "admin-api-keys"),
		Key:          *key,
	})
}

// AdminAPIKeyRevoke handles POST /admin/api-keys/{id}/revoke — Key widerrufen.
// CSRF-Token wird von gorilla/csrf vor dem Handler-Aufruf validiert.
func (h *PageHandler) AdminAPIKeyRevoke(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	if err := h.revokeAPIKey(r, id); err != nil {
		h.renderError(w, r, http.StatusInternalServerError, "Error", err.Error())
		return
	}
	http.Redirect(w, r, "/admin/api-keys", http.StatusSeeOther)
}

// --------------------------------------------------------------------------
// Backend API helpers — raw HTTP calls to /api/admin/api-keys/*
// --------------------------------------------------------------------------

func (h *PageHandler) listAPIKeys(r *http.Request) ([]APIKeyMeta, error) {
	req, err := http.NewRequestWithContext(r.Context(), http.MethodGet,
		h.backendURL()+"/api/admin/api-keys", nil)
	if err != nil {
		return nil, err
	}
	h.forwardAuth(r, req)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("backend returned %d: %s", resp.StatusCode, string(body))
	}
	var keys []APIKeyMeta
	if err := json.Unmarshal(body, &keys); err != nil {
		return nil, fmt.Errorf("parse response: %w", err)
	}
	return keys, nil
}

func (h *PageHandler) createAPIKey(r *http.Request, payload map[string]interface{}) (string, string, error) {
	data, _ := json.Marshal(payload)
	req, err := http.NewRequestWithContext(r.Context(), http.MethodPost,
		h.backendURL()+"/api/admin/api-keys", bytes.NewReader(data))
	if err != nil {
		return "", "", err
	}
	req.Header.Set("Content-Type", "application/json")
	h.forwardAuth(r, req)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", "", err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusCreated {
		return "", "", fmt.Errorf("backend returned %d: %s", resp.StatusCode, string(body))
	}
	var result struct {
		Plaintext string `json:"plaintext"`
		Prefix    string `json:"prefix"`
	}
	if err := json.Unmarshal(body, &result); err != nil {
		return "", "", fmt.Errorf("parse response: %w", err)
	}
	return result.Plaintext, result.Prefix, nil
}

func (h *PageHandler) getAPIKey(r *http.Request, id string) (*APIKeyMeta, error) {
	req, err := http.NewRequestWithContext(r.Context(), http.MethodGet,
		h.backendURL()+"/api/admin/api-keys/"+id, nil)
	if err != nil {
		return nil, err
	}
	h.forwardAuth(r, req)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("backend returned %d", resp.StatusCode)
	}
	var key APIKeyMeta
	if err := json.Unmarshal(body, &key); err != nil {
		return nil, fmt.Errorf("parse response: %w", err)
	}
	return &key, nil
}

func (h *PageHandler) revokeAPIKey(r *http.Request, id string) error {
	req, err := http.NewRequestWithContext(r.Context(), http.MethodDelete,
		h.backendURL()+"/api/admin/api-keys/"+id, nil)
	if err != nil {
		return err
	}
	h.forwardAuth(r, req)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusNoContent {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("backend returned %d: %s", resp.StatusCode, string(body))
	}
	return nil
}

// forwardAuth copies auth-related headers from the incoming browser request
// to the outgoing backend request, so that the backend's auth middleware sees
// the same credentials the Pangolin-edge handed us.
//
// Forwarded headers (must stay in sync with api.HubClient.WithAuthFrom):
//   - X-Label-Hub-Key   — App-side API key
//   - X-Pangolin-User   — Legacy Pangolin SSO identity header
//   - X-Pangolin-Token  — Pangolin Resource custom upstream trust token
//   - Remote-User       — Standard Pangolin SSO identity header
//   - Authorization     — Pangolin Basic-Auth bypass (claude-automation)
//
// The X-Pangolin-Token / Remote-User pair is what makes the SSO-trust path
// work for browser users without an API key. Forgetting one of them means
// every /admin/* route returns 503 because the backend rejects the call as
// unauthenticated.
func (h *PageHandler) forwardAuth(from *http.Request, to *http.Request) {
	for _, hdr := range []string{
		"X-Label-Hub-Key",
		"X-Pangolin-User",
		"X-Pangolin-Token",
		"Remote-User",
		"Authorization",
	} {
		if v := from.Header.Get(hdr); v != "" {
			to.Header.Set(hdr, v)
		}
	}
}

// backendURL returns the backend base URL from the handler.
// Uses the client's base URL field.
func (h *PageHandler) backendURL() string {
	// The client stores the base URL; extract it via the gen field
	// For simplicity, use the env var directly (same as proxy.go)
	u := strings.TrimSuffix(h.client.BaseURL(), "/")
	return u
}
