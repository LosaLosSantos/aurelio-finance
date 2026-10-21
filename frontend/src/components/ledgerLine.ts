/* A ledger row's lines, with its figures as the contract note states them
   (brief BD).

   The ledger is where a reader holds an entry against a contract note or a
   statement, and it printed every figure in whole units: a dividend of 0.1615
   a share read "20 × €0", one of 4.36 "+€4", fees of 1.95 "fees €2"
   (measured in Edge, 2026-10-20). Now the amount and the fees are printed to
   the cent, and the price per unit with every decimal it was entered with.

   The figures leave the line under the name. That line truncates, and at 390
   it was cut on every row, so with cents in it the part cut would have been
   the figure itself. The arithmetic opens the row's own line, which wraps and
   is never clipped (`Row`'s `detail`), before what `ledgerDetail` says there:
   the ex-date and the currency warning. The line under the name keeps the
   date, the rate's day, the account and the ticker.

   Pure, so `tests/ledgerLine.test.ts` runs it under Node. `at` is the locale,
   the reader's unless a test names one. */

import { ledgerDetail, type DetailedEntry } from "./ledgerDetail.ts";
import { locale, money } from "./money.ts";
import { rateLine } from "./rateSource.ts";

/** The ledger fields these lines read, as `TransactionRead` carries them. */
export type LedgerEntry = DetailedEntry & {
  date: string;
  quantity: number;
  unit_price: number;
  price_currency: string | null;
  fees: number;
  amount: number;
  currency: string;
  fx_as_of: string | null;
  fx_source?: string | null;
  symbol?: string | null;
};

/** The line under the name, which truncates: when, at whose rate, where. */
export function ledgerSubtitle(
  t: LedgerEntry,
  fmt: (iso: string) => string,
  institution: string | undefined,
): string {
  return [
    fmt(t.date),
    // A sum fixed at one day's rate says which day, so it can be held
    // against the statement.
    t.fx_as_of ? rateLine(fmt(t.fx_as_of), t.fx_source) : null,
    institution,
    t.symbol,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** The arithmetic: the units at their price, then the fees, or nothing for an
    entry with no price (a close). */
export function ledgerFigures(t: LedgerEntry, at: string | undefined = locale): string | undefined {
  const said = [
    t.price_currency ? `${t.quantity} × ${money(t.price_currency, "price", at).format(t.unit_price)}` : null,
    t.fees ? `fees ${money(t.currency, "cents", at).format(t.fees)}` : null,
  ].filter(Boolean);
  return said.length ? said.join(" · ") : undefined;
}

/** The row's own line: the arithmetic first, then the ex-date and the
    currency warning, or undefined when it has nothing to say. */
export function ledgerOwnLine(
  t: LedgerEntry,
  fmt: (iso: string) => string,
  at: string | undefined = locale,
): string | undefined {
  const said = [ledgerFigures(t, at), ledgerDetail(t, fmt)].filter(Boolean);
  return said.length ? said.join(" · ") : undefined;
}

/** The row's figure: the cash that moved, to the cent, leaving on a buy and
    arriving on every other kind. */
export function ledgerAmount(t: LedgerEntry, at: string | undefined = locale): string {
  return (t.kind === "buy" ? "−" : "+") + money(t.currency, "cents", at).format(t.amount);
}
