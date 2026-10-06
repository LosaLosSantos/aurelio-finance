/* The first date of something that repeats, and what it does (brief AE).

   Two forms ask for it. On a flow it was labelled "start", and the reader
   read it as "the day I typed it in": afraid that a real date in January
   would add every month since to the cash already counted, they typed the
   next payment instead, and then the 1st of a month, not knowing the day is
   the payment day. On a PAC it was "start" too, and the section promised that
   elapsed dates "fill themselves in": so a plan already running at a broker,
   entered with its real first buy, had every month rebuilt at Yahoo's closes
   and written into the records, where it disagrees with the broker's
   statement (brief R measured 42 units against the broker's 36).

   So each form says what its date does. A flow's date is its first payment,
   and the line under its title says the day repeats and the past is already
   in the balance. A PAC's is its first buy, and a save that would write buys
   before today says how many, and, for a plan that has not run yet, offers
   the better way in one press: the plan from its next date, and the broker's
   numbers for today.

   The dates mirror the backend's: start + k months, the day clamped only
   inside a shorter month (`analytics.recurrence`), and a month the plan
   already has counts as its own (`pac._settled_months`). */

/** How many months between two dates of a schedule, as the backend steps it. */
const STEP_MONTHS: Record<string, number> = { monthly: 1, quarterly: 3, semiannual: 6, annual: 12 };

function pad(n: number, width = 2): string {
  return String(n).padStart(width, "0");
}

/** `iso` plus `n` months, the day clamped to the length of the month it lands
    in. In whole numbers, never through a `Date` in local time, so no timezone
    can move it by a day. */
export function addMonths(iso: string, n: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const index = m - 1 + n;
  const year = y + Math.floor(index / 12);
  const month = (((index % 12) + 12) % 12) + 1;
  // Day 0 of the next month is the last day of this one.
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return `${pad(year, 4)}-${pad(month)}-${pad(Math.min(d, last))}`;
}

/** The dates of a schedule from `start` to `until` (both inclusive), bounded
    by `end`: start + k steps, never the date before + one step. */
export function schedule(start: string, frequency: string | null, end: string | null, until: string): string[] {
  const step = STEP_MONTHS[frequency || "monthly"] ?? 1;
  const last = end && end < until ? end : until;
  const out: string[] = [];
  for (let k = 0; k < 10000; k++) {
    const date = addMonths(start, k * step);
    if (date > last) break;
    out.push(date);
  }
  return out;
}

/** The first date of a schedule after `today`, or null when it ends first. */
export function nextAfter(start: string, frequency: string | null, end: string | null, today: string): string | null {
  const step = STEP_MONTHS[frequency || "monthly"] ?? 1;
  for (let k = 0; k < 10000; k++) {
    const date = addMonths(start, k * step);
    if (end && date > end) return null;
    if (date > today) return date;
  }
  return null;
}

/** A plan's dates, as the form holds them and as they are stored. */
export type PlanDates = { start: string; frequency: string | null; end: string | null };

export type PastBuys = {
  /** The dates the save adds buys for, up to today. */
  dates: string[];
  /** Whether the plan, as stored, has run: a date of its own before today. A
      new plan, or one stored to start today or later, has not. */
  hasRun: boolean;
  /** The first date after today, offered in one press to a plan that has not
      run. Null for one that has, and for one that ends before it. */
  next: string | null;
};

/** What saving `draft` would write before today, given the plan as stored
    (null for a new one), or null when it writes nothing there.

    A month the stored schedule already has up to today is the plan's own:
    bought, or waiting for its close, and the backend settles it once (by
    month). So an edit that keeps the first buy, or moves its day, adds
    nothing; an earlier first buy, or a frequency that adds months, adds
    exactly those. A first buy of today is not in the past: today's buy is
    the plan's first, and it waits for today's close like any other. */
export function pastBuys(draft: PlanDates, stored: PlanDates | null, today: string): PastBuys | null {
  if (!draft.start) return null;
  const own = stored?.start ? schedule(stored.start, stored.frequency, stored.end, today) : [];
  const months = new Set(own.map((d) => d.slice(0, 7)));
  const dates = schedule(draft.start, draft.frequency, draft.end, today).filter((d) => !months.has(d.slice(0, 7)));
  if (!dates.some((d) => d < today)) return null;
  const hasRun = own.some((d) => d < today);
  return { dates, hasRun, next: hasRun ? null : nextAfter(draft.start, draft.frequency, draft.end, today) };
}

/** The warning a form shows for `pastBuys`, sentence by sentence. `alternative`
    and `button` are null when there is nothing to offer. */
export function pastBuysWarning(p: PastBuys, start: string): {
  lead: string;
  body: string;
  alternative: string | null;
  button: string | null;
} {
  const n = p.dates.length;
  const what =
    n === 1
      ? `a buy into your records, dated ${p.dates[0]}`
      : `${n} buys into your records, dated from ${p.dates[0]} to ${p.dates[n - 1]}`;
  return {
    lead: p.hasRun ? "This change adds dates before today." : `${start} is in the past.`,
    body: `Saved like this, the app writes ${what}, priced at Yahoo's close rather than at your broker's fills, and marked estimated.`,
    alternative: p.next
      ? "Already running at your broker? Then let everything up to today be the broker's: start the plan on its next date, and enter today's units and cash from its statement on the account's page."
      : null,
    button: p.next ? `Start on ${p.next}` : null,
  };
}

/** Said under the dates once the one press has set the next date. */
export function startsLine(next: string): string {
  return `Starts ${next}. Once it is saved, enter today's units and cash from the broker's statement on the account's page.`;
}

/** Said above the plans once a plan set that way is saved; the accounts it
    touches follow as links. */
export function afterSaveLine(name: string, start: string): string {
  return `${name} starts on ${start}. Record today's situation and cash balance from the broker's statement (start the situation from the last one, so the other positions stay):`;
}

/** A flow's date. A one-off happens on it; anything else is first paid on it,
    and repeats on its day. */
export function flowDateLabel(frequency: string): string {
  return frequency === "one_off" ? "on" : "first payment";
}

/** The line in view under the Income and Expenses titles. */
export const FIRST_PAYMENT_NOTE =
  "The first payment's day is the day it repeats on. A past date is safe: payments before the account's latest balance are already in it.";

/** A PAC's date. */
export const PLAN_DATE_LABEL = "first buy";

/** The line in view under the PAC title: where a buy's figures come from. */
export const PLAN_NOTE =
  "Each date's buy is written the first time the app opens after that day, at its market close (converted at that day's ECB rate when the fund trades in another currency), and marked estimated.";
