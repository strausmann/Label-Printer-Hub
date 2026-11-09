/** A query string from the set values only; undefined, null and empty strings are left out (false and 0 are kept). */
export function queryString(params: Record<string, string | number | boolean | null | undefined>): string {
  const query = new URLSearchParams();
  for (const [name, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    query.set(name, String(value));
  }
  const text = query.toString();
  return text ? `?${text}` : "";
}
