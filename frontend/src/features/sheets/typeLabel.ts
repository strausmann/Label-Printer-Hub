/** The name the sheet list shows for a type, as the server builds it: "<vendor> <first product code>", else the code, else the key. */
export function typeLabel(type: { key: string; vendor: string | null; product_codes: string[] }): string {
  const code = type.product_codes[0];
  if (type.vendor && code) return `${type.vendor} ${code}`;
  return code ?? type.key;
}

/** Label and key together, so two types with the same label can still be told apart. */
export function typeLabelWithKey(type: { key: string; vendor: string | null; product_codes: string[] }): string {
  const label = typeLabel(type);
  return label === type.key ? label : `${label} (${type.key})`;
}
