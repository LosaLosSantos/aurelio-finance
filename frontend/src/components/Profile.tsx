import { useEffect, useState } from "react";
import { getSurvey, saveSurvey, type SurveyAnswer } from "../api/survey";
import {
  getTaxSettings,
  saveTaxSettings,
  type TaxCountryDefault,
  type TaxSettingsRead,
} from "../api/tax";
import { getBaseCurrency, saveBaseCurrency, type BaseCurrencySetting } from "../api/baseCurrency";
import { apiError, btnClass, cardClass, inputClass } from "./ui";

type QType = "boolean" | "single" | "text" | "longtext" | "number";

interface Question {
  key: string;
  topic: string;
  text: string;
  type: QType;
  options?: string[];
  // Branching: only show this question if another answer equals a value.
  showIf?: { key: string; equals: string };
  // Educational: show this explanation when the answer equals a value (e.g. "no").
  explainWhen?: { equals: string; text: string };
  // For boolean questions where "unsure" is a meaningful third answer.
  unsure?: boolean;
}

// Declarative questionnaire. Booleans store "yes"/"no" (or "unsure" when allowed).
const QUESTIONS: Question[] = [
  // --- About you (context) ---
  { key: "about_country", topic: "About you", type: "text", text: "Which country do you live in?" },
  { key: "about_area", topic: "About you", type: "text", text: "Which city or area?" },
  { key: "about_age", topic: "About you", type: "number", text: "Your age?" },
  {
    key: "about_employment",
    topic: "About you",
    type: "single",
    options: ["Employee", "Self-employed", "Business owner", "Student", "Retired", "Not working"],
    text: "Employment status?",
  },
  {
    key: "about_household",
    topic: "About you",
    type: "single",
    options: ["Single", "Couple", "Family with children", "Other"],
    text: "Household?",
  },
  { key: "about_dependents", topic: "About you", type: "number", text: "How many people depend on you financially?" },
  {
    key: "about_home",
    topic: "About you",
    type: "single",
    options: ["Rent", "Own (with mortgage)", "Own (outright)", "Live with family", "Other"],
    text: "Your housing situation?",
  },

  // --- Financial literacy intro (with explanations on "no") ---
  {
    key: "lit_why_invest",
    topic: "Financial literacy",
    type: "boolean",
    text: "Do you know why people invest?",
    explainWhen: {
      equals: "no",
      text: "Investing grows your savings over time and protects them from inflation: money left idle loses purchasing power every year. By investing in assets that yield a return, your capital can grow and outpace inflation, in exchange for some risk.",
    },
  },
  {
    key: "lit_inflation",
    topic: "Financial literacy",
    type: "boolean",
    text: "Do you know what inflation is?",
    explainWhen: {
      equals: "no",
      text: "Inflation is the general rise in prices over time: with the same amount you buy less tomorrow than today. At 3%/year, €100 is worth about €97 of purchasing power after one year, which is why idle cash 'loses value'.",
    },
  },
  {
    key: "lit_risk_return",
    topic: "Financial literacy",
    type: "boolean",
    text: "Do you know the risk/return trade-off?",
    explainWhen: {
      equals: "no",
      text: "Higher potential returns usually require accepting more risk (ups and downs, possible losses). There are no high, guaranteed, risk-free returns. Be wary of anyone promising them.",
    },
  },
  {
    key: "lit_diversification",
    topic: "Financial literacy",
    type: "boolean",
    text: "Do you know what diversification is?",
    explainWhen: {
      equals: "no",
      text: "Diversification means not putting all your eggs in one basket. Spreading across instruments, sectors and regions reduces the chance that a single bad investment hurts everything.",
    },
  },

  // --- Family ---
  { key: "fam_want", topic: "Family", type: "boolean", text: "Do you want to start or grow a family?", unsure: true },
  {
    key: "fam_when",
    topic: "Family",
    type: "single",
    options: ["< 2 years", "2–5 years", "> 5 years"],
    text: "On what horizon?",
    showIf: { key: "fam_want", equals: "yes" },
  },
  {
    key: "fam_children",
    topic: "Family",
    type: "number",
    text: "How many children do you plan for?",
    showIf: { key: "fam_want", equals: "yes" },
  },

  // --- Housing & city ---
  { key: "home_buy", topic: "Housing & city", type: "boolean", text: "Do you plan to buy a home?", unsure: true },
  {
    key: "home_when",
    topic: "Housing & city",
    type: "single",
    options: ["< 2 years", "2–5 years", "> 5 years"],
    text: "When?",
    showIf: { key: "home_buy", equals: "yes" },
  },
  { key: "home_city", topic: "Housing & city", type: "text", text: "Any city/area you plan to move to or settle in?" },

  // --- Career & income ---
  { key: "career_change", topic: "Career & income", type: "boolean", text: "Do you expect a major career or income change soon?", unsure: true },
  {
    key: "career_detail",
    topic: "Career & income",
    type: "text",
    text: "Briefly, what change?",
    showIf: { key: "career_change", equals: "yes" },
  },

  // --- Major purchases ---
  { key: "big_purchase", topic: "Major purchases", type: "boolean", text: "Any large purchase planned (car, renovation, …)?", unsure: true },
  {
    key: "big_purchase_detail",
    topic: "Major purchases",
    type: "text",
    text: "What and roughly when?",
    showIf: { key: "big_purchase", equals: "yes" },
  },

  // --- Retirement & horizon ---
  { key: "ret_age", topic: "Retirement & horizon", type: "number", text: "At what age would you like to retire or be financially independent?" },

  // --- Risk & values ---
  { key: "risk_tolerance", topic: "Risk & values", type: "single", options: ["Low", "Medium", "High"], text: "How would you describe your risk tolerance?" },
  // Classic loss-aversion probe: both options have the SAME expected value
  // (−500), so the answer reveals attitude to risk rather than to the amount.
  {
    key: "risk_loss_choice",
    topic: "Risk & values",
    type: "single",
    options: [
      "A certain loss of 500 €",
      "A 50/50 gamble: lose 1000 € or lose nothing",
    ],
    text: "Which would you choose: a certain loss of 500 €, or a 50% chance of losing 1000 € and a 50% chance of losing nothing?",
  },
  { key: "values_esg", topic: "Risk & values", type: "boolean", text: "Do ethical / ESG considerations matter for your investments?", unsure: true },

  // --- In your words ---
  // The richest input a model can get, and the one no number can replace: how
  // you talk about your own money, and how you want to be talked to.
  {
    key: "self_narrative",
    topic: "In your words",
    type: "longtext",
    text: "Write freely about yourself and your money: what you are working towards, what worries you, what you would never give up, how you want Aurelio to talk to you. Nothing here is validated or scored: it is context.",
  },

  // --- Lifestyle ---
  { key: "lifestyle_notes", topic: "Lifestyle", type: "text", text: "Anything else about your situation, habits, or plans Aurelio should know?" },
];

const TOPICS = [...new Set(QUESTIONS.map((q) => q.topic))];

// The keys this form is authoritative for. Everything else stored under
// /api/survey belongs to somebody else — today the chat, which can write an
// answer to a question this list never asked, because the analyses declare
// what they do not know about you and a form cannot ask that in advance.
const OWN_KEYS = new Set(QUESTIONS.map((q) => q.key));

export default function Profile() {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  /* Answers stored under keys this form does not render, kept so they can be
     posted back untouched. PUT /api/survey replaces the WHOLE set — it deletes
     what its payload does not name — which is correct for a caller that reads
     everything and writes everything back, and is only correct while this form
     IS that caller. Without this, pressing Save here would silently delete
     every question the chat had recorded in conversation. */
  const [carried, setCarried] = useState<SurveyAnswer[]>([]);
  /* The tax settings are a different resource from the questionnaire — three
     keys in `settings`, not survey answers — but they share this page's ONE
     save button on purpose. Two save buttons on one screen is how an edit gets
     lost: you change a rate, press the button you can see, and the rate never
     left the browser. */
  const [tax, setTax] = useState<TaxSettingsRead | null>(null);
  /* Held as strings, so "" can mean cleared. A number input bound to a number
     cannot express "I have not said" — it collapses to 0, which is the reader
     claiming they pay no tax. */
  const [taxCountry, setTaxCountry] = useState("");
  const [cgRate, setCgRate] = useState("");
  const [divRate, setDivRate] = useState("");
  /* The base, as stored and as picked. Saved with the same button, for the
     reason written above; sent only when it changed, because changing it is
     the one save here that asks the rate feed for something. */
  const [base, setBase] = useState<BaseCurrencySetting | null>(null);
  const [pickedBase, setPickedBase] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    void load();
  }, []);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [existing, taxes, currentBase] = await Promise.all([
        getSurvey(),
        getTaxSettings(),
        getBaseCurrency(),
      ]);
      setBase(currentBase);
      setPickedBase(currentBase.base_currency);
      setTax(taxes);
      setTaxCountry(taxes.country ?? "");
      setCgRate(taxes.capital_gains_rate?.toString() ?? "");
      setDivRate(taxes.dividend_withholding_rate?.toString() ?? "");
      const map: Record<string, string> = {};
      for (const a of existing) if (a.answer != null) map[a.question_key] = a.answer;
      setAnswers(map);
      setCarried(
        existing
          .filter((a) => !OWN_KEYS.has(a.question_key) && a.answer != null)
          .map(({ question_key, topic, question, answer }) => ({
            question_key,
            topic,
            question,
            answer,
          })),
      );
    } catch (err) {
      setError(apiError(err, "Could not reach the backend. Is it running on :8000?"));
    } finally {
      setLoading(false);
    }
  }

  function setAnswer(key: string, value: string) {
    setAnswers((a) => ({ ...a, [key]: value }));
    setSaved(false);
  }

  function isVisible(q: Question): boolean {
    return !q.showIf || answers[q.showIf.key] === q.showIf.equals;
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const payload: SurveyAnswer[] = QUESTIONS.filter(
        (q) => isVisible(q) && (answers[q.key] ?? "") !== "",
      ).map((q) => ({
        question_key: q.key,
        topic: q.topic,
        question: q.text,
        answer: answers[q.key],
      }));
      await saveSurvey([...payload, ...carried]);
      // An empty field CLEARS the key rather than storing 0. The backend
      // deletes it, so "not said" has one representation instead of three
      // that look identical on screen.
      setTax(
        await saveTaxSettings({
          country: taxCountry.trim() || null,
          capital_gains_rate: cgRate === "" ? null : Number(cgRate),
          dividend_withholding_rate: divRate === "" ? null : Number(divRate),
        }),
      );
      // Last, so a feed that does not answer leaves everything above saved and
      // says, in the backend's own words, that the base did not change.
      if (base && pickedBase !== base.base_currency) {
        setBase(await saveBaseCurrency(pickedBase));
      }
      setSaved(true);
    } catch (err) {
      setError(apiError(err, "Save failed."));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <p className="text-ink-soft">Loading…</p>;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-ink">Profile &amp; goals</h2>
        <p className="text-sm text-ink-soft">
          A short questionnaire that gives Aurelio your context. Saved on your
          machine; only sent to the LLM when you run an analysis.
        </p>
      </div>

      {error && <p className="text-down">{error}</p>}

      {TOPICS.map((topic) => {
        const qs = QUESTIONS.filter((q) => q.topic === topic && isVisible(q));
        if (qs.length === 0) return null;
        return (
          <section key={topic} className={cardClass + " space-y-4 p-5"}>
            <h3 className="text-sm font-semibold text-ink">{topic}</h3>
            {qs.map((q) => (
              <QuestionField
                key={q.key}
                q={q}
                value={answers[q.key] ?? ""}
                onChange={(v) => setAnswer(q.key, v)}
              />
            ))}
          </section>
        );
      })}

      <TaxSection
        known={tax?.known_countries ?? []}
        country={taxCountry}
        capitalGains={cgRate}
        dividends={divRate}
        onChange={(field, value) => {
          setSaved(false);
          if (field === "country") setTaxCountry(value);
          else if (field === "cg") setCgRate(value);
          else setDivRate(value);
        }}
        onUseDefault={(d) => {
          setSaved(false);
          setCgRate(d.capital_gains_rate.toString());
          setDivRate(d.dividend_withholding_rate.toString());
        }}
      />

      <BaseCurrencySection
        current={base?.base_currency ?? ""}
        available={base?.available ?? []}
        picked={pickedBase}
        onPick={(code) => {
          setSaved(false);
          setPickedBase(code);
        }}
      />

      <div className="flex items-center gap-3">
        <button onClick={save} disabled={saving} className={btnClass}>
          {saving ? "Saving…" : "Save profile"}
        </button>
        {saved && <span className="text-sm text-up">Saved ✓</span>}
      </div>
    </div>
  );
}

/* The currency every total is shown in.

   What the reader has to know before changing it is what moves and what does
   not. Every total moves — the net worth, the history, every converted figure —
   because it is the same wealth measured in another unit, at the ECB rate of
   each figure's own day. Nothing recorded moves: an amount keeps the currency
   it was typed in, and a sum fixed on its day stays what it was. The choices
   are the currencies the ECB publishes, because a total can only be converted
   into one somebody publishes a rate for. */
function BaseCurrencySection({
  current,
  available,
  picked,
  onPick,
}: {
  current: string;
  available: string[];
  picked: string;
  onPick: (code: string) => void;
}) {
  return (
    <section className={cardClass + " space-y-3 p-5"}>
      <h3 className="text-sm font-semibold text-ink">Base currency</h3>
      <p className="text-sm text-ink-soft">
        Every total is shown in this currency: your net worth, its history, every
        converted figure. Changing it moves all of them, the history included:
        it is the same wealth in another unit, converted at the ECB rate of each
        figure's own day. Nothing you recorded is rewritten: every amount keeps
        the currency you typed it in, and a debit or a transfer fixed on its day
        stays what it was.
      </p>
      <label className="flex items-center gap-2 text-sm text-ink">
        Show totals in
        <select
          className={inputClass + " w-28"}
          value={picked}
          onChange={(e) => onPick(e.target.value)}
        >
          {available.map((code) => (
            <option key={code} value={code}>
              {code}
            </option>
          ))}
        </select>
      </label>
      {picked !== current && (
        <p className="text-xs text-warn">
          Saving switches every total from {current} to {picked}. The rates against{" "}
          {picked} are fetched first; if the feed cannot be reached, nothing changes.
        </p>
      )}
      {available.length <= 1 && (
        <p className="text-xs text-ink-faint">
          The rate feed has not answered yet, so {current} is the only currency on offer.
        </p>
      )}
    </section>
  );
}

/* WHAT THIS SECTION IS FOR, AND WHAT IT REFUSES TO BE.

   Two rates and a country name. That is the whole tax model, and keeping it
   that small is the feature rather than a shortcut: a real engine for Italy
   alone would need the 12.5% government-bond rate, harmonised versus
   non-harmonised funds, a four-year loss basket and the rest of it, and the
   way that project fails is by being PRECISE AND WRONG. A reader told
   "roughly 26%, and it says estimated" checks it against their broker. A
   reader shown a confident number does not.

   The country is a LABEL and a seed, never a gate. Nothing downstream branches
   on it: the two rates are what every reader of this figure actually reads, so
   someone whose country this app ships nothing for types their own two numbers
   and gets the identical estimate. Being listed buys a pre-fill and nothing
   else — which is the point, because a rate you looked up this year beats any
   table shipped with an app. France's moved 1.4 points in January. */
function TaxSection({
  known,
  country,
  capitalGains,
  dividends,
  onChange,
  onUseDefault,
}: {
  known: TaxCountryDefault[];
  country: string;
  capitalGains: string;
  dividends: string;
  onChange: (field: "country" | "cg" | "div", value: string) => void;
  onUseDefault: (d: TaxCountryDefault) => void;
}) {
  const match = known.find(
    (d) => d.country.toLowerCase() === country.trim().toLowerCase(),
  );
  const nothingSet = capitalGains === "" && dividends === "";

  return (
    <section className={cardClass + " space-y-4 p-5"}>
      <div>
        <h3 className="text-sm font-semibold text-ink">Tax</h3>
        <p className="mt-1 text-sm text-ink-soft">
          Your own rates, used for an estimate shown beside your portfolio
          figures. Aurelio never puts a tax inside a total: not your net worth,
          not your book value. Leave a field empty if you do not know it: that
          is different from writing 0, and the estimate will say which half it
          could not work out.
        </p>
      </div>

      <div>
        <label className="mb-1 block text-sm text-ink">
          Which country do you pay investment tax in?
        </label>
        <input
          className={inputClass + " w-full"}
          type="text"
          list="tax-countries"
          placeholder="Any country (typing your own rates below works either way)"
          value={country}
          onChange={(e) => onChange("country", e.target.value)}
        />
        <datalist id="tax-countries">
          {known.map((d) => (
            <option key={d.country} value={d.country} />
          ))}
        </datalist>
      </div>

      {match && (
        <div className="rounded-sm bg-tint p-3 text-sm">
          <p className="text-ink">
            {match.country}: {match.regime} ({match.capital_gains_rate}% on
            gains, {match.dividend_withholding_rate}% on dividends).
          </p>
          {/* Offered, never applied on its own. A figure that changed itself
              because a text field changed is a figure nobody declared, and the
              reader cannot tell it apart from one they typed. */}
          <p className="mt-1 text-ink-faint">{match.omits}</p>
          <button
            type="button"
            onClick={() => onUseDefault(match)}
            className="mt-2 rounded-sm border border-olive px-3 py-1.5 text-sm text-olive-deep transition hover:bg-olive-tint"
          >
            Use these as a starting point
          </button>
        </div>
      )}

      <div className="flex flex-wrap gap-6">
        <RateField
          label="Capital gains rate"
          hint="Applied to the gains your sells locked in"
          value={capitalGains}
          onChange={(v) => onChange("cg", v)}
        />
        <RateField
          label="Dividend withholding rate"
          hint="Applied only to dividends still showing the market's gross figure"
          value={dividends}
          onChange={(v) => onChange("div", v)}
        />
      </div>

      {nothingSet && (
        <p className="text-sm text-ink-faint">
          Nothing set, so no tax estimate is shown anywhere: not a zero, and
          not a silent omission. The portfolio page says what it is missing.
        </p>
      )}
    </section>
  );
}

function RateField({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label className="mb-1 block text-sm text-ink">{label}</label>
      <div className="flex items-center gap-2">
        <input
          className={inputClass + " w-28"}
          type="number"
          min={0}
          max={100}
          step="0.001"
          placeholder="not set"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        <span className="text-sm text-ink-soft">%</span>
      </div>
      <p className="mt-1 text-xs text-ink-faint">{hint}</p>
    </div>
  );
}

function QuestionField({
  q,
  value,
  onChange,
}: {
  q: Question;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label className="mb-1 block text-sm text-ink">{q.text}</label>

      {q.type === "boolean" ? (
        <div className="flex gap-2">
          {(q.unsure ? ["yes", "unsure", "no"] : ["yes", "no"]).map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() => onChange(opt)}
              className={
                "rounded-sm border px-3 py-1.5 text-sm capitalize transition " +
                (value === opt
                  ? "border-olive bg-olive-tint text-olive-deep"
                  : "border-rule text-ink-soft hover:bg-ground")
              }
            >
              {opt}
            </button>
          ))}
        </div>
      ) : q.type === "single" ? (
        <select className={inputClass} value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">choose…</option>
          {q.options?.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      ) : q.type === "number" ? (
        <input
          className={inputClass + " w-32"}
          type="number"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : q.type === "longtext" ? (
        <textarea
          className={inputClass + " min-h-40 w-full leading-relaxed"}
          rows={8}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <input
          className={inputClass + " w-full"}
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      )}

      {q.explainWhen && value === q.explainWhen.equals && (
        <p className="mt-2 rounded-sm bg-warn-tint p-3 text-sm text-warn">
          {q.explainWhen.text}
        </p>
      )}
    </div>
  );
}
