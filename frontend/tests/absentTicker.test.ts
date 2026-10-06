/* The line a holding's form says when its ticker is left empty: only the costs
   that apply to the row as it stands, and nothing once a ticker is typed.

   Run by `npm test` with Node's own test runner, which strips the types
   itself. Type-checked by `tsc -b` through tsconfig.node.json. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { absentTickerCost, type HoldingDraft } from "../src/components/absentTicker.ts";

const ISIN = "IE00B4L5Y983";
const draft = (over: Partial<HoldingDraft>): HoldingDraft => ({
  name: "iShares Core MSCI World", symbol: "", isin: ISIN, mode: "qty", policy: "",
  assetClass: "equity", ...over,
});

// Since brief AF a row with no policy has its dividends followed through its
// own history, which needs the ticker: without one, whatever it pays is lost.
const UNPRICED_UNFOLLOWED = "Without a ticker it will not be priced and any dividends it pays will not be collected.";

test("nothing before there is a name, and nothing once a ticker is typed", () => {
  assert.equal(absentTickerCost(draft({ name: "  " })), null);
  assert.equal(absentTickerCost(draft({ symbol: "EUNL.DE" })), null);
});

test("a blank of spaces is no ticker", () => {
  assert.equal(absentTickerCost(draft({ symbol: "   " })), UNPRICED_UNFOLLOWED);
});

test("a total with an ISIN loses nothing for lacking a ticker", () => {
  assert.equal(absentTickerCost(draft({ mode: "total" })), null);
  assert.equal(absentTickerCost(draft({ mode: "total", policy: "dist" })), null);
});

test("price and dividends: only a ticker fixes them, so only a ticker is named", () => {
  assert.equal(absentTickerCost(draft({})), UNPRICED_UNFOLLOWED);
  assert.equal(absentTickerCost(draft({ assetClass: "fund_etf" })), UNPRICED_UNFOLLOWED);
  assert.equal(absentTickerCost(draft({ policy: "acc" })), "Without a ticker it will not be priced.");
  assert.equal(
    absentTickerCost(draft({ policy: "dist" })),
    "Without a ticker it will not be priced and its dividends will not be collected.",
  );
});

test("a coin pays no dividend, so it is told only about its price", () => {
  // pac._follows_dividends never asks Yahoo about crypto with no policy
  assert.equal(absentTickerCost(draft({ assetClass: "crypto" })), "Without a ticker it will not be priced.");
});

test("the look-through: a ticker or an ISIN fixes it, so both are named, in one sentence per state", () => {
  assert.equal(
    absentTickerCost(draft({ isin: "", mode: "total" })),
    "Without a ticker or an ISIN it will not be looked through.",
  );
  // a total is paid no dividends by the app with or without a ticker: pac.py
  // needs a quantity, so a distributing total is not told it loses them
  assert.equal(
    absentTickerCost(draft({ isin: "", mode: "total", policy: "dist" })),
    "Without a ticker or an ISIN it will not be looked through.",
  );
  assert.equal(
    absentTickerCost(draft({ isin: "" })),
    "Without a ticker it will not be priced and any dividends it pays will not be collected, " +
      "and without a ticker or an ISIN it will not be looked through.",
  );
  assert.equal(
    absentTickerCost(draft({ isin: "", policy: "acc" })),
    "Without a ticker it will not be priced, and without a ticker or an ISIN it will not be looked through.",
  );
  assert.equal(
    absentTickerCost(draft({ isin: "", policy: "dist" })),
    "Without a ticker it will not be priced and its dividends will not be collected, " +
      "and without a ticker or an ISIN it will not be looked through.",
  );
});

test("an ISIN is judged as the backend will store it: trimmed, upper-cased, unspaced", () => {
  // crud._clean_isin saves "IE00 B4L5 Y983" as IE00B4L5Y983, which is looked through
  assert.equal(absentTickerCost(draft({ isin: "IE00 B4L5 Y983", mode: "total" })), null);
  assert.equal(absentTickerCost(draft({ isin: " ie00b4l5y983 ", mode: "total" })), null);
  assert.equal(
    absentTickerCost(draft({ isin: "IE00B4L5Y98", mode: "total" })),
    "Without a ticker or an ISIN it will not be looked through.",
  );
});
