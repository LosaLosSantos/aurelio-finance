/* What a ledger entry's cash figure works out to, and whether the stored one
   could only have been typed.

   THE DEFECT THIS EXISTS FOR. The ledger form's debit box was rendered only
   when the entry's two currencies DIFFERED, so a row in one currency always
   sent `amount: null` — "work it out" — and the box that would have shown the
   stored figure was not on screen. Measured in the built app: a buy stored with
   307.42 (the contract note's figure, odd fees and all), opened with the pencil
   and saved CHANGING NOTHING, came back 300.00. And 128 lines above that
   missing box the same form tells the reader "Rows marked 'estimated' came from
   market closes or gross dividends — correct them with the real broker
   amounts", while an auto-recorded dividend is gross with fees 0 and `pac.py`
   says the statement's credit is meant to correct it. Across currencies the
   reader can. For a fund quoted in the account's own currency — the ordinary
   case — there was no box, so the correction the design is built on could not
   be made at all.

   WHY IT IS NOT SIMPLY PRE-FILLED. An empty box means "work it out", and that
   is the gesture that keeps the cash figure in step with an edited quantity:
   change 10 units to 11 and the debit follows. A box pre-filled on every edit
   would silently stop that — the quantity would move and the cash would not.
   So the box is pre-filled only when the stored figure cannot be a derived one.

   HOW THE TWO ARE TOLD APART, WITH NOTHING NEW STORED. `fx_as_of` is null for
   BOTH a derived and a stated same-currency amount (`fx.convert_on` returns
   (100.0, null) for EUR to EUR), so it cannot answer this on its own — and a
   provenance column is not worth adding for it, because the row already knows:
   compare the stored amount with what the row WOULD derive. Equal means the
   figure is indistinguishably derived and nothing is lost by treating it so;
   different means it can only have come from a statement.

   Across two currencies that comparison is not available in the browser — the
   derivation needs the rate of the entry's own day — and there `fx_as_of`
   answers exactly: the app sets it when IT worked the amount out, and leaves it
   empty for a figure the reader stated.

   Pure, and with no runtime imports, so `tests/statedAmount.test.ts` runs it
   under Node without a bundler. */

/** The four kinds of ledger entry, as `models.Transaction` spells them. */
export type Kind = "buy" | "sell" | "dividend" | "close";

export type Entry = {
  kind: string;
  quantity: number;
  unit_price: number;
  fees: number;
  /** What the account moved by, as stored. */
  amount: number;
  currency: string;
  price_currency: string | null;
  /** The ECB day the app worked `amount` out at, null when it did not. */
  fx_as_of: string | null;
};

/* Half a cent: as far as the backend's rounding can move a figure it works
   out, the half cent itself included.

   `crud._transaction_columns` stores every amount it works out in cents
   (since brief AI; before, only when a rate was used), so a derived amount
   is the row's own figure rounded to the cent, never more than half a cent
   from it. At an exact tie it is exactly half a cent away: 1 x 0.125 is
   stored as 0.12, and read as a statement's it would open pre-filled and
   stop following its quantity. Rows stored before keep the double they came
   to (10 x 30.05 as 300.49999999999994), well inside it. A figure further
   than half a cent can only have come from a statement: 300.51 against
   300.50. The hair is the double's own error at the edge. */
const HALF_A_CENT = 0.005;
const HAIR = 1e-9;

/** What one entry costs or pays, from the figures beside it.

    The same rule as `crud._transaction_columns`, which is the one that STORES
    it: a buy costs quantity x price plus fees, everything else nets them off
    and never goes below zero. A second copy of a rule is a debt, and this one
    is declared: the browser cannot call the backend to fill in a placeholder
    as the reader types. It is at least one copy rather than two — the overspend
    warning computed its own before this existed. */
export function derivedAmount(entry: {
  kind: string;
  quantity: number;
  unit_price: number;
  fees: number;
}): number {
  const gross = (entry.quantity || 0) * (entry.unit_price || 0);
  const fees = entry.fees || 0;
  return entry.kind === "buy" ? gross + fees : Math.max(gross - fees, 0);
}

/** Whether this entry's two currencies are different figures.

    Also true when the price currency is EMPTY, which is the case the original
    box missed on top of the matching one: `priceCurrency.trim() !== ""` gated
    the render, so a row that had not said what its price is in had no box
    either. Here an unstated price currency means there is nothing to convert
    FROM, so the amount is in one currency like any other. */
export function acrossCurrencies(
  currency: string,
  priceCurrency: string | null,
): boolean {
  const price = (priceCurrency ?? "").trim();
  return price !== "" && price !== currency.trim();
}

/** Whether a stored amount can only have come from a statement.

    Across currencies: the app stamps `fx_as_of` when it worked the figure out,
    so an empty one is the reader's own. In one currency: it is stated when it
    is further from what the row would derive than the backend's rounding to
    the cent can take it.

    A `close` is neither — its proceeds ARE the amount, typed into the box that
    holds them, and the form puts them back there itself. */
export function wasStated(entry: Entry): boolean {
  if (entry.kind === "close") return false;
  if (acrossCurrencies(entry.currency, entry.price_currency)) {
    return entry.fx_as_of == null;
  }
  return Math.abs(entry.amount - derivedAmount(entry)) > HALF_A_CENT + HAIR;
}

/** What the debit box opens with when an entry is edited: the stored figure
    when only a statement can explain it, and empty — meaning "work it out" —
    otherwise. */
export function debitOnEdit(entry: Entry): string {
  return wasStated(entry) ? String(entry.amount) : "";
}
