/* How far a close may lie from a situation's date for the situation's value
   to be turned into units with it.

   The "→ units" button on the situation form divides the value the reader
   typed by a close. That is arithmetic only when both describe nearly the
   same day: June's value divided by today's price invents a quantity nobody
   held. The allowance is four days, counted between calendar dates. It was
   counted in milliseconds between the two dates' local midnights, so across
   an autumn clock change four days read 4.0417 and the close was refused:
   2026-10-25 to 2026-10-29 in Rome, 2026-11-01 to 2026-11-05 in New York
   (measured 2026-10-05).

   The import names its extension because Node's test runner loads this file
   as it is and resolves nothing without one; the bundler takes either. */

import { daysBetween } from "./calendarDays.ts";

/** The most calendar days a close may lie from the situation's date. */
export const CLOSE_ALLOWANCE_DAYS = 4;

/** Whether a close dated `closeDate` is too far from a situation dated
    `situationDate` to turn the situation's value into units. */
export function closeTooFar(situationDate: string, closeDate: string): boolean {
  return Math.abs(daysBetween(situationDate, closeDate)) > CLOSE_ALLOWANCE_DAYS;
}
