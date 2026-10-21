import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  createExpense,
  createIncomeSource,
  deleteExpense,
  deleteIncomeSource,
  getCashFlowSummary,
  getExpenses,
  getIncomeSources,
  updateExpense,
  updateIncomeSource,
  type CashFlowSummary,
  type Expense,
  type ExpenseCreate,
  type IncomeSource,
  type IncomeSourceCreate,
} from "../api/cashflow";
import {
  createTransfer,
  deleteTransfer,
  getTransfers,
  transferDeletion,
  updateTransfer,
  type Transfer,
} from "../api/transfers";
import { getAccumulationPlans, type AccumulationPlan } from "../api/accumulationPlans";
import { getInstitutions, type Institution } from "../api/institutions";
import { getAllCashAnchors, type CashAnchor } from "../api/cash";
import { accountCurrencyOn } from "./proposedCurrency";
import { askBeforeDeleting } from "./cashDelete";
import { DateField, InstitutionSelect } from "./recordFields";
import { dateRange, subtitle } from "./rowLine";
import { PlanList } from "./Plans";
import {
  EditorButtons,
  Row,
  RowsOrEmpty,
  SAVINGS_RATE,
  Section,
  StatCard,
  apiError,
  btnClass,
  inputClass,
  money,
  todayISO,
  CURRENCY_LIST,
} from "./ui";
import { EMPTY_LINES } from "./emptyStates";
import { useListEditor, type Draft } from "./listEditor";
import { arrivalWasStated, sameSum } from "./statedAmount";
import { rateLine } from "./rateSource";
import { sameCurrency } from "./money";
import { UnconvertedNotice } from "./UnconvertedNotice";
import { IN_FORCE, leftOutLine, notCounted, undatedLine } from "./inForce";
import { EXPENSE as EXPENSE_NEEDS, INCOME as INCOME_NEEDS, TRANSFER, marks, refusal, type Need } from "./required";
import { FIRST_PAYMENT_NOTE, flowDateLabel } from "./firstDate";
import type { Focus } from "../nav";

/* The names the notice gives the monthly figures (brief BA). */
const MONTHLY_FIGURES = {
  monthly_income: "monthly income",
  monthly_expenses: "monthly expenses",
  monthly_net: "monthly net",
};

const KINDS = ["", "active", "passive"];
const NATURES = ["", "essential", "discretionary"];
const FREQUENCIES = ["", "monthly", "quarterly", "semiannual", "annual", "one_off"];
const INCOME_CATEGORIES = ["", "salary", "freelance", "business", "rental", "dividends", "interest", "pension", "other"];
const EXPENSE_CATEGORIES = ["", "housing", "food", "transport", "utilities", "health", "insurance", "debt", "leisure", "education", "other"];

function pct(x: number | null): string {
  return x == null ? "n/a" : `${Math.round(x * 100)}%`;
}

export default function CashFlow({
  focus,
  onFocused,
  onOpenPlans,
}: {
  /** Set when the reader arrived from the account page's cash sentence rather
      than by pressing "Cash flow". Three of that sentence's terms are kept in
      three different sections of THIS page, and landing at the top of all four
      would leave the reader to find the one they asked for. */
  focus: Focus | null;
  onFocused: () => void;
  /** Opens Portfolio at the PAC, where each plan is set and changed. */
  onOpenPlans: () => void;
}) {
  const [summary, setSummary] = useState<CashFlowSummary | null>(null);
  const [incomes, setIncomes] = useState<IncomeSource[]>([]);
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [transfers, setTransfers] = useState<Transfer[]>([]);
  const [plans, setPlans] = useState<AccumulationPlan[]>([]);
  const [institutions, setInstitutions] = useState<Institution[]>([]);
  const [anchors, setAnchors] = useState<CashAnchor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // The three sections a term of the cash sentence can name. Movement is the
  // only arrival cue on purpose: a highlight would need a colour, a duration
  // and a rule for not firing on an ordinary visit — a new concept on a page
  // where every row already prints the institution it belongs to.
  const incomeRef = useRef<HTMLDivElement>(null);
  const expenseRef = useRef<HTMLDivElement>(null);
  const transferRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void loadAll();
  }, []);

  async function loadAll() {
    setLoading(true);
    setError(null);
    try {
      const [s, i, e, t, p, inst, a] = await Promise.all([
        getCashFlowSummary(),
        getIncomeSources(),
        getExpenses(),
        getTransfers(),
        getAccumulationPlans(),
        getInstitutions(),
        getAllCashAnchors(),
      ]);
      setSummary(s);
      setIncomes(i);
      setExpenses(e);
      setTransfers(t);
      setPlans(p);
      setInstitutions(inst);
      setAnchors(a);
    } catch (err) {
      setError(apiError(err, "Could not reach the backend. Is it running on :8000?"));
    } finally {
      setLoading(false);
    }
  }

  function instName(id: number | null): string | undefined {
    if (id == null) return undefined;
    return institutions.find((x) => x.id === id)?.name;
  }

  // Arriving AT a section rather than at the page. The wait for `loading` is
  // the whole subtlety: this component renders "Loading…" first, so on the
  // render that carries the focus none of these sections exist yet and
  // scrolling would silently do nothing.
  useEffect(() => {
    if (!focus || loading) return;
    const target =
      focus === "income" ? incomeRef : focus === "expenses" ? expenseRef : transferRef;
    target.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    // Consumed once. Left set, every later re-render of this page would drag
    // the reader back to the same heading mid-typing.
    onFocused();
  }, [focus, loading, onFocused]);

  if (loading) return <p className="text-ink-soft">Loading…</p>;
  if (error) return <p className="text-down">{error}</p>;
  // The base the reader chose, as the summary was computed in: what a new row
  // with no account to ask is proposed in.
  const base = summary?.base_currency ?? "";
  // What the four figures leave out, said under them; each left-out row says
  // its own reason in the lists below.
  const leftOut = summary ? notCounted(summary) : null;
  const undated = summary ? undatedLine(summary.undated) : null;

  return (
    <div className="space-y-8">
      {summary && (
        <div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard label="Monthly income" value={money(summary.base_currency).format(summary.monthly_income)} valueClass="text-up" />
            <StatCard label="Monthly expenses" value={money(summary.base_currency).format(summary.monthly_expenses)} valueClass="text-down" />
            <StatCard
              label="Monthly net"
              value={money(summary.base_currency).format(summary.monthly_net)}
              valueClass={summary.monthly_net >= 0 ? "text-ink" : "text-down"}
            />
            <StatCard label="Savings rate" value={pct(summary.savings_rate)} valueClass="text-olive" explain={SAVINGS_RATE} />
          </div>
          <p className="mt-3 text-sm text-ink-soft">
            Income: active {money(summary.base_currency).format(summary.active_income)} · passive{" "}
            {money(summary.base_currency).format(summary.passive_income)}. Expenses: essential{" "}
            {money(summary.base_currency).format(summary.essential_expenses)} · discretionary{" "}
            {money(summary.base_currency).format(summary.discretionary_expenses)}. {IN_FORCE}
          </p>
          {(leftOut || undated) && (
            <p className="mt-1 text-sm text-ink-soft">
              {[leftOut && `Not counted: ${leftOut} (marked below).`, undated].filter(Boolean).join(" ")}
            </p>
          )}
          {/* A flow in a code no rate converts, counted in these monthly
              figures as written (brief BA, measured at 279acf8: a salary of
              9,000 TWD read as 9,000.00 EUR a month, and nothing said so). */}
          <div className="mt-3">
            <UnconvertedNotice
              baseCurrency={summary.base_currency}
              parts={[{ items: summary.unconverted ?? [], labels: MONTHLY_FIGURES }]}
            />
          </div>
        </div>
      )}

      <div ref={incomeRef} className="scroll-mt-6">
        <CashFlowSection spec={INCOME} items={incomes} summary={summary} institutions={institutions} anchors={anchors} base={base} instName={instName} onChanged={loadAll} />
      </div>
      <div ref={expenseRef} className="scroll-mt-6">
        <CashFlowSection spec={EXPENSE} items={expenses} summary={summary} institutions={institutions} anchors={anchors} base={base} instName={instName} onChanged={loadAll} />
      </div>
      {/* Listed here, set in Portfolio (brief BD). */}
      <PlanList items={plans} instName={instName} onOpen={onOpenPlans} />
      {/* Last on purpose: a transfer moves money you already have between two
          places you already own, so it changes no total. Income, expenses and
          plans do — they belong above it. */}
      <div ref={transferRef} className="scroll-mt-6">
        <TransferSection items={transfers} institutions={institutions} anchors={anchors} base={base} instName={instName} onChanged={loadAll} />
      </div>
    </div>
  );
}

/* Income and Expense are the same section, twice.

   They were built as two components, ~130 lines each, identical except for one
   field name and two vocabularies — so a fix to one (the delete prompt, the
   error voice, resetting the form after deleting the row being edited) landed
   in one of them and not the other.

   They are NOT the same concept, and the tables stay separate: `kind` says
   active or passive, `nature` says essential or discretionary, and those are
   not one axis with four values. The cash register signs them oppositely. What
   was duplicated is the MECHANISM, and only that is shared here. */

/** The fields both sides carry, as the API returns them. */
type CashFlowRow = {
  id: number;
  name: string;
  category: string | null;
  amount: number;
  currency: string;
  frequency: string | null;
  institution_id: number | null;
  start_date: string | null;
  end_date: string | null;
  notes: string | null;
};

/** The same fields on the way back, minus the id and the note. The note is
    shown on the row and never sent: the form has no box for it, and an edit
    leaves out what it does not send, so the stored note survives every save. */
type CashFlowBase = Omit<CashFlowRow, "id" | "notes">;

type CashFlowSpec<T extends CashFlowRow, P> = {
  /** Which side of the summary's left-out lists a row of this kind is on. */
  side: "income" | "expense";
  title: string;
  hint: string;
  /** What a row of this kind cannot be saved without. */
  needs: Need[];
  emptyText: string;
  /** How the confirm dialog names one of these. */
  noun: string;
  /** The single field name the two sides disagree on — `kind` or `nature`.
      It labels its own select, so the placeholder never drifts from it. */
  tagField: string;
  tagOptions: string[];
  tagOf: (item: T) => string | null;
  categories: string[];
  /** Put the tag back under its own name. The only place either side needs to
      know which name that is. */
  withTag: (base: CashFlowBase, tag: string | null) => P;
  create: (data: P) => Promise<unknown>;
  update: (id: number, data: P) => Promise<unknown>;
  destroy: (id: number) => Promise<unknown>;
};

function CashFlowSection<T extends CashFlowRow, P>({
  spec,
  items,
  summary,
  institutions,
  anchors,
  base,
  instName,
  onChanged,
}: {
  spec: CashFlowSpec<T, P>;
  items: T[];
  /** The figures above, which list the rows they leave out: a row still to
      start or ended says so on its own line. */
  summary: CashFlowSummary | null;
  /** The base the reader chose: what a flow with no account is proposed in. */
  base: string;
  /** Every account's cash anchors: the currency box proposes the linked
      account's on the start date. */
  anchors: CashAnchor[];
  institutions: Institution[];
  instName: (id: number | null) => string | undefined;
  onChanged: () => Promise<void> | void;
}) {
  /* What the currency box proposes while the reader has not typed one (the
     draft's `currency` stays "" until they do): the linked account's currency
     on the start date — its anchor in force then, or its first — and the
     base only with no account, or an account with no anchor. A
     salary credited to a dollar account opened at EUR, hidden, before this. */
  const proposed = (d: Draft) =>
    accountCurrencyOn(
      anchors,
      d.institutionId ? Number(d.institutionId) : null,
      d.startDate || todayISO(),
    ) ?? base;

  const ed = useListEditor<T, P>({
    blank: {
      name: "",
      tag: "",
      category: "",
      amount: "",
      currency: "",
      frequency: "monthly",
      institutionId: "",
      startDate: todayISO(),
      endDate: "",
    },
    toDraft: (i) => ({
      name: i.name,
      tag: spec.tagOf(i) ?? "",
      category: i.category ?? "",
      amount: String(i.amount),
      currency: i.currency,
      frequency: i.frequency ?? "",
      institutionId: i.institution_id ? String(i.institution_id) : "",
      startDate: i.start_date ?? "",
      endDate: i.end_date ?? "",
    }),
    needs: spec.needs,
    toPayload: (d) => {
      return spec.withTag(
        {
          name: d.name.trim(),
          category: d.category || null,
          amount: Number(d.amount),
          currency: d.currency || proposed(d),
          frequency: d.frequency || null,
          institution_id: d.institutionId ? Number(d.institutionId) : null,
          start_date: d.startDate || null,
          end_date: d.endDate || null,
        },
        d.tag || null,
      );
    },
    create: spec.create,
    update: spec.update,
    destroy: spec.destroy,
    confirmDelete: (i) => `Delete ${spec.noun} "${i.name}"?`,
    onChanged,
  });

  return (
    <Section
      title={spec.title}
      hint={spec.hint}
      note={FIRST_PAYMENT_NOTE}
      explain={{
        question: `How is ${spec.noun === "income" ? "an income's" : "an expense's"} currency proposed?`,
        text: `From the cash of the account it is ${spec.noun === "income" ? "credited to" : "paid from"}, on the first payment's date; what you type stays.`,
      }}
    >
      <form onSubmit={ed.submit} className="flex flex-wrap items-center gap-2">
        <input className={inputClass} aria-label="Name" {...marks(spec.needs, "name")} value={ed.draft.name} onChange={(e) => ed.set("name")(e.target.value)} />
        <select className={inputClass} aria-label={spec.tagField === "kind" ? "Kind" : "Nature"} value={ed.draft.tag} onChange={(e) => ed.set("tag")(e.target.value)}>
          {spec.tagOptions.map((t) => (<option key={t} value={t}>{t || `${spec.tagField}…`}</option>))}
        </select>
        <select className={inputClass} aria-label="Category" value={ed.draft.category} onChange={(e) => ed.set("category")(e.target.value)}>
          {spec.categories.map((c) => (<option key={c} value={c}>{c || "category…"}</option>))}
        </select>
        <input className={inputClass + " w-28"} type="number" step="0.01" aria-label="Amount" {...marks(spec.needs, "amount")} value={ed.draft.amount} onChange={(e) => ed.set("amount")(e.target.value)} />
        <input
          className={inputClass + " w-20"}
          placeholder="currency"
          aria-label="Currency"
          list={CURRENCY_LIST}
          value={ed.draft.currency || proposed(ed.draft)}
          onChange={(e) => ed.set("currency")(e.target.value)}
        />
        <select className={inputClass} aria-label="Frequency" value={ed.draft.frequency} onChange={(e) => ed.set("frequency")(e.target.value)}>
          {FREQUENCIES.map((f) => (<option key={f} value={f}>{f || "frequency…"}</option>))}
        </select>
        <InstitutionSelect value={ed.draft.institutionId} onChange={ed.set("institutionId")} institutions={institutions} label="Account" />
        <DateField label={flowDateLabel(ed.draft.frequency)} value={ed.draft.startDate} onChange={ed.set("startDate")} />
        <DateField label="end" value={ed.draft.endDate} onChange={ed.set("endDate")} />
        <EditorButtons editing={ed.editing} submitting={ed.submitting} onCancel={ed.reset} />
      </form>
      {ed.error && <p className="text-down">{ed.error}</p>}
      <RowsOrEmpty loading={false} error={null} empty={items.length === 0} emptyText={spec.emptyText}>
        {items.map((i) => (
          <Row
            key={i.id}
            onEdit={() => ed.startEdit(i)}
            onDelete={() => void ed.destroy(i)}
            title={i.name}
            badge={spec.tagOf(i)}
            subtitle={subtitle([i.category, i.frequency, instName(i.institution_id), dateRange(i.start_date, i.end_date)])}
            detail={summary ? leftOutLine(summary, spec.side, i.id) : undefined}
            note={i.notes}
            value={money(i.currency).format(i.amount)}
          />
        ))}
      </RowsOrEmpty>
    </Section>
  );
}

const INCOME: CashFlowSpec<IncomeSource, IncomeSourceCreate> = {
  side: "income",
  title: "Income",
  hint: "Institution = where it's credited (its cash).",
  needs: INCOME_NEEDS,
  emptyText: EMPTY_LINES.income,
  noun: "income",
  tagField: "kind",
  tagOptions: KINDS,
  tagOf: (i) => i.kind,
  categories: INCOME_CATEGORIES,
  withTag: (base, tag) => ({ ...base, kind: tag }),
  create: createIncomeSource,
  update: updateIncomeSource,
  destroy: deleteIncomeSource,
};

const EXPENSE: CashFlowSpec<Expense, ExpenseCreate> = {
  side: "expense",
  title: "Expenses",
  hint: "Institution = where it's paid from (its cash).",
  needs: EXPENSE_NEEDS,
  emptyText: EMPTY_LINES.expenses,
  noun: "expense",
  tagField: "nature",
  tagOptions: NATURES,
  tagOf: (x) => x.nature,
  categories: EXPENSE_CATEGORIES,
  withTag: (base, tag) => ({ ...base, nature: tag }),
  create: createExpense,
  update: updateExpense,
  destroy: deleteExpense,
};

function TransferSection({
  items,
  institutions,
  anchors,
  base,
  instName,
  onChanged,
}: {
  items: Transfer[];
  institutions: Institution[];
  /** The base: what a side with no anchor at all is proposed in. */
  base: string;
  /** Every account's cash anchors: each side's currency is proposed from the
      anchor of its account in force on the transfer's date. */
  anchors: CashAnchor[];
  instName: (id: number | null) => string | undefined;
  onChanged: () => Promise<void> | void;
}) {
  const [editId, setEditId] = useState<number | null>(null);
  const [date, setDate] = useState(todayISO());
  const [fromId, setFromId] = useState("");
  const [toId, setToId] = useState("");
  const [amount, setAmount] = useState("");
  /* The two sides of a transfer: what left the source account, and what the
     destination was credited in. Each is the reader's choice when they made
     one (null until then) and otherwise the proposal below. `arrived` is the
     credit itself when the reader has it from the destination's statement;
     left blank across two currencies, the backend works it out at the rate
     of the date (the ECB's, or Yahoo's for a currency the ECB does not
     publish) and says which day and whose. */
  const [currencyChoice, setCurrencyChoice] = useState<string | null>(null);
  const [toCurrencyChoice, setToCurrencyChoice] = useState<string | null>(null);
  const [arrived, setArrived] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setEditId(null);
    setDate(todayISO());
    setFromId("");
    setToId("");
    setAmount("");
    setCurrencyChoice(null);
    setToCurrencyChoice(null);
    setArrived("");
  }

  function startEdit(t: Transfer) {
    setEditId(t.id);
    setDate(t.date);
    setFromId(t.from_institution_id ? String(t.from_institution_id) : "");
    setToId(t.to_institution_id ? String(t.to_institution_id) : "");
    setAmount(String(t.amount));
    // What a stored transfer says it moved is the reader's, not a proposal:
    // moving its date or its accounts does not rewrite it.
    setCurrencyChoice(t.currency);
    setToCurrencyChoice(t.to_currency);
    // A credit the reader typed comes back into the box; one worked out from a
    // rate does not, so that changing the date works it out again.
    setArrived(arrivalWasStated(t) ? String(t.to_amount) : "");
  }

  /* Each side proposes its account's currency on the date: the anchor in force
     then, or the account's first. The base only for an account with no anchor
     at all. An EXTERNAL side has no account to ask, and takes
     the other side's currency — a sum from or to outside is stated in the
     currency of the account it touches, and proposing any other would have
     the backend convert it on the way in. */
  const ownCurrency = (id: string) =>
    id ? (accountCurrencyOn(anchors, Number(id), date) ?? base) : null;
  const fromSide = currencyChoice ?? ownCurrency(fromId);
  const toSide = toCurrencyChoice ?? ownCurrency(toId);
  const currency = fromSide ?? toSide ?? base;
  const toCurrency = toSide ?? fromSide ?? base;

  // Two currencies, or a credit that differs from what left: the second sum
  // cannot be read off the first, so its box is shown. Two currencies as the
  // backend reads them: "eur" is EUR, and pence are pounds (brief BA).
  const acrossCurrencies = !sameCurrency(currency, toCurrency);
  const showArrived = acrossCurrencies || arrived !== "";

  async function submit(e: FormEvent) {
    e.preventDefault();
    const refused = refusal(TRANSFER, { date, amount, ends: fromId || toId, currency, toCurrency });
    if (refused) {
      setError(refused);
      return;
    }
    setSubmitting(true);
    setError(null);
    const payload = {
      date,
      from_institution_id: fromId ? Number(fromId) : null,
      to_institution_id: toId ? Number(toId) : null,
      amount: Number(amount),
      currency: currency.trim(),
      to_currency: toCurrency.trim(),
      // Only when the reader has it: otherwise the backend works it out and
      // records the rate's day.
      to_amount: showArrived && arrived !== "" ? Number(arrived) : null,
    };
    try {
      if (editId != null) await updateTransfer(editId, payload);
      else await createTransfer(payload);
      reset();
      await onChanged();
    } catch (err) {
      setError(apiError(err, "Save failed."));
    } finally {
      setSubmitting(false);
    }
  }

  async function remove(t: Transfer) {
    // With what it moves, in the words the chat's card says it with (brief
    // AP): each account's cash today and from which day.
    const question = await askBeforeDeleting(
      "Delete this transfer?",
      () => transferDeletion(t.id),
      (err) => apiError(err, "no answer came."),
    );
    if (!window.confirm(question)) return;
    setError(null);
    try {
      await deleteTransfer(t.id);
      if (editId === t.id) reset();
      await onChanged();
    } catch (err) {
      setError(apiError(err, "Delete failed."));
    }
  }

  return (
    <Section
      title="Transfers"
      hint="Move cash between two of your institutions on a date. It lowers the source's cash and raises the destination's. Between two currencies, what arrived is worked out at the rate of that date (the ECB's, or Yahoo's for a currency the ECB does not publish) unless you type it from the statement."
    >
      <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
        <DateField label="on" value={date} onChange={setDate} mark={marks(TRANSFER, "date")} />
        <InstitutionSelect value={fromId} onChange={setFromId} institutions={institutions} placeholder="from (or external)…" label="From" />
        <span className="text-ink-faint">→</span>
        <InstitutionSelect value={toId} onChange={setToId} institutions={institutions} placeholder="to (or external)…" label="To" />
        <input className={inputClass + " w-28"} type="number" step="0.01" aria-label="Amount" {...marks(TRANSFER, "amount")} value={amount} onChange={(e) => setAmount(e.target.value)} />
        <input
          className={inputClass + " w-20"}
          placeholder="currency"
          aria-label="Currency that left"
          list={CURRENCY_LIST}
          {...marks(TRANSFER, "currency")}
          value={currency}
          onChange={(e) => setCurrencyChoice(e.target.value)}
        />
        <span className="text-ink-faint">→</span>
        <input
          className={inputClass + " w-20"}
          placeholder="currency"
          aria-label="Currency that arrived"
          list={CURRENCY_LIST}
          {...marks(TRANSFER, "toCurrency")}
          value={toCurrency}
          onChange={(e) => setToCurrencyChoice(e.target.value)}
        />
        {showArrived && (
          <input
            className={inputClass + " w-40"}
            type="number"
            step="any"
            min="0"
            placeholder={`Arrived in ${toCurrency || "…"}`}
            aria-label="Amount that arrived"
            value={arrived}
            onChange={(e) => setArrived(e.target.value)}
          />
        )}
        <button className={btnClass} disabled={submitting}>{submitting ? "..." : editId != null ? "Save" : "Add"}</button>
        {editId != null && (
          <button type="button" onClick={reset} className="rounded-sm px-3 py-2 text-sm text-ink-soft hover:text-ink">
            Cancel
          </button>
        )}
      </form>
      {error && <p className="text-down">{error}</p>}
      <RowsOrEmpty loading={false} error={null} empty={items.length === 0} emptyText={EMPTY_LINES.transfers}>
        {items.map((t) => (
          <Row
            key={t.id}
            onEdit={() => startEdit(t)}
            onDelete={() => remove(t)}
            title={`${instName(t.from_institution_id) ?? "External"} → ${instName(t.to_institution_id) ?? "External"}`}
            subtitle={[
              t.date,
              // A credit fixed at one day's rate says which day, and whose
              // (brief BA), so it can be held against the statement.
              t.fx_as_of ? rateLine(t.fx_as_of, t.fx_source) : null,
            ]
              .filter(Boolean)
              .join(" · ")}
            note={t.note}
            value={
              sameSum(t)
                ? money(t.currency).format(t.amount)
                : `${money(t.currency).format(t.amount)} → ${money(t.to_currency).format(t.to_amount)}`
            }
          />
        ))}
      </RowsOrEmpty>
    </Section>
  );
}
