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
   'GBP' and 'gbp' are pounds. Each maps to the major code it is a hundredth
   of, as the backend's pairs do. */
const MINOR_EXACT = new Map([["GBp", "GBP"]]);
const MINOR_ANY_CASE = new Map([
  ["GBX", "GBP"],
  ["ZAC", "ZAR"],
  ["ILA", "ILS"],
]);
const MINOR_PER_MAJOR = 100;

/** A code read in its major unit, as the backend reads it
    (`fx._in_major_units`): the major code, and how many units of the code as
    written make one of it (100 for pence, 1 for a major code). Any other code
    is upper-cased, so "eur" is EUR, which is what the backend converts it as.

    The browser used to compare codes as written, so a row stored as EUR with
    a price in "eur" was two currencies here and one there (brief BA). */
export function majorUnit(currency: string): { code: string; per: number } {
  const raw = currency.trim();
  const minor = MINOR_EXACT.get(raw) ?? MINOR_ANY_CASE.get(raw.toUpperCase());
  if (minor !== undefined) return { code: minor, per: MINOR_PER_MAJOR };
  return { code: raw.toUpperCase(), per: 1 };
}

/** Whether two codes are one currency once read in major units: no rate is
    needed between them, only the minor-unit step (`fx.same_currency`). */
export function sameCurrency(a: string, b: string): boolean {
  return majorUnit(a).code === majorUnit(b).code;
}

/** Whether two codes are one UNIT: one currency, and the same step of it.
    "eur" is EUR's unit; GBp is not GBP's, since a figure in pence beside one
    in pounds is a hundredth of it. */
export function sameUnit(a: string, b: string): boolean {
  const x = majorUnit(a);
  const y = majorUnit(b);
  return x.code === y.code && x.per === y.per;
}

/** `amount` in `from` restated in `to`, two spellings of one currency: the
    minor-unit step alone, 5,000 GBp to 50 GBP (`fx.within_currency`). */
export function withinCurrency(amount: number, from: string, to: string): number {
  return (amount / majorUnit(from).per) * majorUnit(to).per;
}

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
