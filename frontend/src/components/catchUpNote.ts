/* What the start-up banner adds when the catch-up recorded dividends.

   A dividend is recorded at the market's figure: Yahoo's amount per share,
   GROSS, because Yahoo has no withholding tax. What lands in the account is
   what the broker credits after tax, so the row is estimated until the reader
   types that amount over it (which also clears `estimated`, and the tax panel
   stops withholding on it). The banner already says "estimated"; this says
   which figure corrects a dividend, because "the real amount" alone reads as
   the same gross figure from another source.

   Pure, and with no runtime imports, so `tests/catchUpNote.test.ts` runs it
   under Node without a bundler. */

/** The entries `recordedFor` reads, as `TransactionRead` carries them. */
export type Created = { kind: string; symbol: string | null; institution_id: number | null };

/** The recorded dividends counted by ticker and account, in the order they
    were recorded: "Recorded for XDIV.MI at Broker A (4) and YDIV.MI at
    Broker B (1)." A first start after brief AZ can record many at once, the
    dividends of stretches the catch-up never met, so the banner lists where
    they went rather than leaving the reader to count rows. Null when none. */
export function recordedFor(created: Created[], accounts: Record<string, string>): string | null {
  const counts = new Map<string, number>();
  for (const t of created) {
    if (t.kind !== "dividend") continue;
    const at = t.institution_id != null ? accounts[String(t.institution_id)] : undefined;
    const key = at ? `${t.symbol} at ${at}` : (t.symbol ?? "");
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  if (counts.size === 0) return null;
  const items = [...counts].map(([where, n]) => `${where} (${n})`);
  const said = items.length === 1 ? items[0] : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
  return `Recorded for ${said}.`;
}

/** The sentence for `count` recorded dividends, or null when there are none. */
export function dividendsNote(count: number): string | null {
  if (count <= 0) return null;
  return count === 1
    ? "The dividend is the market's gross figure, before tax: correct it with what your broker credited."
    : "The dividends are the market's gross figures, before tax: correct each with what your broker credited.";
}
