/* Where a position's cost came from, in the Portfolio table's titles
   (brief AI).

   A cost is estimated when any unit behind it is: a photographed cost derived
   from a reported return, or a plan's buy at the market close. The titles
   named the first source only, so a position bought by a PAC would have said
   its price was derived from a reported return. Every expected value is
   written here. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { avgCostTitle, plTitle } from "../src/components/costWords.ts";

const ESTIMATED = { cost_known: true, cost_estimated: true };
const PAID = { cost_known: true, cost_estimated: false };
const UNKNOWN = { cost_known: false, cost_estimated: false };

test("an estimated average price names both of its sources", () => {
  assert.equal(
    avgCostTitle(ESTIMATED),
    "Average price paid, ESTIMATED in part: some or all of it is a plan's buy priced at a market close, or a cost derived from a reported return, not a contract note",
  );
});

test("a profit or loss on an estimated price says so, and names both sources", () => {
  assert.equal(
    plTitle(ESTIMATED),
    "Profit or loss against a purchase price ESTIMATED in part (a plan's buy at a market close, or a cost derived from a reported return): real, but not verified against a contract note",
  );
});

test("a price paid and a price unknown read as they did", () => {
  assert.equal(avgCostTitle(PAID), "Average price actually paid, from recorded purchases");
  assert.equal(plTitle(PAID), "Profit or loss against the average price you paid");
  assert.equal(
    avgCostTitle(UNKNOWN),
    "No purchase price on record: this is the price the situation was recorded at, not what you paid",
  );
  assert.equal(
    plTitle(UNKNOWN),
    "Movement since the situation was recorded, NOT profit: no purchase price is on record",
  );
});

test("a cost nobody recorded is unknown, whatever the estimate flag says", () => {
  assert.equal(avgCostTitle({ cost_known: false, cost_estimated: true }), avgCostTitle(UNKNOWN));
});
