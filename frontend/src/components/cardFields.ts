/* A line of a card, written in the reader's language.

   The server sends a card's lines already in the reader's words (brief AJ:
   the reader's cards showed "based_on", "symbol null", a row's id and an ISO
   timestamp): a label, a value, and what kind of value it is. This writes
   the value the way the rest of the app writes one: a day as the reader's
   calendar writes it, a number with their separators, an amount with its
   currency, as `money.ts` does everywhere else.

   No runtime imports but `money.ts`, itself pure, so `npm test` reaches it. */

import { money } from "./money.ts";

/** One line, as the server sends it. */
export interface CardLine {
  label: string;
  value: string;
  kind?: "text" | "date" | "number" | "amount";
  currency?: string | null;
}

/** The value of `line` as the reader reads it, in `lang` (the browser's own
    by default). A value that is not what its kind says is shown as it came. */
export function lineText(line: CardLine, lang: string | undefined = undefined): string {
  const kind = line.kind ?? "text";
  if (kind === "date" && /^\d{4}-\d{2}-\d{2}$/.test(line.value)) {
    const [y, m, d] = line.value.split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString(lang);
  }
  if (kind === "number" || kind === "amount") {
    const n = Number(line.value);
    if (!Number.isFinite(n)) return line.value;
    if (kind === "amount" && line.currency) return money(line.currency, "cents").format(n);
    return n.toLocaleString(lang);
  }
  return line.value;
}
