/* What a ledger row says on a line of its own (brief AZ).

   A dividend keeps its ex-date whatever day its row is dated, and a cash
   figure turns on which of the two the date is, so the row names its ex-date
   on a line that wraps rather than clipping. Every expected value is written
   here; the rows are invented. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { ledgerDetail } from "../src/components/ledgerDetail.ts";

const fmt = (iso: string) => iso.split("-").reverse().join("/");

test("a dividend names its ex-date, whichever day its row is dated", () => {
  assert.equal(ledgerDetail({ kind: "dividend", ex_date: "2026-09-22" }, fmt), "ex-date 22/09/2026");
  assert.equal(ledgerDetail({ kind: "dividend", ex_date: "2026-09-22", currency_note: null }), "ex-date 2026-09-22");
});

test("an entry that keeps no ex-date, and every other kind, say nothing more", () => {
  assert.equal(ledgerDetail({ kind: "dividend", ex_date: null }, fmt), undefined);
  assert.equal(ledgerDetail({ kind: "buy", ex_date: null, currency_note: null }, fmt), undefined);
  assert.equal(ledgerDetail({ kind: "buy", ex_date: "2026-09-15" }, fmt), undefined);
});

test("the warning about a currency keeps its place, after the ex-date when a row has both", () => {
  const note = "typed EUR, the listing trades in USD";
  assert.equal(ledgerDetail({ kind: "buy", ex_date: null, currency_note: note }, fmt), `⚠ ${note}`);
  assert.equal(
    ledgerDetail({ kind: "dividend", ex_date: "2026-09-22", currency_note: note }, fmt),
    `ex-date 22/09/2026 · ⚠ ${note}`,
  );
});
