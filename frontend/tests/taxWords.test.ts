/* What the Portfolio's realized line and its tax panel say about a movement
   (brief AV): a sell or a close realizes a gain only on the units paid for,
   and its result on a situation's value with no purchase price on record is
   a movement, which no rate applies to. The estimated total leaves that tax
   out, so it is never said without it.

   Amounts are formatted by money.ts, as every figure on the page is; every
   word is written here. */

import assert from "node:assert/strict";
import { test } from "node:test";
import type { Schemas } from "../src/api/types";
import { money } from "../src/components/money.ts";
import {
  TOTALS_WINDOW,
  estimatedTotal,
  movementLine,
  realizedMovement,
  taxPanelShown,
} from "../src/components/taxWords.ts";

type TaxEstimate = Schemas["TaxEstimate"];

const eur = money("EUR");

function estimate(over: Partial<TaxEstimate> = {}): TaxEstimate {
  return {
    country: null,
    regime: null,
    capital_gains_rate: 26,
    dividend_withholding_rate: 26,
    configured: true,
    realized_gain: 30,
    taxable_gain: 30,
    capital_gains_tax: 7.8,
    realized_movement: 0,
    dividends_gross_estimated: 0,
    dividends_recorded_net: 0,
    dividend_withholding: 0,
    total: 7.8,
    missing_rates: [],
    caveats: [],
    ...over,
  } as TaxEstimate;
}

test("a total with nothing left out says only that it is in no total", () => {
  assert.deepEqual(estimatedTotal(estimate(), "EUR"), {
    amount: eur.format(7.8),
    words: "estimated, and counted in none of the totals above",
  });
});

test("a total is never said without the movement it leaves out", () => {
  assert.deepEqual(estimatedTotal(estimate({ realized_movement: 100 }), "EUR"), {
    amount: eur.format(7.8),
    words:
      `estimated, and counted in none of the totals above. It leaves out the +${eur.format(100)} ` +
      "of movement realized on situations' values with no purchase price on record, which no rate can be applied to",
  });
});

test("a movement down keeps its sign, and no total means no sentence", () => {
  assert.ok(
    estimatedTotal(estimate({ realized_movement: -40 }), "EUR")!.words.includes(
      `It leaves out the ${eur.format(-40)} of movement`,
    ),
  );
  assert.equal(estimatedTotal(estimate({ total: null }), "EUR"), null);
});

test("the panel's line for the movement, and none when nothing moved", () => {
  assert.equal(
    movementLine(estimate({ realized_movement: 100 }), "EUR"),
    `Realized movement +${eur.format(100)} on situations' values with no purchase price on record: not a gain, and no rate is applied to it`,
  );
  assert.equal(movementLine(estimate(), "EUR"), null);
});

test("a movement alone is something for the panel to say", () => {
  assert.equal(taxPanelShown(estimate({ realized_gain: 0, realized_movement: 30 })), true);
  assert.equal(taxPanelShown(estimate({ realized_gain: 0 })), false);
  assert.equal(taxPanelShown(estimate({ realized_gain: -5 })), true, "a loss is said too");
});

test("the realized line names the movement beside the P/L", () => {
  assert.equal(
    realizedMovement(100, "EUR"),
    `movement +${eur.format(100)} (no purchase price on record)`,
  );
  assert.equal(realizedMovement(0, "EUR"), null);
});

test("the realized line says the window its totals cover", () => {
  /* Brief AW: the totals read every stretch since each account's first
     situation, where they read only what followed its latest. */
  assert.equal(TOTALS_WINDOW, "since each account's first situation");
});
