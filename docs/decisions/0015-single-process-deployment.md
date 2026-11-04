# 0015 — Single-process deployment: the backend serves the UI

- **Status:** Accepted
- **Date:** 2026-11-04
- **Deciders:** maintainer
- **Supersedes:** ADR-0001
- **Decision label:** D1

## Context

ADR 0001 split the hub into a Python backend and a Go frontend container, so UI and printer protocol could evolve in separate language ecosystems. In practice the split cost more than it gave. The Go frontend mostly proxied `/api/*`, duplicated CSRF and SSO header handling, and needed its own image, health check, compose service and release. Operators had to keep two containers in step, and every proxy hop was another place for forwarded identity headers to be mishandled.

The new web UI (ADR 0016) is a static single-page app. It needs no server-side rendering and no runtime of its own.

## Decision

We run one process: the FastAPI backend serves the built UI and the API from the same origin.

The static bundle is served by `backend/app/web/spa.py` with a fallback to `index.html` for client routes; QR resolver paths stay on the backend. A strict Content-Security-Policy is sent with the app shell. One inline style emitted by a UI library is allowed through a `sha256` hash in the policy instead of `unsafe-inline`. Because `/jobs/{id}` is both an API route and a client route, a small middleware answers requests that `Accept: text/html` with the app shell before route authentication, so an unauthenticated browser gets the app (which then shows sign-in) while API clients still get JSON.

One image, `label-printer-hub-backend`, is published. The Go frontend, its image and its compose services are removed.

## Options considered

### Option A — backend serves the SPA (picked)
- Pros: one container, one origin (no CORS, no proxy header hop), one release artifact, one health check.
- Cons: UI and API release together; a UI-only fix needs a backend image.

### Option B — keep two containers, replace Go with a Node or nginx frontend
- Pros: independent deploys.
- Cons: keeps the proxy hop, the duplicated auth handling and the two-image coordination that motivated the change.

### Option C — separate static hosting (CDN or reverse proxy rule)
- Pros: cheap static delivery.
- Cons: pushes deployment complexity to every operator; breaks the self-contained single-compose story.

## Consequences

- Breaking release: the frontend image disappears and deployments change from two containers to one; migration notes cover compose changes and new required variables (`PRINTER_HUB_SECRET_KEY`, `PRINTER_HUB_PUBLIC_URL`).
- API clients that talked to the backend directly are unaffected; clients that used the frontend's `/api/*` proxy switch to the backend address.
- The image tag scheme of ADR 0007 now applies to a single image.
- CSRF protection and SSO header handling live in the backend only (ADR 0019).

## References

- Spec: `docs/superpowers/specs/2026-11-03-web-ui-redesign-design.md` (sections 9 and 10)
- Supersedes ADR-0001; amends ADR-0007; related ADR-0016, ADR-0019
