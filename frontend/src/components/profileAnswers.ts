import type { SurveyAnswer, SurveyAnswerRead, SurveyQuestion } from "../api/survey";
import { isVisible } from "./questionnaire.ts";

/* The answers the Profile form keeps without asking their questions.

   The chat records answers to questions this form never asks
   (`update_profile`), and the chat and the analyses read them like the rest.
   Until brief AN (2026-10-10) the page kept them through a save and showed
   none, so the reader could neither see nor correct what the app tells the
   models about them, except by asking the chat to overwrite it. Now they are
   listed under the form's own questions, each one changed or deleted there,
   and saved with the same button.

   The backend builds the same body when the chat deletes one
   (`tools._profile_as_saved`), so what the chat writes is what this page
   writes. Pure, so `tests/profileAnswers.test.ts` runs it under Node. */

/** The answers on record to questions this form does not ask, in the order
    they are stored, as Save sends them back. */
export function othersOf(asked: SurveyQuestion[], existing: SurveyAnswerRead[]): SurveyAnswer[] {
  const own = new Set(asked.map((q) => q.key));
  return existing
    .filter((a) => !own.has(a.question_key) && a.answer != null)
    .map(({ question_key, topic, question, answer }) => ({ question_key, topic, question, answer }));
}

/** What Save sends, the whole questionnaire: the form's questions it shows
    with an answer, in its order and with its wording and topic; then the
    other answers, one emptied in its box left out, which deletes it. */
export function toSave(
  questions: SurveyQuestion[],
  answers: Record<string, string>,
  others: SurveyAnswer[],
): SurveyAnswer[] {
  const asked = questions
    .filter((q) => isVisible(q, answers) && (answers[q.key] ?? "") !== "")
    .map((q) => ({ question_key: q.key, topic: q.topic, question: q.text, answer: answers[q.key] }));
  const kept = others.filter((a) => (a.answer ?? "").trim() !== "");
  return [...asked, ...kept];
}

/** How an answer the form does not ask is named on the page. */
export function askedAs(answer: SurveyAnswer): string {
  return (answer.question ?? "").trim() || answer.question_key;
}
