const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** DD MMM YYYY, per DESIGN.md — never numeric-only, never relative, never ISO in the UI.
 *
 * Accepts null: `dated` is a nullable column (the model cannot always read a
 * valid date off a real scan), and this used to call `.split("-")` on
 * whatever it was given with no check at all. Real production data hit this
 * directly -- a letter with `dated: null` reached this function via the
 * plain register table with no guard, threw "null is not an object
 * (evaluating 'e.split')", and because nothing in this app catches a render
 * error, React unmounted the ENTIRE page. One row with an unknown date took
 * the whole register down, permanently, on every load, in every browser --
 * not a flaky bug, a deterministic one, for as long as that row existed.
 *
 * An em dash is what DESIGN.md already uses for "unknown" everywhere else
 * (RECEIVED when absent, etc.); an unknown DATED is the same case, not a
 * special one. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return "—";
  return `${String(d).padStart(2, "0")} ${MONTHS[m - 1]} ${y}`;
}

/** Whole days between two ISO dates, or null if either endpoint is unknown.
 *  Elapsed days is always computed from two real dates, never stored -- the LLM
 *  extracts, the database (here, this function) computes. Null, not a bare
 *  number and not NaN: DESIGN.md is explicit that elapsed days always carries
 *  both endpoints, and an endpoint that does not exist cannot be one -- the
 *  gap is genuinely unknown, not zero, so callers render the same "—" rather
 *  than a number that would misstate a chronology in front of a tribunal. */
export function daysBetween(fromIso: string | null, toIso: string | null): number | null {
  if (!fromIso || !toIso) return null;
  const from = new Date(fromIso + "T00:00:00Z").getTime();
  const to = new Date(toIso + "T00:00:00Z").getTime();
  if (Number.isNaN(from) || Number.isNaN(to)) return null;
  return Math.round((to - from) / 86_400_000);
}
