/* A dividend typed on top of one the app recorded is offered the correction
   of that row, never refused (brief AI).

   Measured on a copy of the test database: a hand entry beside the estimated
   row, on its ex-date or a week later, made the cash, the dividends collected
   and the tax panel count the dividend twice; correcting the row counted it
   once, unless its date was moved too, when the next start recorded the
   ex-date again. Every expected value is written here; the rows are
   invented. */

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  AUTO_STAMP,
  correctingLine,
  estimatedDividends,
  movedOffItsDay,
  offerLine,
  olderLine,
  recordedByTheApp,
  type LedgerRow,
} from "../src/components/sameDividend.ts";

const STAMP = "Auto-recorded from market data: a dividend of 0.25 USD per share";

function row(over: Partial<LedgerRow>): LedgerRow {
  return {
    id: 1,
    kind: "dividend",
    date: "2026-09-22",
    institution_id: 7,
    symbol: "ALFA.MI",
    amount: 5.1,
    currency: "EUR",
    estimated: true,
    note: STAMP,
    ...over,
  };
}

const TYPED = { institutionId: 7, symbol: "alfa.mi ", date: "2026-09-29" };

test("an estimated dividend of the same account and ticker is offered, on its day or before the one typed", () => {
  const sameDay = row({ id: 1, date: "2026-09-29" });
  const before = row({ id: 2, date: "2026-09-22" });
  assert.deepEqual(
    estimatedDividends([before, sameDay], TYPED).map((t) => t.id),
    [1, 2],
  );
});

test("a dividend dated after the one typed cannot be the same one", () => {
  assert.deepEqual(estimatedDividends([row({ date: "2026-09-30" })], TYPED), []);
});

test("a corrected dividend, another kind, ticker or account is not offered", () => {
  const rows = [
    row({ id: 1, estimated: false }),
    row({ id: 2, kind: "buy" }),
    row({ id: 3, symbol: "BETA.MI" }),
    row({ id: 4, institution_id: 8 }),
  ];
  assert.deepEqual(estimatedDividends(rows, TYPED), []);
});

test("nothing is offered before the account, the ticker and the date are there", () => {
  const rows = [row({})];
  assert.deepEqual(estimatedDividends(rows, { ...TYPED, institutionId: null }), []);
  assert.deepEqual(estimatedDividends(rows, { ...TYPED, symbol: " " }), []);
  assert.deepEqual(estimatedDividends(rows, { ...TYPED, date: "" }), []);
});

test("the newest comes first, and two on one day by the latest written", () => {
  const rows = [
    row({ id: 1, date: "2026-06-22" }),
    row({ id: 2, date: "2026-09-22" }),
    row({ id: 3, date: "2026-09-22" }),
    row({ id: 4, date: "2026-07-22" }),
  ];
  assert.deepEqual(estimatedDividends(rows, TYPED).map((t) => t.id), [3, 2, 4, 1]);
});

test("the offer says what the rows are and why to correct one", () => {
  assert.equal(
    offerLine("alfa.mi", "Banca Alfa"),
    "Already recorded for ALFA.MI at Banca Alfa, still estimated (the market's gross figure, before tax). If the dividend you are entering is one of these, correct it instead: a second row would count it twice.",
  );
  assert.equal(olderLine(3), null);
  assert.equal(olderLine(4), "And 1 older one.");
  assert.equal(olderLine(6), "And 3 older ones.");
});

test("a correction says the row keeps its ex-date, and that the date typed is not used", () => {
  assert.equal(
    correctingLine("2026-09-22", "2026-09-29"),
    "Correcting the dividend of 2026-09-22 with your figures: save to replace its own. Its date stays 2026-09-22, the ex-date the app finds it by, so 2026-09-29 is not used.",
  );
  assert.equal(
    correctingLine("2026-09-22", "2026-09-22"),
    "Correcting the dividend of 2026-09-22 with your figures: save to replace its own.",
  );
  assert.equal(
    correctingLine("2026-09-22", "2026-09-29", (d) => d.split("-").reverse().join("/")),
    "Correcting the dividend of 22/09/2026 with your figures: save to replace its own. Its date stays 22/09/2026, the ex-date the app finds it by, so 29/09/2026 is not used.",
  );
});

test("a dividend the app recorded is known by its stamp, which an edit keeps", () => {
  assert.equal(AUTO_STAMP, "Auto-recorded from market data");
  assert.equal(recordedByTheApp(row({ estimated: false })), true);
  assert.equal(recordedByTheApp(row({ note: "Credited by the broker" })), false);
  assert.equal(recordedByTheApp(row({ note: null })), false);
  assert.equal(recordedByTheApp(row({ kind: "buy" })), false);
});

test("moving a dividend the app recorded off its ex-date is said", () => {
  assert.equal(
    movedOffItsDay(row({ estimated: false }), "2026-09-29"),
    "The app recorded this dividend on its ex-date, 2026-09-22, and finds it by that day. Moved to 2026-09-29, the dividend of 2026-09-22 is recorded again at the next start, unless this account has a situation dated on or after it.",
  );
});

test("its own day, a row the reader typed, or no date says nothing", () => {
  assert.equal(movedOffItsDay(row({}), "2026-09-22"), null);
  assert.equal(movedOffItsDay(row({ note: "Credited by the broker" }), "2026-09-29"), null);
  assert.equal(movedOffItsDay(row({}), ""), null);
});
