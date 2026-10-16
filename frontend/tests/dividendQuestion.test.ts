/* The questions the catch-up asks about a dividend, in the reader's words,
   and the answers each offers (brief AZ).

   Asked whenever the app cannot pair the reader's entry with a dividend Yahoo
   lists on its own: two entries one dividend could be, one entry two
   dividends could be, an entry beside the app's estimate of the same dividend.
   Every expected value is written here; the rows are invented. */

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  choices,
  questionText,
  recognisedLine,
  type Entry,
  type Formats,
  type Question,
} from "../src/components/dividendQuestion.ts";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

const f: Formats = {
  date: (iso) => {
    const [y, m, d] = iso.split("-").map(Number);
    return `${d} ${MONTHS[m - 1]} ${y}`;
  },
  money: (amount, currency) => `${amount.toFixed(2)} ${currency}`,
  perShare: (amount, currency) => `${amount} ${currency}`,
};

const typed = (id: number, date: string, amount: number): Entry => ({ id, date, amount, currency: "EUR", estimated: false });

function question(over: Partial<Question>): Question {
  return {
    kind: "which_entry",
    institution_id: 7,
    institution_name: "Broker A",
    symbol: "XDIV.MI",
    dividends: [{ ex_date: "2026-09-22", dps: 0.25, currency: "EUR", units: 20, estimate: null }],
    entries: [typed(11, "2026-09-29", 3.7), typed(12, "2026-10-02", 1.2)],
    ...over,
  };
}

test("two entries one dividend could be: which one, or neither, and then it is recorded", () => {
  const q = question({});
  assert.equal(
    questionText(q, f),
    "XDIV.MI at Broker A: Yahoo lists a dividend with ex-date 22 September 2026, 0.25 EUR a share (about 5.00 EUR for 20 units). Two of your entries could be it: 29 September 2026, 3.70 EUR and 2 October 2026, 1.20 EUR. Which one is it?",
  );
  assert.deepEqual(choices(q, f), [
    { label: "The one of 29 September 2026", answer: { institution_id: 7, symbol: "XDIV.MI", answer: "link", transaction_id: 11, ex_date: "2026-09-22" } },
    { label: "The one of 2 October 2026", answer: { institution_id: 7, symbol: "XDIV.MI", answer: "link", transaction_id: 12, ex_date: "2026-09-22" } },
    {
      label: "Neither: record it",
      answer: {
        institution_id: 7, symbol: "XDIV.MI", answer: "apart",
        pairs: [{ transaction_id: 11, ex_date: "2026-09-22" }, { transaction_id: 12, ex_date: "2026-09-22" }],
      },
    },
  ]);
});

test("three entries say none, and an estimate on record is kept by none", () => {
  const three = question({ entries: [typed(11, "2026-09-29", 3.7), typed(12, "2026-10-02", 1.2), typed(13, "2026-10-05", 0.4)] });
  assert.match(questionText(three, f), /Three of your entries could be it: 29 September 2026, 3\.70 EUR, 2 October 2026, 1\.20 EUR and 5 October 2026, 0\.40 EUR\./);
  assert.equal(choices(three, f).at(-1)?.label, "None: record it");
  const estimated = question({
    dividends: [{ ex_date: "2026-09-22", dps: 0.25, currency: "EUR", units: 20, estimate: { id: 9, date: "2026-09-22", amount: 5, currency: "EUR", estimated: true } }],
  });
  assert.match(questionText(estimated, f), /could be it, beside the app's estimate of 5\.00 EUR: /);
  assert.equal(choices(estimated, f).at(-1)?.label, "None: keep the estimate");
});

test("one entry two dividends could be: which one, or none of them", () => {
  const q = question({
    kind: "which_dividend",
    dividends: [
      { ex_date: "2026-07-02", dps: 0.003, currency: "USD", units: 20, estimate: null },
      { ex_date: "2026-08-04", dps: 0.003, currency: "USD", units: 20, estimate: null },
    ],
    entries: [typed(11, "2026-08-16", 0.05)],
  });
  assert.equal(
    questionText(q, f),
    "XDIV.MI at Broker A: your entry of 16 August 2026, 0.05 EUR could be the dividend with ex-date 2 July 2026 or ex-date 4 August 2026. Which one is it?",
  );
  assert.deepEqual(choices(q, f).map((c) => c.label), ["Ex-date 2 July 2026", "Ex-date 4 August 2026", "None of them"]);
  assert.deepEqual(choices(q, f)[2].answer.pairs, [
    { transaction_id: 11, ex_date: "2026-07-02" },
    { transaction_id: 11, ex_date: "2026-08-04" },
  ]);
});

test("an entry beside the app's estimate of the same dividend: keep mine, or keep both", () => {
  const q = question({
    kind: "same_dividend",
    dividends: [{ ex_date: "2026-09-22", dps: 0.25, currency: "EUR", units: 20, estimate: { id: 9, date: "2026-09-22", amount: 5, currency: "EUR", estimated: true } }],
    entries: [typed(11, "2026-09-29", 3.7)],
  });
  assert.equal(
    questionText(q, f),
    "XDIV.MI at Broker A: these two look like one dividend: the app's estimate with ex-date 22 September 2026 (5.00 EUR, the market's gross figure) and your entry of 29 September 2026, 3.70 EUR. Keep yours as the dividend with ex-date 22 September 2026 and remove the estimate, or keep both?",
  );
  assert.deepEqual(choices(q, f), [
    { label: "Keep mine, remove the estimate", answer: { institution_id: 7, symbol: "XDIV.MI", answer: "link", transaction_id: 11, ex_date: "2026-09-22" } },
    { label: "Keep both", answer: { institution_id: 7, symbol: "XDIV.MI", answer: "apart", pairs: [{ transaction_id: 11, ex_date: "2026-09-22" }] } },
  ]);
});

test("a figure a share Yahoo did not give is left out, and so is a gross with no units", () => {
  const q = question({ dividends: [{ ex_date: "2026-09-22", dps: null, currency: "EUR", units: null, estimate: null }] });
  assert.match(questionText(q, f), /Yahoo lists a dividend with ex-date 22 September 2026\. Two of/);
  const noUnits = question({ dividends: [{ ex_date: "2026-09-22", dps: 0.25, currency: "EUR", units: null, estimate: null }] });
  assert.match(questionText(noUnits, f), /ex-date 22 September 2026, 0\.25 EUR a share\. Two of/);
});

test("a dividend whose window holds the latest balance asks whether the balance held it", () => {
  const q = question({ kind: "in_balance", entries: [], balance_date: "2026-09-25" });
  assert.equal(
    questionText(q, f),
    "XDIV.MI at Broker A: Yahoo lists a dividend with ex-date 22 September 2026, before your balance of 25 September 2026: 0.25 EUR a share, about 5.00 EUR gross for the 20 units held then. Was its money already in that balance?",
  );
  assert.deepEqual(choices(q, f), [
    { label: "Yes, it was in it", answer: { institution_id: 7, symbol: "XDIV.MI", ex_date: "2026-09-22", balance_date: "2026-09-25", answer: "in_balance" } },
    { label: "No, it came after", answer: { institution_id: 7, symbol: "XDIV.MI", ex_date: "2026-09-22", balance_date: "2026-09-25", answer: "after_balance" } },
  ]);
});

test("before the first situation, the question says whose units it counts", () => {
  const q = question({ kind: "in_balance", entries: [], balance_date: "2026-09-25", first_situation: "2026-09-25" });
  assert.match(questionText(q, f), /about 5\.00 EUR gross for the 20 units of your first situation, of 25 September 2026\. Was its money/);
});

test("an entry the catch-up recognised is said once, with both days", () => {
  assert.equal(
    recognisedLine({ institution_name: "Broker A", symbol: "XDIV.MI", ex_date: "2026-09-22", entry: typed(11, "2026-09-29", 3.7) }, f),
    "XDIV.MI at Broker A: your entry of 29 September 2026 is the dividend with ex-date 22 September 2026, so it was not recorded again.",
  );
});
