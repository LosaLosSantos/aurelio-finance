/* What the ledger paid before an account's latest situation, proposed on the
   Portfolio (brief AW).

   A situation started from the last one before brief AV, or one it could not
   price, folded what had been paid into the situation's value: measured on
   an invented fund, 110.00 read as paid where the ledger held 410.00. The
   backend walks every situation with the ledger between them
   (`positions.recover_paid`) and proposes, per row, what was paid that the row
   does not say. The reader sees each figure before it is written (their
   choice, 2026-10-15): "Keep as paid" writes it as the row's cost, "No" leaves
   the row and never proposes it again.

   Purchases a situation's units disagreed with are said too, one line per
   row, without a button: what was not read, the units the situation says
   against the ledger's, and the two remedies (the reviewer's guards).

   Pure, so `tests/paidRecovery.test.ts` runs it under Node: the formatters
   come in as arguments, and the page passes the reader's own. */

import type { PaidProposal, UnreadPurchases } from "../api/portfolio";

/** How a figure, a day and a number of units are printed. */
export type Formats = {
  money: (amount: number) => string;
  day: (iso: string) => string;
  units: (n: number) => string;
};

/** The notice's heading and the line under it. */
export const NOTICE_TITLE = "Paid before a situation, read back from the ledger";
export const NOTICE_NOTE =
  "These purchases went into a situation's value. Keep as paid makes them the row's cost, " +
  "for the units they bought; No leaves the row as it is, and it is not proposed again.";

/** Units that are all of a row's are said as all of them. */
function sameUnits(a: number, b: number): boolean {
  return Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a), Math.abs(b));
}

/** One proposal: "Fondo Gamma: €300 paid for 3 of the 13 units, from the
    purchases on record since 2 Mar 2026." A cost recorded where the reading
    started is named first; a cost the row carries is said beside it, since
    the proposal then replaces it. */
export function proposalLine(p: PaidProposal, f: Formats): string {
  const share = sameUnits(p.units, p.quantity)
    ? `for all ${f.units(p.quantity)} units`
    : `for ${f.units(p.units)} of the ${f.units(p.quantity)} units`;
  const bought = p.entries.some((e) => e.kind === "buy");
  const source =
    p.opening_paid != null
      ? `from the cost recorded on ${f.day(p.since)}${bought ? " and the purchases on record since" : ""}`
      : `from the purchases on record since ${f.day(p.since)}`;
  const row =
    p.row_units > 0
      ? ` The row says ${f.money(p.row_paid)} for ${f.units(p.row_units)} units${p.row_estimated ? ", estimated" : ""}.`
      : "";
  return `${p.asset_name}: ${f.money(p.paid)} paid ${share}, ${source}.${row}`;
}

/** An entry the proposal read: "16 Mar 2026: bought 1 for €100 (est.)". */
export function entryLine(e: PaidProposal["entries"][number], f: Formats): string {
  const verb = e.kind === "sell" ? "sold" : "bought";
  return `${f.day(e.date)}: ${verb} ${f.units(e.quantity)} for ${f.money(e.amount)}${e.estimated ? " (est.)" : ""}`;
}

/** Purchases a disagreeing situation left unread, in one line. A cost
    recorded where the reading started, part of the figure, is named first. */
export function unreadLine(u: UnreadPurchases, f: Formats): string {
  const purchases = u.purchases === 1 ? "1 purchase" : `${u.purchases} purchases`;
  const behind =
    u.opening_paid != null
      ? `the cost recorded on ${f.day(u.since)} and ${purchases} since`
      : `${purchases} since ${f.day(u.since)}`;
  return (
    `${u.asset_name}: ${f.money(u.paid)} paid for ${f.units(u.units)} units ` +
    `(${behind}) is not read, because the situation of ` +
    `${f.day(u.situation_date)} says ${f.units(u.stated_units)} units where the ledger gives ` +
    `${f.units(u.walked_units)}. Correct those purchases to their contract notes, or that ` +
    "situation's units, and it is proposed."
  );
}

/** The button that accepts every proposal shown, from two of them. */
export function acceptAllLabel(n: number): string | null {
  return n >= 2 ? `Keep all ${n} as paid` : null;
}
