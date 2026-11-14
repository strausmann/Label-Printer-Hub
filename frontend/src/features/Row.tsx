// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import type { ReactNode } from "react";

/** One label/value line of a `<dl>` panel. On phones the label is narrower, so a value like a licence id stays beside it. */
export function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-line py-2 last:border-b-0 sm:gap-x-6">
      <dt className="w-32 shrink-0 text-ink-2 sm:w-40">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}
