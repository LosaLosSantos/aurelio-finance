/* What the Portfolio table's "est.", "N% paid", "cost unknown" and "since
   situation" mean, said behind its "?" (brief AU; the words were the cells'
   tooltips), and what a row partly paid says (brief AV).

   A cost is estimated when any unit behind it is: a photographed cost derived
   from a reported return, or a plan's buy at the market close. The words
   named the first source only until brief AI, so a position bought by a PAC
   said its price was derived from a reported return. A row photographed with
   no cost and bought since said "cost unknown" for all of it until brief AV.
   Every expected value is written here. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { COST_WORDS, paidShare, plSplit, pricedPaid } from "../src/components/costWords.ts";

test("the question names the four marks the cells carry", () => {
  assert.equal(COST_WORDS.question, "What do est., % paid, cost unknown and since situation mean?");
});

test("an estimated price names both of its sources, and what that does to its P/L", () => {
  assert.ok(
    COST_WORDS.text.startsWith(
      "est.: the price paid is estimated in part. Some or all of it is a plan's buy priced at a market close, or a cost derived from a reported return, not a contract note, so the P/L against it is real but not verified.",
    ),
  );
});

test("a share paid says what is paid, what is a situation's value, and how to make the rest a cost", () => {
  assert.ok(
    COST_WORDS.text.includes(
      " N% paid: of the price on record, that share is money paid, by a buy or a cost typed on a situation; the rest is the value a situation was recorded at. The P/L then shows separately the gain or loss on the units paid for and, marked since situation, the movement on the rest, which is not a profit. To make the rest a cost, type what all the units cost on the situation's row (Records, the account, the situation).",
    ),
  );
});

test("what was paid before a situation started from the last is read back from the ledger, said", () => {
  /* Brief AW: the paid part a situation folded into its value is proposed
     back above the table, and written only on the reader's press. */
  assert.ok(
    COST_WORDS.text.includes(
      " A situation started from the last one keeps what was paid where it could price the row. Where it could not, or before this version, what had been paid went into that situation's value: the app reads it back from the ledger, proposes it above the table, and writes it only if you keep it.",
    ),
  );
});

test("an unknown cost: the recorded value is the situation's, and the P/L a movement, not a profit", () => {
  assert.ok(
    COST_WORDS.text.endsWith(
      " Cost unknown: no purchase price is on record. Recorded is then the value the situation was recorded at, not what you paid, and the P/L under it, marked since situation, is the movement since that situation, not a profit.",
    ),
  );
});

// --- A row partly paid ----------------------------------------------------------------

const row = (over: Partial<Parameters<typeof paidShare>[0]> = {}) => ({
  cost_known: false,
  book_value: 1300,
  book_paid: 300,
  delta: 130,
  delta_paid: 30,
  ...over,
});

test("a row partly paid says its share, rounded, never 100% nor 0%", () => {
  assert.equal(paidShare(row()), "23% paid");
  assert.equal(paidShare(row({ book_value: 1936, book_paid: 766 })), "40% paid");
  assert.equal(paidShare(row({ book_paid: 1294 })), "over 99% paid", "99.5% is not all of it");
  assert.equal(paidShare(row({ book_paid: 6 })), "under 1% paid", "0.46% is not nothing");
});

test("a row all paid, or with nothing paid, says no share", () => {
  assert.equal(paidShare(row({ cost_known: true, book_paid: 1300 })), null);
  assert.equal(paidShare(row({ book_paid: 0 })), null);
  assert.equal(paidShare(row({ book_value: 0, book_paid: 0 })), null);
});

test("its P/L in two parts: on the units paid for, and the movement on the rest", () => {
  assert.deepEqual(plSplit(row()), { paid: 30, movement: 100 });
  assert.deepEqual(plSplit(row({ delta: 70, delta_paid: -30 })), { paid: -30, movement: 100 });
  assert.equal(plSplit(row({ delta: null, delta_paid: null })), null, "nothing priced it");
  assert.equal(plSplit(row({ cost_known: true, book_paid: 1300, delta_paid: 130 })), null);
  assert.equal(plSplit(row({ book_paid: 0, delta_paid: 0 })), null);
});

test("of the P/L on priced rows, the part on money paid, when not all of it is", () => {
  const all = row({ cost_known: true, book_value: 900, book_paid: 900, delta: 60, delta_paid: 60 });
  const none = row({ book_paid: 0, delta: 140, delta_paid: 0 });
  const unpriced = row({ delta: null, delta_paid: null });
  assert.equal(pricedPaid([all, row(), none, unpriced]), 90);
  assert.equal(pricedPaid([all, unpriced]), null, "every priced row is all paid");
});
