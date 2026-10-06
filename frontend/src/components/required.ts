/* What a form cannot be sent without, said once per form.

   Thirteen forms used to swallow a press on an empty field: the button
   worked, nothing was sent, and nothing was said. Five of them did it through
   one line in the shared list editor, eight in their own submit handlers. And
   no field anywhere said it was required, so the reader learned which ones
   were by pressing and watching nothing happen.

   One list per form now drives three things that used to be separate, or
   missing: the sentence a refused press says, `aria-required` on the field,
   and the question its empty box asks. They cannot disagree, because there is
   only one list to read. The API schemas' own required arrays were not used
   for this, deliberately: in four forms they do not match what the form
   actually refuses (a holding needs a value the schema leaves optional, a
   goal's schema requires the name its form calls optional), and a marker has
   to tell the reader what THIS form will refuse.

   No runtime imports, so `npm test` reaches it. */

/** One field the form needs before it can send anything. */
export interface Need {
  /** The form's own name for the value, as passed to `refusal`. */
  key: string;
  /** How the shared sentence names it: "the name", "a ticker". */
  noun: string;
  /** The question its empty box asks. Left out for a select, whose first
      option already asks; for a date, which cannot show a placeholder; and
      for a currency box, 54px wide, where no question fits ("Currency?" is
      65px) and which opens filled in anyway. Every question here must fit
      its box with room to spare: tests/questionsFit.test.ts measures them
      against the font. */
  ask?: string;
  /** A sentence of its own, for a field whose absence has a reason worth
      giving. Said on its own, and only once the plain ones are filled in. */
  says?: string;
}

type Values = Record<string, string | number | null | undefined>;

function empty(v: string | number | null | undefined): boolean {
  return v == null || String(v).trim() === "";
}

/** The needs whose value is still empty, in the form's order. */
export function missing(needs: Need[], values: Values): Need[] {
  return needs.filter((n) => empty(values[n.key]));
}

function list(nouns: string[]): string {
  if (nouns.length === 1) return nouns[0];
  return `${nouns.slice(0, -1).join(", ")} and ${nouns[nouns.length - 1]}`;
}

/** What a refused press says, or null when nothing is missing.

    The plain needs are said together, in one sentence, because a reader
    filling a form should learn everything that is left at once. A need with a
    sentence of its own waits until the plain ones are in: those sentences were
    written to arrive when their field is the one thing left. */
export function refusal(needs: Need[], values: Values): string | null {
  const gone = missing(needs, values);
  const plain = gone.filter((n) => !n.says);
  if (plain.length > 0) return `Fill in ${list(plain.map((n) => n.noun))}.`;
  return gone.length > 0 ? (gone[0].says as string) : null;
}

/** The attributes that mark `key` as needed, to spread onto its control:
    `aria-required`, and the question its empty box asks. Nothing for a field
    this form does not need in its current state. */
export function marks(
  needs: Need[],
  key: string,
): { "aria-required"?: true; placeholder?: string } {
  const need = needs.find((n) => n.key === key);
  if (!need) return {};
  return need.ask ? { "aria-required": true, placeholder: need.ask } : { "aria-required": true };
}

// --- The rules, one per form ------------------------------------------------

const NAME: Need = { key: "name", noun: "the name", ask: "What is it called?" };
const AMOUNT: Need = { key: "amount", noun: "the amount", ask: "How much?" };

export const INSTITUTION: Need[] = [{ ...NAME, ask: "Which bank or broker?" }];

export const INCOME: Need[] = [{ ...NAME, ask: "What is it? e.g. Salary" }, AMOUNT];
export const EXPENSE: Need[] = [{ ...NAME, ask: "What is it? e.g. Rent" }, AMOUNT];

/** The dated series: a cash anchor, a valuation, a balance. `noun` and `ask`
    are the amount's, which is the one part that differs. */
export function dated(noun: string, ask: string): Need[] {
  return [
    { key: "date", noun: "the date" },
    { key: "amount", noun, ask },
  ];
}

/** The three dated series. Their questions live here rather than at the
    call sites, so the fit test sees every question the forms can ask. */
export const CASH_ANCHOR = dated("the cash", "How much?");
export const VALUATION = dated("the value", "What is it worth?");
export const BALANCE = dated("the balance", "How much is left?");

export const REAL_ASSET: Need[] = [
  { ...NAME, ask: "What is it? e.g. Milan flat" },
  {
    key: "currency",
    noun: "the currency",
    says: "Say which currency this asset is valued in.",
  },
];

export const DEBT: Need[] = [
  { ...NAME, ask: "What is it? e.g. Car loan" },
  { key: "currency", noun: "the currency", says: "Say which currency this debt is in." },
];

/** A goal: the dropdown carries the meaning, so the free label is needed only
    for "other", where it IS the goal. */
export function goal(type: string): Need[] {
  return [
    { key: "type", noun: "what the goal is for" },
    ...(type === "other" ? [{ key: "name", noun: "what the goal is", ask: "What is the goal?" }] : []),
    { key: "currency", noun: "the currency", says: "Say which currency this goal is in." },
  ];
}

const CURRENCIES_MOVED =
  "Say which currencies these are: what left the source, and what the destination was credited in.";

/** A transfer. Its source-or-destination is an either/or that no one field
    carries: `ends` is either of them, said as a sentence and marked on
    neither box. */
export const TRANSFER: Need[] = [
  { key: "date", noun: "the date" },
  AMOUNT,
  { key: "ends", noun: "a source or a destination", says: "Pick a source and/or a destination institution." },
  { key: "currency", noun: "the currency", says: CURRENCIES_MOVED },
  { key: "toCurrency", noun: "the currency", says: CURRENCIES_MOVED },
];

/** A PAC. At least one target needs a ticker; the first target's box carries
    the mark, since a second row left empty is simply ignored. Where each
    ticker is held is said by the form, per target, after these. */
export const PLAN: Need[] = [
  { ...NAME, ask: "What is it called?" },
  { key: "amount", noun: "the budget", ask: "How much?" },
  { key: "ticker", noun: "a ticker", ask: "Which ticker?" },
  {
    key: "sourceId",
    noun: "the account it is funded from",
    says: "A plan has to take the money from somewhere: name the account it is funded from, so each contribution leaves a real balance.",
  },
];

/** A position in a situation: a total, or a quantity and a price. */
export function holding(mode: "total" | "qty"): Need[] {
  return [
    { key: "name", noun: "the name", ask: "What is it? (type to search)" },
    ...(mode === "qty"
      ? [
          { key: "quantity", noun: "the quantity", ask: "Units?" },
          { key: "unitPrice", noun: "the price", ask: "Price?" },
        ]
      : [{ key: "value", noun: "the value", ask: "Worth?" }]),
  ];
}

const CURRENCIES_TRADED = "Say which currencies these are: the price's, and the account's the money moved in.";

/** A ledger row. A close needs what came back, and zero is an answer; a
    buy, a sell or a dividend needs what was traded and at what, where a
    dividend's price is what each share paid. */
export function transaction(kind: string, isClose: boolean): Need[] {
  return [
    { key: "assetName", noun: "the asset", ask: "What is it? (type to search)" },
    ...(isClose
      ? [{ key: "fees", noun: "the proceeds", ask: "Proceeds?" }]
      : [
          { key: "symbol", noun: "the ticker", ask: "Ticker or ISIN?" },
          { key: "quantity", noun: "the quantity", ask: "Units?" },
          kind === "dividend"
            ? { key: "unitPrice", noun: "the dividend per share", ask: "Per share?" }
            : { key: "unitPrice", noun: "the price", ask: "Price?" },
        ]),
    {
      key: "institutionId",
      noun: "the institution",
      says:
        kind === "buy"
          ? "A buy has to come from somewhere: pick where you keep it, so the cash leaves the right account."
          : `A ${kind} has to say where it is held: pick the institution, so the cash reaches the right account.`,
    },
    { key: "currency", noun: "the currency", says: CURRENCIES_TRADED },
    ...(isClose
      ? []
      : [{ key: "priceCurrency", noun: "the currency", says: CURRENCIES_TRADED }]),
  ];
}
