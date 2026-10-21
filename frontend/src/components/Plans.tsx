/* The PAC: a plan that buys the same funds on a schedule (brief BD).

   It was set in Records, Cash flow, the one section there whose figures that
   page does not count, and the only one that buys securities. It is set and
   changed here now, on Portfolio, beside the ledger its buys are written to
   (the reader's choice, D1). Cash flow keeps the plans listed, read only,
   with the way here (`PlanList`), since that is where the reader has always
   looked for them.

   `PlanSection` is the section as it was in CashFlow.tsx, with the same
   requests and the same answers; its two line helpers are lifted out of it
   so the list says the same words. */

import { useState, type FormEvent } from "react";
import {
  createAccumulationPlan,
  deleteAccumulationPlan,
  updateAccumulationPlan,
  type AccumulationPlan,
} from "../api/accumulationPlans";
import type { Institution } from "../api/institutions";
import type { CashAnchor } from "../api/cash";
import type { PortfolioRow } from "../api/portfolio";
import { accountCurrencyOn } from "./proposedCurrency";
import { InstrumentPicker, type InstrumentChoice } from "./InstrumentPicker";
import { DateField, InstitutionSelect } from "./recordFields";
import { dateRange, subtitle } from "./rowLine";
import { EMPTY_LINES } from "./emptyStates";
import { PLAN, marks, refusal } from "./required";
import { PLAN_DATE_LABEL, PLAN_NOTE, afterSaveLine, pastBuys, pastBuysWarning, startsLine } from "./firstDate";
import {
  Row,
  RowsOrEmpty,
  Section,
  apiError,
  btnClass,
  inputClass,
  money,
  todayISO,
  CURRENCY_LIST,
} from "./ui";

const PAC_FREQUENCIES = ["monthly", "quarterly", "semiannual", "annual"];

type TargetDraft = {
  key: number;
  symbol: string;
  name: string;
  isin: string;
  institutionId: string;
  weight: string;
};

let targetKey = 0;
/** `institutionId` is a parameter because a new target row added to a plan
    that already names its source starts AT that source: visibly, in the
    field, not as a fallback applied on the way out. See `pickSource`. */
const emptyTarget = (institutionId = ""): TargetDraft => ({
  key: ++targetKey,
  symbol: "",
  name: "",
  isin: "",
  institutionId,
  weight: "1",
});

/** A plan just saved from its next date, and the accounts it touches, where
    today's situation and cash are recorded. */
export type PlanSaved = { name: string; start: string; accounts: Institution[] };

function planSubtitle(
  p: AccumulationPlan,
  instName: (id: number | null) => string | undefined,
): string | undefined {
  const total = p.targets.reduce((s, t) => s + (t.weight > 0 ? t.weight : 0), 0) || 1;
  // Show the normalised share, not what was typed: someone who wrote 3 and 2
  // meant 60/40, and 60/40 is what the plan will actually buy.
  const tgt = p.targets.length
    ? p.targets
        .map((t) =>
          p.targets.length > 1
            ? `${t.asset_name || t.symbol} ${Math.round((t.weight / total) * 100)}%`
            : t.asset_name || t.symbol,
        )
        .join(" + ")
    : "nothing yet";
  const insts = [...new Set(p.targets.map((t) => instName(t.institution_id)).filter(Boolean))];
  return subtitle([
    `from ${instName(p.source_institution_id) ?? "cash"} → ${tgt}`,
    insts.join(", ") || undefined,
    dateRange(p.start_date, p.end_date),
  ]);
}

/** Money set aside and not yet invested is the saver's fact, not the
    scheduler's bookkeeping, so it gets the line that does not truncate,
    and cents, which the whole-unit format would round away to "0 €" on a remainder that is
    smaller than one unit by construction. It is a running balance rather
    than one occurrence's change, hence "set aside", not "left over last
    time". Silent when there is nothing waiting.

    A finished plan gets the other sentence, because nothing ever clears the
    remainder when the schedule runs out: promising it to "the next
    contribution" would be promising one that is never coming. */
function planDetail(p: AccumulationPlan): string | undefined {
  if (!p.carried_remainder) return undefined;
  const amount = money(p.currency, "cents").format(p.carried_remainder);
  const ended = p.end_date != null && p.end_date < todayISO();
  return ended
    ? `${amount} set aside and never invested: this plan has ended`
    : `${amount} set aside, waiting for the next contribution`;
}

export function PlanSection({
  items,
  institutions,
  anchors,
  base,
  positions,
  instName,
  onChanged,
  onOpenAccount,
  saved,
  onSaved,
}: {
  items: AccumulationPlan[];
  institutions: Institution[];
  /** Every account's cash anchors: the plan's currency is proposed from its
      source account's. */
  anchors: CashAnchor[];
  /** The base: what a plan funded by an account with no anchor is proposed in. */
  base: string;
  positions: PortfolioRow[];
  instName: (id: number | null) => string | undefined;
  onChanged: () => Promise<void> | void;
  /** See `CashFlow`'s prop of the same name. */
  onOpenAccount: (i: Institution) => void;
  /** The plan just saved from its next date, until the next save or edit. */
  saved: PlanSaved | null;
  onSaved: (s: PlanSaved | null) => void;
}) {
  const [editId, setEditId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  // What the contribution is paid in: the source account's cash. The reader's
  // choice once they typed one (null until then); see `currency` below for the
  // proposal. The funds it buys are priced in their own listings' currencies,
  // converted at each close.
  const [currencyChoice, setCurrencyChoice] = useState<string | null>(null);
  const [frequency, setFrequency] = useState("monthly");
  const [execution, setExecution] = useState("whole_units");
  const [sourceId, setSourceId] = useState("");
  const [targets, setTargets] = useState<TargetDraft[]>([emptyTarget()]);
  const [startDate, setStartDate] = useState(todayISO());
  const [endDate, setEndDate] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The next date the one press put in the date box, while the box still
  // holds it: the form then says what is left to do. A date typed over it
  // takes that back.
  const [pressed, setPressed] = useState<string | null>(null);

  // Proposed from the source account on the start date (its anchor in force
  // then, or its first), and the base only for an account with no
  // anchor. A plan funded by a dollar account used to be saved as a euro plan,
  // with no box on the form to say so.
  const currency =
    currencyChoice ??
    accountCurrencyOn(anchors, sourceId ? Number(sourceId) : null, startDate || todayISO()) ??
    base;

  function reset() {
    setEditId(null);
    setName("");
    setAmount("");
    setCurrencyChoice(null);
    setFrequency("monthly");
    setExecution("whole_units");
    setSourceId("");
    setTargets([emptyTarget()]);
    setStartDate(todayISO());
    setEndDate("");
    setPressed(null);
  }

  function startEdit(p: AccumulationPlan) {
    setPressed(null);
    onSaved(null);
    setEditId(p.id);
    setName(p.name);
    setAmount(String(p.amount));
    // A stored plan's currency is what it says, not a proposal.
    setCurrencyChoice(p.currency);
    setFrequency(p.frequency ?? "monthly");
    setExecution(p.execution ?? "whole_units");
    setSourceId(p.source_institution_id ? String(p.source_institution_id) : "");
    setTargets(
      p.targets.length
        ? p.targets.map((t) => ({
            key: ++targetKey,
            symbol: t.symbol,
            name: t.asset_name ?? "",
            isin: t.isin ?? "",
            institutionId: t.institution_id ? String(t.institution_id) : "",
            weight: String(t.weight),
          }))
        : [emptyTarget()],
    );
    setStartDate(p.start_date ?? "");
    setEndDate(p.end_date ?? "");
  }

  function patchTarget(key: number, patch: Partial<TargetDraft>) {
    setTargets((ts) => ts.map((t) => (t.key === key ? { ...t, ...patch } : t)));
  }

  /* Most people buy where the cash is, so naming the source answers the second
     question too, and the whole difference between help and a trap is WHERE
     the answer lands.

     It is written into the target's own field, so the select reads "Broker A"
     instead of "Where is it held?" and the reader is looking at the answer
     they are about to save. A fallback applied at submit time would show a
     blank field and send an institution, which on a field this load-bearing is
     how a wrong one gets saved without anybody choosing it.

     Only targets that have not answered yet. A target the reader picked from
     the "you already hold this" lane carries the institution it is ACTUALLY
     held at (`applyPick`), and that is a fact about a real position, not a
     guess: changing the source must not overwrite it.

     Nothing is seeded on LOAD. A saved plan whose target names no institution
     opens with that field blank, exactly as it was stored, because writing a
     value into a form the reader has not touched is how they save something
     they never chose. Naming the source afterwards does seed it: that is a
     deliberate act, and the seeded name is on screen in front of them when
     they press Save. Load and act are different things. */
  function pickSource(v: string) {
    setSourceId(v);
    if (!v) return;
    setTargets((ts) => ts.map((t) => (t.institutionId ? t : { ...t, institutionId: v })));
  }

  // A plan that points at a position you already hold is the normal case, and
  // getting the ticker wrong is not cosmetic: executions are matched to
  // positions by (institution, symbol), so a mistyped ticker silently starts a
  // SECOND position for the same fund instead of adding to the one you have.
  const owned = positions.filter((p) => p.symbol);
  const ownedForPicker = owned.map((p) => ({
    symbol: p.symbol ?? "",
    name: p.asset_name,
    institution: p.institution,
  }));
  const matchOf = (symbol: string) =>
    owned.find((p) => (p.symbol ?? "").toUpperCase() === symbol.trim().toUpperCase());

  // One pick, three sources. The catalogue gives an identity and no ticker;
  // the other two give a ticker. Only the owned lane can also say WHERE the
  // position is held, and filling that is not a nicety: executions are matched
  // by (institution, symbol), so a target with the right ticker at the wrong
  // institution starts a second position just as surely as a typo would.
  function applyPick(key: number, c: InstrumentChoice) {
    if (c.source === "catalogue") {
      patchTarget(key, { name: c.name, isin: c.isin });
      return;
    }
    const patch: Partial<TargetDraft> = { name: c.name, symbol: c.symbol };
    if (c.source === "owned") {
      const inst = institutions.find((i) => i.name === c.institution);
      if (inst) patch.institutionId = String(inst.id);
    }
    patchTarget(key, patch);
  }

  const filled = targets.filter((t) => t.symbol.trim());
  const weightTotal = filled.reduce((sum, t) => sum + (Number(t.weight) || 0), 0);
  const unknown = filled.filter((t) => !matchOf(t.symbol));
  const share = (t: TargetDraft) =>
    weightTotal > 0 ? Math.round(((Number(t.weight) || 0) / weightTotal) * 100) : 0;

  const homeless = filled.filter((t) => !t.institutionId);

  // What this save would write before today, said before it is pressed. An
  // edit starts from the plan as stored, whose own months are not new.
  const stored = editId != null ? (items.find((p) => p.id === editId) ?? null) : null;
  const past = pastBuys(
    { start: startDate, frequency, end: endDate || null },
    stored?.start_date ? { start: stored.start_date, frequency: stored.frequency, end: stored.end_date } : null,
    todayISO(),
  );
  const warning = past ? pastBuysWarning(past, startDate) : null;
  const next = past?.next ?? null;

  /** The accounts a plan touches, the source first: one link each after it is
      saved from its next date. */
  function touched(): Institution[] {
    const ids = [...new Set([sourceId, ...filled.map((t) => t.institutionId)].filter(Boolean))];
    return ids.flatMap((id) => institutions.filter((i) => String(i.id) === id));
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const refused = refusal(PLAN, { name, amount, ticker: filled.length > 0 ? "yes" : "", sourceId });
    if (refused) {
      setError(refused);
      return;
    }
    /* Both ends of one sentence: money moves FROM an account INTO a holding,
       and a plan that names neither is describing a purchase nobody made.

       With both blank the plan's spending added itself to the net worth:
       every buy it writes gets `cash_institution_id` from the source, so with
       no source both institution columns are null, the cash register skips a
       row that matches no institution there is, and the position it created
       counts in full. Measured at 1000.00 of cash: two contributions of 100.00
       read 1200.00, with the cash still 1000.00.

       The two are said separately because they fail differently. A missing
       source moves a total. A missing target institution does not: it makes a
       position no situation can photograph and no sale can settle, which is a
       different wrong.

       Last, after the fields the form already required, so the sentence
       arrives when the institution is the one thing left. Both halves are
       needed: the placeholder is `disabled`, so blank cannot be chosen BACK,
       and this catches the two ways it can still be blank here: a form nobody
       has touched, and a plan loaded for editing that was saved without one.
       Validation on its own would leave a pickable option that writes a null;
       a disabled option on its own would let both of those through. */
    // The source's sentence is PLAN's, in required.ts: said by the check
    // above once the plain fields are in.
    if (homeless.length > 0) {
      setError(
        `Say where ${homeless.map((t) => t.symbol.trim().toUpperCase() || "it").join(", ")} will be held. A position held nowhere is one no situation can photograph and no sale can settle.`,
      );
      return;
    }
    setSubmitting(true);
    setError(null);
    const payload = {
      name: name.trim(),
      amount: Number(amount),
      currency,
      frequency: frequency || null,
      execution: execution || null,
      source_institution_id: Number(sourceId),
      start_date: startDate || null,
      end_date: endDate || null,
      targets: filled.map((t) => ({
        symbol: t.symbol.trim(),
        isin: t.isin.trim().toUpperCase() || null,
        asset_name: t.name.trim() || null,
        institution_id: Number(t.institutionId),
        weight: Number(t.weight) > 0 ? Number(t.weight) : 1,
      })),
    };
    onSaved(null);
    try {
      if (editId != null) await updateAccumulationPlan(editId, payload);
      else await createAccumulationPlan(payload);
      // Saved from the one press: what is left of the better way is the
      // broker's numbers for today, on the pages of the accounts it touches.
      if (pressed !== null && pressed === startDate) {
        onSaved({ name: payload.name, start: startDate, accounts: touched() });
      }
      reset();
      await onChanged();
    } catch (err) {
      setError(apiError(err, "Save failed."));
    } finally {
      setSubmitting(false);
    }
  }

  async function remove(p: AccumulationPlan) {
    if (!window.confirm(`Delete plan "${p.name}"?`)) return;
    setError(null);
    try {
      await deleteAccumulationPlan(p.id);
      if (editId === p.id) reset();
      await onChanged();
    } catch (err) {
      setError(apiError(err, "Delete failed."));
    }
  }

  return (
    <Section
      title="PAC"
      hint="Recurring buys: how much moves, into what, how often."
      note={PLAN_NOTE}
      explain={{
        question: "How does a PAC work?",
        text: "A plan names both ends (the account each contribution leaves, and where each investment is held), because money moves from one to the other and a plan that says neither is describing a purchase nobody made. Where each investment is held starts as the account funding the plan: change it if you buy that one somewhere else. With several targets the budget is spent as one pot, so a whole-unit broker leaves one small remainder instead of one per fund, and it carries to the next contribution. Whole units: the broker buys only whole units and the remainder stays in cash; fractional: it spends the contribution to the cent. Check which one yours does: it changes what a contribution buys. The budget's currency is proposed from the funding account's cash on the first buy's date; what you type stays. A ticker takes its exchange's suffix (VWCE.MI), and a listing in another currency is bought at its close converted into the plan's currency, at the rate of that day: the ECB's, or Yahoo's for a currency the ECB does not publish.",
      }}
    >
      <form onSubmit={submit} className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <input className={inputClass} aria-label="Plan name" {...marks(PLAN, "name")} value={name} onChange={(e) => setName(e.target.value)} />
          <input className={inputClass + " w-28"} type="number" step="0.01" aria-label="Budget" {...marks(PLAN, "amount")} value={amount} onChange={(e) => setAmount(e.target.value)} />
          <input
            className={inputClass + " w-20"}
            placeholder="currency"
            aria-label="Currency"
            list={CURRENCY_LIST}
            value={currency}
            onChange={(e) => setCurrencyChoice(e.target.value)}
          />
          <select className={inputClass} aria-label="Frequency" value={frequency} onChange={(e) => setFrequency(e.target.value)}>
            {PAC_FREQUENCIES.map((f) => (<option key={f} value={f}>{f}</option>))}
          </select>
          <select
            className={inputClass}
            value={execution}
            onChange={(e) => setExecution(e.target.value)}
            aria-label="How your broker fills the order"
          >
            <option value="whole_units">whole units</option>
            <option value="fractional">fractional</option>
          </select>
          <InstitutionSelect
            value={sourceId}
            onChange={pickSource}
            institutions={institutions}
            placeholder="Which account funds it?"
            required
            label="Account it is funded from"
          />
          <DateField label={PLAN_DATE_LABEL} value={startDate} onChange={setStartDate} />
          <DateField label="end" value={endDate} onChange={setEndDate} />
        </div>

        {/* In view, under the date that causes it: a consequence, which a "?"
            never holds, said before Add is pressed. */}
        {warning ? (
          <div className="space-y-2 border-l-2 border-warn bg-warn-tint px-3 py-2 text-xs text-warn">
            <p className="max-w-[76ch]">
              <b>{warning.lead}</b> {warning.body}
            </p>
            {warning.alternative && next && (
              <div className="flex flex-wrap items-center gap-3">
                <p className="max-w-[68ch]">{warning.alternative}</p>
                <button
                  type="button"
                  onClick={() => {
                    setStartDate(next);
                    setPressed(next);
                  }}
                  className="rounded-sm border border-olive px-3 py-1 text-xs font-medium text-olive transition hover:bg-surface"
                >
                  {warning.button}
                </button>
              </div>
            )}
          </div>
        ) : (
          pressed !== null && pressed === startDate && <p className="text-xs text-ink-soft">{startsLine(pressed)}</p>
        )}

        <div className="flex flex-col gap-2 border-l-2 border-rule pl-3">
          {targets.map((t, i) => (
            <div key={t.key} className="flex flex-wrap items-center gap-2">
              <span className="w-4 text-xs tabular-nums text-ink-faint">{i + 1}</span>
              <InstrumentPicker
                value={t.name}
                onChange={(v) => patchTarget(t.key, { name: v })}
                owned={ownedForPicker}
                placeholder="Buy what? Type to search"
                onPick={(c) => applyPick(t.key, c)}
              />
              <input className={inputClass + " w-32"} aria-label="Ticker" placeholder="Ticker" {...(i === 0 ? marks(PLAN, "ticker") : {})} value={t.symbol} onChange={(e) => patchTarget(t.key, { symbol: e.target.value })} />
              <input className={inputClass + " w-36"} placeholder="ISIN (optional)" aria-label="ISIN" value={t.isin} onChange={(e) => patchTarget(t.key, { isin: e.target.value })} />
              <InstitutionSelect
                value={t.institutionId}
                onChange={(v) => patchTarget(t.key, { institutionId: v })}
                institutions={institutions}
                placeholder="Where is it held?"
                required
                label="Where it is held"
              />
              <input
                className={inputClass + " w-20"}
                type="number"
                step="0.1"
                min="0"
                placeholder="share"
                aria-label="Share of the budget"
                value={t.weight}
                onChange={(e) => patchTarget(t.key, { weight: e.target.value })}
              />
              <span className="w-11 text-right text-xs tabular-nums text-ink-soft">
                {t.symbol.trim() && weightTotal > 0 ? `${share(t)}%` : ""}
              </span>
              {targets.length > 1 && (
                <button
                  type="button"
                  onClick={() => setTargets((ts) => ts.filter((x) => x.key !== t.key))}
                  className="rounded-sm px-2 py-1 text-sm text-ink-faint hover:text-down"
                  aria-label="Remove this target"
                >
                  ×
                </button>
              )}
            </div>
          ))}
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => setTargets((ts) => [...ts, emptyTarget(sourceId)])}
              className="rounded-sm text-sm text-olive hover:underline"
            >
              + add another investment
            </button>
            {filled.length > 1 && amount && (
              <span className="text-xs text-ink-faint">
                {money(currency).format(Number(amount))} split {filled.map((t) => `${share(t)}%`).join(" / ")}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button className={btnClass} disabled={submitting}>
            {submitting ? "..." : editId != null ? "Save" : "Add"}
          </button>
          {editId != null && (
            <button type="button" onClick={reset} className="rounded-sm px-3 py-2 text-sm text-ink-soft hover:text-ink">
              Cancel
            </button>
          )}
        </div>
      </form>
      {error && <p className="text-down">{error}</p>}
      {saved && (
        <p className="text-sm text-ink-soft">
          {afterSaveLine(saved.name, saved.start)}{" "}
          {saved.accounts.map((i, n) => (
            <span key={i.id}>
              {n > 0 && " · "}
              <button type="button" onClick={() => onOpenAccount(i)} className="text-olive underline-offset-2 hover:underline">
                Open {i.name}
              </button>
            </span>
          ))}
        </p>
      )}
      {unknown.length > 0 && (
        <p className="border-l-2 border-warn bg-warn-tint px-3 py-2 text-xs text-warn">
          <b>{unknown.map((t) => t.symbol.trim().toUpperCase()).join(", ")}</b> matches no
          position you hold: fine for a new plan, but a typo starts a second position
          instead of adding to yours.
        </p>
      )}
      <RowsOrEmpty loading={false} error={null} empty={items.length === 0} emptyText={EMPTY_LINES.pac}>
        {items.map((p) => (
          <Row
            key={p.id}
            onEdit={() => startEdit(p)}
            onDelete={() => remove(p)}
            title={p.name}
            badge={p.frequency}
            subtitle={planSubtitle(p, instName)}
            detail={planDetail(p)}
            note={p.notes}
            value={money(p.currency).format(p.amount)}
          />
        ))}
      </RowsOrEmpty>
    </Section>
  );
}


/** What Cash flow says of the plans: each one as the PAC lists it, that it is
    set and changed in Portfolio, and that the page's monthly figures do not
    count it; with the way there, which lands on the PAC. */
export function PlanList({
  items,
  instName,
  onOpen,
}: {
  items: AccumulationPlan[];
  instName: (id: number | null) => string | undefined;
  onOpen: () => void;
}) {
  return (
    <Section
      title="PAC"
      hint="Your recurring buys. Each plan is set and changed in Portfolio, beside the ledger its buys go to; the monthly figures above do not count them."
    >
      <RowsOrEmpty loading={false} error={null} empty={items.length === 0} emptyText={EMPTY_LINES.pacListed}>
        {items.map((p) => (
          <Row
            key={p.id}
            title={p.name}
            badge={p.frequency}
            subtitle={planSubtitle(p, instName)}
            detail={planDetail(p)}
            note={p.notes}
            value={money(p.currency).format(p.amount)}
          />
        ))}
      </RowsOrEmpty>
      <button type="button" onClick={onOpen} className="text-sm text-olive underline-offset-2 hover:underline">
        Open the PAC in Portfolio
      </button>
    </Section>
  );
}
