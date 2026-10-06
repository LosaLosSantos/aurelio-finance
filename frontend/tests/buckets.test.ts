/* The situation's buckets add up to its total.

   Run by `npm test` with Node's own test runner, which strips the types itself:
   no bundler and no test framework, because the module under test has no
   runtime imports. Type-checked by `tsc -b` through tsconfig.node.json. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { BUCKETS, bucketOf, classOnSave, sortIntoBuckets } from "../src/components/buckets.ts";

// Every class the backend knows (models.Holding.asset_class), none at all, and
// one nobody has invented yet — the rule has to hold for all of them, not just
// for the classes someone thought of.
const CLASSES = [
  "cash",
  "equity",
  "bond",
  "fund_etf",
  "crypto",
  "real_estate",
  "commodity",
  "other",
  null,
  "a_class_from_next_year",
];

// Whole numbers, so the sums compare exactly.
const holdings = CLASSES.map((asset_class, i) => ({ id: i, asset_class, value_base: 100 * (i + 1) }));
const sum = (rows: { value_base: number }[]) => rows.reduce((acc, h) => acc + h.value_base, 0);

test("every holding is shown in exactly one bucket, and the subtotals add up to the total", () => {
  const sorted = sortIntoBuckets(holdings);
  for (const h of holdings) {
    const shownIn = sorted.filter((s) => s.holdings.includes(h)).map((s) => s.bucket.label);
    assert.equal(shownIn.length, 1, `${String(h.asset_class)} is shown in ${JSON.stringify(shownIn)}`);
  }
  const subtotals = sorted.map((s) => sum(s.holdings));
  assert.equal(subtotals.reduce((a, b) => a + b, 0), sum(holdings));
});

test("Stocks & ETF shows fund_etf beside equity — every PAC purchase is fund_etf", () => {
  assert.equal(bucketOf("fund_etf").label, "Stocks & ETF");
  assert.equal(bucketOf("equity").label, "Stocks & ETF");
});

test("a class no bucket names is shown in Other, never nowhere", () => {
  for (const cls of ["cash", "real_estate", null, undefined, "a_class_from_next_year"]) {
    assert.equal(bucketOf(cls).label, "Other", String(cls));
  }
});

test("a new holding takes its bucket's class; an edited one keeps its own", () => {
  const stocks = BUCKETS.find((b) => b.label === "Stocks & ETF")!;
  const other = BUCKETS.find((b) => b.label === "Other")!;
  assert.equal(classOnSave(stocks, null), "equity");
  assert.equal(classOnSave(stocks, { asset_class: "fund_etf" }), "fund_etf");
  assert.equal(classOnSave(other, { asset_class: "cash" }), "cash");
  assert.equal(classOnSave(other, { asset_class: null }), null);
});
