import { useEffect, useState, type FormEvent } from "react";
import {
  createBalance,
  createLiability,
  deleteBalance,
  deleteLiability,
  getBalances,
  getLiabilities,
  getLiability,
  updateBalance,
  updateLiability,
  type Liability,
  type LiabilityBalance,
} from "../api/liabilities";
import { getRealAssets, type RealAsset } from "../api/realAssets";
import {
  Breadcrumb,
  Row,
  RowsOrEmpty,
  Section,
  apiError,
  btnClass,
  inputClass,
  money,
  type Crumb,
  CURRENCY_LIST,
} from "./ui";
import { CancelButton } from "./ui";
import { getBaseCurrency } from "../api/baseCurrency";
import { DatedAmountEditor } from "./DatedAmountEditor";
import { useReopened } from "./reopen";
import { BALANCE, DEBT, marks, refusal } from "./required";

const KINDS = ["", "mortgage", "personal_loan", "auto_loan", "student_loan", "credit_card", "other"];

// "personal_loan" -> "personal loan"
function prettyKind(s: string | null): string | null {
  return s ? s.replace(/_/g, " ") : s;
}

/* Which debt is open is App's state, so the chat can be told which one "this"
   is, and so the page is where you left it when you come back to Records. On
   arrival the debt is read again; one that is gone climbs to the list. See
   reopen.ts. */
export default function Debts({
  liability,
  onLiability,
}: {
  liability: Liability | null;
  onLiability: (l: Liability | null) => void;
}) {
  const checked = useReopened(liability, getLiability, onLiability);
  if (!checked) return null;

  const crumbs: Crumb[] = [
    { label: "Debts", active: !liability, onClick: () => onLiability(null) },
  ];
  if (liability) crumbs.push({ label: liability.name, active: true, onClick: () => {} });

  return (
    <div className="space-y-5">
      <Breadcrumb items={crumbs} />
      {!liability ? (
        <DebtsLevel onSelect={onLiability} />
      ) : (
        <BalancesLevel liability={liability} />
      )}
    </div>
  );
}

function DebtsLevel({ onSelect }: { onSelect: (l: Liability) => void }) {
  const [items, setItems] = useState<Liability[]>([]);
  const [assets, setAssets] = useState<RealAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // The form's refusals and failed saves, apart from a failed load: RowsOrEmpty
  // shows an error INSTEAD of the rows, so a sentence about the form must not
  // go there (SnapshotsLevel learned this first).
  const [formError, setFormError] = useState<string | null>(null);
  const [editId, setEditId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [kind, setKind] = useState("");
  const [rate, setRate] = useState("");
  const [assetId, setAssetId] = useState("");
  /* A debt belongs to no account, so there is none to propose its currency
     from: the base the reader chose is the proposal, and what they type in the
     box wins. An edited debt keeps its own. */
  const [base, setBase] = useState("");
  const [currencyChoice, setCurrencyChoice] = useState<string | null>(null);
  const currency = currencyChoice ?? base;
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    void load();
  }, []);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [liabs, ras, b] = await Promise.all([getLiabilities(), getRealAssets(), getBaseCurrency()]);
      setItems(liabs);
      setAssets(ras);
      setBase(b.base_currency);
    } catch (err) {
      setError(apiError(err, "Could not reach the backend. Is it running on :8000?"));
    } finally {
      setLoading(false);
    }
  }

  function reset() {
    setEditId(null);
    setName("");
    setKind("");
    setRate("");
    setAssetId("");
    setCurrencyChoice(null);
  }

  function startEdit(l: Liability) {
    setEditId(l.id);
    setName(l.name);
    setKind(l.kind ?? "");
    setRate(l.interest_rate != null ? String(l.interest_rate) : "");
    setAssetId(l.real_asset_id ? String(l.real_asset_id) : "");
    setCurrencyChoice(l.currency);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const refused = refusal(DEBT, { name, currency });
    if (refused) {
      setFormError(refused);
      return;
    }
    setSubmitting(true);
    setFormError(null);
    const payload = {
      name: name.trim(),
      kind: kind || null,
      currency: currency.trim(),
      interest_rate: rate ? Number(rate) : null,
      real_asset_id: assetId ? Number(assetId) : null,
    };
    try {
      if (editId != null) await updateLiability(editId, payload);
      else await createLiability(payload);
      reset();
      await load();
    } catch (err) {
      setFormError(apiError(err, "Save failed."));
    } finally {
      setSubmitting(false);
    }
  }

  async function remove(l: Liability) {
    if (!window.confirm(`Delete "${l.name}"? This also removes its balance history.`)) return;
    setError(null);
    try {
      await deleteLiability(l.id);
      if (editId === l.id) reset();
      await load();
    } catch (err) {
      setError(apiError(err, "Delete failed."));
    }
  }

  function assetName(id: number | null): string | undefined {
    if (id == null) return undefined;
    return assets.find((a) => a.id === id)?.name;
  }

  function debtSubtitle(l: Liability): string | undefined {
    const parts: string[] = [];
    const linked = assetName(l.real_asset_id);
    if (linked) parts.push(`finances ${linked}`);
    if (l.interest_rate != null) parts.push(`${l.interest_rate}%/yr`);
    return parts.length ? parts.join(" · ") : undefined;
  }

  return (
    <Section
      title="Debts"
      hint="Mortgage, loans… Net worth subtracts the latest balance of each. Link a mortgage to its asset to see your equity."
    >
      <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
        <input className={inputClass} aria-label="Name" {...marks(DEBT, "name")} value={name} onChange={(e) => setName(e.target.value)} />
        <select className={inputClass} value={kind} onChange={(e) => setKind(e.target.value)}>
          {KINDS.map((k) => (<option key={k} value={k}>{prettyKind(k) || "kind…"}</option>))}
        </select>
        <input className={inputClass + " w-28"} type="number" step="0.01" placeholder="Rate %/yr" value={rate} onChange={(e) => setRate(e.target.value)} />
        <input
          className={inputClass + " w-20"}
          placeholder="currency"
          {...marks(DEBT, "currency")}
          list={CURRENCY_LIST}
          title="The currency the debt is owed in. Proposed from your base currency; change it and it stays as you typed it."
          value={currency}
          onChange={(e) => setCurrencyChoice(e.target.value)}
        />
        <select className={inputClass} value={assetId} onChange={(e) => setAssetId(e.target.value)}>
          <option value="">finances asset…</option>
          {assets.map((a) => (<option key={a.id} value={a.id}>{a.name}</option>))}
        </select>
        <button className={btnClass} disabled={submitting}>{submitting ? "..." : editId != null ? "Save" : "Add"}</button>
        {editId != null && <CancelButton onClick={reset} />}
      </form>
      {formError && <p className="text-down">{formError}</p>}
      <RowsOrEmpty loading={loading} error={error} empty={items.length === 0} emptyText="No debts, lucky you.">
        {items.map((l) => (
          <Row
            key={l.id}
            onClick={() => onSelect(l)}
            onEdit={() => startEdit(l)}
            onDelete={() => remove(l)}
            title={l.name}
            badge={prettyKind(l.kind)}
            subtitle={debtSubtitle(l)}
            note={l.notes}
            value={l.latest_balance != null ? money(l.currency).format(l.latest_balance) : undefined}
          />
        ))}
      </RowsOrEmpty>
    </Section>
  );
}

function BalancesLevel({ liability }: { liability: Liability }) {
  const [items, setItems] = useState<LiabilityBalance[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void load();
  }, [liability.id]);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setItems(await getBalances(liability.id));
    } catch (err) {
      setError(apiError(err, "Could not load balances."));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Section
      title={`Outstanding balance: ${liability.name}`}
      explain={{
        question: "What is the outstanding balance?",
        text: "The remaining principal, as your amortization statement shows it.",
      }}
    >
      <DatedAmountEditor
        items={items}
        loading={loading}
        loadError={error}
        dateOf={(b) => b.date}
        amountOf={(b) => b.balance}
        currencyOf={() => liability.currency}
        toPayload={(date, balance) => ({ date, balance })}
        create={(p) => createBalance(liability.id, p)}
        update={updateBalance}
        destroy={deleteBalance}
        onChanged={load}
        noun="balance"
        amountLabel="Remaining"
        needs={BALANCE}
        emptyText="No balances yet."
      />
    </Section>
  );
}
