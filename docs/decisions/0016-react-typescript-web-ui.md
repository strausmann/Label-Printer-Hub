# 0016 — React + TypeScript web UI

- **Status:** Accepted
- **Date:** 2026-11-04
- **Deciders:** maintainer
- **Supersedes:** ADR-0003
- **Restates:** ADR-0010 (PWA progressive enhancement)
- **Decision label:** D2

## Context

ADR 0003 chose a Go-rendered, HTMX-driven UI with Tailwind. With the Go frontend gone (ADR 0015) the UI becomes a client-side app. The new UI has interaction needs that server-rendered fragments handled poorly: a cart and bulk-print flow (ADR 0013), live queue state over server-sent events (ADR 0009), a camera barcode scanner, accessible form controls, and English/German text.

## Decision

We build the UI as a single-page app in React and TypeScript, using the stack in spec section 5.1 (Vite build, TanStack Router and Query, react-aria components, a token-based design system per D3), served by the backend (ADR 0015).

The PWA behaviour of ADR 0010 stays: the app is fully usable without any PWA feature, and installability, offline shell and update handling are layered on top. Specifics for this stack:

- The service worker uses `registerType: "prompt"`. A new version never swaps in silently; the user sees an update prompt and chooses when to reload, so an open print cart or form is never lost.
- Barcode scanning uses the browser `BarcodeDetector` when present and falls back to a ZXing WebAssembly decoder running in a web worker, so it works on browsers without native support.
- Text is localised with Lingui, English and German. English is the default (D8).

## Options considered

### Option A — React + TypeScript SPA (picked)
- Pros: component model fits cart, queue and settings screens; mature accessible primitives; strong typing against the OpenAPI contract (ADR 0011).
- Cons: a Node toolchain in the build; larger client bundle than HTMX.

### Option B — keep Go + HTMX + Tailwind
- Pros: no JS build chain, small payload.
- Cons: requires keeping the Go service ADR 0015 removes; weak fit for client-side scanning, optimistic cart state and rich forms.

### Option C — another SPA framework (Svelte, Vue)
- Pros: smaller runtimes.
- Cons: smaller ecosystem for accessible component primitives and WASM/worker tooling the maintainers already know in React.

## Consequences

- A frontend build step (Node) is part of the image build; the runtime image contains only the static output.
- Prompt-on-update means an old client can talk to a newer backend until the user accepts the update; the API stays backward compatible within a release.
- ADR 0003 is superseded; ADR 0010's principle is unchanged but its HTMX baseline no longer applies.

## References

- Spec: `docs/superpowers/specs/2026-11-03-web-ui-redesign-design.md` (section 5)
- Supersedes ADR-0003; restates ADR-0010; related ADR-0009, ADR-0011, ADR-0013, ADR-0015
