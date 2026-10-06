import { useEffect, useState, type FormEvent } from "react";
import {
  computeRequiredReturn,
  createGoal,
  deleteGoal,
  getGoals,
  updateGoal,
  type Goal,
  type RequiredReturnResult,
} from "../api/goals";
import { getBaseCurrency } from "../api/baseCurrency";
import {
  Row,
  RowsOrEmpty,
  Section,
  apiError,
  btnClass,
  inputClass,
  money,
  CURRENCY_LIST,
} from "./ui";
import { goal, marks, refusal } from "./required";

const GOAL_TYPES: { value: string; label: string }[] = [
  { value: "protect_inflation", label: "Protect from inflation" },
  { value: "stable_income", label: "Stable / passive income" },
  { value: "long_term_growth", label: "Long-term growth" },
  { value: "emergency_fund", label: "Emergency fund" },
  { value: "target_amount", label: "Target amount by a date" },
  { value: "other", label: "Something else (describe it)" },
];

function typeLabel(value: string | null): string | null {
  return GOAL_TYPES.find((t) => t.value === value)?.label ?? value;
}

export default function Goals() {
  const [items, setItems] = useState<Goal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [editId, setEditId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [type, setType] = useState("");
  const [targetAmount, setTargetAmount] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [currentAmount, setCurrentAmount] = useState("");
  const [monthly, setMonthly] = useState("");
  /* A goal belongs to no account: its currency is proposed from the base the
     reader chose, and what they type in the box wins. An edited goal keeps its
     own. */
  const [base, setBase] = useState("");
  const [currencyChoice, setCurrencyChoice] = useState<string | null>(null);
  const currency = currencyChoice ?? base;
  const [submitting, setSubmitting] = useState(false);

  const [rr, setRr] = useState<RequiredReturnResult | null>(null);

  useEffect(() => {
    void load();
  }, []);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [goals, b] = await Promise.all([getGoals(), getBaseCurrency()]);
      setItems(goals);
      setBase(b.base_currency);
    } catch (err) {
      setError(apiError(err, "Could not reach the backend. Is it running on :8000?"));
    } finally {
      setLoading(false);
    }
  }

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
    setEditId(null);
    setName("");
    setType("");
    setTargetAmount("");
    setTargetDate("");
    setCurrentAmount("");
    setMonthly("");
    setCurrencyChoice(null);
  }

  function startEdit(g: Goal) {
    setEditId(g.id);
    setName(g.name);
    setType(g.type ?? "");
    setTargetAmount(g.target_amount != null ? String(g.target_amount) : "");
    setTargetDate(g.target_date ?? "");
    setCurrentAmount(g.current_amount != null ? String(g.current_amount) : "");
    setMonthly(g.monthly_contribution != null ? String(g.monthly_contribution) : "");
    setCurrencyChoice(g.currency);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    // The dropdown carries the meaning; a free label like "get rich" adds
    // nothing, so it is optional — except for "other", where it IS the goal.
    const refused = refusal(goal(type), { type, name, currency });
    if (refused) {
      setError(refused);
      return;
    }
    setSubmitting(true);
    setError(null);
    const payload = {
      name: name.trim() || (typeLabel(type) ?? type),
      type,
      currency: currency.trim(),
      target_amount: isTarget && targetAmount ? Number(targetAmount) : null,
      target_date: isTarget && targetDate ? targetDate : null,
      current_amount: isTarget && currentAmount ? Number(currentAmount) : null,
      monthly_contribution: isTarget && monthly ? Number(monthly) : null,
    };
    try {
      if (editId != null) await updateGoal(editId, payload);
      else await createGoal(payload);
      reset();
      await load();
    } catch (err) {
      setError(apiError(err, "Save failed."));
    } finally {
      setSubmitting(false);
    }
  }

  async function remove(g: Goal) {
    if (!window.confirm(`Delete goal "${g.name}"?`)) return;
    setError(null);
    try {
      await deleteGoal(g.id);
      if (editId === g.id) reset();
      await load();
    } catch (err) {
      setError(apiError(err, "Delete failed."));
    }
  }

  function goalSubtitle(g: Goal): string | undefined {
    if (g.type === "target_amount" && g.target_amount && g.target_date) {
      return `target ${money(g.currency).format(g.target_amount)} by ${g.target_date}`;
    }
    return undefined;
  }

  if (loading) return <p className="text-ink-soft">Loading…</p>;

  return (
    <Section
      title="Goals"
      hint="Pick a safe goal type, or set a concrete target (amount + date) to see the annual return it would require."
    >
      <form onSubmit={submit} className="space-y-3">
        <div className="flex flex-wrap gap-2">
          <select className={inputClass} {...marks(goal(type), "type")} value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">what is this goal for?…</option>
            {GOAL_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
          <input
            className={inputClass + " min-w-64 flex-1"}
            placeholder="Detail (optional), e.g. flat in Milan"
            {...marks(goal(type), "name")}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>

        {isTarget && (
          <div className="flex flex-wrap items-center gap-2">
            <input className={inputClass + " w-36"} type="number" step="0.01" placeholder="Target" value={targetAmount} onChange={(e) => setTargetAmount(e.target.value)} />
            <input className={inputClass} type="date" value={targetDate} onChange={(e) => setTargetDate(e.target.value)} />
            <input className={inputClass + " w-36"} type="number" step="0.01" placeholder="Current" value={currentAmount} onChange={(e) => setCurrentAmount(e.target.value)} />
            <input className={inputClass + " w-40"} type="number" step="0.01" placeholder="Monthly contribution" value={monthly} onChange={(e) => setMonthly(e.target.value)} />
            <input
              className={inputClass + " w-20"}
              placeholder="currency"
              {...marks(goal(type), "currency")}
              list={CURRENCY_LIST}
              title="The currency the target, what you have and the contribution are in. Proposed from your base currency; change it and it stays as you typed it."
              value={currency}
              onChange={(e) => setCurrencyChoice(e.target.value)}
            />
          </div>
        )}

        {rr && <RequiredReturnNote rr={rr} />}

        <div className="flex items-center gap-2">
          <button className={btnClass} disabled={submitting}>{submitting ? "..." : editId != null ? "Save goal" : "Add goal"}</button>
          {editId != null && (
            <button type="button" onClick={reset} className="rounded-sm px-3 py-2 text-sm text-ink-soft hover:text-ink">
              Cancel
            </button>
          )}
        </div>
      </form>

      {error && <p className="text-down">{error}</p>}

      <RowsOrEmpty loading={false} error={null} empty={items.length === 0} emptyText="No goals yet.">
        {items.map((g) => (
          <Row
            key={g.id}
            onEdit={() => startEdit(g)}
            onDelete={() => remove(g)}
            title={typeLabel(g.type) ?? g.name}
            subtitle={[g.name !== typeLabel(g.type) ? g.name : null, goalSubtitle(g)]
              .filter(Boolean)
              .join(" · ") || undefined}
            note={g.notes}
            value={g.type === "target_amount" && g.target_amount ? money(g.currency).format(g.target_amount) : undefined}
          />
        ))}
      </RowsOrEmpty>
    </Section>
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
