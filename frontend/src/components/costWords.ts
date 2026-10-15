/* What a position's average price and its P/L say about where its cost came
   from, on the Portfolio table (brief AI, brief AV).

   A cost is estimated when any unit behind it is (`positions.replay` on the
   backend): a photographed cost derived from a reported return, or a plan's
   buy, which is priced at the market close and marked estimated until the
   reader corrects it. The words named the first source only, so a position
   bought by a PAC said its price was "derived from a reported return", and
   until brief AI it was not even marked.

   A cost is also known in part (brief AV): a row photographed with no cost
   and bought since holds both a situation's value and money paid, and it said
   "cost unknown" for all of it. It now says how much was paid ("23% paid"),
   and its P/L in two figures: the gain or loss on the units paid for, and the
   movement on the rest since its situation, which is not a profit.

   The cells say "est.", "N% paid", "cost unknown" and "since situation". What
   those words mean was a tooltip on every cell, which a phone never shows and
   a keyboard never reaches; it is said once, behind the table's "?" (brief
   AU).

   Pure, so `tests/costWords.test.ts` runs it under Node without a bundler;
   its shape is ui.tsx's `Explain`, written out so nothing here imports JSX. */

import type { PortfolioRow } from "../api/portfolio";

/** The Portfolio table's "?". */
export const COST_WORDS: { question: string; text: string } = {
  question: "What do est., % paid, cost unknown and since situation mean?",
  text:
    "est.: the price paid is estimated in part. Some or all of it is a plan's buy priced at a market close, or a cost derived from a reported return, not a contract note, so the P/L against it is real but not verified." +
    " N% paid: of the price on record, that share is money paid, by a buy or a cost typed on a situation; the rest is the value a situation was recorded at. The P/L then shows separately the gain or loss on the units paid for and, marked since situation, the movement on the rest, which is not a profit. To make the rest a cost, type what all the units cost on the situation's row (Records, the account, the situation)." +
    " A situation started from the last one keeps what was paid where it could price the row. Where it could not, or before this version, what had been paid went into that situation's value: the app reads it back from the ledger, proposes it above the table, and writes it only if you keep it." +
    " Cost unknown: no purchase price is on record. Recorded is then the value the situation was recorded at, not what you paid, and the P/L under it, marked since situation, is the movement since that situation, not a profit.",
};

/** The fields of a Portfolio row these words read. */
type CostRow = Pick<PortfolioRow, "cost_known" | "book_value" | "book_paid" | "delta" | "delta_paid">;

/** How much of a row's price on record was paid, for a row partly paid:
    "23% paid". Null for a row all paid, or with nothing paid. Never "100%"
    of a row not all paid, nor "0%" of one that holds a paid cent. */
export function paidShare(r: CostRow): string | null {
  if (r.cost_known || !(r.book_paid > 0) || !(r.book_value > 0)) return null;
  const n = Math.round((r.book_paid / r.book_value) * 100);
  if (n >= 100) return "over 99% paid";
  if (n <= 0) return "under 1% paid";
  return `${n}% paid`;
}

/** The P/L of a row partly paid, in its two parts: the gain or loss on the
    units paid for, and the movement on the rest since its situation. Null
    for a row all paid or with nothing paid, which keep one figure, and for a
    row nothing priced. */
export function plSplit(r: CostRow): { paid: number; movement: number } | null {
  if (paidShare(r) === null || r.delta == null || r.delta_paid == null) return null;
  return { paid: r.delta_paid, movement: r.delta - r.delta_paid };
}

/** Of the P/L the priced rows add up to, the part on money paid; null when
    every priced row is all paid, and the whole of it is. */
export function pricedPaid(rows: CostRow[]): number | null {
  const priced = rows.filter((r) => r.delta != null);
  if (priced.every((r) => r.cost_known)) return null;
  return priced.reduce((sum, r) => sum + (r.delta_paid ?? 0), 0);
}
