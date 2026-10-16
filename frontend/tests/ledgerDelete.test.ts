/* The ledger's Delete says what follows the press (brief AO).

   A deletion stays one: the PAC does not buy the occurrence of a buy deleted
   from it again, and its carry goes to zero; the app does not record a
   dividend on the day of one deleted again. Measured on copies of the test
   database before the change: a PAC's occurrence bought again with the
   deleted buy's leftover counted twice, a dividend recorded again. Every
   expected value is written here; the rows are invented. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { deleteQuestion, type LedgerEntry } from "../src/components/ledgerDelete.ts";

function row(over: Partial<LedgerEntry>): LedgerEntry {
  return {
    id: 1,
    kind: "buy",
    date: "2026-09-15",
    asset_name: "Example World UCITS ETF",
    symbol: "XWLD.MI",
    institution_id: 7,
    plan_id: null,
    plan_occurrence: null,
    ex_date: null,
    ...over,
  };
}

test("an entry the reader made is asked about as it always was, and nothing brings it back", () => {
  const typed = row({});
  assert.equal(
    deleteQuestion(typed, [typed]),
    'Delete buy "Example World UCITS ETF" of 2026-09-15? Nothing brings it back.',
  );
});

test("the last buy of a PAC's occurrence says the PAC will not buy it again, and invites the correction", () => {
  const bought = row({ plan_id: 3, plan_occurrence: "2026-09-13", date: "2026-09-14" });
  assert.equal(
    deleteQuestion(bought, [bought, row({ id: 2, plan_id: 3, plan_occurrence: "2026-08-13" })]),
    'Delete buy "Example World UCITS ETF" of 2026-09-14? Its PAC will not buy its occurrence of 2026-09-13 again. What the PAC carries goes to zero, and that money stays in the account\'s cash. If your broker did buy it, correct it with the figures from your statement instead.',
  );
});

test("one buy of an occurrence that has another says the occurrence keeps it", () => {
  const leg = row({ id: 1, plan_id: 3, plan_occurrence: "2026-09-13" });
  const other = row({ id: 2, plan_id: 3, plan_occurrence: "2026-09-13", symbol: "XBND.MI" });
  assert.match(
    deleteQuestion(leg, [leg, other]),
    /Its PAC's occurrence of 2026-09-13 keeps its other buy, and this fund is not bought for it again\. What the PAC carries goes to zero/,
  );
});

test("a buy whose PAC is gone is the reader's to delete like any other", () => {
  const orphan = row({ plan_id: null, plan_occurrence: "2026-09-13" });
  assert.match(deleteQuestion(orphan, [orphan]), /\? Nothing brings it back\.$/);
});

test("a dividend that keeps no ex-date says the app will not record one on its day again", () => {
  const paid = row({ kind: "dividend", date: "2026-09-23", symbol: "XDIV.MI", asset_name: "Example Dividend Share" });
  assert.equal(
    deleteQuestion(paid, [paid]),
    'Delete dividend "Example Dividend Share" of 2026-09-23? The app will not record a dividend of XDIV.MI at this account on 2026-09-23 again. If your broker paid it, correct it with the credit from your statement instead.',
  );
});

test("a dividend moved to the day it was paid is named by the ex-date it keeps (brief AZ)", () => {
  const moved = row({
    kind: "dividend", date: "2026-09-30", ex_date: "2026-09-23", symbol: "XDIV.MI", asset_name: "Example Dividend Share",
  });
  const fmt = (iso: string) => iso.split("-").reverse().join("/");
  assert.equal(
    deleteQuestion(moved, [moved], fmt),
    'Delete dividend "Example Dividend Share" of 30/09/2026? The app will not record the dividend of XDIV.MI with ex-date 23/09/2026 at this account again. If your broker paid it, correct it with the credit from your statement instead.',
  );
});

test("a dividend held at no account is nothing the app records, so nothing brings it back", () => {
  const loose = row({ kind: "dividend", institution_id: null });
  assert.match(deleteQuestion(loose, [loose]), /Nothing brings it back\.$/);
});

test("the days are written as the page writes them", () => {
  const bought = row({ plan_id: 3, plan_occurrence: "2026-09-13", date: "2026-09-14" });
  const fmt = (iso: string) => iso.split("-").reverse().join("/");
  assert.match(deleteQuestion(bought, [bought], fmt), /of 14\/09\/2026\? Its PAC will not buy its occurrence of 13\/09\/2026 again\./);
});
