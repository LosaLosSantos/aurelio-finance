/* The Profile tab as one path: who you are, in your words, what you want.

   It used to be three blocks stacked in no order: the questionnaire with its
   own heading and save, the Theme card, then Goals with a save of its own. A
   reader who typed answers and then added a goal with the goal's own button
   left the tab with the goal stored and the answers gone, nothing said
   (measured, brief BC). Now the tab reads in three parts, in this order, one
   save keeps all of it (`profileSave.ts`), and a strip at the top says which
   part the reader is in, how far each part is answered and what is not saved
   yet.

   The parts are the page's, not the backend's: each question keeps the topic
   `app/questionnaire.py` gives it, which is also what its saved answer
   carries to the models, and the page only says in which part a topic is
   read.

   No runtime imports, so `npm test` reaches it. */

import type { SurveyQuestion } from "../api/survey";

export type PartKey = "situation" | "words" | "goals";

export interface Part {
  key: PartKey;
  title: string;
  /** The part inside a sentence ("2 in your goals"). */
  short: string;
  /** One sentence under the part's title: what it is for. */
  hint: string;
}

/** The path, in its order. Tax and the base currency close the first part,
    before the goals, because a goal's currency is proposed from the base. */
export const PARTS: Part[] = [
  {
    key: "situation",
    title: "Your situation",
    short: "your situation",
    hint: "About you and what is coming up, then where you pay tax and the currency you count in.",
  },
  {
    key: "words",
    title: "In your words",
    short: "your words",
    hint: "What no question asks, written as you would say it.",
  },
  {
    key: "goals",
    title: "Your goals",
    short: "your goals",
    hint: "What you want your money to do. A target amount by a date shows the yearly return it would need.",
  },
];

/** The topics read in "In your words": the two questions answered in free
    text. Every other topic, a new one included, is read in "Your situation". */
const WORDS_TOPICS = ["In your words", "Lifestyle"];

export function partOf(topic: string | null | undefined): PartKey {
  return topic != null && WORDS_TOPICS.includes(topic) ? "words" : "situation";
}

/** Whether a question is shown with these answers: always, or, for a
    follow-up, while the answer it follows is the one it waits for. The rule
    of `questionnaire.ts`'s `isVisible`, written out so this module needs no
    runtime import. */
function shown(q: SurveyQuestion, answers: Record<string, string>): boolean {
  return !q.show_if || answers[q.show_if.key] === q.show_if.equals;
}

/** The questions of `part` the page shows with these answers, in order. */
export function questionsOf(
  part: PartKey,
  questions: SurveyQuestion[],
  answers: Record<string, string>,
): SurveyQuestion[] {
  return questions.filter((q) => partOf(q.topic) === part && shown(q, answers));
}

/** What the strip says beside a part: how far it is answered. */
export function partStatus(
  part: PartKey,
  questions: SurveyQuestion[],
  answers: Record<string, string>,
  goals: number,
): string {
  if (part === "goals") {
    if (goals === 0) return "none yet";
    return goals === 1 ? "1 goal" : `${goals} goals`;
  }
  const asked = questionsOf(part, questions, answers);
  const answered = asked.filter((q) => (answers[q.key] ?? "").trim() !== "").length;
  return `${answered} of ${asked.length} answered`;
}

/** The part the reader is in, from where each part starts on the page
    (`tops`, page coordinates) and where the reader reads: the last part whose
    start has passed a third of the way down the room under the strip, or,
    once the page is scrolled to its end, the last part that has come into
    view (a short last part never reaches that line). The first part when none
    has. */
export function currentPart(
  tops: number[],
  view: { stripBottom: number; height: number; scrolled: number; pageHeight: number },
): number {
  if (view.scrolled + view.height >= view.pageHeight - 2) {
    let last = 0;
    tops.forEach((top, i) => {
      if (top < view.scrolled + view.height) last = i;
    });
    return last;
  }
  const line = view.scrolled + view.stripBottom + (view.height - view.stripBottom) / 3;
  let at = 0;
  tops.forEach((top, i) => {
    if (top <= line) at = i;
  });
  return at;
}

/** What waits for "Save profile", counted by the part it belongs to: an
    answer, a tax field or the base in its part, a goal in "Your goals". */
export type Waiting = Record<PartKey, number>;

export function waitingTotal(w: Waiting): number {
  return w.situation + w.words + w.goals;
}

function changes(n: number): string {
  return n === 1 ? "1 change" : `${n} changes`;
}

/** The strip's words for what is not saved yet, or null when nothing is. */
export function unsavedWords(w: Waiting): string | null {
  const n = waitingTotal(w);
  return n > 0 ? `${changes(n)} not saved` : null;
}

/** What the page asks before the reader leaves it with changes not saved,
    or null when nothing waits: how many, and in which parts. */
export function leaveQuestion(w: Waiting): string | null {
  const n = waitingTotal(w);
  if (n === 0) return null;
  const where = PARTS.filter((p) => w[p.key] > 0).map((p) => `${w[p.key]} in ${p.short}`);
  const listed = where.length === 1 ? where[0] : `${where.slice(0, -1).join(", ")} and ${where[where.length - 1]}`;
  return `Your profile has ${changes(n)} not saved: ${listed}. Leave without saving them?`;
}

/** The key of the main column. A ledger write from the banner (a dividend
    answered there) changes the version so the page in view reads it again,
    which remounts it; the Profile shows nothing of the ledger, and a remount
    would drop every change it holds, so while it is open the key stays. */
export function mainKey(tab: string, ledgerVersion: number): string {
  return tab === "profile" ? "profile" : `ledger-${ledgerVersion}`;
}
