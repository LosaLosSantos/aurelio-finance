/* What a position's average price and its P/L say about where its cost came
   from, on the Portfolio table (brief AI).

   A cost is estimated when any unit behind it is (`positions.replay` on the
   backend): a photographed cost derived from a reported return, or a plan's
   buy, which is priced at the market close and marked estimated until the
   reader corrects it. The titles named the first source only, so a position
   bought by a PAC said its price was "derived from a reported return", and
   until brief AI it was not even marked.

   Pure, so `tests/costWords.test.ts` runs it under Node without a bundler. */

type CostRow = { cost_known: boolean; cost_estimated: boolean };

/** The title over a row's average price. */
export function avgCostTitle(r: CostRow): string {
  if (!r.cost_known) {
    return "No purchase price on record: this is the price the situation was recorded at, not what you paid";
  }
  if (r.cost_estimated) {
    return "Average price paid, ESTIMATED in part: some or all of it is a plan's buy priced at a market close, or a cost derived from a reported return, not a contract note";
  }
  return "Average price actually paid, from recorded purchases";
}

/** The title over a row's profit or loss. */
export function plTitle(r: CostRow): string {
  if (!r.cost_known) {
    return "Movement since the situation was recorded, NOT profit: no purchase price is on record";
  }
  if (r.cost_estimated) {
    return "Profit or loss against a purchase price ESTIMATED in part (a plan's buy at a market close, or a cost derived from a reported return): real, but not verified against a contract note";
  }
  return "Profit or loss against the average price you paid";
}
