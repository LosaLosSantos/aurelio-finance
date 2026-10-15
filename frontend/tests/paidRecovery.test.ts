/* What the ledger paid before a situation, proposed on the Portfolio (brief
   AW). Measured on an invented fund: a situation started from the last one
   before brief AV read 110.00 paid where the ledger held 410.00. The page now
   proposes the paid part back, row by row, and says which purchases a
   disagreeing situation left unread. Every expected value is written here;
   the formatters are plain so the sentences are the module's alone. */

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  NOTICE_NOTE,
  NOTICE_TITLE,
  acceptAllLabel,
  entryLine,
  proposalLine,
  unreadLine,
  type Formats,
} from "../src/components/paidRecovery.ts";

const DAYS: Record<string, string> = {
  "2026-03-02": "2 Mar 2026",
  "2026-03-16": "16 Mar 2026",
  "2026-04-20": "20 Apr 2026",
  "2026-05-04": "4 May 2026",
};
const f: Formats = {
  money: (n) => `€${n}`,
  day: (iso) => DAYS[iso] ?? iso,
  units: (n) => String(n),
};

const base = {
  holding_id: 7,
  institution_id: 1,
  institution: "Banca Gamma",
  asset_name: "Fondo Gamma",
  symbol: "GAMMA.MI",
  situation_date: "2026-05-04",
  quantity: 13,
  paid: 300,
  units: 3,
  estimated: false,
  since: "2026-03-02",
  opening_paid: null,
  opening_units: null,
  entries: [{ date: "2026-03-16", kind: "buy", quantity: 1, amount: 100, estimated: false }],
  row_paid: 0,
  row_units: 0,
  row_estimated: false,
};

test("a proposal says what was paid, for how many of the units, and since when", () => {
  assert.equal(
    proposalLine(base, f),
    "Fondo Gamma: €300 paid for 3 of the 13 units, from the purchases on record since 2 Mar 2026.",
  );
});

test("a cost recorded where the reading started is named before the purchases", () => {
  const p = { ...base, quantity: 12, paid: 1100, units: 12, opening_paid: 900, opening_units: 10 };
  assert.equal(
    proposalLine(p, f),
    "Fondo Gamma: €1100 paid for all 12 units, from the cost recorded on 2 Mar 2026 and the purchases on record since.",
  );
  assert.equal(
    proposalLine({ ...p, entries: [] }, f),
    "Fondo Gamma: €1100 paid for all 12 units, from the cost recorded on 2 Mar 2026.",
  );
});

test("a cost the row carries is said beside the figure that replaces it", () => {
  const p = { ...base, paid: 295, estimated: true, row_paid: 300, row_units: 3, row_estimated: true };
  assert.equal(
    proposalLine(p, f),
    "Fondo Gamma: €295 paid for 3 of the 13 units, from the purchases on record since 2 Mar 2026. The row says €300 for 3 units, estimated.",
  );
});

test("each entry read is one line, an estimated buy marked", () => {
  assert.equal(
    entryLine({ date: "2026-03-16", kind: "buy", quantity: 1, amount: 100, estimated: true }, f),
    "16 Mar 2026: bought 1 for €100 (est.)",
  );
  assert.equal(
    entryLine({ date: "2026-04-20", kind: "sell", quantity: 7, amount: 735, estimated: false }, f),
    "20 Apr 2026: sold 7 for €735",
  );
});

test("purchases left unread are one line, with the units on both sides and the two remedies", () => {
  const u = {
    holding_id: 7,
    institution_id: 1,
    institution: "Banca Gamma",
    asset_name: "Fondo Gamma",
    symbol: "GAMMA.MI",
    situation_date: "2026-05-04",
    stated_units: 13,
    walked_units: 12,
    paid: 200,
    units: 2,
    since: "2026-03-02",
    purchases: 1,
    opening_paid: null,
  };
  assert.equal(
    unreadLine(u, f),
    "Fondo Gamma: €200 paid for 2 units (1 purchase since 2 Mar 2026) is not read, because the situation of 4 May 2026 says 13 units where the ledger gives 12. Correct those purchases to their contract notes, or that situation's units, and it is proposed.",
  );
  assert.ok(unreadLine({ ...u, purchases: 3 }, f).includes("(3 purchases since 2 Mar 2026)"));
  assert.ok(
    unreadLine({ ...u, paid: 1100, units: 12, opening_paid: 900 }, f).startsWith(
      "Fondo Gamma: €1100 paid for 12 units (the cost recorded on 2 Mar 2026 and 1 purchase since) is not read",
    ),
  );
});

test("all at once from two proposals, not for one", () => {
  assert.equal(acceptAllLabel(1), null);
  assert.equal(acceptAllLabel(2), "Keep all 2 as paid");
});

test("the notice says what a press does, and no sentence carries a long dash", () => {
  assert.equal(NOTICE_TITLE, "Paid before a situation, read back from the ledger");
  assert.equal(
    NOTICE_NOTE,
    "These purchases went into a situation's value. Keep as paid makes them the row's cost, for the units they bought; No leaves the row as it is, and it is not proposed again.",
  );
  const dashes = [String.fromCharCode(0x2014), String.fromCharCode(0x2013)];
  const said = [NOTICE_TITLE, NOTICE_NOTE, proposalLine(base, f), entryLine(base.entries[0], f)];
  for (const s of said) for (const d of dashes) assert.ok(!s.includes(d), s);
});
