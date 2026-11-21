// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

// Pieces used by more than one mockup.
import { badge, field, icon, input, select, seg, stepper } from "./lib.mjs";

/** The three position controls of #246 (M1 inside Edit details, M2 inside the type page). */
export function positionControls({ band = "Top", from = "Right edge", offset = "54.0", focusOffset = false } = {}) {
  return `<div class="col g16">
  <div class="field"><label>Band</label>${seg(["Automatic", "Top", "Bottom", "Left", "Right"], band)}
    <p class="hint">Automatic chooses the largest free band. A band you choose is a rule: if it has no room on a printer, the code is not printed there.</p></div>
  <div class="grid2">
    <div class="field"><label>Start from</label>${seg(["Left or top", "Right or bottom"], from === "Right edge" ? "Right or bottom" : "Left or top")}</div>
    <div class="field"><label>Offset from that end</label>${stepper(offset, "mm", { focus: focusOffset })}
      <p class="hint">Steps of 0.5 mm. Distance from the end of the label grid to where the code starts.</p></div>
  </div></div>`;
}

export const LEGEND = `<ul class="row wrap-row g16 small muted" aria-label="Legend">
  <li class="row g8"><svg width="22" height="14" aria-hidden="true"><rect x="1" y="1" width="20" height="12" fill="none" stroke="var(--ink-3)"/><path d="M3 12 12 2M8 12l9-10M13 12l6-8" stroke="var(--ink-3)" fill="none"/></svg>Preprinted area</li>
  <li class="row g8"><svg width="22" height="14" aria-hidden="true"><rect x="1" y="1" width="20" height="12" fill="var(--info-soft)" stroke="var(--link)" stroke-width="2"/></svg>Sheet code</li>
  <li class="row g8"><svg width="22" height="14" aria-hidden="true"><rect x="1" y="1" width="20" height="12" fill="none" stroke="var(--bad)" stroke-dasharray="3 2"/></svg>Refused or does not fit</li>
  <li class="row g8"><svg width="22" height="14" aria-hidden="true"><rect x="1" y="1" width="20" height="12" fill="var(--accent-soft)" stroke="var(--accent)"/></svg>Label</li></ul>`;
