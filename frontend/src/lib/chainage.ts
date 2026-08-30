/** "Km 12+400" -> 12400 (metres). Returns null if the string doesn't parse. */
export function parseChainageMetres(display: string | null): number | null {
  if (!display) return null;
  const m = display.match(/Km\s*(\d+)\+(\d{3})/);
  if (!m) return null;
  return Number(m[1]) * 1000 + Number(m[2]);
}
