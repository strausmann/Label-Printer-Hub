// Package frontend exposes the embedded web assets so cmd/server/main.go can
// reference them via //go:embed from a file that is at the same directory
// level as the web/ subtree.
//
// Go's //go:embed directive uses paths relative to the source file — so the
// embed declarations for web/static and web/templates must live here
// (frontend/) rather than in cmd/server/, which is two levels below.
package frontend

import "embed"

// StaticFS embeds the compiled static assets (Tailwind CSS, HTMX JS, icons).
// The sub-tree is rooted at "web/static" — use fs.Sub(StaticFS, "web/static")
// to strip the prefix before passing to http.FileServer.
//
//go:embed web/static
var StaticFS embed.FS

// TemplateFS embeds all html/template sources for server-side rendering.
// Parse with: template.ParseFS(TemplateFS, "web/templates/*.html")
//
//go:embed web/templates
var TemplateFS embed.FS
