# 0003 — Go + Tailwind + HTMX + PWA for the frontend

- **Status:** Accepted
- **Date:** 2026-05-10
- **Deciders:** maintainer

## Context

ADR 0001 established that the frontend is a separate container. We need to choose the frontend stack: web server language, HTML rendering approach, CSS framework, and progressive-web-app (PWA) strategy for smartphone use.

The maintainer wants Go on the backend of the frontend service (i.e. the runtime that serves HTML), Tailwind for styling, and PWA installability so the hub can be added to a phone home screen and feel native.

## Decision

The frontend container runs a **Go HTTP server** (using a lightweight router like `chi` or `echo`) that:

- Renders HTML on the server using Go's `html/template`
- Serves Tailwind-CSS-built static assets
- Embeds **HTMX** for partial updates and SSE consumption (`hx-ext="sse"`)
- Ships a **Web App Manifest** + **Service Worker** to be installable as a PWA
- Uses the **Web Notifications API** for active-tab toasts; later, **Web Push** for background notifications (see issue #5)
- Proxies API calls and the SSE stream to the backend over the internal docker network

## Options considered

### Option A — Go + Tailwind + HTMX + PWA (chosen)
- Pros: small static binary; fast cold start; easy multi-arch image; HTMX is a low-JS pattern that works well with server-rendered HTML; PWA support is mature in modern browsers
- Cons: another language to maintain alongside Python backend; need OpenAPI codegen (or hand-written client) for the backend client

### Option B — Static SPA (Svelte/Vue/Solid) + Go static server
- Pros: rich interactivity client-side; clear data-flow
- Cons: more JS to ship; complex build pipeline; harder PWA story without framework-specific helpers; SSE consumption ergonomics are still fine in vanilla but we lose the HTMX simplicity

### Option C — Go + HTMX without Tailwind (custom CSS)
- Pros: zero dependency
- Cons: every UI change becomes a CSS-engineering exercise; Tailwind dramatically speeds iteration with consistent design tokens

## Consequences

- Frontend container is Go-based (`golang:1.23-alpine` build → `gcr.io/distroless/static` runtime, image ~20 MB)
- Dependencies: `chi` or `echo` (HTTP router), `html/template`, **`oapi-codegen` for typed backend client** (see ADR 0011)
- Build pipeline includes Node + Tailwind for CSS (build-time only; not in runtime image)
- Service Worker scope covers the entire app; offline shell strategy caches HTML/CSS/JS, network-first for API
- Manifest metadata: name, short_name, icons (192px + 512px PNG), theme_color, start_url, display=standalone
- Notifications: opt-in button in UI calls `Notification.requestPermission()`; SSE event type `notify` triggers `new Notification(title, opts)` (see issue [#5](https://github.com/strausmann/label-printer-hub/issues/5))
- Web Push (background) tracked separately as Phase 2 in issue #5
- iOS Safari requires extra meta tags (`apple-touch-icon`, `apple-mobile-web-app-*`) for full PWA experience
- Lighthouse PWA score target: ≥ 90

## References

- Issue [#1](https://github.com/strausmann/label-printer-hub/issues/1) — closed by this ADR
- Issue [#5](https://github.com/strausmann/label-printer-hub/issues/5) — browser notifications follow-up
- Issue [#15](https://github.com/strausmann/label-printer-hub/issues/15) — PWA manifest + service worker
- Related: ADR 0001 (two-container), ADR 0009 (SSE), ADR 0010 (PWA progressive enhancement)
