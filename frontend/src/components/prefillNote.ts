/* What an account's page says after "Start from the last one": where the new
   situation was copied from, what the market priced, which rows still need
   the reader, and, among those, which lost the part of their cost that had
   been paid (brief AV).

   A row partly bought since the situation it started from keeps what was
   paid, and for how many units, only when the market priced it on that day;
   one nothing priced carries no cost (crud.clone_latest_snapshot says why),
   and the reader was told only that it "still needs you". The page now says
   what was lost and how to get it back.

   Pure, so tests/prefillNote.test.ts runs it under Node. */

import type { PrefilledSnapshot } from "../api/snapshots";
import { locale } from "./money.ts";

type Answer = Pick<PrefilledSnapshot, "copied_from" | "repriced" | "needs_attention" | "paid_not_kept"> &
  Partial<Pick<PrefilledSnapshot, "not_a_code">>;

function units(n: number): string {
  return `${n.toLocaleString(locale, { maximumFractionDigits: 4 })} ${n === 1 ? "unit" : "units"}`;
}

/** The note under the button, from what the backend answered. */
export function prefillWords(s: Answer): string {
  const head = s.needs_attention.length
    ? `Copied from ${s.copied_from}. ${s.repriced.length} priced from the market. Only ${s.needs_attention.join(", ")} still needs you.`
    : `Copied from ${s.copied_from}, all ${s.repriced.length} positions priced from the market.`;
  const lost = s.paid_not_kept.map(
    (r) =>
      ` On ${r.asset_name}, what was paid (${units(r.units_paid)}) is not kept, because nothing could price it on that day: delete this situation and start again from the last one when a price is available.`,
  );
  // A currency that is not a code, copied as written (brief BA): the new
  // situation would otherwise carry it forward with nothing said.
  const codes = (s.not_a_code ?? []).map(
    (r) =>
      ` On ${r.asset_name}, the currency '${r.currency}' is not a currency code and was copied as written: correct it on that row.`,
  );
  return head + codes.join("") + lost.join("");
}
