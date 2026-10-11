import { useEffect, useState } from "react";
import {
  getSurvey,
  getSurveyQuestions,
  saveSurvey,
  type SurveyAnswer,
  type SurveyQuestion,
} from "../api/survey";
import {
  getTaxSettings,
  saveTaxSettings,
  type TaxCountryDefault,
  type TaxSettingsRead,
} from "../api/tax";
import { getBaseCurrency, saveBaseCurrency, type BaseCurrencySetting } from "../api/baseCurrency";
import { choicesOf, isVisible, topicsOf, unshownAnswer } from "./questionnaire";
import { askedAs, othersOf, toSave } from "./profileAnswers";
import { apiError, btnClass, cardClass, inputClass } from "./ui";

/* The questions are the backend's (`GET /api/survey/questions`, app/questionnaire.py):
   the chat's answers to them are checked against the same list, so the two
   cannot disagree about what a question takes. Booleans store "yes"/"no" (or
   "unsure" when allowed). The keys in that list are the ones this form is
   authoritative for; everything else stored under /api/survey belongs to
   somebody else, today the chat, which can write an answer to a question this
   list never asked, because the analyses declare what they do not know about
   you and a form cannot ask that in advance. */

export default function Profile() {
  const [questions, setQuestions] = useState<SurveyQuestion[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  /* Answers stored under keys this form does not ask, posted back with every
     Save. PUT /api/survey replaces the WHOLE set (it deletes what its payload
     does not name), which is correct for a caller that reads
     everything and writes everything back, and is only correct while this form
     IS that caller. Without this, pressing Save here would silently delete
     every question the chat had recorded in conversation. Shown since brief AN
     (`OtherAnswers`), each changed or deleted here (`profileAnswers.ts`). */
  const [carried, setCarried] = useState<SurveyAnswer[]>([]);
  // The ones deleted here and not saved yet, said under the list with a way back.
  const [dropped, setDropped] = useState<SurveyAnswer[]>([]);
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
      const [asked, existing, taxes, currentBase] = await Promise.all([
        getSurveyQuestions(),
        getSurvey(),
        getTaxSettings(),
        getBaseCurrency(),
      ]);
      setQuestions(asked);
      setBase(currentBase);
      setPickedBase(currentBase.base_currency);
      setTax(taxes);
      setTaxCountry(taxes.country ?? "");
      setCgRate(taxes.capital_gains_rate?.toString() ?? "");
      setDivRate(taxes.dividend_withholding_rate?.toString() ?? "");
      const map: Record<string, string> = {};
      for (const a of existing) if (a.answer != null) map[a.question_key] = a.answer;
      setAnswers(map);
      setCarried(othersOf(asked, existing));
      setDropped([]);
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

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await saveSurvey(toSave(questions, answers, carried));
      // What the save kept: an answer emptied in its box went with it.
      setCarried((kept) => kept.filter((a) => (a.answer ?? "").trim() !== ""));
      setDropped([]);
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
          machine; sent to the AI model through OpenRouter when you run an
          analysis or ask the chat.
        </p>
      </div>

      {error && <p className="text-down">{error}</p>}

      {topicsOf(questions).map((topic) => {
        const qs = questions.filter((q) => q.topic === topic && isVisible(q, answers));
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

      <OtherAnswers
        answers={carried}
        dropped={dropped}
        onChange={(key, value) => {
          setSaved(false);
          setCarried((all) => all.map((a) => (a.question_key === key ? { ...a, answer: value } : a)));
        }}
        onDelete={(key) => {
          setSaved(false);
          const gone = carried.find((a) => a.question_key === key);
          setCarried((all) => all.filter((a) => a.question_key !== key));
          if (gone) setDropped((all) => [...all, gone]);
        }}
        onRestore={(key) => {
          const back = dropped.find((a) => a.question_key === key);
          setDropped((all) => all.filter((a) => a.question_key !== key));
          if (back) setCarried((all) => [...all, back]);
        }}
      />

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

/* The answers on record to questions this form does not ask (brief AN).

   The chat records them, and the chat and the analyses read them like every
   other answer, so the reader is owed seeing them and correcting them where
   they correct the rest: each in a box of its own, a delete beside it, all
   saved with the page's one button. A deleted one stays listed under the
   others until the save, with a way back. */
function OtherAnswers({
  answers,
  dropped,
  onChange,
  onDelete,
  onRestore,
}: {
  answers: SurveyAnswer[];
  dropped: SurveyAnswer[];
  onChange: (key: string, value: string) => void;
  onDelete: (key: string) => void;
  onRestore: (key: string) => void;
}) {
  if (answers.length === 0 && dropped.length === 0) return null;
  return (
    <section className={cardClass + " space-y-4 p-5"}>
      <div>
        <h3 className="text-sm font-semibold text-ink">Other answers</h3>
        <p className="mt-1 text-sm text-ink-soft">
          Answers to questions this form does not ask, recorded in the chat. The chat and
          the analyses read them like the rest: change one or delete it here, then save.
        </p>
      </div>
      {answers.map((a) => (
        <div key={a.question_key} className="space-y-1">
          <label className="block text-sm text-ink" htmlFor={`other-${a.question_key}`}>
            {askedAs(a)}
            {a.topic && <span className="ml-2 text-xs text-ink-faint">{a.topic}</span>}
          </label>
          <div className="flex items-start gap-2">
            <textarea
              id={`other-${a.question_key}`}
              className={inputClass + " min-h-16 w-full"}
              value={a.answer ?? ""}
              onChange={(e) => onChange(a.question_key, e.target.value)}
            />
            <button
              type="button"
              onClick={() => onDelete(a.question_key)}
              className="shrink-0 rounded-sm px-3 py-2 text-sm text-ink-soft transition hover:text-down"
            >
              Delete
            </button>
          </div>
        </div>
      ))}
      {dropped.length > 0 && (
        <div className="text-xs text-warn">
          <p>Deleted when you save:</p>
          <ul className="mt-1 space-y-1">
            {dropped.map((a) => (
              <li key={a.question_key}>
                {askedAs(a)}{" "}
                <button
                  type="button"
                  onClick={() => onRestore(a.question_key)}
                  className="text-olive underline-offset-2 hover:underline"
                >
                  Keep it
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
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
  q: SurveyQuestion;
  value: string;
  onChange: (v: string) => void;
}) {
  // An answer on record that no button, option or number box can show: written
  // before the chat's answers were checked against the question (brief AL).
  const unshown = unshownAnswer(q, value);
  return (
    <div>
      <label className="mb-1 block text-sm text-ink">{q.text}</label>

      {q.type === "boolean" ? (
        <div className="flex gap-2">
          {choicesOf(q).map((opt) => (
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
          {q.options.map((o) => (
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

      {unshown && <p className="mt-2 text-sm text-warn">{unshown}</p>}

      {q.explain_when && value === q.explain_when.equals && (
        <p className="mt-2 rounded-sm bg-warn-tint p-3 text-sm text-warn">
          {q.explain_when.text}
        </p>
      )}
    </div>
  );
}
