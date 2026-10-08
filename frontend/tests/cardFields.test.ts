/* A line of a card, written in the reader's language.

   Brief AJ: the server words a card's lines (a label, a value, its kind) and
   the panel writes the value as the rest of the app writes one. Run by
   `npm test` with Node's own test runner; type-checked by `tsc -b`. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { lineText } from "../src/components/cardFields.ts";

test("a day is written as the reader's calendar writes it", () => {
  // Day first in Italian; whether it is padded differs between ICU versions.
  assert.match(lineText({ label: "Since", value: "2026-10-08", kind: "date" }, "it-IT"), new RegExp("^0?8/10/2026$"));
  assert.equal(lineText({ label: "Since", value: "2026-10-08", kind: "date" }, "en-US"), "10/8/2026");
});

test("a number with the reader's separators", () => {
  // Five digits: Italian groups from there in every ICU version.
  assert.equal(lineText({ label: "Units", value: "12345.5", kind: "number" }, "it-IT"), "12.345,5");
  assert.equal(lineText({ label: "Units", value: "1234.5", kind: "number" }, "en-US"), "1,234.5");
});

test("an amount with its currency, a minor unit as typed", () => {
  const euros = lineText({ label: "Amount", value: "80", kind: "amount", currency: "EUR" });
  assert.match(euros, /80/);
  assert.match(euros, /€|EUR/);
  assert.match(lineText({ label: "Amount", value: "3361", kind: "amount", currency: "GBp" }), /GBp$/);
});

test("text, and a value that is not what its kind says, are shown as they came", () => {
  assert.equal(lineText({ label: "Rests on", value: "An invented answer." }), "An invented answer.");
  assert.equal(lineText({ label: "Since", value: "soon", kind: "date" }), "soon");
  assert.equal(lineText({ label: "Units", value: "many", kind: "number" }), "many");
});
