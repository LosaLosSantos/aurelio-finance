import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
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
import { createGoal, deleteGoal, getGoals, updateGoal } from "../api/goals";
import { choicesOf, isVisible, topicsOf, unshownAnswer } from "./questionnaire";
import { askedAs, toSave } from "./profileAnswers";
import { choiceClass } from "./choice";
import { PARTS, currentPart, partOf, partStatus, unsavedWords, waitingTotal, type PartKey, type Waiting } from "./profilePath";
import { asSent, baseConflict, laidOver, pageFrom, refusalWords, saveProfile, taxToSend, waiting } from "./profileSave";
import * as goalDrafts from "./goalDrafts";
import Goals from "./Goals";
import PathStrip from "./PathStrip";
import { apiError, cardClass, inputClass, statLabelClass } from "./ui";

/* The questions are the backend's (`GET /api/survey/questions`, app/questionnaire.py):
   the chat's answers to them are checked against the same list, so the two
   cannot disagree about what a question takes. Booleans store "yes"/"no" (or
   "unsure" when allowed). The keys in that list are the ones this form is
   authoritative for; everything else stored under /api/survey belongs to
   somebody else, today the chat, which can write an answer to a question this
   list never asked, because the analyses declare what they do not know about
   you and a form cannot ask that in advance.

   One path since brief BC (`profilePath.ts`): who you are (the questions,
   then where you pay tax and the currency you count in), in your words, what
   you want (the goals). One save keeps all of it, the goals included, laid
   over what is stored at that moment so nothing written elsewhere meanwhile
   is lost (`profileSave.ts`); the strip at the top says where the reader is
   and what is not saved yet, and the app asks before the reader leaves with
   changes waiting (`onWaiting`). */

export default function Profile({ onWaiting }: { onWaiting: (w: Waiting | null) => void }) {
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
  // The answers as the page read them, as a save sends them: what "not saved"
  // is counted against, and what the save tells the reader's changes by.
  const [loaded, setLoaded] = useState<SurveyAnswer[]>([]);
  /* The tax settings are a different resource from the questionnaire (three
     keys in `settings`, not survey answers), but they share this page's ONE
     save button on purpose. Two save buttons on one screen is how an edit gets
     lost: you change a rate, press the button you can see, and the rate never
     left the browser. */
  const [tax, setTax] = useState<TaxSettingsRead | null>(null);
  /* Held as strings, so "" can mean cleared. A number input bound to a number
     cannot express "I have not said": it collapses to 0, which is the reader
     claiming they pay no tax. */
  const [taxCountry, setTaxCountry] = useState("");
  const [cgRate, setCgRate] = useState("");
  const [divRate, setDivRate] = useState("");
  /* The base, as stored and as picked. Saved with the same button, for the
     reason written above; sent only when it changed, because changing it is
     the one save here that asks the rate feed for something. */
  const [base, setBase] = useState<BaseCurrencySetting | null>(null);
  const [pickedBase, setPickedBase] = useState("");
  // The goals, held until the save like everything else on the page.
  const [goals, setGoals] = useState<goalDrafts.GoalDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  // What the last save could not do, or what the reader held back.
  const [said, setSaid] = useState<{ tone: "refused" | "held"; text: string } | null>(null);
  const [current, setCurrent] = useState(0);
  const partRefs = useRef<(HTMLElement | null)[]>([]);
  const stripRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void load();
  }, []);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [asked, existing, taxes, currentBase, storedGoals] = await Promise.all([
        getSurveyQuestions(),
        getSurvey(),
        getTaxSettings(),
        getBaseCurrency(),
        getGoals(),
      ]);
      setQuestions(asked);
      setBase(currentBase);
      setPickedBase(currentBase.base_currency);
      setTax(taxes);
      setTaxCountry(taxes.country ?? "");
      setCgRate(taxes.capital_gains_rate?.toString() ?? "");
      setDivRate(taxes.dividend_withholding_rate?.toString() ?? "");
      const page = pageFrom(asked, existing);
      setAnswers(page.answers);
      setCarried(page.others);
      setLoaded(page.loaded);
      setDropped([]);
      setGoals(goalDrafts.fromStored(storedGoals));
    } catch (err) {
      setError(apiError(err, "Could not reach the backend. Is it running on :8000?"));
    } finally {
      setLoading(false);
    }
  }

  const now = toSave(questions, answers, carried);
  const waits = waiting({
    questions,
    loaded,
    now,
    tax: {
      stored: {
        country: tax?.country ?? null,
        capital_gains_rate: tax?.capital_gains_rate ?? null,
        dividend_withholding_rate: tax?.dividend_withholding_rate ?? null,
      },
      now: taxToSend(taxCountry, cgRate, divRate),
    },
    base: { loaded: base?.base_currency ?? pickedBase, picked: pickedBase },
    drafts: goals,
  });
  const total = waitingTotal(waits);

  // The app asks before leaving the tab with changes waiting; it hears what
  // waits here, and nothing once the page is gone.
  useEffect(() => {
    onWaiting({ situation: waits.situation, words: waits.words, goals: waits.goals });
  }, [onWaiting, waits.situation, waits.words, waits.goals]);
  useEffect(() => () => onWaiting(null), [onWaiting]);

  // Closing or reloading the browser's tab asks too, through the browser.
  useEffect(() => {
    if (total === 0) return;
    const ask = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", ask);
    return () => window.removeEventListener("beforeunload", ask);
  }, [total]);

  // Which part the reader is in (`currentPart`), read again on each scroll.
  useLayoutEffect(() => {
    if (loading) return;
    let frame = 0;
    const read = () => {
      frame = 0;
      const tops = partRefs.current.map((el) => (el ? el.getBoundingClientRect().top + window.scrollY : Infinity));
      setCurrent(
        currentPart(tops, {
          stripBottom: stripRef.current?.getBoundingClientRect().bottom ?? 0,
          height: window.innerHeight,
          scrolled: window.scrollY,
          pageHeight: document.documentElement.scrollHeight,
        }),
      );
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(read);
    };
    read();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [loading]);

  function setAnswer(key: string, value: string) {
    setAnswers((a) => ({ ...a, [key]: value }));
  }

  async function save() {
    setSaving(true);
    setSaid(null);
    setSaved(false);
    const result = await saveProfile(
      {
        questions,
        loaded,
        now,
        tax: taxToSend(taxCountry, cgRate, divRate),
        drafts: goals,
        base: { loaded: base?.base_currency ?? pickedBase, picked: pickedBase },
      },
      {
        getSurvey,
        putSurvey: saveSurvey,
        putTax: saveTaxSettings,
        getGoals,
        postGoal: createGoal,
        putGoal: updateGoal,
        deleteGoal,
        getBase: getBaseCurrency,
        putBase: saveBaseCurrency,
        ask: (question) => window.confirm(question),
        sentence: apiError,
      },
    );
    if (result.keptBack && result.read) {
      // The reader kept what is on record for what changed on both sides:
      // the page shows it, their other changes still waiting over it.
      const merged = laidOver(questions, loaded, now, result.read.map(asSent), "stored").body;
      const page = pageFrom(questions, result.read, merged);
      setAnswers(page.answers);
      setCarried(page.others);
      setLoaded(page.loaded);
      setDropped((all) => all.filter((d) => !page.others.some((o) => o.question_key === d.question_key)));
      setGoals(result.drafts);
      if (result.base && base) {
        if (baseConflict(base.base_currency, pickedBase, result.base.base_currency)) {
          setPickedBase(result.base.base_currency);
        }
        setBase(result.base);
      }
      setSaid({
        tone: "held",
        text: "Nothing was saved. What changed on both sides now shows what is on record; your other changes wait for Save profile.",
      });
    } else {
      if (result.survey) {
        const page = pageFrom(questions, result.survey);
        setAnswers(page.answers);
        setCarried(page.others);
        setLoaded(page.loaded);
        setDropped([]);
      }
      if (result.tax) setTax(result.tax);
      setGoals(result.drafts);
      if (result.base) setBase(result.base);
      const refused = refusalWords(result);
      if (refused) setSaid({ tone: "refused", text: refused });
      else setSaved(true);
    }
    setSaving(false);
  }

  if (loading) return <p className="text-ink-soft">Loading…</p>;

  function go(index: number) {
    partRefs.current[index]?.scrollIntoView({ block: "start" });
  }

  function topicCards(part: PartKey) {
    return topicsOf(questions)
      .filter((topic) => partOf(topic) === part)
      .map((topic) => {
        const qs = questions.filter((q) => q.topic === topic && isVisible(q, answers));
        if (qs.length === 0) return null;
        return (
          <section key={topic} className={cardClass + " space-y-4 p-5"}>
            <h4 className="text-sm font-semibold text-ink">{topic}</h4>
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
      });
  }

  function heading(index: number) {
    const part = PARTS[index];
    return (
      <div className="space-y-1">
        <p className={statLabelClass}>
          Part {index + 1} of {PARTS.length}
        </p>
        <h3 className="font-display text-2xl leading-tight text-ink">{part.title}</h3>
        <p className="max-w-[68ch] text-sm text-ink-soft">{part.hint}</p>
      </div>
    );
  }

  // Each part's place, and room above every field the cursor lands on, so
  // neither hides under the strip.
  const partClass =
    "scroll-mt-28 space-y-6 [&_button]:scroll-mt-32 [&_input]:scroll-mt-32 [&_select]:scroll-mt-32 [&_textarea]:scroll-mt-32";

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h2 className="font-display text-2xl leading-tight text-ink">Your profile</h2>
        <p className="max-w-[68ch] text-sm text-ink-soft">
          Who you are and what you want, in three parts. Every question is optional, and nothing
          is kept until you press Save profile.
        </p>
        <p className="max-w-[76ch] text-xs text-ink-faint">
          Saved on your machine; sent to the AI model through OpenRouter when you run an
          analysis or ask the chat.
        </p>
      </div>

      {error && <p className="text-down">{error}</p>}

      <div className="space-y-10">
        <PathStrip
          stripRef={stripRef}
          parts={PARTS.map((p) => ({
            key: p.key,
            title: p.title,
            status: partStatus(p.key, questions, answers, goalDrafts.counted(goals)),
          }))}
          current={current}
          onGo={go}
          unsaved={unsavedWords(waits)}
          saved={saved}
          saving={saving}
          onSave={save}
          said={said}
        />

        <section ref={(el) => { partRefs.current[0] = el; }} className={partClass}>
          {heading(0)}
          {topicCards("situation")}
          <TaxSection
            known={tax?.known_countries ?? []}
            country={taxCountry}
            capitalGains={cgRate}
            dividends={divRate}
            onChange={(field, value) => {
              if (field === "country") setTaxCountry(value);
              else if (field === "cg") setCgRate(value);
              else setDivRate(value);
            }}
            onUseDefault={(d) => {
              setCgRate(d.capital_gains_rate.toString());
              setDivRate(d.dividend_withholding_rate.toString());
            }}
          />
          <BaseCurrencySection
            current={base?.base_currency ?? ""}
            available={base?.available ?? []}
            picked={pickedBase}
            onPick={setPickedBase}
          />
        </section>

        <section ref={(el) => { partRefs.current[1] = el; }} className={partClass}>
          {heading(1)}
          {topicCards("words")}
          <OtherAnswers
            answers={carried}
            dropped={dropped}
            onChange={(key, value) => {
              setCarried((all) => all.map((a) => (a.question_key === key ? { ...a, answer: value } : a)));
            }}
            onDelete={(key) => {
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
        </section>

        <section ref={(el) => { partRefs.current[2] = el; }} className={partClass}>
          {heading(2)}
          <Goals
            drafts={goals}
            base={pickedBase}
            emptyText="No goals yet."
            onAdd={(g) => setGoals((all) => goalDrafts.add(all, g))}
            onChange={(ref, g) => setGoals((all) => goalDrafts.changeRef(all, ref, g))}
            onRemove={(at) => setGoals((all) => goalDrafts.remove(all, at))}
            onKeep={(at) => setGoals((all) => goalDrafts.keep(all, at))}
          />
        </section>
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
        <h4 className="text-sm font-semibold text-ink">Other answers</h4>
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
   because it is the same wealth measured in another unit, at the rate of
   each figure's own day (the ECB's, or Yahoo's for a currency the ECB does
   not publish). Nothing recorded moves: an amount keeps the currency
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
      <h4 className="text-sm font-semibold text-ink">Base currency</h4>
      <p className="text-sm text-ink-soft">
        Every total is shown in this currency: your net worth, its history, every
        converted figure. Changing it moves all of them, the history included:
        it is the same wealth in another unit, converted at the rate of each
        figure's own day: the ECB's, or Yahoo's for a currency the ECB does not
        publish. Nothing you recorded is rewritten: every amount keeps
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
  const countryId = useId();

  return (
    <section className={cardClass + " space-y-4 p-5"}>
      <div>
        <h4 className="text-sm font-semibold text-ink">Tax</h4>
        <p className="mt-1 text-sm text-ink-soft">
          Your own rates, used for an estimate shown beside your portfolio
          figures. Aurelio never puts a tax inside a total: not your net worth,
          not your book value. Leave a field empty if you do not know it: that
          is different from writing 0, and the estimate will say which half it
          could not work out.
        </p>
      </div>

      <div>
        <label htmlFor={countryId} className="mb-1 block text-sm text-ink">
          Which country do you pay investment tax in?
        </label>
        <input
          id={countryId}
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
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm text-ink">
        {label}
      </label>
      <div className="flex items-center gap-2">
        <input
          id={id}
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
  // The question names what answers it: its box, or the group of its answers,
  // in which the chosen one is pressed (brief AY).
  const id = useId();
  const questionId = `${id}-question`;
  return (
    <div>
      <label
        id={questionId}
        htmlFor={q.type === "boolean" ? undefined : id}
        className="mb-1 block text-sm text-ink"
      >
        {q.text}
      </label>

      {q.type === "boolean" ? (
        <div role="group" aria-labelledby={questionId} className="flex gap-2">
          {choicesOf(q).map((opt) => (
            <button
              key={opt}
              type="button"
              aria-pressed={value === opt}
              onClick={() => onChange(opt)}
              className={choiceClass(value === opt) + " capitalize"}
            >
              {opt}
            </button>
          ))}
        </div>
      ) : q.type === "single" ? (
        <select id={id} className={inputClass} value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">choose…</option>
          {q.options.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      ) : q.type === "number" ? (
        <input
          id={id}
          className={inputClass + " w-32"}
          type="number"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : q.type === "longtext" ? (
        <textarea
          id={id}
          className={inputClass + " min-h-40 w-full leading-relaxed"}
          rows={8}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <input
          id={id}
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
