/* A currency's unit, read as the backend reads it (`fx._in_major_units`,
   `fx.same_currency`, `fx.within_currency`), brief BA. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { majorUnit, sameCurrency, sameUnit, withinCurrency } from "../src/components/money.ts";

test("a code in its major unit: pence are pounds, and case is the backend's", () => {
  assert.deepEqual(majorUnit("GBp"), { code: "GBP", per: 100 });
  assert.deepEqual(majorUnit("GBX"), { code: "GBP", per: 100 });
  assert.deepEqual(majorUnit("gbx"), { code: "GBP", per: 100 });
  assert.deepEqual(majorUnit("ZAC"), { code: "ZAR", per: 100 });
  assert.deepEqual(majorUnit("ILA"), { code: "ILS", per: 100 });
  // 'GBp' alone is matched on its case: "gbp" and "GBP" are pounds.
  assert.deepEqual(majorUnit("gbp"), { code: "GBP", per: 1 });
  assert.deepEqual(majorUnit(" eur "), { code: "EUR", per: 1 });
  assert.deepEqual(majorUnit("TWD"), { code: "TWD", per: 1 });
});

test("one currency spelt two ways is one currency", () => {
  assert.equal(sameCurrency("EUR", "eur"), true);
  assert.equal(sameCurrency("GBP", "GBp"), true);
  assert.equal(sameCurrency("GBX", "GBp"), true);
  assert.equal(sameCurrency("EUR", "USD"), false);
  assert.equal(sameCurrency("Doll", "doll"), true);
});

test("one unit is one currency at the same step: pence are not pounds' unit", () => {
  assert.equal(sameUnit("EUR", "eur"), true);
  assert.equal(sameUnit("GBP", "gbp"), true);
  assert.equal(sameUnit("GBp", "GBX"), true);
  assert.equal(sameUnit("GBP", "GBp"), false);
  assert.equal(sameUnit("EUR", "USD"), false);
});

test("within one currency only the minor-unit step is taken", () => {
  assert.equal(withinCurrency(5000, "GBp", "GBP"), 50);
  assert.equal(withinCurrency(50, "GBP", "GBp"), 5000);
  assert.equal(withinCurrency(200, "EUR", "eur"), 200);
});
