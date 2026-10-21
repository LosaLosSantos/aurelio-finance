/* The net worth chart's words and its days (brief BD).

   The card said "Hover for the financial / real / debt breakdown behind each
   point", a pointer's word, while the breakdown is reached three ways: a tap
   shows it, and so does the keyboard, the chart's surface taking the focus
   and the arrow keys moving it from point to point (measured in Edge,
   2026-10-20). The words now name all three, and the table beside the chart.

   And it named a day without its year: over two years of records its axis
   read three "Oct 6". A tick now says its year, on a line under its day,
   when the points span a year or more, which is when a day and a month can
   come round again; under a year the axis is as it was.

   Pure, so `tests/chartDays.test.ts` runs it under Node. `at` is the locale,
   the reader's unless a test names one. */

import { locale } from "./money.ts";

/** What the card says under its title. */
export const BREAKDOWN_WORDS =
  "Tap or point at the chart for each point's financial, real and debt figures, or tab to it and use the arrow keys; the table lists them all.";

/** Whether the points, from `first` to `last` (ISO days), span a year or
    more: the last on or after the first's day and month a year later. */
export function spansAYear(first: string, last: string): boolean {
  const years = Number(last.slice(0, 4)) - Number(first.slice(0, 4));
  return years > 1 || (years === 1 && last.slice(5) >= first.slice(5));
}

/** A tick's lines: its day ("Oct 6"), and under it its year when the span
    needs it. */
export function tickLines(iso: string, withYear: boolean, at: string | undefined = locale): string[] {
  const day = new Date(iso + "T00:00:00");
  const said = day.toLocaleDateString(at, { day: "numeric", month: "short" });
  return withYear ? [said, String(day.getFullYear())] : [said];
}
