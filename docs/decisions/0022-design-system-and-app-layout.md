<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# 0022 — Design system and app layout

- **Status:** Accepted
- **Date:** 2026-11-10
- **Deciders:** maintainer
- **Decision label:** D3 (and D12 for the `ink-500` value)
- **Amended:** 2026-11-21 (#255, #316, #319, #320) — the app shell has a top bar with search, notification centre and cart, and a phone menu, see "Amendment — 2026-11-21" at the end
- **Related:** [0016](0016-react-typescript-web-ui.md) (the web UI stack), [0010](0010-pwa-progressive-enhancement.md)

## Context

The web UI (ADR 0016) needs one visual language and one layout, shared by every screen, usable on a phone at a label shelf and on a desktop. D3 recorded "design token set" in the register but pointed only at a section of a redesign spec; there was no ADR, and the original mockups were never public. This ADR records what the code does, so that the values can be read from the repository.

## Decision

**We use a three-layer token set, one app shell with two navigation forms, light and dark themes, and fixed mobile rules, and we check UI work against the running app.**

### Tokens (D3)

The source of truth is `frontend/src/design/tokens.css`; `tokens.ts` mirrors it and `tokens.test.ts` keeps both in step and checks contrast. `frontend/src/index.css` maps the semantic roles onto Tailwind utilities (`bg-surface`, `text-ink-2`, `rounded-r2`).

Three layers: primitive values, semantic roles, use in components.

| Primitive | Value | | Primitive | Value |
|---|---|---|---|---|
| `paper-50` | `#F6F4EF` | | `amber-500` | `#D4912A` |
| `paper-100` | `#EFEBE3` | | `amber-600` | `#B8771A` |
| `paper-200` | `#E3DED3` | | `amber-100` | `#F6E6C8` |
| `paper-300` | `#CFC8BA` | | `stamp-600` | `#2F4E8F` |
| `ink-900` | `#1F1D1A` | | `green-600` | `#2E7A4E` |
| `ink-700` | `#4A463F` | | `orange-600` | `#B5651B` |
| `ink-500` | `#6B655A` | | `red-600` | `#B0352B` |

`ink-500` is `#6B655A` to meet WCAG AA contrast on the paper background (D12).

**Colour roles** (light / dark): `bg` (`#F6F4EF` / `#171614`), `surface` (`#FDFCF9` / `#201E1B`), `sunken`, `line`, `line-strong`, `ink`, `ink-2`, `ink-3`, `accent` (amber: `#D4912A` / `#E2A445`), `accent-ink`, `accent-soft`, `link` (stamp blue: `#2F4E8F` / `#8FAEE6`), and the state roles `ok`, `warn`, `bad`. State is never carried by colour alone: it always comes with text or an icon.

**Tape colours** (`tape-white`, `-yellow`, `-green`, `-blue`, `-red`, `-black`, `-clear`) describe the loaded material and never mean state. Clear tape has no colour; its swatch shows the surface through a dashed edge.

**Type roles:** Atkinson Hyperlegible for text and Atkinson Hyperlegible Mono for codes and IDs (weight 600). Scale: title 28/700, section 20/700, body 15/400, small 13/400, code 15/600. Spacing is a 4 px grid. Radii: 6, 10 and 14 px. The focus ring is 3 px in the link colour, with a 2 px offset.

**Themes.** Light is the default; dark follows `prefers-color-scheme` unless the person chose a theme, which is stored as `data-theme` on the root element. Both themes are first-class: every screen is checked in both.

### App shell and navigation

One shell wraps every page. From 1024 px wide it shows a fixed **sidebar** (grouped navigation, hidden entries removed, an integrations group built from the configured integrations, a connection indicator). Below 1024 px it shows a **tab bar** with five fixed slots, Overview, Printers, Scan (large, centre), Jobs and Sheets, so Scan stays in the middle while Sheets is hidden when the feature is off. The active destination is shown by weight and a bar, not by colour alone.

### Mobile rules

- Form inputs use 16 px text, because smaller fields make iOS zoom into the page.
- Touch targets are at least 44 px (`h-11` / `min-h-11`) on buttons and links; the tab bar is 64 px high.
- Tappable elements disable the double-tap delay and the tap highlight, give a short press feedback (a 3 % scale, 120 ms), and respect `prefers-reduced-motion` by cutting animations to near zero.
- The tab bar and full-height areas respect the safe-area inset and use dynamic viewport units.

### How UI work is checked

- The design skills are loaded before UI code is written and used again at the end of the task.
- Playwright screenshots are taken at 1280 px and 390 px wide, light and dark, as review artifacts (not as a pixel-diff gate, which would turn red on every font or library update).
- Behaviour is covered by component tests and end-to-end tests; contrast is covered by the token test.

## Options considered

### Option A — CSS custom property tokens mapped into Tailwind (chosen)
- Pros: one source for CSS and utilities; themes switch by redefining roles; testable.
- Cons: a mirrored TypeScript copy must be kept in step (guarded by `tokens.test.ts`).

### Option B — Tailwind default palette
- Pros: no custom work.
- Cons: no theme roles, no tape colours, and the look would be generic.

### Option C — a component library with its own theme
- Pros: ready-made components.
- Cons: a second token system to reconcile; harder to meet the contrast and mobile rules.

## Consequences

- Changing a token value is a design decision: it changes `tokens.css`, `tokens.ts` and this ADR together.
- New screens use roles, not raw colours or pixel values.
- A screen that fails the 16 px / 44 px rules or only works in one theme is not finished.

## References

- Tokens: `frontend/src/design/tokens.css`, `frontend/src/design/tokens.ts`, `frontend/src/index.css`
- Shell: `frontend/src/shell/Sidebar.tsx`, `frontend/src/shell/TabBar.tsx`, `frontend/src/shell/AppShell.tsx`
- Related ADRs: [0010](0010-pwa-progressive-enhancement.md), [0016](0016-react-typescript-web-ui.md)

## Amendment — 2026-11-21 (ADR audit): the top bar and the phone menu

Since 1.7.0 the app shell has a third part next to the sidebar and the tab bar: a **top bar** above the content (`frontend/src/shell/TopBar.tsx`, placed by `frontend/src/shell/AppShell.tsx:37`). It holds:

- the **global search**: from 1024 px a field with suggestions, below it a magnifier that opens a search dialog (`frontend/src/features/search/GlobalSearch.tsx:33,57`, `SearchDialog.tsx`; #320);
- **Scan** as a button from 1024 px; on a phone Scan stays in the centre slot of the tab bar;
- the **notification centre** (`frontend/src/features/notifications/NotificationCentre.tsx`; #255), which also shows the hub's one-time notices from `GET /api/v1/notices` (`backend/app/api/routes/notices.py:43-44`);
- a permanent **cart icon** with the item count (`frontend/src/shell/CartButton.tsx`; #316);
- from 1024 px the about link, the theme switch and sign-out.

Below 1024 px the top bar starts with a **menu** that reaches every area, including those the five tab-bar slots leave out, such as calibration, settings, integrations and printer administration (`frontend/src/shell/PhoneMenu.tsx`, button at line 137; #319). The sidebar and the tab bar stay as described above, and the mobile rules apply to the top bar and the menu as well.

