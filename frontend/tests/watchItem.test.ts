/* What a watchlist line says about the instrument it names.

   Brief AG: a line can now be a single share, named by the symbol Yahoo lists
   it under and with no ISIN. These pin that a share's line says so, and that
   "null" never stands where an ISIN would, while a fund's line says exactly
   what it said before.

   Run by `npm test` with Node's own test runner. Type-checked by `tsc -b`
   through tsconfig.node.json. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { identityOf, isShare, prefillNote } from "../src/components/watchItem.ts";

const SHARE = { isin: null, symbol: "ACME.MI" };
const FUND = { isin: "XA0000000011", symbol: "EXF1.MI" };
const BARE_FUND = { isin: "XA0000000011", symbol: null };
const YOURS =
  " How many, at what price and where are yours too. Recording this leaves the watchlist line where it is: drop it with ✕ when the idea is done.";

test("a line with no ISIN is a share, and one with an ISIN a fund", () => {
  assert.equal(isShare(SHARE), true);
  assert.equal(isShare(FUND), false);
  assert.equal(isShare(BARE_FUND), false);
});

test("a share's line names it by its symbol, as Yahoo lists it", () => {
  assert.equal(identityOf(SHARE), "ACME.MI · share, as Yahoo lists it");
});

test("a fund's line names it by its ISIN, with the ticker beside it as before", () => {
  assert.equal(identityOf(FUND), "XA0000000011 · EXF1.MI");
  assert.equal(identityOf(BARE_FUND), "XA0000000011");
});

test("the ledger form says where a share's symbol came from, and never null", () => {
  const note = prefillNote(SHARE);
  assert.equal(
    note,
    "ACME.MI: the symbol Yahoo lists this share under, checked when the card was drawn and again when you accepted it. Check it is the listing you bought on." +
      YOURS,
  );
  assert.ok(!note.includes("null"));
});

test("the ledger form says for a fund what it said before", () => {
  assert.equal(
    prefillNote(FUND),
    "XA0000000011 · EXF1.MI: the ISIN identifies the fund; the ticker came from the live lookup, so check it is the listing you actually bought on." +
      YOURS,
  );
  assert.equal(
    prefillNote(BARE_FUND),
    "XA0000000011. That identifies the fund but does not price it: the ticker of the listing you bought on is still yours to give." +
      YOURS,
  );
});
