import { test } from "node:test";
import assert from "node:assert/strict";

import type { BaseCurrencySetting } from "../src/api/baseCurrency.ts";
import type { Goal, GoalCreate } from "../src/api/goals.ts";
import type { SurveyAnswer, SurveyAnswerRead, SurveyQuestion } from "../src/api/survey.ts";
import type { TaxSettings } from "../src/api/tax.ts";
import { fromStored, type GoalDraft } from "../src/components/goalDrafts.ts";
import { toSave } from "../src/components/profileAnswers.ts";
import {
  conflictQuestion,
  laidOver,
  pageFrom,
  refusalWords,
  saveProfile,
  taxToSend,
  waiting,
  type SaveApi,
} from "../src/components/profileSave.ts";

// Invented questions in the backend's shape: a yes/no with a follow-up, a
// town, an age, the free text.
const QUESTIONS = [
  { key: "move", topic: "About you", text: "Do you plan to move?", type: "boolean", options: [], unsure: false },
  {
    key: "move_when", topic: "About you", text: "When?", type: "text", options: [], unsure: false,
    show_if: { key: "move", equals: "yes" },
  },
  { key: "town", topic: "About you", text: "Which town?", type: "text", options: [], unsure: false },
  { key: "age", topic: "About you", text: "Your age?", type: "number", options: [], unsure: false },
  { key: "story", topic: "In your words", text: "Write freely.", type: "longtext", options: [], unsure: false },
] as unknown as SurveyQuestion[];

function sent(question_key: string, answer: string | null, topic = "About you", question: string | null = null): SurveyAnswer {
  const q = QUESTIONS.find((x) => x.key === question_key);
  return { question_key, topic: q ? q.topic : topic, question: q ? q.text : question, answer };
}

function read(a: SurveyAnswer, id = 1): SurveyAnswerRead {
  return {
    question_key: a.question_key, topic: a.topic ?? null, question: a.question ?? null, answer: a.answer ?? null,
    id, created_at: "2026-10-19T08:00:00+00:00",
  };
}

// The other answer the chat records (`update_profile`) while the page is open.
const RETIRE = sent("retire_at", "55", "Retirement & horizon", "At what age would you like to retire?");

test("an answer written elsewhere while the page is open is kept when a city typed here is saved", () => {
  // P0's measured case: the page read nothing, the chat wrote one answer,
  // the reader typed a town.
  const loaded: SurveyAnswer[] = [];
  const now = [sent("town", "Example Town")];
  const { body, conflicts } = laidOver(QUESTIONS, loaded, now, [RETIRE], "here");
  assert.deepEqual(body, [sent("town", "Example Town"), RETIRE]);
  assert.deepEqual(conflicts, []);
});

test("with nothing changed elsewhere, the answers sent are the page's, byte for byte", () => {
  const answers = { move: "yes", move_when: "2027", age: "36" };
  const others = [RETIRE];
  const loaded = toSave(QUESTIONS, { move: "no", age: "36" }, others);
  const now = toSave(QUESTIONS, answers, others);
  const { body, conflicts } = laidOver(QUESTIONS, loaded, now, loaded, "here");
  assert.deepEqual(body, now);
  assert.deepEqual(conflicts, []);
});

test("an answer changed only elsewhere is kept, not the page's older copy of it", () => {
  const loaded = [sent("age", "36"), sent("town", "Old Town")];
  const now = [sent("age", "36"), sent("town", "New Town")];
  const stored = [sent("age", "37"), sent("town", "Old Town")];
  assert.deepEqual(laidOver(QUESTIONS, loaded, now, stored, "here").body, [sent("age", "37"), sent("town", "New Town")]);
});

test("the same answer changed on both sides is asked about, with both, and the choice decides", () => {
  const loaded = [sent("age", "36")];
  const now = [sent("age", "38")];
  const stored = [sent("age", "37")];
  const here = laidOver(QUESTIONS, loaded, now, stored, "here");
  assert.deepEqual(here.conflicts, [{ question: "Your age?", stored: "37", here: "38" }]);
  assert.deepEqual(here.body, [sent("age", "38")]);
  assert.deepEqual(laidOver(QUESTIONS, loaded, now, stored, "stored").body, [sent("age", "37")]);
  // Changed on both sides to the same words: nothing to ask.
  assert.deepEqual(laidOver(QUESTIONS, loaded, [sent("age", "37")], stored, "here").conflicts, []);
});

test("an answer emptied here goes, and one deleted elsewhere stays gone", () => {
  const loaded = [sent("age", "36"), sent("town", "Old Town"), RETIRE];
  const now = [sent("town", "Old Town"), RETIRE];
  const stored = [sent("age", "36"), sent("town", "Old Town")];
  assert.deepEqual(laidOver(QUESTIONS, loaded, now, stored, "here").body, [sent("town", "Old Town")]);
});

test("a follow-up whose answer no longer reads yes goes from the merged set, as the form's save drops it", () => {
  const loaded = [sent("move", "yes"), sent("move_when", "2027")];
  const now = [sent("move", "yes"), sent("move_when", "2027"), sent("town", "Example Town")];
  // Elsewhere, the move was answered "no" and its follow-up taken away.
  const stored = [sent("move", "no")];
  assert.deepEqual(laidOver(QUESTIONS, loaded, now, stored, "here").body, [sent("move", "no"), sent("town", "Example Town")]);
});

test("the question names every field changed on both sides, with both values", () => {
  assert.equal(conflictQuestion({ answers: [], goals: [], base: null }), null);
  assert.equal(
    conflictQuestion({
      answers: [{ question: "Your age?", stored: "37", here: "38" }, { question: "Which town?", stored: null, here: "Example Town" }],
      goals: [{ name: "A new car", elsewhere: "deleted", here: "changed" }],
      base: { stored: "USD", here: "GBP" },
    }),
    [
      "While this page was open, your profile was also changed elsewhere (the chat writes answers, goals and the base currency too). Changed on both sides:",
      '- "Your age?": on record now "37", on this page "38"',
      '- "Which town?": on record now no answer, on this page "Example Town"',
      '- the goal "A new car": deleted elsewhere, changed on this page',
      "- the base currency: on record now USD, on this page GBP",
      "OK saves this page's over them. Cancel saves nothing and shows what is on record for these; your other changes wait for the next save.",
    ].join("\n"),
  );
});

test("the tax is sent as the page sent it: an empty box clears its key", () => {
  assert.deepEqual(taxToSend(" Germany ", "26", ""), { country: "Germany", capital_gains_rate: 26, dividend_withholding_rate: null });
  assert.deepEqual(taxToSend("", "", "0"), { country: null, capital_gains_rate: null, dividend_withholding_rate: 0 });
});

test("what waits is counted in the part it belongs to", () => {
  const loaded = [sent("age", "36"), sent("story", "Before"), RETIRE];
  const now = [sent("age", "37"), sent("story", "After"), sent("town", "Example Town")];
  const goals: GoalDraft[] = [{ kind: "added", ref: "new:1", now: { name: "Rainy days", type: "emergency_fund", currency: "EUR" } }];
  assert.deepEqual(
    waiting({
      questions: QUESTIONS,
      loaded,
      now,
      tax: { stored: { country: null, capital_gains_rate: 26, dividend_withholding_rate: null }, now: taxToSend("Germany", "26", "") },
      base: { loaded: "EUR", picked: "CHF" },
      drafts: goals,
    }),
    // age and town, the country and the base; the story and the chat's answer
    // (deleted here); one goal.
    { situation: 4, words: 2, goals: 1 },
  );
});

test("after a save the page holds what was stored, and counts nothing waiting", () => {
  const stored = [read(sent("move", "yes")), read(sent("move_when", "2027"), 2), read(RETIRE, 3)];
  const page = pageFrom(QUESTIONS, stored);
  assert.deepEqual(page.answers, { move: "yes", move_when: "2027" });
  assert.deepEqual(page.others, [RETIRE]);
  assert.deepEqual(page.loaded, [sent("move", "yes"), sent("move_when", "2027"), RETIRE]);
});

// --- the save itself, its requests given by a fake --------------------------

function goal(id: number, name: string): Goal {
  return {
    id, name, type: "long_term_growth", currency: "EUR", target_amount: null, target_date: null,
    current_amount: null, monthly_contribution: null, notes: null, created_at: "2026-10-19T08:00:00+00:00",
  };
}

class Refused extends Error {
  sentence: string;
  constructor(sentence: string) {
    super(sentence);
    this.sentence = sentence;
  }
}

function fake(stored: { survey: SurveyAnswer[]; goals: Goal[]; base: string }, opts: { refuse?: (call: string) => string | null; answer?: boolean } = {}) {
  const calls: string[] = [];
  const asked: string[] = [];
  let nextId = 100;
  const go = <T,>(call: string, value: () => T): Promise<T> => {
    calls.push(call);
    const no = opts.refuse?.(call) ?? null;
    return no === null ? Promise.resolve(value()) : Promise.reject(new Refused(no));
  };
  const api: SaveApi = {
    getSurvey: () => go("GET /api/survey", () => stored.survey.map((a, i) => read(a, i + 1))),
    putSurvey: (body) => go(`PUT /api/survey ${JSON.stringify(body.map((a) => [a.question_key, a.answer]))}`, () => body.map((a, i) => read(a, i + 1))),
    putTax: (body: TaxSettings) =>
      go(`PUT /api/settings/tax ${JSON.stringify(body)}`, () => ({
        country: body.country ?? null,
        capital_gains_rate: body.capital_gains_rate ?? null,
        dividend_withholding_rate: body.dividend_withholding_rate ?? null,
        known_countries: [],
      })),
    getGoals: () => go("GET /api/goals", () => stored.goals),
    postGoal: (body: GoalCreate) => go(`POST /api/goals ${body.name}`, () => ({ ...goal(nextId++, body.name), ...body })),
    putGoal: (id: number, body: GoalCreate) => go(`PUT /api/goals/${id} ${body.name}`, () => ({ ...goal(id, body.name), ...body })),
    deleteGoal: (id: number) => go(`DELETE /api/goals/${id}`, () => undefined),
    getBase: () => go("GET /api/settings/base-currency", (): BaseCurrencySetting => ({ base_currency: stored.base, available: [] })),
    putBase: (code: string) => go(`PUT /api/settings/base-currency ${code}`, (): BaseCurrencySetting => ({ base_currency: code, available: [] })),
    ask: (question: string) => {
      asked.push(question);
      return opts.answer ?? true;
    },
    sentence: (err: unknown, fallback: string) => (err instanceof Refused ? err.sentence : fallback),
  };
  return { api, calls, asked };
}

const TAX = taxToSend("", "26", "");
const G1 = goal(1, "Retire at 60");
const G2 = goal(2, "A new car");
const G3 = goal(3, "Emergency fund");

function threeGoals(): GoalDraft[] {
  return [
    { kind: "changed", ref: "id:1", goal: G1, now: { ...G1, name: "Retire at 58" } },
    { kind: "added", ref: "new:1", now: { name: "Rainy days", type: "emergency_fund", currency: "EUR" } },
    { kind: "deleted", ref: "id:3", goal: G3 },
    { kind: "kept", ref: "id:2", goal: G2 },
  ];
}

test("one save sends the answers laid over what is stored, the tax, each goal in order, the base last", async () => {
  const { api, calls, asked } = fake({ survey: [RETIRE], goals: [G1, G2, G3], base: "EUR" });
  const result = await saveProfile(
    { questions: QUESTIONS, loaded: [], now: [sent("town", "Example Town")], tax: TAX, drafts: threeGoals(), base: { loaded: "EUR", picked: "CHF" } },
    api,
  );
  assert.deepEqual(calls, [
    "GET /api/survey",
    "GET /api/goals",
    "GET /api/settings/base-currency",
    'PUT /api/survey [["town","Example Town"],["retire_at","55"]]',
    'PUT /api/settings/tax {"country":null,"capital_gains_rate":26,"dividend_withholding_rate":null}',
    "PUT /api/goals/1 Retire at 58",
    "DELETE /api/goals/3",
    "POST /api/goals Rainy days",
    "PUT /api/settings/base-currency CHF",
  ]);
  assert.deepEqual(asked, []);
  assert.equal(result.refused, null);
  assert.equal(result.keptBack, false);
  assert.deepEqual(result.drafts.map((d) => [d.kind, d.kind === "kept" ? d.goal.name : ""]), [
    ["kept", "Retire at 58"],
    ["kept", "A new car"],
    ["kept", "Rainy days"],
  ]);
  assert.equal(result.base?.base_currency, "CHF");
});

test("a save that carries no goal and no base reads only the answers", async () => {
  const { api, calls } = fake({ survey: [], goals: [G1], base: "EUR" });
  await saveProfile(
    { questions: QUESTIONS, loaded: [], now: [sent("age", "36")], tax: TAX, drafts: fromStored([G1]), base: { loaded: "EUR", picked: "EUR" } },
    api,
  );
  assert.deepEqual(calls, ["GET /api/survey", 'PUT /api/survey [["age","36"]]', 'PUT /api/settings/tax {"country":null,"capital_gains_rate":26,"dividend_withholding_rate":null}']);
});

test("refused at the second goal: what came before is saved and said so, that goal waits with its sentence, the rest waits", async () => {
  const { api, calls } = fake(
    { survey: [], goals: [G1, G2, G3], base: "EUR" },
    { refuse: (call) => (call === "DELETE /api/goals/3" ? "Goal not found." : null) },
  );
  const result = await saveProfile(
    { questions: QUESTIONS, loaded: [], now: [sent("age", "36")], tax: TAX, drafts: threeGoals(), base: { loaded: "EUR", picked: "CHF" } },
    api,
  );
  // Nothing after the refusal was sent: not the third goal, not the base.
  assert.deepEqual(calls.slice(3), [
    'PUT /api/survey [["age","36"]]',
    'PUT /api/settings/tax {"country":null,"capital_gains_rate":26,"dividend_withholding_rate":null}',
    "PUT /api/goals/1 Retire at 58",
    "DELETE /api/goals/3",
  ]);
  assert.ok(result.survey, "the answers are saved, and the result says so");
  assert.ok(result.tax, "the tax is saved, and the result says so");
  assert.equal(result.base, null, "the base is not said to be saved");
  assert.equal(result.refused, 'The goal "Emergency fund" was not saved: Goal not found.');
  // The strip points at the row, which carries the sentence.
  assert.equal(refusalWords(result), 'The goal "Emergency fund" was not saved: its row says why. Everything before it was saved; the rest waits.');
  assert.deepEqual(
    result.drafts.map((d) => [d.kind, d.kind === "kept" ? d.goal.name : "", "error" in d ? d.error : undefined]),
    [
      ["kept", "Retire at 58", undefined],
      ["kept", "A new car", undefined],
      ["deleted", "", "Goal not found."],
      ["added", "", undefined],
    ],
  );
});

test("refused at the answers, nothing is saved and nothing said saved", async () => {
  const { api, calls } = fake({ survey: [], goals: [], base: "EUR" }, { refuse: (call) => (call.startsWith("PUT /api/survey") ? "answer: too long" : null) });
  const result = await saveProfile(
    { questions: QUESTIONS, loaded: [], now: [sent("age", "36")], tax: TAX, drafts: [], base: { loaded: "EUR", picked: "EUR" } },
    api,
  );
  assert.equal(calls.length, 2);
  assert.equal(result.survey, null);
  assert.equal(result.tax, null);
  assert.equal(result.refused, "Nothing was saved: answer: too long");
  // Not a goal's: the strip says it in full, the one place it is said.
  assert.equal(refusalWords(result), "Nothing was saved: answer: too long");
});

test("changed on both sides and Cancel pressed: the question is asked, and nothing is written", async () => {
  const { api, calls, asked } = fake({ survey: [sent("age", "37")], goals: [{ ...G1, name: "Retire early" }, G2, G3], base: "EUR" }, { answer: false });
  const result = await saveProfile(
    { questions: QUESTIONS, loaded: [sent("age", "36")], now: [sent("age", "38")], tax: TAX, drafts: threeGoals(), base: { loaded: "EUR", picked: "EUR" } },
    api,
  );
  assert.deepEqual(calls, ["GET /api/survey", "GET /api/goals"]);
  assert.equal(asked.length, 1);
  assert.ok(asked[0].includes('"Your age?": on record now "37", on this page "38"'));
  assert.ok(asked[0].includes('the goal "Retire at 60": changed elsewhere, changed on this page'));
  assert.equal(result.keptBack, true);
  assert.equal(result.survey, null);
  // The page takes what is on record for the goal in question; the others wait.
  assert.deepEqual(result.drafts.map((d) => d.kind), ["kept", "kept", "deleted", "added"]);
});

test("changed on both sides and OK pressed: the page's are written over", async () => {
  const { api, calls } = fake({ survey: [sent("age", "37")], goals: [], base: "EUR" }, { answer: true });
  const result = await saveProfile(
    { questions: QUESTIONS, loaded: [sent("age", "36")], now: [sent("age", "38")], tax: TAX, drafts: [], base: { loaded: "EUR", picked: "EUR" } },
    api,
  );
  assert.equal(calls[1], 'PUT /api/survey [["age","38"]]');
  assert.equal(result.refused, null);
});

test("the answers on record cannot be read: nothing is written", async () => {
  const { api, calls } = fake({ survey: [], goals: [], base: "EUR" }, { refuse: (call) => (call === "GET /api/survey" ? "The backend did not answer." : null) });
  const result = await saveProfile(
    { questions: QUESTIONS, loaded: [], now: [sent("age", "36")], tax: TAX, drafts: [], base: { loaded: "EUR", picked: "EUR" } },
    api,
  );
  assert.deepEqual(calls, ["GET /api/survey"]);
  assert.equal(result.refused, "Nothing was saved: the profile on record could not be read. The backend did not answer.");
});
