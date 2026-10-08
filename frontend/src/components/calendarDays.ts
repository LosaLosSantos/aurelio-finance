/* Days the reader sees, counted by the calendar.

   A date in this app is a calendar day, "YYYY-MM-DD", and today is the day it
   is on the reader's clock. The situation page used to count a date's age as
   the hours since its local midnight, rounded to days: from noon on, a
   situation dated that very day was "1 days ago" and carried the warning
   meant for an old one (seen at about 15:00 on 2026-10-05, brief AE). Counted
   between calendar dates, the hour of the day cannot move the count, nor can
   a day of 23 or 25 hours when the clocks change. */

const DAY_MS = 86_400_000;

/** The calendar day of an instant on the reader's clock, as YYYY-MM-DD. Never
    `toISOString()`: that is the day in UTC, which near midnight is not the
    reader's (or the backend's) day. */
export function localDay(now: Date): string {
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${m}-${d}`;
}

/** Midnight UTC of a calendar date: the same 24 hours apart every day. */
function utcMidnight(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

/** Whole days from one calendar date to another, positive when `to` is later. */
export function daysBetween(from: string, to: string): number {
  return Math.round((utcMidnight(to) - utcMidnight(from)) / DAY_MS);
}

/** How many days ago a calendar date was: 0 all through the day it names. */
export function daysAgo(date: string, now: Date = new Date()): number {
  return daysBetween(date, localDay(now));
}

/** "1 day", "18 days". */
export function dayCount(n: number): string {
  return `${n} ${n === 1 ? "day" : "days"}`;
}

/** How old a date is, in words: "today", "1 day ago", "6 days ago". What the
    Portfolio page says beside the date its prices are of (brief AJ): a price
    days old read like today's. */
export function ageWords(date: string, now: Date = new Date()): string {
  const n = daysAgo(date, now);
  return n <= 0 ? "today" : `${dayCount(n)} ago`;
}
