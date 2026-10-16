/* What an account's page says after "Start from the last one" (brief AV): the
   two sentences it always said, and what was paid on a row nothing priced
   that day and is not kept. Every expected value is written here. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { prefillWords } from "../src/components/prefillNote.ts";

const answer = (over = {}) => ({
  copied_from: "2026-07-16",
  repriced: ["EUNL.DE", "INVW.MI", "IS3N.DE", "SAP.DE"],
  needs_attention: [] as string[],
  paid_not_kept: [] as { asset_name: string; units_paid: number }[],
  ...over,
});

test("every row priced: the sentence it always said", () => {
  assert.equal(prefillWords(answer()), "Copied from 2026-07-16, all 4 positions priced from the market.");
});

test("a row nothing priced, with nothing paid on it: the sentence it always said", () => {
  assert.equal(
    prefillWords(answer({ repriced: ["SAP.DE"], needs_attention: ["A bond fund"] })),
    "Copied from 2026-07-16. 1 priced from the market. Only A bond fund still needs you.",
  );
});

test("a row nothing priced loses what was paid on it, and the page says how to get it back", () => {
  assert.equal(
    prefillWords(
      answer({
        repriced: [],
        needs_attention: ["Invented World Fund"],
        paid_not_kept: [{ asset_name: "Invented World Fund", units_paid: 3 }],
      }),
    ),
    "Copied from 2026-07-16. 0 priced from the market. Only Invented World Fund still needs you." +
      " On Invented World Fund, what was paid (3 units) is not kept, because nothing could price it on that day: delete this situation and start again from the last one when a price is available.",
  );
});

test("one unit is a unit, and each row is said", () => {
  const note = prefillWords(
    answer({
      repriced: [],
      needs_attention: ["Fund A", "Fund B"],
      paid_not_kept: [
        { asset_name: "Fund A", units_paid: 1 },
        { asset_name: "Fund B", units_paid: 1.5 },
      ],
    }),
  );
  assert.ok(note.includes(" On Fund A, what was paid (1 unit) is not kept,"));
  assert.ok(note.includes(" On Fund B, what was paid (1.5 units) is not kept,"));
});

test("a currency that is not a code is said, and copied as written (brief BA)", () => {
  assert.equal(
    prefillWords(
      answer({
        repriced: [],
        needs_attention: ["Lump"],
        not_a_code: [{ asset_name: "Lump", currency: "Doll" }],
      }),
    ),
    "Copied from 2026-07-16. 0 priced from the market. Only Lump still needs you." +
      " On Lump, the currency 'Doll' is not a currency code and was copied as written: correct it on that row.",
  );
});
