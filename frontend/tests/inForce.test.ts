/* What the monthly figures leave out, said beside them (brief AI).

   The figures count the income and expenses in force today; the ones still
   to start and the ones that have ended come back listed apart, and the page
   says so under the figures and on each left-out row. Every expected value
   is written here; the flows are invented. */

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  IN_FORCE,
  leftOutLine,
  notCounted,
  undatedLine,
} from "../src/components/inForce.ts";

type Side = "income" | "expense";

function flow(side: Side, id: number, frequency: string | null, start: string | null, end: string | null) {
  return { side, id, name: `flow ${id}`, frequency, start_date: start, end_date: end };
}

const NOTHING = { scheduled: [], ended: [], undated: 0 };

test("the figures say what they are", () => {
  assert.equal(IN_FORCE, "In force today, as a monthly run-rate; one-off items excluded.");
});

test("nothing left out says nothing", () => {
  assert.equal(notCounted(NOTHING), null);
});

test("what starts later and what has ended are counted apart", () => {
  const summary = {
    scheduled: [flow("income", 1, "monthly", "2026-10-30", null)],
    ended: [flow("expense", 2, "monthly", "2025-01-01", "2026-06-30")],
    undated: 0,
  };
  assert.equal(notCounted(summary), "1 income that starts later, 1 expense that has ended");
});

test("several of one kind are counted together, with the verb agreeing", () => {
  const summary = {
    scheduled: [
      flow("income", 1, "monthly", "2026-10-30", null),
      flow("expense", 2, "quarterly", "2026-11-01", null),
      flow("expense", 3, null, "2026-12-01", null),
    ],
    ended: [
      flow("income", 4, "monthly", "2025-01-01", "2026-05-31"),
      flow("income", 5, "annual", "2024-01-01", "2026-01-31"),
    ],
    undated: 0,
  };
  assert.equal(
    notCounted(summary),
    "1 income and 2 expenses that start later, 2 incomes that have ended",
  );
});

test("a one-off is never in the monthly figures, so it is not counted as left out", () => {
  const summary = {
    scheduled: [flow("expense", 7, "one_off", "2026-11-15", null)],
    ended: [],
    undated: 0,
  };
  assert.equal(notCounted(summary), null);
});

test("a flow with no first payment date is said to be counted", () => {
  assert.equal(undatedLine(0), null);
  assert.equal(undatedLine(1), "1 flow with no first payment date is counted as in force.");
  assert.equal(undatedLine(3), "3 flows with no first payment date are counted as in force.");
});

test("a row that starts later says when, and that it is not counted until then", () => {
  const summary = { ...NOTHING, scheduled: [flow("income", 1, "monthly", "2026-10-30", null)] };
  assert.equal(leftOutLine(summary, "income", 1), "Starts on 2026-10-30: not counted until then.");
});

test("a row that has ended says when, and that it is no longer counted", () => {
  const summary = { ...NOTHING, ended: [flow("expense", 2, "monthly", "2025-01-01", "2026-06-30")] };
  assert.equal(leftOutLine(summary, "expense", 2), "Ended on 2026-06-30: no longer counted.");
});

test("a one-off still to come says the day it falls on", () => {
  const summary = { ...NOTHING, scheduled: [flow("expense", 7, "one_off", "2026-11-15", null)] };
  assert.equal(leftOutLine(summary, "expense", 7), "On 2026-11-15, once: not in the monthly figures.");
});

test("a row in force carries no line, and an income is never an expense", () => {
  const summary = { ...NOTHING, scheduled: [flow("income", 1, "monthly", "2026-10-30", null)] };
  assert.equal(leftOutLine(summary, "income", 9), undefined);
  assert.equal(leftOutLine(summary, "expense", 1), undefined);
});
