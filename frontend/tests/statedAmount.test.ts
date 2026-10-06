/* A figure the reader stated survives an edit about something else; a figure
   the app worked out keeps following the quantity.

   Run by `npm test` with Node's own test runner, which strips the types itself:
   no bundler and no test framework, because the module under test has no
   runtime imports. Type-checked by `tsc -b` through tsconfig.node.json. */

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  acrossCurrencies,
  debitOnEdit,
  derivedAmount,
  wasStated,
  type Entry,
} from "../src/components/statedAmount.ts";

function entry(over: Partial<Entry> = {}): Entry {
  return {
    kind: "buy",
    quantity: 10,
    unit_price: 30,
    fees: 0,
    amount: 300,
    currency: "EUR",
    price_currency: "EUR",
    fx_as_of: null,
    ...over,
  };
}

test("a buy costs its fees, everything else nets them off", () => {
  assert.equal(derivedAmount({ kind: "buy", quantity: 10, unit_price: 30, fees: 2.5 }), 302.5);
  assert.equal(derivedAmount({ kind: "sell", quantity: 10, unit_price: 30, fees: 2.5 }), 297.5);
  assert.equal(derivedAmount({ kind: "dividend", quantity: 10, unit_price: 0.5, fees: 0 }), 5);
  // Proceeds after fees, floored at zero: value cannot leave by going negative.
  assert.equal(derivedAmount({ kind: "sell", quantity: 1, unit_price: 10, fees: 40 }), 0);
});

test("a same-currency amount that is what the row derives is treated as derived", () => {
  assert.equal(wasStated(entry()), false);
  assert.equal(debitOnEdit(entry()), "");
});

test("a same-currency amount that is NOT what the row derives is the reader's", () => {
  // The contract note's figure: 10 x 30.00 with odd fees folded in.
  const stated = entry({ amount: 307.42 });
  assert.equal(wasStated(stated), true);
  assert.equal(debitOnEdit(stated), "307.42");
});

test("a figure a double cannot hold exactly is still not a statement's", () => {
  // 10 x 30.05 is 300.49999999999994 as a double, and the backend stores it
  // unrounded because no rate was used. Half a cent of tolerance — the point
  // at which two figures round to different cents — or every such row would
  // open pre-filled and then stop following its quantity.
  const derived = entry({ unit_price: 30.05, amount: 10 * 30.05 });
  assert.equal(wasStated(derived), false);
  // And a figure that rounds to a different cent IS a statement's.
  assert.equal(wasStated(entry({ unit_price: 30.05, amount: 300.51 })), true);
  // The boundary itself, from both sides: 300.504 still rounds to 300.50.
  assert.equal(wasStated(entry({ unit_price: 30.05, amount: 300.504 })), false);
  assert.equal(wasStated(entry({ unit_price: 30.05, amount: 300.506 })), true);
});

test("across two currencies the rate day answers instead", () => {
  const worked_out = entry({ price_currency: "USD", amount: 240, fx_as_of: "2026-09-11" });
  assert.equal(wasStated(worked_out), false);
  assert.equal(debitOnEdit(worked_out), "");

  const off_a_statement = entry({ price_currency: "USD", amount: 241.13, fx_as_of: null });
  assert.equal(wasStated(off_a_statement), true);
  assert.equal(debitOnEdit(off_a_statement), "241.13");
});

test("an unstated price currency is one currency, not two", () => {
  // The original box was gated on `priceCurrency.trim() !== ""`, so a row that
  // never said what its price was in had no box either — a second way to lose
  // the same figure.
  assert.equal(acrossCurrencies("EUR", null), false);
  assert.equal(acrossCurrencies("EUR", ""), false);
  assert.equal(acrossCurrencies("EUR", "  "), false);
  assert.equal(acrossCurrencies("EUR", "EUR"), false);
  assert.equal(acrossCurrencies("EUR", "USD"), true);
  // And such a row is judged by its figures, like any other one-currency row.
  assert.equal(wasStated(entry({ price_currency: null, amount: 300 })), false);
  assert.equal(wasStated(entry({ price_currency: null, amount: 307.42 })), true);
});

test("a close is neither: its proceeds are the amount, in their own box", () => {
  const closed = entry({ kind: "close", quantity: 0, unit_price: 0, amount: 412 });
  assert.equal(wasStated(closed), false);
  assert.equal(debitOnEdit(closed), "");
});

test("an auto-recorded gross dividend opens empty, and can be corrected", () => {
  // What `pac.py` writes: gross, fees 0, the amount derived from the ex-date's
  // dividend per share. The form must offer the box so the statement's NET
  // credit can replace it — that correction is what `estimated` promises.
  const gross = entry({ kind: "dividend", quantity: 100, unit_price: 0.5, amount: 50 });
  assert.equal(wasStated(gross), false, "as written by the catch-up, it is derived");
  assert.equal(debitOnEdit(gross), "");
  // Once corrected with the net credit, an edit about anything else keeps it.
  const corrected = entry({ kind: "dividend", quantity: 100, unit_price: 0.5, amount: 43.75 });
  assert.equal(debitOnEdit(corrected), "43.75");
});
