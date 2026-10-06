import { EditorButtons, Row, RowsOrEmpty, inputClass, money, CURRENCY_LIST } from "./ui";
import { useListEditor } from "./listEditor";
import { marks, type Need } from "./required";

/* "A date and an amount, one row per date" — written three times, identically.

   Liability balances, real-asset valuations and cash anchors are three tables
   with the same shape: a parent, an ISO date, a value, and UNIQUE(parent, date)
   — one dated series per parent, where the row in force at a date is the
   latest one on or before it. Each had its
   own copy of the same twelve-line form and the same list, and each had made
   the same small decisions independently: reset the draft when the row being
   edited is deleted, name the row in the confirm dialog, and say "a X for that
   date may already exist" when the save fails, because a unique constraint is
   the one error the reader can actually act on.

   Those two sentences are now derived from ONE `noun`, so they cannot disagree
   about what the thing is called.

   What is NOT shared is each caller's surrounding chrome: the equity line above
   valuations, the projection breakdown above cash anchors. Those are three
   different explanations of three different things, and folding them in here
   would have been the bad abstraction — this owns the repeated part and stops. */

export function DatedAmountEditor<T extends { id: number; note: string | null }, P>({
  items,
  loading = false,
  loadError = null,
  dateOf,
  amountOf,
  subtitleOf,
  currencyOf,
  proposedCurrency,
  toPayload,
  create,
  update,
  destroy,
  onChanged,
  /** Singular, lower case: "balance", "valuation", "cash anchor". It names the
      thing in the confirm dialog AND in the save error. */
  noun,
  amountLabel,
  needs,
  emptyText,
  /** Date pickers cannot show a placeholder, so a form whose date is not
      self-evident labels it. */
  dateLabel,
  /** "" when the reader should pick a date deliberately (a valuation is AS OF
      a day they are reading off a statement); today when the common case is
      now (the cash you are holding as you type). */
  blankDate = "",
  addLabel = "Add",
  amountWidth = "",
}: {
  items: T[];
  loading?: boolean;
  loadError?: string | null;
  dateOf: (item: T) => string;
  amountOf: (item: T) => number;
  subtitleOf?: (item: T) => string | undefined;
  /** The currency each row's amount is written in: its own for a cash
      anchor, its parent's for a valuation or a balance. Required, because it
      is how every row is PRINTED — a list of typed figures that does not say
      what they are in prints a dollar balance with the base's sign. It is also
      what an edited anchor sends back. */
  currencyOf: (item: T) => string;
  /** For a row that carries its OWN currency (a cash anchor): what a new row
      is proposed to be in on `date`. Given, the form shows a currency box
      holding the reader's choice when they typed one and this proposal
      otherwise; a change of date moves the proposal and never the choice.
      Left out, the row takes its parent's currency and no box is shown. */
  proposedCurrency?: (date: string) => string;
  /** `currency` is the reader's choice, or the edited row's (see
      `currencyOf`), or the proposal for the date — or "" for a row with no
      box. */
  toPayload: (date: string, amount: number, currency: string) => P;
  create: (data: P) => Promise<unknown>;
  update: (id: number, data: P) => Promise<unknown>;
  destroy: (id: number) => Promise<unknown>;
  onChanged: () => Promise<void> | void;
  noun: string;
  /** The amount box's name: "Remaining", "Value", "Actual cash". */
  amountLabel: string;
  /** What a row cannot be saved without, and the question each empty box
      asks: CASH_ANCHOR, VALUATION or BALANCE in required.ts. */
  needs: Need[];
  emptyText: string;
  dateLabel?: string;
  blankDate?: string;
  addLabel?: string;
  amountWidth?: string;
}) {
  const ed = useListEditor<T, P>({
    blank: { date: blankDate, amount: "", currency: "" },
    toDraft: (i) => ({
      date: dateOf(i),
      amount: String(amountOf(i)),
      currency: currencyOf(i),
    }),
    needs,
    toPayload: (d) => toPayload(d.date, Number(d.amount), d.currency || proposedCurrency?.(d.date) || ""),
    create,
    update,
    destroy,
    confirmDelete: (i) => `Delete the ${noun} of ${dateOf(i)}?`,
    saveError: `Save failed (a ${noun} for that date may already exist).`,
    onChanged,
  });

  const rows = items.map((i) => (
    <Row
      key={i.id}
      onEdit={() => ed.startEdit(i)}
      onDelete={() => void ed.destroy(i)}
      title={dateOf(i)}
      subtitle={subtitleOf?.(i)}
      note={i.note}
      value={money(currencyOf(i)).format(amountOf(i))}
    />
  ));

  return (
    <>
      <form
        onSubmit={ed.submit}
        className="flex flex-wrap items-center gap-2"
      >
        {dateLabel && <label className="text-xs text-ink-soft">{dateLabel}</label>}
        <input
          className={inputClass}
          type="date"
          // The <label> above is a bare word beside the box, not attached to
          // it, so the box had no name: measured, the anchor's date on the
          // account page read as '' in the accessibility tree. Named with the
          // same word a sighted reader sees, or "Date" where there is none.
          aria-label={dateLabel ?? "Date"}
          {...marks(needs, "date")}
          value={ed.draft.date}
          onChange={(e) => ed.set("date")(e.target.value)}
        />
        <input
          className={inputClass + (amountWidth ? " " + amountWidth : "")}
          type="number"
          step="0.01"
          aria-label={amountLabel}
          {...marks(needs, "amount")}
          value={ed.draft.amount}
          onChange={(e) => ed.set("amount")(e.target.value)}
        />
        {proposedCurrency && (
          <input
            className={inputClass + " w-20"}
            placeholder="currency"
            list={CURRENCY_LIST}
            title="The currency this amount is in. Proposed from the anchor in force on this date; change it and it stays as you typed it."
            value={ed.draft.currency || proposedCurrency(ed.draft.date)}
            onChange={(e) => ed.set("currency")(e.target.value)}
          />
        )}
        <EditorButtons
          editing={ed.editing}
          submitting={ed.submitting}
          onCancel={ed.reset}
          addLabel={addLabel}
        />
      </form>

      {ed.error && (
        <p className="text-down">{ed.error}</p>
      )}

      <RowsOrEmpty
        loading={loading}
        error={loadError}
        empty={items.length === 0}
        emptyText={emptyText}
      >
        {rows}
      </RowsOrEmpty>
    </>
  );
}
