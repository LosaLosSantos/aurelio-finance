/* A ledger row's figures as the contract note states them (brief BD): the
   amount and the fees to the cent, the price per unit with every decimal it
   was entered with, on the row's own line, which wraps; the line under the
   name, which truncates, holds no figure. Every expected value is written
   here, in en-US; the rows are invented. */

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  ledgerAmount,
  ledgerFigures,
  ledgerOwnLine,
  ledgerSubtitle,
  type LedgerEntry,
} from "../src/components/ledgerLine.ts";

const AT = "en-US";
const fmt = (iso: string) => iso.split("-").reverse().join("/");

function entry(over: Partial<LedgerEntry>): LedgerEntry {
  return {
    kind: "buy",
    date: "2026-08-03",
    quantity: 20,
    unit_price: 9.047,
    price_currency: "EUR",
    fees: 0,
    amount: 180.94,
    currency: "EUR",
    fx_as_of: null,
    fx_source: null,
    symbol: "ZZDV.DE",
    ex_date: null,
    currency_note: null,
    ...over,
  };
}

test("a dividend reads its amount a share as entered and its total to the cent", () => {
  const small = entry({ kind: "dividend", unit_price: 0.1615, amount: 3.23 });
  assert.equal(ledgerFigures(small, AT), "20 × €0.1615");
  assert.equal(ledgerAmount(small, AT), "+€3.23");
  const other = entry({ kind: "dividend", unit_price: 0.218, amount: 4.36 });
  assert.equal(ledgerFigures(other, AT), "20 × €0.218");
  assert.equal(ledgerAmount(other, AT), "+€4.36");
});

test("a buy reads its price, its fees and what left the account to the cent", () => {
  const buy = entry({ fees: 1.95, amount: 182.89 });
  assert.equal(ledgerFigures(buy, AT), "20 × €9.047 · fees €1.95");
  assert.equal(ledgerAmount(buy, AT), "−€182.89");
  const round = entry({ quantity: 4, unit_price: 191, fees: 2, amount: 766 });
  assert.equal(ledgerFigures(round, AT), "4 × €191.00 · fees €2.00");
  assert.equal(ledgerAmount(round, AT), "−€766.00");
});

test("a price in another currency, in pence or in a currency with no minor unit keeps its own digits", () => {
  assert.equal(ledgerFigures(entry({ kind: "dividend", unit_price: 0.25, price_currency: "USD" }), AT), "20 × $0.25");
  assert.equal(ledgerFigures(entry({ quantity: 10, unit_price: 3361.5, price_currency: "GBp" }), AT), "10 × 3,361.5 GBp");
  assert.equal(ledgerFigures(entry({ quantity: 100, unit_price: 1234, price_currency: "JPY" }), AT), "100 × ¥1,234");
  assert.equal(ledgerAmount(entry({ kind: "sell", amount: 1234, currency: "JPY" }), AT), "+¥1,234");
});

test("a close states no arithmetic, only what came back", () => {
  const close = entry({ kind: "close", quantity: 0, unit_price: 0, price_currency: null, amount: 1250 });
  assert.equal(ledgerFigures(close, AT), undefined);
  assert.equal(ledgerOwnLine(close, fmt, AT), undefined);
  assert.equal(ledgerAmount(close, AT), "+€1,250.00");
});

test("the row's own line opens with the arithmetic, then the ex-date and the warning", () => {
  const note = "typed EUR, the listing trades in USD";
  const dividend = entry({ kind: "dividend", unit_price: 0.1615, amount: 3.23, ex_date: "2026-09-12", currency_note: note });
  assert.equal(ledgerOwnLine(dividend, fmt, AT), `20 × €0.1615 · ex-date 12/09/2026 · ⚠ ${note}`);
  assert.equal(ledgerOwnLine(entry({ fees: 1.95, amount: 182.89 }), fmt, AT), "20 × €9.047 · fees €1.95");
});

test("the line under the name, which truncates, holds no figure", () => {
  assert.equal(ledgerSubtitle(entry({}), fmt, "Example Broker"), "03/08/2026 · Example Broker · ZZDV.DE");
  assert.equal(
    ledgerSubtitle(entry({ fx_as_of: "2026-08-03", fx_source: "ECB" }), fmt, undefined),
    "03/08/2026 · at the ECB rate of 03/08/2026 · ZZDV.DE",
  );
});
