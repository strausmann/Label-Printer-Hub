package handlers

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strconv"
	"strings"

	"github.com/go-chi/chi/v5"
)

// ---------------------------------------------------------------------------
// Datentypen für die Admin-Drucker-Seiten
// ---------------------------------------------------------------------------

// AdminPrinterRead ist die Frontend-Darstellung eines Druckers aus der Admin-API.
type AdminPrinterRead struct {
	Id          string                 `json:"id"`
	Name        string                 `json:"name"`
	Slug        string                 `json:"slug"`
	Model       string                 `json:"model"`
	Backend     string                 `json:"backend"`
	Connection  map[string]interface{} `json:"connection"`
	Queue       map[string]interface{} `json:"queue"`
	CutDefaults map[string]interface{} `json:"cut_defaults"`
	Enabled     bool                   `json:"enabled"`
	CreatedAt   string                 `json:"created_at"`
	UpdatedAt   string                 `json:"updated_at"`
}

// AdminPrinterListData enthält Daten für die Druckerliste.
type AdminPrinterListData struct {
	TemplateData
	Printers        []AdminPrinterRead
	IncludeDisabled bool
}

// AdminPrinterFormData enthält Daten für das Erstell- und Bearbeitungsformular.
type AdminPrinterFormData struct {
	TemplateData
	Printer  *AdminPrinterRead
	IsEdit   bool
	Slug     string
	Error    string
	FormName string
	FormSlug string
	FormModel string
	FormBackend string
	FormHost    string
	FormPort    string
	FormQueueTimeoutS   string
	FormCutDefaultsHalfCut bool
	FormSnmpDiscover    bool
	FormSnmpCommunity   string
}

// AdminPrinterDetailData enthält Daten für die Drucker-Detailseite.
type AdminPrinterDetailData struct {
	TemplateData
	Printer AdminPrinterRead
}

// AdminPrinterConfirmData enthält Daten für den Deaktivierungs-Bestätigungsdialog.
type AdminPrinterConfirmData struct {
	TemplateData
	Printer AdminPrinterRead
}

// ---------------------------------------------------------------------------
// Handler — Liste
// ---------------------------------------------------------------------------

// ListPrintersPage behandelt GET /admin/printers — Auflistung aller Drucker.
func (h *PageHandler) ListPrintersPage(w http.ResponseWriter, r *http.Request) {
	includeDisabled := r.URL.Query().Get("include_disabled") == "true"
	printers, err := h.listAdminPrinters(r, includeDisabled)
	if err != nil {
		slog.Error("ListPrintersPage: Backend-Fehler", "err", err)
		h.renderError(w, r, http.StatusServiceUnavailable, "Service nicht verfügbar", err.Error())
		return
	}
	h.renderPage(w, r, "admin_printers", AdminPrinterListData{
		TemplateData:    h.baseData(r, "admin"),
		Printers:        printers,
		IncludeDisabled: includeDisabled,
	})
}

// ---------------------------------------------------------------------------
// Handler — Erstellen
// ---------------------------------------------------------------------------

// NewPrinterPage behandelt GET /admin/printers/new — leeres Erstell-Formular.
func (h *PageHandler) NewPrinterPage(w http.ResponseWriter, r *http.Request) {
	h.renderPage(w, r, "admin_printers_form", AdminPrinterFormData{
		TemplateData: h.baseData(r, "admin"),
		IsEdit:       false,
	})
}

// CreatePrinter behandelt POST /admin/printers/new — neuen Drucker anlegen.
// CSRF-Token wird von gorilla/csrf vor dem Handler-Aufruf validiert.
func (h *PageHandler) CreatePrinter(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseForm(); err != nil {
		h.renderError(w, r, http.StatusBadRequest, "Ungültige Anfrage", err.Error())
		return
	}

	name := strings.TrimSpace(r.FormValue("name"))
	slug := strings.TrimSpace(r.FormValue("slug"))
	model := strings.TrimSpace(r.FormValue("model"))
	backend := strings.TrimSpace(r.FormValue("backend"))
	host := strings.TrimSpace(r.FormValue("host"))
	portStr := r.FormValue("port")
	queueTimeoutStr := r.FormValue("queue_timeout_s")
	halfCut := r.FormValue("cut_defaults_half_cut") == "on"
	snmpDiscover := r.FormValue("snmp_discover") == "on"
	snmpCommunity := r.FormValue("snmp_community")

	// Formular-Daten für Rerender bei Fehler
	formData := AdminPrinterFormData{
		TemplateData:           h.baseData(r, "admin"),
		IsEdit:                 false,
		FormName:               name,
		FormSlug:               slug,
		FormModel:              model,
		FormBackend:            backend,
		FormHost:               host,
		FormPort:               portStr,
		FormQueueTimeoutS:      queueTimeoutStr,
		FormCutDefaultsHalfCut: halfCut,
		FormSnmpDiscover:       snmpDiscover,
		FormSnmpCommunity:      snmpCommunity,
	}

	// Validierung
	if name == "" {
		formData.Error = "Name darf nicht leer sein."
		h.renderPage(w, r, "admin_printers_form", formData)
		return
	}
	port, err := strconv.Atoi(portStr)
	if err != nil || port < 1 || port > 65535 {
		formData.Error = fmt.Sprintf("Port muss zwischen 1 und 65535 liegen (eingegeben: %q).", portStr)
		h.renderPage(w, r, "admin_printers_form", formData)
		return
	}
	queueTimeout := 30
	if queueTimeoutStr != "" {
		qt, err := strconv.Atoi(queueTimeoutStr)
		if err != nil || qt < 1 || qt > 3600 {
			formData.Error = fmt.Sprintf("Queue-Timeout muss zwischen 1 und 3600 Sekunden liegen (eingegeben: %q).", queueTimeoutStr)
			h.renderPage(w, r, "admin_printers_form", formData)
			return
		}
		queueTimeout = qt
	}

	payload := buildPrinterCreatePayload(name, slug, model, backend, host, port, queueTimeout, halfCut, snmpDiscover, snmpCommunity)
	printer, apiErr := h.createAdminPrinter(r, payload)
	if apiErr != nil {
		slog.Warn("CreatePrinter: Backend-Fehler", "err", apiErr)
		formData.Error = apiErr.Error()
		h.renderPage(w, r, "admin_printers_form", formData)
		return
	}

	http.Redirect(w, r, "/admin/printers/"+printer.Slug, http.StatusSeeOther)
}

// ---------------------------------------------------------------------------
// Handler — Detail
// ---------------------------------------------------------------------------

// PrinterDetailPage behandelt GET /admin/printers/{id} über chi-URL-Parameter.
func (h *PageHandler) PrinterDetailPage(w http.ResponseWriter, r *http.Request) {
	h.PrinterDetailPageWithSlug(w, r, chi.URLParam(r, "id"))
}

// PrinterDetailPageWithSlug ist die testbare Variante mit explizitem Slug-Parameter.
func (h *PageHandler) PrinterDetailPageWithSlug(w http.ResponseWriter, r *http.Request, slug string) {
	printer, err := h.getAdminPrinter(r, slug)
	if err != nil {
		slog.Warn("PrinterDetailPage: Drucker nicht gefunden", "slug", slug, "err", err)
		h.renderError(w, r, http.StatusNotFound, "Nicht gefunden", fmt.Sprintf("Drucker %q nicht gefunden.", slug))
		return
	}
	h.renderPage(w, r, "admin_printers_detail", AdminPrinterDetailData{
		TemplateData: h.baseData(r, "admin"),
		Printer:      *printer,
	})
}

// ---------------------------------------------------------------------------
// Handler — Bearbeiten
// ---------------------------------------------------------------------------

// EditPrinterPage behandelt GET /admin/printers/{id}/edit über chi-URL-Parameter.
func (h *PageHandler) EditPrinterPage(w http.ResponseWriter, r *http.Request) {
	h.EditPrinterPageWithSlug(w, r, chi.URLParam(r, "id"))
}

// EditPrinterPageWithSlug ist die testbare Variante mit explizitem Slug-Parameter.
func (h *PageHandler) EditPrinterPageWithSlug(w http.ResponseWriter, r *http.Request, slug string) {
	printer, err := h.getAdminPrinter(r, slug)
	if err != nil {
		slog.Warn("EditPrinterPage: Drucker nicht gefunden", "slug", slug, "err", err)
		h.renderError(w, r, http.StatusNotFound, "Nicht gefunden", fmt.Sprintf("Drucker %q nicht gefunden.", slug))
		return
	}

	// Verbindungsdaten aus dem Connection-Map extrahieren
	host, _ := printer.Connection["host"].(string)
	portVal := printer.Connection["port"]
	portStr := ""
	switch v := portVal.(type) {
	case float64:
		portStr = strconv.Itoa(int(v))
	case int:
		portStr = strconv.Itoa(v)
	}

	timeoutStr := ""
	if q, ok := printer.Queue["timeout_s"]; ok {
		switch v := q.(type) {
		case float64:
			timeoutStr = strconv.Itoa(int(v))
		case int:
			timeoutStr = strconv.Itoa(v)
		}
	}

	halfCut := false
	if cd, ok := printer.CutDefaults["half_cut"]; ok {
		halfCut, _ = cd.(bool)
	}

	// SNMP-Felder aus dem verschachtelten Connection-Objekt extrahieren.
	// Ohne diesen Prefill würde ein Edit-Submit ohne Eingabe die SNMP-Konfig
	// auf discover=false, community="" überschreiben (silent data loss).
	snmpDiscover := false
	snmpCommunity := ""
	if snmpRaw, ok := printer.Connection["snmp"]; ok {
		if snmpMap, ok := snmpRaw.(map[string]interface{}); ok {
			if d, ok := snmpMap["discover"]; ok {
				snmpDiscover, _ = d.(bool)
			}
			if c, ok := snmpMap["community"]; ok {
				snmpCommunity, _ = c.(string)
			}
		}
	}

	h.renderPage(w, r, "admin_printers_form", AdminPrinterFormData{
		TemplateData:           h.baseData(r, "admin"),
		Printer:                printer,
		IsEdit:                 true,
		Slug:                   slug,
		FormName:               printer.Name,
		FormModel:              printer.Model,
		FormBackend:            printer.Backend,
		FormHost:               host,
		FormPort:               portStr,
		FormQueueTimeoutS:      timeoutStr,
		FormCutDefaultsHalfCut: halfCut,
		FormSnmpDiscover:       snmpDiscover,
		FormSnmpCommunity:      snmpCommunity,
	})
}

// UpdatePrinter behandelt POST /admin/printers/{id}/edit über chi-URL-Parameter.
// CSRF-Token wird von gorilla/csrf vor dem Handler-Aufruf validiert.
func (h *PageHandler) UpdatePrinter(w http.ResponseWriter, r *http.Request) {
	h.UpdatePrinterWithSlug(w, r, chi.URLParam(r, "id"))
}

// UpdatePrinterWithSlug ist die testbare Variante mit explizitem Slug-Parameter.
func (h *PageHandler) UpdatePrinterWithSlug(w http.ResponseWriter, r *http.Request, slug string) {
	if err := r.ParseForm(); err != nil {
		h.renderError(w, r, http.StatusBadRequest, "Ungültige Anfrage", err.Error())
		return
	}

	name := strings.TrimSpace(r.FormValue("name"))
	host := strings.TrimSpace(r.FormValue("host"))
	portStr := r.FormValue("port")
	queueTimeoutStr := r.FormValue("queue_timeout_s")
	halfCut := r.FormValue("cut_defaults_half_cut") == "on"
	snmpDiscover := r.FormValue("snmp_discover") == "on"
	snmpCommunity := r.FormValue("snmp_community")

	formData := AdminPrinterFormData{
		TemplateData:           h.baseData(r, "admin"),
		IsEdit:                 true,
		Slug:                   slug,
		FormName:               name,
		FormHost:               host,
		FormPort:               portStr,
		FormQueueTimeoutS:      queueTimeoutStr,
		FormCutDefaultsHalfCut: halfCut,
		FormSnmpDiscover:       snmpDiscover,
		FormSnmpCommunity:      snmpCommunity,
	}

	// Validierung
	if portStr != "" {
		port, err := strconv.Atoi(portStr)
		if err != nil || port < 1 || port > 65535 {
			formData.Error = fmt.Sprintf("Port muss zwischen 1 und 65535 liegen (eingegeben: %q).", portStr)
			h.renderPage(w, r, "admin_printers_form", formData)
			return
		}
	}
	if queueTimeoutStr != "" {
		qt, err := strconv.Atoi(queueTimeoutStr)
		if err != nil || qt < 1 || qt > 3600 {
			formData.Error = fmt.Sprintf("Queue-Timeout muss zwischen 1 und 3600 Sekunden liegen (eingegeben: %q).", queueTimeoutStr)
			h.renderPage(w, r, "admin_printers_form", formData)
			return
		}
	}

	payload := buildPrinterUpdatePayload(name, host, portStr, queueTimeoutStr, halfCut, snmpDiscover, snmpCommunity)
	if apiErr := h.updateAdminPrinter(r, slug, payload); apiErr != nil {
		slog.Warn("UpdatePrinter: Backend-Fehler", "slug", slug, "err", apiErr)
		formData.Error = apiErr.Error()
		h.renderPage(w, r, "admin_printers_form", formData)
		return
	}

	http.Redirect(w, r, "/admin/printers/"+slug, http.StatusSeeOther)
}

// ---------------------------------------------------------------------------
// Handler — Deaktivieren
// ---------------------------------------------------------------------------

// DisablePrinterConfirmPage behandelt GET /admin/printers/{id}/disable.
func (h *PageHandler) DisablePrinterConfirmPage(w http.ResponseWriter, r *http.Request) {
	h.DisablePrinterConfirmPageWithSlug(w, r, chi.URLParam(r, "id"))
}

// DisablePrinterConfirmPageWithSlug ist die testbare Variante.
func (h *PageHandler) DisablePrinterConfirmPageWithSlug(w http.ResponseWriter, r *http.Request, slug string) {
	printer, err := h.getAdminPrinter(r, slug)
	if err != nil {
		slog.Warn("DisablePrinterConfirmPage: Drucker nicht gefunden", "slug", slug, "err", err)
		h.renderError(w, r, http.StatusNotFound, "Nicht gefunden", fmt.Sprintf("Drucker %q nicht gefunden.", slug))
		return
	}
	h.renderPage(w, r, "admin_printers_confirm_disable", AdminPrinterConfirmData{
		TemplateData: h.baseData(r, "admin"),
		Printer:      *printer,
	})
}

// DisablePrinter behandelt POST /admin/printers/{id}/disable.
// CSRF-Token wird von gorilla/csrf vor dem Handler-Aufruf validiert.
func (h *PageHandler) DisablePrinter(w http.ResponseWriter, r *http.Request) {
	h.DisablePrinterWithSlug(w, r, chi.URLParam(r, "id"))
}

// DisablePrinterWithSlug ist die testbare Variante.
func (h *PageHandler) DisablePrinterWithSlug(w http.ResponseWriter, r *http.Request, slug string) {
	if err := h.disableAdminPrinter(r, slug); err != nil {
		slog.Warn("DisablePrinter: Backend-Fehler", "slug", slug, "err", err)
		h.renderError(w, r, http.StatusInternalServerError, "Fehler", err.Error())
		return
	}
	http.Redirect(w, r, "/admin/printers", http.StatusSeeOther)
}

// ---------------------------------------------------------------------------
// Handler — Aktivieren
// ---------------------------------------------------------------------------

// EnablePrinter behandelt POST /admin/printers/{id}/enable.
// CSRF-Token wird von gorilla/csrf vor dem Handler-Aufruf validiert.
func (h *PageHandler) EnablePrinter(w http.ResponseWriter, r *http.Request) {
	h.EnablePrinterWithSlug(w, r, chi.URLParam(r, "id"))
}

// EnablePrinterWithSlug ist die testbare Variante.
func (h *PageHandler) EnablePrinterWithSlug(w http.ResponseWriter, r *http.Request, slug string) {
	if err := h.enableAdminPrinter(r, slug); err != nil {
		slog.Warn("EnablePrinter: Backend-Fehler", "slug", slug, "err", err)
		h.renderError(w, r, http.StatusInternalServerError, "Fehler", err.Error())
		return
	}
	http.Redirect(w, r, "/admin/printers/"+slug, http.StatusSeeOther)
}

// ---------------------------------------------------------------------------
// Backend-API-Hilfsfunktionen
// ---------------------------------------------------------------------------

const adminPrintersPath = "/api/v1/admin/printers"

func (h *PageHandler) listAdminPrinters(r *http.Request, includeDisabled bool) ([]AdminPrinterRead, error) {
	path := h.backendURL() + adminPrintersPath
	if includeDisabled {
		path += "?include_disabled=true"
	}
	req, err := http.NewRequestWithContext(r.Context(), http.MethodGet, path, nil)
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
		return nil, fmt.Errorf("Backend lieferte %d: %s", resp.StatusCode, string(body))
	}
	var printers []AdminPrinterRead
	if err := json.Unmarshal(body, &printers); err != nil {
		return nil, fmt.Errorf("Antwort parsen: %w", err)
	}
	return printers, nil
}

func (h *PageHandler) createAdminPrinter(r *http.Request, payload map[string]interface{}) (*AdminPrinterRead, error) {
	data, _ := json.Marshal(payload)
	req, err := http.NewRequestWithContext(r.Context(), http.MethodPost,
		h.backendURL()+adminPrintersPath, bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	h.forwardAuth(r, req)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusCreated {
		return nil, fmt.Errorf("Backend lieferte %d: %s", resp.StatusCode, string(body))
	}
	var printer AdminPrinterRead
	if err := json.Unmarshal(body, &printer); err != nil {
		return nil, fmt.Errorf("Antwort parsen: %w", err)
	}
	return &printer, nil
}

func (h *PageHandler) getAdminPrinter(r *http.Request, slug string) (*AdminPrinterRead, error) {
	req, err := http.NewRequestWithContext(r.Context(), http.MethodGet,
		h.backendURL()+adminPrintersPath+"/"+slug, nil)
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
	if resp.StatusCode == http.StatusNotFound {
		return nil, fmt.Errorf("nicht gefunden")
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("Backend lieferte %d: %s", resp.StatusCode, string(body))
	}
	var printer AdminPrinterRead
	if err := json.Unmarshal(body, &printer); err != nil {
		return nil, fmt.Errorf("Antwort parsen: %w", err)
	}
	return &printer, nil
}

func (h *PageHandler) updateAdminPrinter(r *http.Request, slug string, payload map[string]interface{}) error {
	data, _ := json.Marshal(payload)
	req, err := http.NewRequestWithContext(r.Context(), http.MethodPut,
		h.backendURL()+adminPrintersPath+"/"+slug, bytes.NewReader(data))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	h.forwardAuth(r, req)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("Backend lieferte %d: %s", resp.StatusCode, string(body))
	}
	return nil
}

func (h *PageHandler) disableAdminPrinter(r *http.Request, slug string) error {
	req, err := http.NewRequestWithContext(r.Context(), http.MethodPost,
		h.backendURL()+adminPrintersPath+"/"+slug+"/disable", nil)
	if err != nil {
		return err
	}
	h.forwardAuth(r, req)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("Backend lieferte %d: %s", resp.StatusCode, string(body))
	}
	return nil
}

func (h *PageHandler) enableAdminPrinter(r *http.Request, slug string) error {
	req, err := http.NewRequestWithContext(r.Context(), http.MethodPost,
		h.backendURL()+adminPrintersPath+"/"+slug+"/enable", nil)
	if err != nil {
		return err
	}
	h.forwardAuth(r, req)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("Backend lieferte %d: %s", resp.StatusCode, string(body))
	}
	return nil
}

// ---------------------------------------------------------------------------
// Payload-Hilfsfunktionen
// ---------------------------------------------------------------------------

func buildPrinterCreatePayload(name, slug, model, backend, host string, port, queueTimeout int, halfCut, snmpDiscover bool, snmpCommunity string) map[string]interface{} {
	connection := map[string]interface{}{
		"host": host,
		"port": port,
		"snmp": map[string]interface{}{
			"discover":  snmpDiscover,
			"community": snmpCommunity,
		},
	}
	return map[string]interface{}{
		"name":     name,
		"slug":     slug,
		"model":    model,
		"backend":  backend,
		"connection": connection,
		"queue": map[string]interface{}{
			"timeout_s": queueTimeout,
		},
		"cut_defaults": map[string]interface{}{
			"half_cut": halfCut,
		},
		"enabled": true,
	}
}

func buildPrinterUpdatePayload(name, host, portStr, queueTimeoutStr string, halfCut, snmpDiscover bool, snmpCommunity string) map[string]interface{} {
	payload := map[string]interface{}{}
	if name != "" {
		payload["name"] = name
	}
	if host != "" || portStr != "" {
		conn := map[string]interface{}{}
		if host != "" {
			conn["host"] = host
		}
		if port, err := strconv.Atoi(portStr); err == nil && port > 0 {
			conn["port"] = port
		}
		conn["snmp"] = map[string]interface{}{
			"discover":  snmpDiscover,
			"community": snmpCommunity,
		}
		payload["connection"] = conn
	}
	if queueTimeoutStr != "" {
		if qt, err := strconv.Atoi(queueTimeoutStr); err == nil {
			payload["queue"] = map[string]interface{}{"timeout_s": qt}
		}
	}
	payload["cut_defaults"] = map[string]interface{}{"half_cut": halfCut}
	return payload
}
