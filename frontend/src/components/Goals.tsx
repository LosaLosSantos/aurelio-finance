import { useEffect, useState, type FormEvent } from "react";
import { computeRequiredReturn, type GoalCreate, type RequiredReturnResult } from "../api/goals";
import { Row, btnClass, cardClass, inputClass, money, CURRENCY_LIST } from "./ui";
import { goal, marks, refusal } from "./required";
import { goalBody, shownAs, type GoalDraft } from "./goalDrafts";

const GOAL_TYPES: { value: string; label: string }[] = [
  { value: "protect_inflation", label: "Protect from inflation" },
  { value: "stable_income", label: "Stable / passive income" },
  { value: "long_term_growth", label: "Long-term growth" },
  { value: "emergency_fund", label: "Emergency fund" },
  { value: "target_amount", label: "Target amount by a date" },
  { value: "other", label: "Something else (describe it)" },
];

function typeLabel(value: string | null | undefined): string | null {
  return GOAL_TYPES.find((t) => t.value === value)?.label ?? value ?? null;
}

/* The path's third part: the goals, held with the rest of the profile until
   "Save profile" (brief BC, `goalDrafts.ts`). The form adds a goal to the
   list or changes one; a row the save has still to write says "not saved",
   and a deleted one waits under the list with a way back, as the other
   answers do. The Profile holds the list and writes it; this part holds the
   form.

   A new goal's currency is proposed from the base currency picked in the
   first part, as shown there: it used to be the base read when this block
   loaded, so a base changed and saved on the same page left the goal
   proposing the old one until a reload (measured, brief BC). What the reader
   types in the box wins, and an edited goal keeps its own. */
export default function Goals({
  drafts,
  base,
  onAdd,
  onChange,
  onRemove,
  onKeep,
  emptyText,
}: {
  drafts: GoalDraft[];
  /** The base currency picked in the first part. */
  base: string;
  onAdd: (now: GoalCreate) => void;
  /** The goal `ref` names changed: a ref, not a place in the list, which a
      save made while the form is open can reorder. */
  onChange: (ref: string, now: GoalCreate) => void;
  onRemove: (at: number) => void;
  onKeep: (at: number) => void;
  emptyText: string;
}) {
  const [editRef, setEditRef] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [type, setType] = useState("");
  const [targetAmount, setTargetAmount] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [currentAmount, setCurrentAmount] = useState("");
  const [monthly, setMonthly] = useState("");
  const [currencyChoice, setCurrencyChoice] = useState<string | null>(null);
  const currency = currencyChoice ?? base;
  const [error, setError] = useState<string | null>(null);
  const [rr, setRr] = useState<RequiredReturnResult | null>(null);

  useEffect(() => {
    if (type !== "target_amount" || !targetAmount || !targetDate) {
      setRr(null);
      return;
    }
    let cancelled = false;
    computeRequiredReturn({
      current_amount: Number(currentAmount) || 0,
      monthly_contribution: Number(monthly) || 0,
      target_amount: Number(targetAmount),
      target_date: targetDate,
    })
      .then((res) => !cancelled && setRr(res))
      .catch(() => !cancelled && setRr(null));
    return () => {
      cancelled = true;
    };
  }, [type, targetAmount, targetDate, currentAmount, monthly]);

  const isTarget = type === "target_amount";

  function reset() {
    setEditRef(null);
    setName("");
    setType("");
    setTargetAmount("");
    setTargetDate("");
    setCurrentAmount("");
    setMonthly("");
    setCurrencyChoice(null);
    setError(null);
  }

  function startEdit(at: number) {
    const g = shownAs(drafts[at]);
    setEditRef(drafts[at].ref);
    setError(null);
    setName(g.name);
    setType(g.type ?? "");
    setTargetAmount(g.target_amount != null ? String(g.target_amount) : "");
    setTargetDate(g.target_date ?? "");
    setCurrentAmount(g.current_amount != null ? String(g.current_amount) : "");
    setMonthly(g.monthly_contribution != null ? String(g.monthly_contribution) : "");
    setCurrencyChoice(g.currency);
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    // The dropdown carries the meaning; a free label like "get rich" adds
    // nothing, so it is optional, except for "other", where it IS the goal.
    const refused = refusal(goal(type), { type, name, currency });
    if (refused) {
      setError(refused);
      return;
    }
    const now = goalBody(
      { name, type, currency, targetAmount, targetDate, currentAmount, monthly },
      typeLabel(type),
    );
    if (editRef != null) onChange(editRef, now);
    else onAdd(now);
    reset();
  }

  function goalSubtitle(g: GoalCreate): string | undefined {
    if (g.type === "target_amount" && g.target_amount && g.target_date) {
      return `target ${money(g.currency).format(g.target_amount)} by ${g.target_date}`;
    }
    return undefined;
  }

  const listed = drafts.map((d, at) => ({ d, at })).filter(({ d }) => d.kind !== "deleted");
  const deleted = drafts.map((d, at) => ({ d, at })).filter(({ d }) => d.kind === "deleted");

  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="space-y-3">
        <div className="flex flex-wrap gap-2">
          <select className={inputClass} aria-label="What the goal is for" {...marks(goal(type), "type")} value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">what is this goal for?…</option>
            {GOAL_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
          <input
            className={inputClass + " min-w-64 flex-1"}
            placeholder="Detail (optional), e.g. flat in Milan"
            aria-label={type === "other" ? "What the goal is" : "Detail"}
            {...marks(goal(type), "name")}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>

        {isTarget && (
          <div className="flex flex-wrap items-center gap-2">
            <input className={inputClass + " w-36"} type="number" step="0.01" placeholder="Target" aria-label="Target" value={targetAmount} onChange={(e) => setTargetAmount(e.target.value)} />
            <input className={inputClass} type="date" aria-label="Target date" value={targetDate} onChange={(e) => setTargetDate(e.target.value)} />
            <input className={inputClass + " w-36"} type="number" step="0.01" placeholder="Current" aria-label="What you have now" value={currentAmount} onChange={(e) => setCurrentAmount(e.target.value)} />
            <input className={inputClass + " w-40"} type="number" step="0.01" placeholder="Monthly contribution" aria-label="Monthly contribution" value={monthly} onChange={(e) => setMonthly(e.target.value)} />
            <input
              className={inputClass + " w-20"}
              placeholder="currency"
              aria-label="Currency"
              {...marks(goal(type), "currency")}
              list={CURRENCY_LIST}
              value={currency}
              onChange={(e) => setCurrencyChoice(e.target.value)}
            />
          </div>
        )}

        {rr && <RequiredReturnNote rr={rr} />}

        <div className="flex items-center gap-2">
          <button className={btnClass}>{editRef != null ? "Change goal" : "Add goal"}</button>
          {editRef != null && (
            <button type="button" onClick={reset} className="rounded-sm px-3 py-2 text-sm text-ink-soft hover:text-ink">
              Cancel
            </button>
          )}
        </div>
      </form>

      {error && <p className="text-down">{error}</p>}

      {listed.length === 0 ? (
        <p className="text-ink-soft">{emptyText}</p>
      ) : (
        <ul className={cardClass + " divide-y divide-hair overflow-hidden"}>
          {listed.map(({ d, at }) => {
            const g = shownAs(d);
            return (
              <Row
                key={d.ref}
                onEdit={() => startEdit(at)}
                onDelete={() => {
                  if (editRef === d.ref) reset();
                  onRemove(at);
                }}
                // The goal's own name says what the row is, so it is the title,
                // which wraps and is never cut; the kind of goal goes under it. At
                // 390 a name kept in the attributes line was cut ("A sabbatical
                // year walking the Camino", 171 of 197px; brief AU).
                title={g.name}
                subtitle={[g.name !== typeLabel(g.type) ? typeLabel(g.type) : null, goalSubtitle(g)]
                  .filter(Boolean)
                  .join(" · ") || undefined}
                badge={d.kind === "kept" ? undefined : "not saved"}
                detail={d.kind !== "kept" && d.error ? `Refused at the last save: ${d.error}` : undefined}
                note={d.kind === "kept" || d.kind === "changed" ? d.goal.notes : undefined}
                value={g.type === "target_amount" && g.target_amount ? money(g.currency).format(g.target_amount) : undefined}
              />
            );
          })}
        </ul>
      )}

      {deleted.length > 0 && (
        <div className="text-xs text-warn">
          <p id="goals-deleted">Deleted when you save:</p>
          <ul aria-labelledby="goals-deleted" className="mt-1 space-y-1">
            {deleted.map(({ d, at }) => (
              <li key={d.ref}>
                {shownAs(d).name}{" "}
                <button type="button" onClick={() => onKeep(at)} className="text-olive underline-offset-2 hover:underline">
                  Keep it
                </button>
                {d.kind === "deleted" && d.error && <span className="block text-down">Refused at the last save: {d.error}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function RequiredReturnNote({ rr }: { rr: RequiredReturnResult }) {
  const r = rr.required_annual_return;
  const tone =
    r === null || r > 0.12
      ? "bg-down-tint text-down"
      : r > 0.08
        ? "bg-warn-tint text-warn"
        : "bg-up-tint text-up";
  const rate = r === null ? "unreachable" : `${(r * 100).toFixed(1)}%/yr`;
  return (
    <p className={"rounded-sm p-3 text-sm " + tone}>
      Over ~{rr.years} years this requires a return of <strong>{rate}</strong>. {rr.assessment}
    </p>
  );
}
