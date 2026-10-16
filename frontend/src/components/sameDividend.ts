/* A dividend entered by hand on top of the one the app recorded (brief AI).

   The catch-up records a dividend on its ex-date at the market's gross
   figure, marked estimated, and the reader is meant to correct that row with
   what the broker credited. Typed as a new row instead, it was stored beside
   it, and the cash, the dividends collected and the tax panel all counted
   both (measured 2026-10-07 on a copy of the test database): one dividend
   gross and again net, and a withholding estimated on money already taxed.
   The API cannot tell that from a special dividend paid on the same
   day, so nothing is refused (the reader's rule): the form names the
   estimated rows the new one may be, and offers to correct one instead.

   Wider than the same day: a statement shows the PAYMENT date, which follows
   the ex-date, and a row typed on it was counted twice the same way. So every
   still-estimated dividend of that account and ticker dated on or before the
   typed date is offered, newest first.

   The ex-date is also how the catch-up knows a dividend is recorded. Until
   brief AZ it was the row's date, so a row moved off it left that day empty
   and the next start recorded the dividend there again (measured 2026-10-07,
   and again the same day at `eaa89fc`). A row now keeps its ex-date in a
   column of its own, which no form sends, so a correction takes the date
   typed, the day the broker credited it, and says the ex-date stays. Only a
   row of the app's that has not been given its ex-date yet is still found by
   its date, and moving it is said, not refused.

   Pure, so `tests/sameDividend.test.ts` runs it under Node without a
   bundler. Dates go in as ISO strings; `fmt` is how the page prints them. */

/** The ledger fields these rules read, as `TransactionRead` carries them. */
export type LedgerRow = {
  id: number;
  kind: string;
  date: string;
  institution_id: number | null;
  symbol: string | null;
  amount: number;
  currency: string;
  estimated: boolean;
  note: string | null;
  ex_date: string | null;
};

/** How many estimated rows are named; any older ones are counted. */
export const SHOWN = 3;

/** The start of the note the catch-up writes on every dividend it records
    (`pac.execute_dividends`). An edit keeps it, and the backend's tests pin
    it (`test_a_stamp_says_where_a_row_came_from.py`). */
export const AUTO_STAMP = "Auto-recorded from market data";

const asIs = (iso: string) => iso;

/** The still-estimated dividends of one account and ticker dated on or before
    `date`, newest first: the rows a dividend being typed may already be. */
export function estimatedDividends<T extends LedgerRow>(
  rows: T[],
  typed: { institutionId: number | null; symbol: string; date: string },
): T[] {
  const symbol = typed.symbol.trim().toUpperCase();
  if (typed.institutionId == null || !symbol || !typed.date) return [];
  return rows
    .filter(
      (t) =>
        t.kind === "dividend" &&
        t.estimated &&
        t.institution_id === typed.institutionId &&
        (t.symbol ?? "").toUpperCase() === symbol &&
        t.date <= typed.date,
    )
    .sort((a, b) => (a.date === b.date ? b.id - a.id : a.date < b.date ? 1 : -1));
}

/** The sentence over the offered rows. */
export function offerLine(symbol: string, where: string): string {
  return `Already recorded for ${symbol.trim().toUpperCase()} at ${where}, still estimated (the market's gross figure, before tax). If the dividend you are entering is one of these, correct it instead: a second row would count it twice.`;
}

/** What is said of the estimated rows beyond the ones named, or null. */
export function olderLine(count: number): string | null {
  const older = count - SHOWN;
  if (older <= 0) return null;
  return older === 1 ? "And 1 older one." : `And ${older} older ones.`;
}

/** The day the catch-up finds a dividend by: its ex-date where the row keeps
    one, otherwise its own date. */
export function keyDay(row: Pick<LedgerRow, "date" | "ex_date">): string {
  return row.ex_date ?? row.date;
}

/** Said once the form has become the correction of a row: it keeps its
    ex-date and takes the date in the box, the day the broker credited it. */
export function correctingLine(exDate: string, typedDate: string, fmt = asIs): string {
  const said = `Correcting the dividend with ex-date ${fmt(exDate)} with your figures: save to replace its own.`;
  return typedDate && typedDate !== exDate
    ? `${said} It will be dated ${fmt(typedDate)}, the day your broker credited it, and keep its ex-date.`
    : said;
}

/** The line under the form when a dividend that keeps its ex-date is dated
    on another day, or null. */
export function exDateStays(
  row: Pick<LedgerRow, "kind" | "ex_date">,
  date: string,
  fmt = asIs,
): string | null {
  if (row.kind !== "dividend" || !row.ex_date || !date || date === row.ex_date) return null;
  return `Its ex-date stays ${fmt(row.ex_date)}: the app finds this dividend by that day, whatever day it is dated.`;
}

/** Whether the app's catch-up recorded this row, by the stamp it wrote. */
export function recordedByTheApp(row: Pick<LedgerRow, "kind" | "note">): boolean {
  return row.kind === "dividend" && (row.note ?? "").startsWith(AUTO_STAMP);
}

/** The line under the form when a dividend the app recorded, and has not
    given its ex-date yet, is being moved off the day it was recorded on, or
    null. */
export function movedOffItsDay(
  row: Pick<LedgerRow, "kind" | "note" | "date" | "ex_date">,
  date: string,
  fmt = asIs,
): string | null {
  if (row.ex_date || !recordedByTheApp(row) || !date || date === row.date) return null;
  return `The app recorded this dividend on its ex-date, ${fmt(row.date)}, and finds it by that day. Moved to ${fmt(date)}, the dividend of ${fmt(row.date)} is recorded again at the next start, unless this account has a situation dated on or after it.`;
}
