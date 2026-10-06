import type { CashAnchor } from "../api/cash";

/* What a form proposes as a currency before the reader has typed one.

   A proposal, never a decision: a form keeps the reader's own choice beside it
   and uses that whenever there is one, so a change of account or of date moves
   the proposal and leaves a currency picked by hand where it was. The proposal
   exists because the alternative was worse than empty — every box opened at
   the new-row currency, and a reader who did not touch it recorded euro leaving
   a dollar account, past the very requirement that a currency be stated. */

/** The currency an account keeps its cash in on `date`: that of its anchor in
    force then — the latest dated on or before it — or of its first anchor when
    the date comes before them all. Null for an account with no anchor, and for
    no account: nothing then says what currency its money is in.

    The same rule the dividend catch-up credits an account by
    (`pac.execute_dividends` in the backend). */
export function accountCurrencyOn(
  anchors: CashAnchor[],
  institutionId: number | null,
  date: string,
): string | null {
  if (institutionId == null) return null;
  const own = anchors
    .filter((a) => a.institution_id === institutionId)
    .sort((a, b) => a.date.localeCompare(b.date));
  if (own.length === 0) return null;
  const inForce = own.filter((a) => a.date <= date).pop();
  return (inForce ?? own[0]).currency;
}

/** The trading currency the price cache has learned for a listing, or null.
    Tickers are matched without regard to case, as Yahoo matches them. */
export function listingCurrencyOf(
  listing: Record<string, string>,
  symbol: string,
): string | null {
  const wanted = symbol.trim().toUpperCase();
  if (!wanted) return null;
  for (const [sym, currency] of Object.entries(listing)) {
    if (sym.toUpperCase() === wanted) return currency;
  }
  return null;
}
