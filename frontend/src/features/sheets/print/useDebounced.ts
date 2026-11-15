// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useEffect, useRef, useState } from "react";

/**
 * A value that follows `value` after it has stayed the same for `ms`. The first value is
 * immediate. `pending` is true while the settled value is behind the current one. Values are
 * compared by their JSON, so an object rebuilt on every render does not restart the wait.
 */
export function useDebounced<T>(value: T, ms: number): { value: T; pending: boolean } {
  const key = JSON.stringify(value);
  const [settled, setSettled] = useState({ key, value });
  const latest = useRef(value);
  useEffect(() => {
    latest.current = value;
  });
  useEffect(() => {
    if (key === settled.key) return;
    const timer = setTimeout(() => setSettled({ key, value: latest.current }), ms);
    return () => clearTimeout(timer);
  }, [key, ms, settled.key]);
  return { value: settled.value, pending: key !== settled.key };
}
