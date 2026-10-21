/* A currency's unit, read as the backend reads it (`fx._in_major_units`,
   `fx.same_currency`, `fx.within_currency`), brief BA. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { majorUnit, money, priceWithCode, sameCurrency, sameUnit, withinCurrency } from "../src/components/money.ts";

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

/* A price per unit as a contract note states it (brief BD): the currency's
   own minor digits at least, every further digit it carries, up to eight. */

test("a price per unit keeps every decimal it carries, and the currency's own at least", () => {
  const eur = money("EUR", "price", "en-US");
  assert.equal(eur.format(0.1615), "€0.1615");
  assert.equal(eur.format(9.047), "€9.047");
  assert.equal(eur.format(9.1445), "€9.1445");
  assert.equal(eur.format(191), "€191.00");
  assert.equal(eur.format(1 / 3), "€0.33333333");
  assert.equal(money("JPY", "price", "en-US").format(1234.5), "¥1,234.5");
  assert.equal(money("JPY", "price", "en-US").format(1234), "¥1,234");
});

test("pence and a code no rate knows keep their digits beside the code", () => {
  assert.equal(money("GBp", "price", "en-US").format(3361.5), "3,361.5 GBp");
  assert.equal(money("Doll", "price", "en-US").format(12.3456), "12.3456 Doll");
});

test("the cents and the whole units are as they were", () => {
  assert.equal(money("EUR", "cents", "en-US").format(4.36), "€4.36");
  assert.equal(money("EUR", "cents", "en-US").format(766), "€766.00");
  assert.equal(money("EUR", "whole", "en-US").format(4.36), "€4");
  assert.equal(money("GBp", "cents", "en-US").format(3361.456), "3,361.46 GBp");
});

test("a listing's price beside its code keeps every decimal it carries", () => {
  assert.equal(priceWithCode(0.1615, "USD", "en-US"), "0.1615 USD");
  assert.equal(priceWithCode(131.5, "USD", "en-US"), "131.5 USD");
  assert.equal(priceWithCode(3361.5, "GBp", "en-US"), "3,361.5 GBp");
});
