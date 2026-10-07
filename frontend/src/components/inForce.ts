/* What the monthly figures leave out, said beside them (brief AI).

   The Cash flow page and the Dashboard show the income and expenses IN FORCE
   today, as the chat and the analysis read them: one computation on the
   backend (`analytics.compute_flows_in_force`), which lists apart the flows
   whose first payment is after today and the ones that have ended. Until
   then the page summed every flow whatever its dates, so a salary starting
   next month read as one already paid, and nothing said otherwise.

   These are the words: the sentence under the figures, what the figures
   leave out, and the line a left-out row carries. A one-off is never in the
   monthly figures, so the count of what is left out does not name one; its
   row says when it falls.

   Pure, with type-only imports, so `tests/inForce.test.ts` runs it under
   Node without a bundler. */

import type { Schemas } from "../api/types";

type Summary = Pick<Schemas["CashFlowSummary"], "scheduled" | "ended" | "undated">;
type LeftOut = Schemas["FlowNotCounted"];

/** What the figures are, said once under them on both pages. */
export const IN_FORCE = "In force today, as a monthly run-rate; one-off items excluded.";

const ONCE = "one_off";

function counted(n: number, noun: string): string | null {
  return n > 0 ? `${n} ${noun}${n === 1 ? "" : "s"}` : null;
}

/** "1 income and 2 expenses that start later", or null for none. */
function phrase(flows: LeftOut[], one: string, many: string): string | null {
  const recurring = flows.filter((f) => f.frequency !== ONCE);
  const nouns = [
    counted(recurring.filter((f) => f.side === "income").length, "income"),
    counted(recurring.filter((f) => f.side === "expense").length, "expense"),
  ].filter((n): n is string => n !== null);
  if (nouns.length === 0) return null;
  return `${nouns.join(" and ")} that ${recurring.length === 1 ? one : many}`;
}

/** What the figures leave out, by count: "1 income that starts later, 1
    expense that has ended". Null when they leave out nothing that repeats. */
export function notCounted(summary: Summary): string | null {
  const parts = [
    phrase(summary.scheduled, "starts later", "start later"),
    phrase(summary.ended, "has ended", "have ended"),
  ].filter((p): p is string => p !== null);
  return parts.length ? parts.join(", ") : null;
}

/** A flow with no first payment date is counted: said, since the figures
    cannot show it. Null when there is none. */
export function undatedLine(n: number): string | null {
  if (n <= 0) return null;
  return n === 1
    ? "1 flow with no first payment date is counted as in force."
    : `${n} flows with no first payment date are counted as in force.`;
}

/** The line a row carries when the figures leave it out, or undefined. */
export function leftOutLine(
  summary: Summary,
  side: "income" | "expense",
  id: number,
): string | undefined {
  const later = summary.scheduled.find((f) => f.side === side && f.id === id);
  if (later) {
    return later.frequency === ONCE
      ? `On ${later.start_date}, once: not in the monthly figures.`
      : `Starts on ${later.start_date}: not counted until then.`;
  }
  const gone = summary.ended.find((f) => f.side === side && f.id === id);
  if (gone && gone.frequency !== ONCE) return `Ended on ${gone.end_date}: no longer counted.`;
  return undefined;
}
