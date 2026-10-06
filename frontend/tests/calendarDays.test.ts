/* Today's own situation never reads as a past one, at any hour.

   The situation page counted a date's age as the hours since its local
   midnight, rounded to days: from noon on, a situation dated that very day
   was "1 days ago" and carried the warning meant for an old one. Seen in the
   browser at about 15:00 on 2026-10-05 (brief AE). Days are counted between
   calendar dates now, so neither the hour nor a 23 or 25 hour day can move
   the count.

   Each test sets the time zone it needs (`process.env.TZ`, which Node applies
   at once): the days the clocks change are tested wherever the suite runs,
   CI's UTC included. Every expected value is written here. */

import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { dayCount, daysAgo, daysBetween, localDay } from "../src/components/calendarDays.ts";

const ZONE = process.env.TZ;
afterEach(() => {
  if (ZONE === undefined) delete process.env.TZ;
  else process.env.TZ = ZONE;
});

/** Every minute of a calendar day on the clock of the zone in force. */
function everyMinuteOf(year: number, month: number, day: number): Date[] {
  const out: Date[] = [];
  for (let h = 0; h < 24; h++) {
    for (let m = 0; m < 60; m++) out.push(new Date(year, month - 1, day, h, m, 30));
  }
  return out;
}

const ZONES = ["UTC", "Europe/Rome", "America/New_York", "Pacific/Kiritimati", "Pacific/Pago_Pago"];

test("a situation dated today is 0 days old at every minute of the day, in every zone", () => {
  for (const zone of ZONES) {
    process.env.TZ = zone;
    for (const now of everyMinuteOf(2026, 10, 5)) {
      assert.equal(daysAgo("2026-10-05", now), 0, `${zone}, ${now.toString()}`);
    }
  }
});

test("yesterday's is 1 day old at every minute of today", () => {
  for (const zone of ZONES) {
    process.env.TZ = zone;
    for (const now of everyMinuteOf(2026, 10, 5)) {
      assert.equal(daysAgo("2026-10-04", now), 1, `${zone}, ${now.toString()}`);
    }
  }
});

test("on the days the clocks change, today is still today and yesterday one day back", () => {
  process.env.TZ = "Europe/Rome";
  // 2026-03-29 has 23 hours there, 2026-10-25 has 25.
  for (const [today, yesterday, y, m, d] of [
    ["2026-03-29", "2026-03-28", 2026, 3, 29],
    ["2026-10-25", "2026-10-24", 2026, 10, 25],
  ] as const) {
    for (const now of everyMinuteOf(y, m, d)) {
      assert.equal(daysAgo(today, now), 0, now.toString());
      assert.equal(daysAgo(yesterday, now), 1, now.toString());
    }
  }
});

test("the day of an instant is the reader's calendar day, at both ends of it", () => {
  process.env.TZ = "Europe/Rome";
  assert.equal(localDay(new Date(2026, 9, 5, 0, 0, 0)), "2026-10-05");
  assert.equal(localDay(new Date(2026, 9, 5, 23, 59, 59)), "2026-10-05");
  assert.equal(localDay(new Date(2026, 0, 1, 0, 0, 1)), "2026-01-01");
});

test("days between two calendar dates", () => {
  assert.equal(daysBetween("2026-10-05", "2026-10-05"), 0);
  assert.equal(daysBetween("2026-02-28", "2026-03-01"), 1);
  assert.equal(daysBetween("2028-02-28", "2028-03-01"), 2);
  assert.equal(daysBetween("2025-12-31", "2026-01-01"), 1);
  assert.equal(daysBetween("2026-09-17", "2026-10-05"), 18);
  assert.equal(daysBetween("2026-10-06", "2026-10-05"), -1);
});

test("one day is a day, two are days", () => {
  assert.equal(dayCount(1), "1 day");
  assert.equal(dayCount(2), "2 days");
  assert.equal(dayCount(18), "18 days");
});
