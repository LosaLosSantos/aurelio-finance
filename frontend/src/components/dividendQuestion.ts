/* A question the catch-up asks about a dividend, in the reader's words, and
   the answers it offers (brief AZ).

   The catch-up records a dividend on its ex-date at the market's figure, and
   recognises the reader's own entry of it when the pairing is unique both
   ways: the only entry in the dividend's window, and the only dividend whose
   window holds the entry. Anything less is asked here, and nothing is written
   until it is answered: two entries one dividend could be, one entry two
   dividends could be, an entry beside the app's own estimate of the same
   dividend (two rows for one dividend, which the cash and the tax estimate
   both counted). And a dividend whose window holds the account's latest
   balance, with no payment date known: whether its money was already in that
   balance, which only the reader's statement says. Each answer is a request
   to `/api/transactions/dividend-answer`: "link" (this entry is that
   dividend), "apart" (it is not), "in_balance" or "after_balance".

   Pure, and with no runtime imports, so `tests/dividendQuestion.test.ts` runs
   it under Node without a bundler. Dates go in as ISO strings; the page says
   how dates, amounts and figures a share are printed (`Formats`). */

/** An entry as a question names it (`DividendEntryRead`). */
export type Entry = { id: number; date: string; amount: number; currency: string; estimated: boolean };

/** A dividend Yahoo lists, as a question names it (`ListedDividend`). */
export type Listed = {
  ex_date: string;
  dps: number | null;
  currency: string | null;
  units: number | null;
  estimate: Entry | null;
};

/** A question the catch-up asked (`DividendQuestion`). */
export type Question = {
  kind: string;
  institution_id: number;
  institution_name: string;
  symbol: string;
  dividends: Listed[];
  entries: Entry[];
  balance_date?: string | null;
  first_situation?: string | null;
};

/** The body of an answer (`DividendAnswer`). */
export type Answer = {
  institution_id: number;
  symbol: string;
  answer: "link" | "apart" | "in_balance" | "after_balance";
  transaction_id?: number;
  ex_date?: string;
  pairs?: { transaction_id: number; ex_date: string }[];
  balance_date?: string;
};

export type Choice = { label: string; answer: Answer };

export type Formats = {
  /** A day, as the page prints one in a sentence. */
  date(iso: string): string;
  /** An amount the account moved, cents included. */
  money(amount: number, currency: string): string;
  /** A dividend a share, every digit Yahoo gave. */
  perShare(amount: number, currency: string): string;
};

const COUNTS = ["", "One", "Two", "Three", "Four", "Five"];

/** "a and b", "a, b and c". */
function listed(items: string[], last = "and"): string {
  return items.length <= 1 ? items.join("") : `${items.slice(0, -1).join(", ")} ${last} ${items[items.length - 1]}`;
}

function where(q: Question): string {
  return `${q.symbol} at ${q.institution_name}`;
}

function entry(e: Entry, f: Formats): string {
  return `${f.date(e.date)}, ${f.money(e.amount, e.currency)}`;
}

/** "ex-date 22 September 2026, 0.25 EUR a share (about €5.00 for 20 units)". */
function dividend(d: Listed, f: Formats): string {
  let said = `ex-date ${f.date(d.ex_date)}`;
  if (d.dps != null && d.currency) {
    said += `, ${f.perShare(d.dps, d.currency)} a share`;
    if (d.units != null) said += ` (about ${f.money(d.dps * d.units, d.currency)} for ${d.units} units)`;
  }
  return said;
}

function link(q: Question, e: Entry, d: Listed): Answer {
  return { institution_id: q.institution_id, symbol: q.symbol, answer: "link", transaction_id: e.id, ex_date: d.ex_date };
}

function apart(q: Question, pairs: [Entry, Listed][]): Answer {
  return {
    institution_id: q.institution_id,
    symbol: q.symbol,
    answer: "apart",
    pairs: pairs.map(([e, d]) => ({ transaction_id: e.id, ex_date: d.ex_date })),
  };
}

/** The question, as one sentence or two. */
export function questionText(q: Question, f: Formats): string {
  const [d] = q.dividends;
  const [e] = q.entries;
  if (q.kind === "same_dividend" && d?.estimate && e) {
    return `${where(q)}: these two look like one dividend: the app's estimate with ex-date ${f.date(d.ex_date)} (${f.money(d.estimate.amount, d.estimate.currency)}, the market's gross figure) and your entry of ${entry(e, f)}. Keep yours as the dividend with ex-date ${f.date(d.ex_date)} and remove the estimate, or keep both?`;
  }
  if (q.kind === "which_entry" && d) {
    const count = COUNTS[q.entries.length] ?? String(q.entries.length);
    const beside = d.estimate
      ? `, beside the app's estimate of ${f.money(d.estimate.amount, d.estimate.currency)}`
      : "";
    return `${where(q)}: Yahoo lists a dividend with ${dividend(d, f)}. ${count} of your entries could be it${beside}: ${listed(q.entries.map((x) => entry(x, f)))}. Which one is it?`;
  }
  if (q.kind === "which_dividend" && e) {
    const days = q.dividends.map((x) => `ex-date ${f.date(x.ex_date)}`);
    return `${where(q)}: your entry of ${entry(e, f)} could be the dividend with ${listed(days, "or")}. Which one is it?`;
  }
  if (q.kind === "in_balance" && d && q.balance_date) {
    // The money of a dividend whose window holds the account's latest
    // balance, with no payment date known: the reader's statement says
    // whether that balance held it.
    const units = q.first_situation
      ? `${d.units} units of your first situation, of ${f.date(q.first_situation)}`
      : `${d.units} units held then`;
    const gross =
      d.dps != null && d.currency && d.units != null
        ? `: ${f.perShare(d.dps, d.currency)} a share, about ${f.money(d.dps * d.units, d.currency)} gross for the ${units}`
        : "";
    return `${where(q)}: Yahoo lists a dividend with ex-date ${f.date(d.ex_date)}, before your balance of ${f.date(q.balance_date)}${gross}. Was its money already in that balance?`;
  }
  return `${where(q)}: a dividend the app cannot pair with your entries.`;
}

/** The answers the question offers, in the order they are shown. */
export function choices(q: Question, f: Formats): Choice[] {
  const [d] = q.dividends;
  const [e] = q.entries;
  if (q.kind === "same_dividend" && d && e) {
    return [
      { label: "Keep mine, remove the estimate", answer: link(q, e, d) },
      { label: "Keep both", answer: apart(q, [[e, d]]) },
    ];
  }
  if (q.kind === "which_entry" && d) {
    const none = d.estimate ? "None: keep the estimate" : q.entries.length === 2 ? "Neither: record it" : "None: record it";
    return [
      ...q.entries.map((x) => ({ label: `The one of ${f.date(x.date)}`, answer: link(q, x, d) })),
      { label: none, answer: apart(q, q.entries.map((x) => [x, d] as [Entry, Listed])) },
    ];
  }
  if (q.kind === "which_dividend" && e) {
    return [
      ...q.dividends.map((x) => ({ label: `Ex-date ${f.date(x.ex_date)}`, answer: link(q, e, x) })),
      { label: "None of them", answer: apart(q, q.dividends.map((x) => [e, x] as [Entry, Listed])) },
    ];
  }
  if (q.kind === "in_balance" && d && q.balance_date) {
    const about = { institution_id: q.institution_id, symbol: q.symbol, ex_date: d.ex_date, balance_date: q.balance_date };
    return [
      { label: "Yes, it was in it", answer: { ...about, answer: "in_balance" } },
      { label: "No, it came after", answer: { ...about, answer: "after_balance" } },
    ];
  }
  return [];
}

/** What the banner says, once, of a dividend whose payment day Yahoo names
    and is still ahead: recorded that day, so it is not taken for one missed. */
export function waitingLine(
  w: { institution_name: string; symbol: string; ex_date: string; paid_on: string; dps: number | null; currency: string | null },
  f: Formats,
): string {
  const figure = w.dps != null && w.currency ? `${f.perShare(w.dps, w.currency)} a share, ` : "";
  return `${w.symbol} at ${w.institution_name}: ${figure}ex-date ${f.date(w.ex_date)}, paid on ${f.date(w.paid_on)}: recorded that day.`;
}

/** What the banner says of an entry the catch-up recognised. */
export function recognisedLine(
  r: { institution_name: string; symbol: string; ex_date: string; entry: Entry },
  f: Formats,
): string {
  return `${r.symbol} at ${r.institution_name}: your entry of ${f.date(r.entry.date)} is the dividend with ex-date ${f.date(r.ex_date)}, so it was not recorded again.`;
}
