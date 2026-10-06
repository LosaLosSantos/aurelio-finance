/* Figures, in the currency they are written in.

   Two facts decide how an amount is printed, and they come from different
   places. The LOCALE is the reader's — punctuation and symbol placement. The
   CURRENCY is the number's — and a number has one no matter who reads it: an
   anchor typed in dollars is a dollar amount whatever the app's base is, and
   printing it with a euro sign beside a converted total is the defect 0bf262b
   closed for situations (89 lira shown as 89 EUR). So the currency is always an
   argument here, never a module-level setting a call site inherits.

   `money(currency)` returns the same shape as `Intl.NumberFormat` — a
   `.format(n)` — so a call site reads the same whether it prints a row's typed
   figure or a converted total: `money(row.currency).format(row.amount)`.

   No React and no DOM, on purpose: this is plain arithmetic about strings, and
   it can be run by `node` alone. */

/* The reader's own conventions, resolved once and imported everywhere.

   This used to be the string "it-IT", written out at thirteen call sites, so
   every reader got Italian punctuation and Italian date order whatever their
   own is: 31/12/2026 to someone expecting 12/31/2026, and 1.234,56 to someone
   expecting 1,234.56 — the same digits meaning something else.

   Resolved ONCE on purpose. A locale decided in six files is one file away from
   six locales, which is the shape of the duplication this codebase keeps
   finding in itself.

   `undefined` is a real answer, not a missing one: every Intl and toLocale*
   API reads it as "use the runtime's own locale", which is exactly right when
   navigator is absent — a test, a build step. */
export const locale: string | undefined =
  typeof navigator !== "undefined" && navigator.language ? navigator.language : undefined;

/** What every formatter here is: the one method the call sites use. */
export type Money = { format(amount: number): string };

/** "whole" drops the cents (a total, a balance); "cents" keeps the currency's
    own minor digits, for the few figures where they are the fact. */
export type Precision = "whole" | "cents";

/* Minor units, as the backend reads them (`fx._MINOR_EXACT`,
   `fx._MINOR_ANY_CASE`). `Intl` knows none of these as codes, and it reads
   currency codes case-insensitively — so "GBp" would be accepted as GBP and
   3361 pence printed as £3,361, the hundredfold error the backend already
   guards against. A minor unit is printed as a number and its code instead,
   exactly as typed: "3,361 GBp". 'GBp' is matched on its exact case, because
   'GBP' and 'gbp' are pounds. */
const MINOR_EXACT = new Set(["GBp"]);
const MINOR_ANY_CASE = new Set(["GBX", "ZAC", "ILA"]);

const built = new Map<string, Money>();

/** A formatter for amounts in `currency`, built on first use and kept: an
    `Intl.NumberFormat` is not free to construct and a list asks for the same
    one per row. */
export function money(currency: string, precision: Precision = "whole"): Money {
  const code = currency.trim();
  // Precision first: it is one of two fixed words with no colon in them, so
  // everything after the first colon is the code, whatever was typed there.
  const key = `${precision}:${code}`;
  let formatter = built.get(key);
  if (formatter === undefined) {
    formatter = build(code, precision);
    built.set(key, formatter);
  }
  return formatter;
}

function build(code: string, precision: Precision): Money {
  const digits: Intl.NumberFormatOptions =
    precision === "whole" ? { maximumFractionDigits: 0 } : {};
  if (MINOR_EXACT.has(code) || MINOR_ANY_CASE.has(code.toUpperCase())) {
    return labelled(code, precision);
  }
  try {
    return new Intl.NumberFormat(locale, { style: "currency", currency: code, ...digits });
  } catch {
    // Not a code `Intl` knows. The backend stores what it was sent as long as
    // it is not blank, and a page that throws on one odd row shows nothing at
    // all — so the figure is printed with the code beside it, as typed.
    return labelled(code, precision);
  }
}

function labelled(code: string, precision: Precision): Money {
  const plain = new Intl.NumberFormat(
    locale,
    precision === "whole" ? { maximumFractionDigits: 0 } : { maximumFractionDigits: 2 },
  );
  return { format: (amount: number) => `${plain.format(amount)} ${code}` };
}
