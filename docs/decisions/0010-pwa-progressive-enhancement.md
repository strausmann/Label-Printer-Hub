# 0010 — PWA with progressive enhancement

- **Status:** Accepted
- **Date:** 2026-05-10
- **Deciders:** maintainer

## Context

The hub is intended to be used both from a desktop browser (admin / dashboard view) and from a smartphone (operator workflow: scan barcode → print label). For the smartphone use case the maintainer wants a "feels native" experience: app icon on the home screen, full-screen launch, optional offline shell, and OS-level toast notifications.

Browsers can deliver this via the **Progressive Web App** (PWA) bundle of standards: Web App Manifest, Service Worker, Web Notifications API, Web Push API.

A common failure mode of PWAs is to assume the modern browser features (Service Worker, manifest, push) are mandatory and break when one is missing or denied (e.g. Firefox on iOS, lockdown corporate browsers, no notification permission). The hub must remain fully usable as a regular web app even when no PWA features are available.

## Decision

The hub's UI is built as a **progressively-enhanced PWA**.

**Baseline (always works):** plain server-rendered HTML + HTMX + Tailwind CSS. Every workflow (list printers, submit print job, view queue, change tape, see history) works in any browser supporting HTMX (effectively all current browsers).

**Layered enhancements (when available):**

| Feature | Standard | Fallback if unavailable |
|---|---|---|
| Add to home screen | Web App Manifest | Browser still loads UI normally |
| Standalone display mode | manifest `display: standalone` | Runs in a regular tab |
| App icon | manifest icons (192px + 512px) + apple-touch-icon | Browser default favicon |
| Offline shell | Service Worker cache (HTML/CSS/JS) | No offline; user sees connection error |
| Toast notifications (active tab) | Web Notifications API after `Notification.requestPermission()` | SSE updates the in-page status; no toast |
| Background notifications | Web Push API (Phase 2) | Active-tab toasts only |
| Re-scan barcode (camera) | `getUserMedia` | Manual text entry |

The PWA is served by the frontend container (per ADR 0003). The Service Worker scope is the entire app. Cache strategy: HTML/CSS/JS/icons cached for offline shell; API calls (`/api/*`) network-first (no caching).

Notifications follow a two-phase rollout:
- **Phase 1 (MVP)**: active-tab toasts via SSE → Notifications API. Browser/PWA must be open.
- **Phase 2 (post-MVP)**: Web Push with VAPID for true background notifications. See issue [#5](https://github.com/strausmann/label-printer-hub/issues/5).

## Options considered

### Option A — Progressive PWA (chosen)
- Pros: graceful degradation; works everywhere; no hard requirement on Service Workers; smartphone story is excellent when modern browser available
- Cons: contributors must remember to add fallbacks for new features

### Option B — PWA-required (no fallback)
- Pros: simpler code path
- Cons: breaks on iOS Firefox, in private windows, when SW registration fails, when notifications denied — too many failure modes for self-hosted software

### Option C — No PWA, just a regular website
- Pros: simplest
- Cons: doesn't deliver the maintainer's smartphone use case ("install once, works like an app"); no toast notifications

## Consequences

- Frontend serves `/manifest.webmanifest` and `/sw.js` from `frontend/web/static/`
- Service Worker registered with `navigator.serviceWorker.register('/sw.js')` if available; `if ('serviceWorker' in navigator)` guard mandatory
- App icons committed at 192px and 512px (generic placeholder, no Brother branding — see [`policies/trademarks.md`](../policies/trademarks.md))
- iOS Safari quirks: `<meta name="apple-mobile-web-app-capable" content="yes">`, `<link rel="apple-touch-icon" href="…">`
- Lighthouse PWA score target: ≥ 90 (mandatory CI check once UI is built)
- Notifications opt-in button visible whenever permission is `default`; hidden when `granted` or `denied`
- Documentation in `docs/getting-started.md` covers "Install on iPhone" and "Install on Android" steps
- Contributors who add new UI features must document the no-JavaScript / no-PWA fallback in their PR description

## References

- Issue [#15](https://github.com/strausmann/label-printer-hub/issues/15) — manifest + service worker
- Issue [#5](https://github.com/strausmann/label-printer-hub/issues/5) — browser notifications
- [MDN: Progressive Web Apps](https://developer.mozilla.org/docs/Web/Progressive_web_apps)
- [web.dev: Service Worker patterns](https://web.dev/learn/pwa/service-workers)
- Related: ADR 0003 (frontend stack)
