/* What a ledger row says on a line of its own (brief AZ).

   A dividend's row keeps its ex-date, the day the app finds it by, whatever
   day the row is dated: the app records a dividend on its ex-date, or on the
   day Yahoo says it is paid, and the reader corrects it to the day the broker
   credited it. The date alone said nothing about which of the two it was, and
   a cash figure turns on it: a balance typed between the ex-date and the
   payment does not hold the money. So the row names its ex-date, on `Row`'s
   `detail` line, which wraps rather than clipping: in the subtitle, which
   truncates, a window 360px wide cut a moved dividend's ex-date short
   (measured in Edge, 2026-10-16). A row still on its ex-date says that day
   twice, which is the point: its date is the ex-date, not the day the money
   arrived. An entry that keeps no ex-date (one the reader typed, not
   recognised as a listed dividend) says nothing more, as before.

   The same line already carried the warning about a currency typed against
   the listing's, and still does, after the ex-date when a row has both.

   Pure, so `tests/ledgerDetail.test.ts` runs it under Node without a bundler.
   Dates go in as ISO strings; `fmt` is how the page prints them. */

/** The ledger fields this reads, as `TransactionRead` carries them. */
export type DetailedEntry = { kind: string; ex_date: string | null; currency_note?: string | null };

const asIs = (iso: string) => iso;

/** The row's own line, or undefined when it has nothing to say. */
export function ledgerDetail(entry: DetailedEntry, fmt: (iso: string) => string = asIs): string | undefined {
  const said = [
    entry.kind === "dividend" && entry.ex_date ? `ex-date ${fmt(entry.ex_date)}` : null,
    entry.currency_note ? `⚠ ${entry.currency_note}` : null,
  ].filter(Boolean);
  return said.length ? said.join(" · ") : undefined;
}
