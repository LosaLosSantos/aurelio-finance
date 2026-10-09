/* The Profile form's questions, read as the form reads them.

   The list itself is the backend's (`GET /api/survey/questions`), the one the
   chat's answers are checked against: brief AL moved it out of Profile.tsx
   after the chat wrote a goal into a yes/no question, which the form then had
   no button to show. A stored answer the form cannot show is shown here in
   words, and nothing replaces it until the reader does.

   No runtime imports, so `npm test` reaches it. */

import type { SurveyQuestion } from "../api/survey";

/** What the form offers to press or pick, in its order: yes and no ("unsure"
    between them where offered), the options of a choice, nothing for a
    question answered in words or digits. */
export function choicesOf(q: SurveyQuestion): string[] {
  if (q.type === "boolean") return q.unsure ? ["yes", "unsure", "no"] : ["yes", "no"];
  if (q.type === "single") return q.options;
  return [];
}

/** Whether the form can show `value` as `q`'s answer: one of its choices, a
    number in a number box, any words in a text box. Nothing stored is shown
    as nothing. */
export function canShow(q: SurveyQuestion, value: string): boolean {
  if (value === "") return true;
  const choices = choicesOf(q);
  if (choices.length > 0) return choices.includes(value);
  if (q.type === "number") return value.trim() !== "" && Number.isFinite(Number(value));
  return true;
}

/** The sentence under a question whose stored answer the form cannot show,
    or null when it can. The answer stays on record until the reader picks
    another: a save without one sends it back as it was. */
export function unshownAnswer(q: SurveyQuestion, value: string): string | null {
  if (canShow(q, value)) return null;
  const replace =
    q.type === "boolean"
      ? "which is none of these answers. Press one"
      : q.type === "single"
        ? "which is none of these options. Pick one"
        : "which is not a number. Type one";
  return `On record: "${value}", ${replace} to replace it; saved without one, it stays as it is.`;
}

/** Whether `q` is shown, given the answers so far: a question that follows
    another is shown only while that one's answer is the one it follows. */
export function isVisible(q: SurveyQuestion, answers: Record<string, string>): boolean {
  return !q.show_if || answers[q.show_if.key] === q.show_if.equals;
}

/** The topics, in the order the questions bring them. */
export function topicsOf(questions: SurveyQuestion[]): string[] {
  return [...new Set(questions.map((q) => q.topic))];
}
