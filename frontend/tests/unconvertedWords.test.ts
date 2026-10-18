/* What a page says about a code it counts as written (brief BA, D2 (c)):
   the kind of code and its rows first, then each figure's own share, merged
   across the page's payloads. Every expected value is written here. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { unconvertedWords } from "../src/components/unconvertedWords.ts";

const twd = {
  currency: "TWD",
  not_a_code: false,
  rows: [
    { kind: "cash balance", name: "Taipei cash", where: "2026-09-16" },
    { kind: "real asset", name: "Taipei flat", where: null },
  ],
  more_rows: 0,
  shares: { net_worth: 2300, cash_total: 700 },
};

test("a currency no source quotes: its kind, its rows, then each figure's share", () => {
  const [said] = unconvertedWords(
    [{ items: [twd], labels: { net_worth: "net worth", cash_total: "cash" } }],
    "EUR",
  );
  assert.deepEqual(said, {
    code: "TWD",
    kind: "TWD is a currency no source quotes, so no rate converts it.",
    rows: "Written on: cash balance Taipei cash (2026-09-16); real asset Taipei flat.",
    figures: "Counted here as written, as if in EUR: net worth 2,300.00 TWD; cash 700.00 TWD.",
  });
});

test("a typo is said as not a code, with the rows beyond those named counted", () => {
  const [said] = unconvertedWords(
    [{
      items: [{
        currency: "Doll",
        not_a_code: true,
        rows: [{ kind: "real asset", name: "Old car" }],
        more_rows: 2,
        shares: { real_total: 2000 },
      }],
      labels: { real_total: "real assets" },
    }],
    "EUR",
  );
  assert.equal(said.kind, "'Doll' is not a currency code: correct it on the row it is written on.");
  assert.equal(said.rows, "Written on: real asset Old car; and 2 more.");
  assert.equal(said.figures, "Counted here as written, as if in EUR: real assets 2,000.00 Doll.");
});

test("a page's payloads merge by code, each figure under its own name", () => {
  const blocks = unconvertedWords(
    [
      { items: [twd], labels: { net_worth: "net worth", cash_total: "cash" } },
      {
        items: [{ currency: "TWD", not_a_code: false, shares: { monthly_income: 9000, monthly_net: 9000 } }],
        labels: { monthly_income: "monthly income", monthly_net: "monthly net" },
      },
    ],
    "EUR",
  );
  assert.equal(blocks.length, 1);
  assert.equal(
    blocks[0].figures,
    "Counted here as written, as if in EUR: net worth 2,300.00 TWD; cash 700.00 TWD; " +
      "monthly income 9,000.00 TWD; monthly net 9,000.00 TWD.",
  );
});

test("a figure the page does not show is left out, and a debt's share keeps its sign", () => {
  const [said] = unconvertedWords(
    [{
      items: [{ currency: "TWD", not_a_code: false, shares: { monthly_net: -100, hidden: 5 } }],
      labels: { monthly_net: "monthly net" },
    }],
    "EUR",
  );
  assert.equal(said.figures, "Counted here as written, as if in EUR: monthly net -100.00 TWD.");
  assert.equal(said.rows, null);
});

test("the history says at how many points, never an amount", () => {
  const [said] = unconvertedWords(
    [{ items: [twd], labels: { net_worth: "net worth" } }],
    "EUR",
    [{ unconverted: [] }, { unconverted: ["TWD"] }, { unconverted: ["TWD"] }],
  );
  assert.equal(
    said.figures,
    "Counted here as written, as if in EUR: net worth 2,300.00 TWD; the history, at 2 of its 3 points.",
  );
});

test("a code only earlier points count is said too", () => {
  const blocks = unconvertedWords([], "EUR", [{ unconverted: ["TWD"] }, { unconverted: [] }]);
  assert.deepEqual(blocks, [{
    code: "TWD",
    kind: "TWD is a currency no source quotes, so no rate converts it.",
    rows: null,
    figures: "Counted here as written, as if in EUR: the history, at 1 of its 2 points.",
  }]);
});

test("nothing passed through says nothing", () => {
  assert.deepEqual(unconvertedWords([{ items: [], labels: {} }], "EUR", []), []);
});
