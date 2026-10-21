/* The net worth chart's words and days (brief BD): words a finger and a
   keyboard can act on, and a tick that says its year when the points span a
   year or more. Every expected value is written here, in en-US. */

import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { BREAKDOWN_WORDS, spansAYear, tickLines } from "../src/components/chartDays.ts";

const ZONE = process.env.TZ;
afterEach(() => {
  process.env.TZ = ZONE;
});

test("the words name a tap, a pointer and the keyboard, and the table, and no hover", () => {
  assert.equal(
    BREAKDOWN_WORDS,
    "Tap or point at the chart for each point's financial, real and debt figures, or tab to it and use the arrow keys; the table lists them all.",
  );
  assert.doesNotMatch(BREAKDOWN_WORDS, /hover/i);
});

test("a span reaches a year on the first day's anniversary, not the day before", () => {
  assert.equal(spansAYear("2024-10-06", "2025-10-05"), false);
  assert.equal(spansAYear("2024-10-06", "2025-10-06"), true);
  assert.equal(spansAYear("2024-10-06", "2026-10-20"), true);
  assert.equal(spansAYear("2025-11-24", "2026-10-20"), false);
  assert.equal(spansAYear("2025-12-31", "2026-01-01"), false);
  assert.equal(spansAYear("2024-12-31", "2026-01-01"), true);
});

test("a span from the 29th of February reaches a year when the 1st of March comes round", () => {
  assert.equal(spansAYear("2024-02-29", "2025-02-28"), false);
  assert.equal(spansAYear("2024-02-29", "2025-03-01"), true);
});

test("a tick says its day, and its year on a line of its own when the span needs it", () => {
  assert.deepEqual(tickLines("2024-10-06", false, "en-US"), ["Oct 6"]);
  assert.deepEqual(tickLines("2024-10-06", true, "en-US"), ["Oct 6", "2024"]);
  assert.deepEqual(tickLines("2026-01-06", true, "en-US"), ["Jan 6", "2026"]);
});

test("a tick's day and year are the day it names, in any time zone", () => {
  for (const zone of ["UTC", "Europe/Rome", "America/Los_Angeles", "Pacific/Kiritimati"]) {
    process.env.TZ = zone;
    assert.deepEqual(tickLines("2025-01-01", true, "en-US"), ["Jan 1", "2025"]);
    assert.deepEqual(tickLines("2024-12-31", true, "en-US"), ["Dec 31", "2024"]);
  }
});
