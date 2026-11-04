import { useCallback, useMemo, useState } from "react";
import type { SettingView } from "./api";

/** `null` on a secret means "remove the saved value". */
export type DraftValue = string | boolean | null;

/** What the form shows for a setting before anyone typed: never a secret. */
export function initialValue(view: SettingView | undefined): string | boolean {
  if (!view) return "";
  if (view.kind === "bool") return Boolean(view.value);
  if (view.kind === "secret") return "";
  return view.value === null || view.value === undefined ? "" : String(view.value);
}

/** Compare URLs the way a person would: surrounding space and a closing slash do not make a new address. */
export const sameUrl = (a: string, b: string) => a.trim().replace(/\/+$/, "") === b.trim().replace(/\/+$/, "");

/** The value to send for a draft entry, or `undefined` when it is not valid yet. */
export function toPayloadValue(view: SettingView, draft: DraftValue): unknown {
  switch (view.kind) {
    case "bool":
      return Boolean(draft);
    case "secret":
      return draft === null ? "" : String(draft);
    case "int":
    case "float": {
      const text = String(draft).trim();
      if (text === "") return null;
      const n = Number(text);
      if (!Number.isFinite(n) || (view.kind === "int" && !Number.isInteger(n))) return undefined;
      return n;
    }
    default:
      return String(draft);
  }
}

/**
 * The edits of one form: only entries that differ from what the server has are kept, so a
 * save sends exactly what changed and nothing that is locked or secret-and-untouched.
 */
export function useSettingsDraft(views: SettingView[] | undefined) {
  const [draft, setDraft] = useState<Record<string, DraftValue>>({});
  const byKey = useMemo(() => new Map((views ?? []).map((v) => [v.key, v])), [views]);

  const set = useCallback(
    (key: string, value: DraftValue) =>
      setDraft((current) => {
        const view = byKey.get(key);
        const next = { ...current };
        if (view && value === initialValue(view)) delete next[key];
        else next[key] = value;
        return next;
      }),
    [byKey],
  );

  const valueOf = (key: string): DraftValue => (key in draft ? draft[key]! : initialValue(byKey.get(key)));
  const isDirty = (key: string) => key in draft;

  /** `{key: value}` for the keys in `only` (default all); `invalid` lists keys that cannot be sent. */
  const payload = (only?: readonly string[]) => {
    const values: Record<string, unknown> = {};
    const invalid: string[] = [];
    for (const key of Object.keys(draft)) {
      if (only && !only.includes(key)) continue;
      const view = byKey.get(key);
      if (!view || view.locked) continue;
      const value = toPayloadValue(view, draft[key]!);
      if (value === undefined) invalid.push(key);
      else values[key] = value;
    }
    return { values, invalid };
  };

  const clear = useCallback((only?: readonly string[]) => {
    setDraft((current) => {
      if (!only) return {};
      const next = { ...current };
      for (const key of only) delete next[key];
      return next;
    });
  }, []);

  return { valueOf, set, isDirty, payload, clear, view: (key: string) => byKey.get(key) };
}
