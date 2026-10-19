/* "Save profile": the one save of the Profile tab (brief BC).

   It writes what the three blocks used to write with two buttons: the
   answers (`PUT /api/survey`, the whole set), the tax rates, the goals (one
   request each, `goalDrafts.ts`) and the base currency, last, so a rate feed
   that does not answer leaves everything else saved.

   `PUT /api/survey` replaces the whole set, and the page used to send the set
   as it had read it: an answer the chat recorded while the page was open was
   deleted by the page's next save (measured, brief BC's P0). So the save
   first reads what is stored now and lays the reader's changes over it: what
   the reader changed, against what the page read, is theirs; everything else
   is as stored, the chat's answers included. The goals and the base are read
   again only when the save carries them. Something changed on both sides is
   asked about, once and before anything is written, and never picked in
   silence. When nothing changed elsewhere, the answers sent are byte for
   byte what the page sent before.

   A refused request stops the save there: what was written before it is
   saved and said so, the refused one says the backend's sentence, the rest
   waits for the next save.

   No runtime imports outside these pure modules, so `npm test` reaches it:
   the requests are given to it. */

import type { BaseCurrencySetting } from "../api/baseCurrency";
import type { Goal, GoalCreate } from "../api/goals";
import type { SurveyAnswer, SurveyAnswerRead, SurveyQuestion } from "../api/survey";
import type { TaxSettings, TaxSettingsRead } from "../api/tax";
import {
  goalConflicts,
  pending,
  refusedAt,
  resolve,
  shownAs,
  writeOf,
  written,
  type GoalConflict,
  type GoalDraft,
} from "./goalDrafts.ts";
import { othersOf, toSave } from "./profileAnswers.ts";
import { partOf, type Waiting } from "./profilePath.ts";
import { isVisible } from "./questionnaire.ts";

function said(a: SurveyAnswer | undefined): string | null {
  return a?.answer ?? null;
}

function byKey(list: SurveyAnswer[]): Map<string, SurveyAnswer> {
  return new Map(list.map((a) => [a.question_key, a]));
}

/** An answer as a save sends it, from one as stored. */
export function asSent(a: SurveyAnswerRead): SurveyAnswer {
  return { question_key: a.question_key, topic: a.topic, question: a.question, answer: a.answer };
}

/** An answer changed on both sides since the page read it. */
export interface AnswerConflict {
  question: string;
  stored: string | null;
  here: string | null;
}

/** The answers a save sends: the reader's changes (`now` against `loaded`,
    both as a save sends them) laid over the answers as stored now. An answer
    changed on both sides, to different words, is a conflict, and `choice`
    takes the reader's ("here") or the one on record ("stored"). The form's
    rule for follow-ups applies to the merged set, so a follow-up whose
    answer no longer reads "yes" goes, as the form's save drops it. */
export function laidOver(
  questions: SurveyQuestion[],
  loaded: SurveyAnswer[],
  now: SurveyAnswer[],
  stored: SurveyAnswer[],
  choice: "here" | "stored",
): { body: SurveyAnswer[]; conflicts: AnswerConflict[] } {
  const L = byKey(loaded);
  const N = byKey(now);
  const S = byKey(stored);
  const order = [...new Set([...now.map((a) => a.question_key), ...stored.map((a) => a.question_key)])];
  const keys = [...new Set([...order, ...loaded.map((a) => a.question_key)])];
  const conflicts: AnswerConflict[] = [];
  const final = new Map<string, SurveyAnswer>();
  for (const k of keys) {
    const mine = said(N.get(k)) !== said(L.get(k));
    const theirs = said(S.get(k)) !== said(L.get(k));
    let take: SurveyAnswer | undefined;
    if (mine && theirs && said(N.get(k)) !== said(S.get(k))) {
      const entry = N.get(k) ?? S.get(k) ?? L.get(k);
      conflicts.push({ question: entry?.question || k, stored: said(S.get(k)), here: said(N.get(k)) });
      take = choice === "here" ? N.get(k) : S.get(k);
    } else if (mine) {
      take = N.get(k);
    } else {
      // Not the reader's: as stored, in the page's words while they agree.
      take = theirs ? S.get(k) : (N.get(k) ?? S.get(k));
    }
    if (take) final.set(k, take);
  }
  const merged = order.filter((k) => final.has(k)).map((k) => final.get(k) as SurveyAnswer);
  const answers: Record<string, string> = {};
  for (const a of merged) answers[a.question_key] = a.answer ?? "";
  const asked = new Map(questions.map((q) => [q.key, q]));
  const body = merged.filter((a) => {
    const q = asked.get(a.question_key);
    return !q || isVisible(q, answers);
  });
  return { body, conflicts };
}

/** What the page holds once it takes the answers as stored: the form's
    answers, the other answers, and `loaded`, what "not saved" is counted
    against. After a save, `stored` is what the save wrote. After a Cancel,
    `merged` is `laidOver(..., "stored")`'s body: what is on record, with the
    reader's changes that were not in question still waiting over it. */
export function pageFrom(
  questions: SurveyQuestion[],
  stored: SurveyAnswerRead[],
  merged?: SurveyAnswer[],
): { answers: Record<string, string>; others: SurveyAnswer[]; loaded: SurveyAnswer[] } {
  const asked = new Set(questions.map((q) => q.key));
  const map: Record<string, string> = {};
  for (const a of stored) if (asked.has(a.question_key) && a.answer != null) map[a.question_key] = a.answer;
  const others = othersOf(questions, stored);
  const loaded = toSave(questions, map, others);
  if (!merged) return { answers: map, others, loaded };
  const shown: Record<string, string> = {};
  for (const a of merged) if (asked.has(a.question_key) && a.answer != null) shown[a.question_key] = a.answer;
  return { answers: shown, others: merged.filter((a) => !asked.has(a.question_key)), loaded };
}

/** The base changed on both sides, to different currencies. */
export interface BaseConflict {
  stored: string;
  here: string;
}

export function baseConflict(loaded: string, picked: string, stored: string): BaseConflict | null {
  return picked !== loaded && stored !== loaded && stored !== picked ? { stored, here: picked } : null;
}

function quoted(v: string | null): string {
  return v === null || v.trim() === "" ? "no answer" : `"${v}"`;
}

/** What the page asks when something changed on both sides, or null. */
export function conflictQuestion(c: {
  answers: AnswerConflict[];
  goals: GoalConflict[];
  base: BaseConflict | null;
}): string | null {
  const lines = [
    ...c.answers.map((a) => `- "${a.question}": on record now ${quoted(a.stored)}, on this page ${quoted(a.here)}`),
    ...c.goals.map((g) => `- the goal "${g.name}": ${g.elsewhere} elsewhere, ${g.here} on this page`),
    ...(c.base ? [`- the base currency: on record now ${c.base.stored}, on this page ${c.base.here}`] : []),
  ];
  if (lines.length === 0) return null;
  return [
    "While this page was open, your profile was also changed elsewhere (the chat writes answers, goals and the base currency too). Changed on both sides:",
    ...lines,
    "OK saves this page's over them. Cancel saves nothing and shows what is on record for these; your other changes wait for the next save.",
  ].join("\n");
}

/** The tax settings as a save sends them, from the page's three boxes: an
    empty box clears its key rather than storing 0, so "not said" has one
    representation instead of three that look identical on screen. */
export function taxToSend(country: string, capitalGains: string, dividends: string): TaxSettings {
  return {
    country: country.trim() || null,
    capital_gains_rate: capitalGains === "" ? null : Number(capitalGains),
    dividend_withholding_rate: dividends === "" ? null : Number(dividends),
  };
}

/** What waits for the save, by the part it belongs to (`profilePath.ts`):
    each answer the reader changed, in its question's part (an answer the form
    does not ask is read in "In your words"); each tax field and the base, in
    "Your situation"; each goal, in "Your goals". */
export function waiting(args: {
  questions: SurveyQuestion[];
  loaded: SurveyAnswer[];
  now: SurveyAnswer[];
  tax: { stored: TaxSettings; now: TaxSettings };
  base: { loaded: string; picked: string };
  drafts: GoalDraft[];
}): Waiting {
  const w: Waiting = { situation: 0, words: 0, goals: pending(args.drafts) };
  const L = byKey(args.loaded);
  const N = byKey(args.now);
  const asked = new Map(args.questions.map((q) => [q.key, q]));
  for (const k of new Set([...L.keys(), ...N.keys()])) {
    if (said(L.get(k)) === said(N.get(k))) continue;
    const q = asked.get(k);
    w[q ? partOf(q.topic) : "words"] += 1;
  }
  const { stored, now } = args.tax;
  if ((stored.country ?? null) !== (now.country ?? null)) w.situation += 1;
  if ((stored.capital_gains_rate ?? null) !== (now.capital_gains_rate ?? null)) w.situation += 1;
  if ((stored.dividend_withholding_rate ?? null) !== (now.dividend_withholding_rate ?? null)) w.situation += 1;
  if (args.base.picked !== args.base.loaded) w.situation += 1;
  return w;
}

/** The requests, given by the page (the API's own functions) or by a test. */
export interface SaveApi {
  getSurvey: () => Promise<SurveyAnswerRead[]>;
  putSurvey: (body: SurveyAnswer[]) => Promise<SurveyAnswerRead[]>;
  putTax: (body: TaxSettings) => Promise<TaxSettingsRead>;
  getGoals: () => Promise<Goal[]>;
  postGoal: (body: GoalCreate) => Promise<Goal>;
  putGoal: (id: number, body: GoalCreate) => Promise<Goal>;
  deleteGoal: (id: number) => Promise<void>;
  getBase: () => Promise<BaseCurrencySetting>;
  putBase: (code: string) => Promise<BaseCurrencySetting>;
  /** Asks the reader; true goes on. The page gives the browser's confirm. */
  ask: (question: string) => boolean;
  /** The backend's own sentence for a refused request. */
  sentence: (err: unknown, fallback: string) => string;
}

export interface SaveInput {
  questions: SurveyQuestion[];
  /** The answers as the page read them, as a save sends them. */
  loaded: SurveyAnswer[];
  /** What the page holds, as a save sends it. */
  now: SurveyAnswer[];
  tax: TaxSettings;
  drafts: GoalDraft[];
  base: { loaded: string; picked: string };
}

/** What a press of "Save profile" did. Each field is set only when it is
    true of the backend: a request taken, or a read made. */
export interface SaveResult {
  /** The answers as stored after the save, when that request was taken. */
  survey: SurveyAnswerRead[] | null;
  /** The answers as stored when the save read them (taken by the page when
      the reader cancels, so it shows what is on record). */
  read: SurveyAnswerRead[] | null;
  tax: TaxSettingsRead | null;
  /** The page's goals after the save: those written as stored, the refused
      one with its sentence, the rest as they wait. */
  drafts: GoalDraft[];
  /** The base after the save, or as read when the reader cancelled. */
  base: BaseCurrencySetting | null;
  /** The reader cancelled the question: nothing was written. */
  keptBack: boolean;
  /** What was refused, in the backend's words; null when nothing was. */
  refused: string | null;
  /** The goal the save was refused at, by name, when it was a goal's request:
      its row carries the backend's sentence. */
  refusedGoal: string | null;
}

/** What the strip says of a save refused part way: a goal's refusal points
    at its row, which says why, so the strip stays a line or two on a phone;
    any other refusal is said in full there, the one place it is said. */
export function refusalWords(result: Pick<SaveResult, "refused" | "refusedGoal">): string | null {
  if (result.refused === null) return null;
  if (result.refusedGoal !== null) {
    return `The goal "${result.refusedGoal}" was not saved: its row says why. Everything before it was saved; the rest waits.`;
  }
  return result.refused;
}

export async function saveProfile(input: SaveInput, api: SaveApi): Promise<SaveResult> {
  const result: SaveResult = {
    survey: null, read: null, tax: null, drafts: input.drafts, base: null, keptBack: false, refused: null, refusedGoal: null,
  };
  const moveBase = input.base.picked !== input.base.loaded;
  let storedGoals: Goal[] | null = null;
  let storedBase: BaseCurrencySetting | null = null;
  try {
    result.read = await api.getSurvey();
    if (pending(input.drafts) > 0) storedGoals = await api.getGoals();
    if (moveBase) storedBase = await api.getBase();
  } catch (err) {
    result.refused = `Nothing was saved: the profile on record could not be read. ${api.sentence(err, "")}`.trim();
    return result;
  }

  const stored = result.read.map(asSent);
  const answers = laidOver(input.questions, input.loaded, input.now, stored, "here");
  const goals = storedGoals ? goalConflicts(input.drafts, storedGoals) : [];
  const base = storedBase ? baseConflict(input.base.loaded, input.base.picked, storedBase.base_currency) : null;
  const question = conflictQuestion({ answers: answers.conflicts, goals, base });
  if (question !== null && !api.ask(question)) {
    result.keptBack = true;
    if (storedGoals) result.drafts = resolve(input.drafts, storedGoals, "stored");
    result.base = storedBase;
    return result;
  }

  try {
    result.survey = await api.putSurvey(answers.body);
  } catch (err) {
    result.refused = `Nothing was saved: ${api.sentence(err, "the answers were refused.")}`;
    return result;
  }
  try {
    result.tax = await api.putTax(input.tax);
  } catch (err) {
    result.refused = `The tax rates were not saved: ${api.sentence(err, "they were refused.")}`;
    return result;
  }

  const drafts = storedGoals ? resolve(input.drafts, storedGoals, "here") : [...input.drafts];
  const after: GoalDraft[] = [];
  for (let i = 0; i < drafts.length; i++) {
    const d = drafts[i];
    const w = writeOf(d);
    if (w === null) {
      after.push(d);
      continue;
    }
    try {
      let answer: Goal | null = null;
      if (w.method === "POST") answer = await api.postGoal(w.body);
      else if (w.method === "PUT") answer = await api.putGoal(w.id, w.body);
      else await api.deleteGoal(w.id);
      const kept = written(d, answer);
      if (kept) after.push(kept);
    } catch (err) {
      const sentence = api.sentence(err, "it was refused.");
      after.push(refusedAt(d, sentence), ...drafts.slice(i + 1));
      result.drafts = after;
      result.refused = `The goal "${shownAs(d).name}" was not saved: ${sentence}`;
      result.refusedGoal = shownAs(d).name;
      return result;
    }
  }
  result.drafts = after;

  if (moveBase) {
    try {
      result.base = await api.putBase(input.base.picked);
    } catch (err) {
      result.refused = `The base currency was not changed: ${api.sentence(err, "the change was refused.")}`;
      return result;
    }
  }
  return result;
}
