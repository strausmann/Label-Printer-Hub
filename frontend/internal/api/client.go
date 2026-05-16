// Package api provides a typed HTTP client for the label-printer-hub backend API.
//
// The generated client (client.gen.go) is produced by oapi-codegen from the
// backend's OpenAPI spec. This file wraps the generated client with convenience
// methods and sentinel errors.
//
// Task 3 (oapi-codegen scaffolding) adds the generated file and typed helper
// methods. This stub allows handlers/base.go to compile in Task 2 before
// the full client generation step.
package api

import "errors"

// ErrNotFound is returned by client methods when the backend responds with 404.
var ErrNotFound = errors.New("not found")

// ErrBadGateway is returned when the backend is unreachable or returns 5xx.
var ErrBadGateway = errors.New("backend unavailable")

// Client is a typed HTTP client for the backend REST API.
// The zero-value is not usable — use NewClient.
type Client struct {
	baseURL    string
	httpClient interface{} // placeholder until oapi-codegen is wired in Task 3
}

// NewClient constructs a Client that targets the given backend base URL.
// backendURL must not have a trailing slash (e.g. "http://backend:8000").
func NewClient(backendURL string) *Client {
	return &Client{baseURL: backendURL}
}
