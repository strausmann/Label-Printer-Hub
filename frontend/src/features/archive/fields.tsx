// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import type { ReactNode } from "react";
import { Label, Text, TextArea, TextField } from "react-aria-components";
import { HINT, LABEL } from "../settings/controls";
import { FIELD } from "../../shell/SignIn";

/** A labelled multi-line field; the description is tied to it for screen readers. */
export function TextAreaField({
  label,
  value,
  onChange,
  description,
  rows = 4,
  mono,
  required,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  description?: ReactNode;
  rows?: number;
  mono?: boolean;
  required?: boolean;
}) {
  return (
    <TextField value={value} onChange={onChange} isRequired={required} className="flex min-w-0 flex-col gap-1.5">
      <Label className={LABEL}>{label}</Label>
      <TextArea rows={rows} spellCheck={false} className={`${FIELD} h-auto! py-2 ${mono ? "font-mono text-small" : ""}`} />
      {description ? (
        <Text slot="description" className={HINT}>
          {description}
        </Text>
      ) : null}
    </TextField>
  );
}

/** A type's state in a word, with a shape: never colour alone. */
export function Badge({ children, tone = "plain" }: { children: ReactNode; tone?: "plain" | "warn" }) {
  return (
    <span
      className={`inline-flex items-center rounded-r1 border px-2 text-small leading-6 font-bold ${
        tone === "warn" ? "border-warn text-ink" : "border-line-strong text-ink-2"
      }`}
    >
      {tone === "warn" ? (
        <svg viewBox="0 0 10 10" width="8" height="8" aria-hidden="true" className="mr-1.5 fill-warn">
          <path d="M5 0 10 5 5 10 0 5Z" />
        </svg>
      ) : null}
      {children}
    </span>
  );
}
