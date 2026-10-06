/* What a form cannot be sent without, and what it says when pressed anyway.

   Thirteen forms used to answer an empty field with silence. These pin the
   rule that replaced it: one list per form, read three ways (the sentence,
   aria-required, the question in the empty box), so the three cannot drift.
   The order cases are the ones the forms were written around: a sentence
   with a reason of its own arrives only when its field is the one thing left.

   Run by `npm test` with Node's own test runner, which strips the types
   itself. Type-checked by `tsc -b` through tsconfig.node.json. */

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  DEBT,
  EXPENSE,
  INCOME,
  INSTITUTION,
  PLAN,
  REAL_ASSET,
  TRANSFER,
  dated,
  goal,
  holding,
  marks,
  missing,
  refusal,
  transaction,
} from "../src/components/required.ts";

const keys = (needs: { key: string }[]) => needs.map((n) => n.key);

test("nothing missing: no sentence", () => {
  assert.equal(refusal(INCOME, { name: "Salary", amount: "3000" }), null);
});

test("one plain field missing is named alone", () => {
  assert.equal(refusal(INSTITUTION, { name: "  " }), "Fill in the name.");
});

test("every plain field missing is named in one sentence, in the form's order", () => {
  assert.equal(refusal(EXPENSE, {}), "Fill in the name and the amount.");
  assert.equal(
    refusal(transaction("buy", false), {}),
    "Fill in the asset, the ticker, the quantity and the price.",
  );
});

test("a zero is a value, not an empty box", () => {
  assert.equal(refusal(INCOME, { name: "Gift", amount: 0 }), null);
  assert.equal(refusal(transaction("close", true), { assetName: "X", fees: "0", institutionId: "1", currency: "EUR" }), null);
});

test("a sentence of its own waits for the plain fields", () => {
  const debt = { name: "", currency: "" };
  assert.equal(refusal(DEBT, debt), "Fill in the name.");
  assert.equal(refusal(DEBT, { ...debt, name: "Mortgage" }), "Say which currency this debt is in.");
  assert.equal(refusal(REAL_ASSET, { name: "Flat", currency: "" }), "Say which currency this asset is valued in.");
});

test("the transaction's institution speaks before its currencies, as the form was written", () => {
  const filled = { assetName: "VWCE", symbol: "VWCE.MI", quantity: "2", unitPrice: "100" };
  assert.match(refusal(transaction("buy", false), filled) ?? "", /^A buy has to come from somewhere/);
  assert.match(refusal(transaction("sell", false), filled) ?? "", /^A sell has to say where it is held/);
  assert.match(
    refusal(transaction("buy", false), { ...filled, institutionId: "3", currency: "EUR" }) ?? "",
    /^Say which currencies these are: the price's/,
  );
});

test("a close needs what came back, and no ticker, quantity, price or price currency", () => {
  assert.deepEqual(keys(transaction("close", true)), ["assetName", "fees", "institutionId", "currency"]);
  assert.equal(refusal(transaction("close", true), {}), "Fill in the asset and the proceeds.");
  assert.equal(refusal(transaction("close", true), { assetName: "X" }), "Fill in the proceeds.");
});

test("a dividend's price is what each share paid", () => {
  assert.equal(
    refusal(transaction("dividend", false), { assetName: "X", symbol: "X", quantity: "10" }),
    "Fill in the dividend per share.",
  );
});

test("a holding needs a value in total mode, a quantity and a price in qty mode", () => {
  assert.deepEqual(keys(holding("total")), ["name", "value"]);
  assert.deepEqual(keys(holding("qty")), ["name", "quantity", "unitPrice"]);
  assert.equal(refusal(holding("qty"), { name: "VWCE", quantity: "3" }), "Fill in the price.");
});

test("a goal's label is needed only for 'other', where it is the goal", () => {
  assert.deepEqual(keys(goal("house")), ["type", "currency"]);
  assert.deepEqual(keys(goal("other")), ["type", "name", "currency"]);
  assert.equal(refusal(goal("other"), { type: "other", currency: "EUR" }), "Fill in what the goal is.");
});

test("a plan names what is missing before it asks for the source", () => {
  assert.equal(refusal(PLAN, { name: "PAC", amount: "", ticker: "" }), "Fill in the budget and a ticker.");
  assert.match(refusal(PLAN, { name: "PAC", amount: "300", ticker: "1" }) ?? "", /^A plan has to take the money from somewhere/);
});

test("a transfer asks for a source or a destination before its currencies", () => {
  assert.equal(
    refusal(TRANSFER, { date: "2026-09-24", amount: "100", currency: "EUR", toCurrency: "EUR" }),
    "Pick a source and/or a destination institution.",
  );
  assert.equal(refusal(TRANSFER, { date: "2026-09-24", amount: "", ends: "" }), "Fill in the amount.");
});

test("a transfer's two currencies share one sentence", () => {
  const base = { date: "2026-09-24", amount: "100", ends: "2" };
  const said = refusal(TRANSFER, { ...base, currency: "EUR" });
  assert.equal(said, refusal(TRANSFER, { ...base, toCurrency: "USD" }));
  assert.match(said ?? "", /^Say which currencies these are: what left the source/);
});

test("a dated series needs its date and its amount, under the amount's own noun", () => {
  assert.equal(refusal(dated("the value", "What is it worth?"), {}), "Fill in the date and the value.");
});

test("marks: aria-required on every need, the question only where a box can show one", () => {
  assert.deepEqual(marks(INCOME, "amount"), { "aria-required": true, placeholder: "How much?" });
  assert.deepEqual(marks(TRANSFER, "date"), { "aria-required": true });
  assert.deepEqual(marks(PLAN, "sourceId"), { "aria-required": true });
  assert.deepEqual(marks(goal("house"), "name"), {});
});

test("every question is a question; only selects, dates, the either-or and currency boxes ask none", () => {
  const all = [INSTITUTION, INCOME, EXPENSE, REAL_ASSET, DEBT, TRANSFER, PLAN, dated("the value", "What is it worth?"),
    goal("other"), holding("total"), holding("qty"), transaction("buy", false), transaction("close", true)].flat();
  for (const n of all) if (n.ask) assert.match(n.ask, /\?/, n.key);
  const unasked = all.filter((n) => !n.ask).map((n) => n.key);
  assert.deepEqual([...new Set(unasked)].sort(), [
    "currency", "date", "ends", "institutionId", "priceCurrency", "sourceId", "toCurrency", "type",
  ]);
});

test("missing keeps the form's order", () => {
  assert.deepEqual(keys(missing(transaction("buy", false), { symbol: "X" })), [
    "assetName", "quantity", "unitPrice", "institutionId", "currency", "priceCurrency",
  ]);
});
