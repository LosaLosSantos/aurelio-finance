import { useState } from "react";
import { answerDividend, type CatchUpResult, type DividendQuestion } from "../api/transactions";
import { choices, questionText, type Answer, type Formats } from "./dividendQuestion";
import { apiError, locale, money } from "./ui";

/* The questions the catch-up asks about dividends (brief AZ), in the start-up
   banner, each with the answers it offers. Nothing is written until one is
   pressed; the answer goes to the backend, which checks it against the ledger
   as it is now, writes it and runs the dividend catch-up again, and what that
   returns replaces the questions shown. A question that no longer stands is
   refused with a sentence, said under it. The words are
   `dividendQuestion.ts`'s. */

// A day in a sentence: the long form, which no reader takes for another day.
const longDate = (iso: string) =>
  new Date(iso + "T00:00:00").toLocaleDateString(locale, { day: "numeric", month: "long", year: "numeric" });

const perShare = new Intl.NumberFormat(locale, { maximumFractionDigits: 6 });

export const BANNER_FORMATS: Formats = {
  date: longDate,
  money: (amount, currency) => money(currency, "cents").format(amount),
  perShare: (amount, currency) => `${perShare.format(amount)} ${currency}`,
};

function keyOf(q: DividendQuestion): string {
  return [q.kind, q.institution_id, q.symbol, ...q.dividends.map((d) => d.ex_date), ...q.entries.map((e) => e.id)].join(":");
}

export default function DividendQuestions({
  questions,
  onAnswered,
}: {
  questions: DividendQuestion[];
  onAnswered: (result: CatchUpResult) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<{ key: string; text: string } | null>(null);

  async function answer(key: string, body: Answer) {
    setBusy(true);
    setRefused(null);
    try {
      onAnswered(await answerDividend(body));
    } catch (err) {
      setRefused({ key, text: apiError(err, "The answer could not be saved.") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <ul className="w-full space-y-2">
      {questions.map((q) => {
        const key = keyOf(q);
        return (
          <li key={key}>
            <p>{questionText(q, BANNER_FORMATS)}</p>
            <div className="mt-1 flex flex-wrap gap-2">
              {choices(q, BANNER_FORMATS).map((c) => (
                <button
                  key={c.label}
                  type="button"
                  disabled={busy}
                  onClick={() => answer(key, c.answer)}
                  className="rounded border border-olive px-2 py-0.5 text-xs font-medium text-olive-deep hover:bg-surface disabled:opacity-50"
                >
                  {c.label}
                </button>
              ))}
            </div>
            {refused?.key === key && <p className="mt-1 text-xs text-down">{refused.text}</p>}
          </li>
        );
      })}
    </ul>
  );
}
