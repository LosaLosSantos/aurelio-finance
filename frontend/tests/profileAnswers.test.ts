import { test } from "node:test";
import assert from "node:assert/strict";

import type { SurveyAnswerRead, SurveyQuestion } from "../src/api/survey.ts";
import { askedAs, othersOf, toSave } from "../src/components/profileAnswers.ts";

// Two invented questions of the form, the second a follow-up of the first.
const QUESTIONS = [
  { key: "move", topic: "Plans", text: "Do you plan to move?", type: "boolean", options: [], unsure: false },
  {
    key: "move_when", topic: "Plans", text: "When?", type: "text", options: [], unsure: false,
    show_if: { key: "move", equals: "yes" },
  },
] as unknown as SurveyQuestion[];

function stored(question_key: string, answer: string | null, question: string | null = null): SurveyAnswerRead {
  return { id: 1, created_at: "2026-10-10T08:00:00+00:00", question_key, topic: "Other", question, answer };
}

test("the answers the form does not ask are the ones it lists apart", () => {
  const existing = [
    stored("move", "yes"),
    stored("calm_in_a_fall", "I held", "How did you react to the last fall?"),
    stored("nothing_said", null, "Anything else?"),
  ];
  assert.deepEqual(othersOf(QUESTIONS, existing), [
    { question_key: "calm_in_a_fall", topic: "Other", question: "How did you react to the last fall?", answer: "I held" },
  ]);
});

test("save sends the form's shown answers in its order, then the others", () => {
  const others = [{ question_key: "calm_in_a_fall", topic: "Other", question: "How?", answer: "I held" }];
  assert.deepEqual(toSave(QUESTIONS, { move: "yes", move_when: "2027" }, others), [
    { question_key: "move", topic: "Plans", question: "Do you plan to move?", answer: "yes" },
    { question_key: "move_when", topic: "Plans", question: "When?", answer: "2027" },
    others[0],
  ]);
});

test("an answer emptied in its box is left out of the save, which deletes it", () => {
  const others = [
    { question_key: "calm_in_a_fall", topic: "Other", question: "How?", answer: "  " },
    { question_key: "kept", topic: "Other", question: "Kept?", answer: "yes" },
  ];
  assert.deepEqual(
    toSave(QUESTIONS, { move: "no" }, others).map((a) => a.question_key),
    ["move", "kept"],
  );
});

test("a follow-up the form no longer shows is left out, as the backend leaves it out", () => {
  assert.deepEqual(
    toSave(QUESTIONS, { move: "no", move_when: "2027" }, []).map((a) => a.question_key),
    ["move"],
  );
});

test("an answer is named by its question, or by its key when it has none", () => {
  assert.equal(askedAs({ question_key: "k", question: "Asked?", answer: "a" }), "Asked?");
  assert.equal(askedAs({ question_key: "k", question: null, answer: "a" }), "k");
});
