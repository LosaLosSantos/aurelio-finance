/* What a page says about a code it counts as written, because no rate
   converts it (brief BA, the reader's decision D2 (c), 2026-10-16).

   One block per code, in the order the reader acts on it:
     1. what kind of code it is: not a currency code (a typo, corrected on its
        row), or a currency no source quotes (nothing to correct; the figures
        that hold it are in two units);
     2. where it is written: the rows, by kind and name;
     3. how much of each figure on this page it is, as written: each figure's
        own share, measured by the backend on the figure itself (`notice`).

   The third used to be a volume of rows, every amount passed through added
   up, which matched no figure: measured at 279acf8, a household's notice said
   4,000.00 over 5 while 2,300.00 of its net worth and 900.00 of its book were
   the code. A page shows several payloads (the Dashboard four), so the
   blocks are merged by code here, each share under the name its figure has
   on the page. The history says at how many of its points the code is
   counted, and never an amount: a sum over points would count one row once
   per point.

   Pure, so tests/unconvertedWords.test.ts runs it under Node. */

import { locale } from "./money.ts";

export type UnconvertedRow = { kind: string; name: string; where?: string | null };

/** One code as a payload says it (`schemas.UnconvertedCode`). */
export type UnconvertedCode = {
  currency: string;
  not_a_code: boolean;
  rows?: UnconvertedRow[];
  more_rows?: number;
  shares?: Record<string, number>;
};

/** One payload's notice, and the name each of its figures has on the page. */
export type NoticePart = { items: UnconvertedCode[]; labels: Record<string, string> };

/** The history's points, each with the codes it counts as written. */
export type HistoryPoints = { unconverted?: string[] }[];

export type CodeSaid = {
  code: string;
  /** What kind of code, and what the reader can do: the first words read. */
  kind: string;
  /** Where it is written, or null when no row could be named. */
  rows: string | null;
  /** How much of each figure on the page it is, or null for none. */
  figures: string | null;
};

function plain(amount: number): string {
  return amount.toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function shown(code: string): string {
  return code === "" ? "no stated currency" : code;
}

function kindWords(code: string, notACode: boolean): string {
  if (code === "") return "A row states no currency: say which one on the row.";
  return notACode
    ? `'${code}' is not a currency code: correct it on the row it is written on.`
    : `${code} is a currency no source quotes, so no rate converts it.`;
}

function rowWords(row: UnconvertedRow): string {
  return `${row.kind} ${row.name}${row.where ? ` (${row.where})` : ""}`;
}

/** Every code a page counts as written, merged across its payloads. */
export function unconvertedWords(
  parts: NoticePart[],
  baseCurrency: string,
  history?: HistoryPoints,
): CodeSaid[] {
  const order: string[] = [];
  const merged = new Map<
    string,
    { notACode: boolean; rows: UnconvertedRow[]; more: number; figures: string[] }
  >();
  for (const part of parts) {
    for (const item of part.items) {
      let entry = merged.get(item.currency);
      if (entry === undefined) {
        entry = { notACode: item.not_a_code, rows: [], more: 0, figures: [] };
        merged.set(item.currency, entry);
        order.push(item.currency);
      }
      // Every payload reads the same census, so the first one with rows names them.
      if (entry.rows.length === 0 && item.rows && item.rows.length > 0) {
        entry.rows = item.rows;
        entry.more = item.more_rows ?? 0;
      }
      for (const [figure, amount] of Object.entries(item.shares ?? {})) {
        const label = part.labels[figure];
        if (label === undefined) continue;
        entry.figures.push(`${label} ${plain(amount)} ${shown(item.currency)}`);
      }
    }
  }
  if (history && history.length > 0) {
    // A code only earlier points count (a row sold since) is said too, its
    // kind read by the shape the backend checks (`schemas._CURRENCY_CODE`).
    for (const point of history) {
      for (const code of point.unconverted ?? []) {
        if (!merged.has(code)) {
          merged.set(code, { notACode: !/^[A-Za-z]{3}$/.test(code), rows: [], more: 0, figures: [] });
          order.push(code);
        }
      }
    }
    for (const code of order) {
      const at = history.filter((p) => (p.unconverted ?? []).includes(code)).length;
      if (at > 0) {
        merged.get(code)!.figures.push(
          `the history, at ${at} of its ${history.length} ${history.length === 1 ? "point" : "points"}`,
        );
      }
    }
  }
  return order.map((code) => {
    const entry = merged.get(code)!;
    const named = entry.rows.map(rowWords);
    if (entry.more > 0) named.push(`and ${entry.more} more`);
    return {
      code,
      kind: kindWords(code, entry.notACode),
      rows: named.length > 0 ? `Written on: ${named.join("; ")}.` : null,
      figures:
        entry.figures.length > 0
          ? `Counted here as written, as if in ${baseCurrency}: ${entry.figures.join("; ")}.`
          : null,
    };
  });
}
