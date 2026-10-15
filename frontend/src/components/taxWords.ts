/* What the Portfolio's realized line and its tax panel say about a movement
   (brief AV).

   A sell or a close realizes a gain or a loss only on the units paid for. On
   a situation's value that no purchase price was recorded for, its result is
   a movement since that situation: not a profit, and no rate can be applied
   to it, because its gain depends on a cost nobody wrote down. The estimate's
   total therefore leaves that tax out, and the total is never said without
   it: `estimatedTotal` writes both in one sentence, so no caller can print
   the one and forget the other.

   Pure, so tests/taxWords.test.ts runs it under Node. */

import type { Schemas } from "../api/types";
import { money } from "./money.ts";

type TaxEstimate = Schemas["TaxEstimate"];

/** The window the realized P/L, the dividends collected and the tax estimate
    cover (brief AW): every stretch of the ledger since each account's first
    situation. They covered only what followed each account's latest one, so a
    new situation took out of all three what had been realized and collected
    since the one before (measured: 208.33, 12.00 and 54.17 to 0.00). */
export const TOTALS_WINDOW = "since each account's first situation";

/** An amount with its sign always said: a movement goes up or down. */
function signed(amount: number, base: string): string {
  return (amount > 0 ? "+" : "") + money(base).format(amount);
}

/** The movement beside the realized P/L, or null when none was realized:
    "movement +€100 (no purchase price on record)". */
export function realizedMovement(movement: number, base: string): string | null {
  if (!movement) return null;
  return `movement ${signed(movement, base)} (no purchase price on record)`;
}

/** Whether the panel has anything to say: a gain or a loss realized, a
    movement realized, or a dividend still at the market's gross figure. */
export function taxPanelShown(est: TaxEstimate): boolean {
  return (
    est.realized_gain !== 0 || est.realized_movement !== 0 || est.dividends_gross_estimated > 0
  );
}

/** The estimated total, and in the same sentence what it leaves out; null
    when there is no total. */
export function estimatedTotal(
  est: TaxEstimate,
  base: string,
): { amount: string; words: string } | null {
  if (est.total == null) return null;
  const leftOut = est.realized_movement
    ? `. It leaves out the ${signed(est.realized_movement, base)} of movement realized on situations' values with no purchase price on record, which no rate can be applied to`
    : "";
  return {
    amount: money(base).format(est.total),
    words: `estimated, and counted in none of the totals above${leftOut}`,
  };
}

/** The panel's line for the movement, beside the realized gain's; null when
    none was realized. */
export function movementLine(est: TaxEstimate, base: string): string | null {
  if (!est.realized_movement) return null;
  return `Realized movement ${signed(est.realized_movement, base)} on situations' values with no purchase price on record: not a gain, and no rate is applied to it`;
}
