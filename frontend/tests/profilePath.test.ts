import { test } from "node:test";
import assert from "node:assert/strict";

import type { SurveyQuestion } from "../src/api/survey.ts";
import {
  PARTS,
  currentPart,
  leaveQuestion,
  mainKey,
  partOf,
  partStatus,
  questionsOf,
  unsavedWords,
} from "../src/components/profilePath.ts";

// Invented questions in the backend's topics: a yes/no with a follow-up and a
// text in "About you", the free text in "In your words".
const QUESTIONS = [
  { key: "move", topic: "About you", text: "Do you plan to move?", type: "boolean", options: [], unsure: false },
  {
    key: "move_when", topic: "About you", text: "When?", type: "text", options: [], unsure: false,
    show_if: { key: "move", equals: "yes" },
  },
  { key: "town", topic: "Housing & city", text: "Which town?", type: "text", options: [], unsure: false },
  { key: "story", topic: "In your words", text: "Write freely.", type: "longtext", options: [], unsure: false },
] as unknown as SurveyQuestion[];

test("the path reads who you are, then your own words, then what you want", () => {
  assert.deepEqual(
    PARTS.map((p) => [p.key, p.title]),
    [
      ["situation", "Your situation"],
      ["words", "In your words"],
      ["goals", "Your goals"],
    ],
  );
});

test("a topic is read in its part, and a topic the page does not know in the first", () => {
  assert.equal(partOf("About you"), "situation");
  assert.equal(partOf("Risk & values"), "situation");
  assert.equal(partOf("In your words"), "words");
  assert.equal(partOf("Lifestyle"), "words");
  assert.equal(partOf("A topic added later"), "situation");
  assert.equal(partOf(null), "situation");
});

test("a part counts the questions it shows, a follow-up once it is shown", () => {
  assert.deepEqual(questionsOf("situation", QUESTIONS, { move: "yes" }).map((q) => q.key), ["move", "move_when", "town"]);
  assert.equal(partStatus("situation", QUESTIONS, { move: "yes" }, 0), "1 of 3 answered");
  assert.equal(partStatus("situation", QUESTIONS, { move: "no", move_when: "2027" }, 0), "1 of 2 answered");
  assert.equal(partStatus("situation", QUESTIONS, { move: "yes", move_when: " ", town: "Example Town" }, 0), "2 of 3 answered");
  assert.equal(partStatus("words", QUESTIONS, {}, 0), "0 of 1 answered");
});

test("the goals' part counts goals", () => {
  assert.equal(partStatus("goals", QUESTIONS, {}, 0), "none yet");
  assert.equal(partStatus("goals", QUESTIONS, {}, 1), "1 goal");
  assert.equal(partStatus("goals", QUESTIONS, {}, 3), "3 goals");
});

test("the part in view is the last one past a third of the room under the strip", () => {
  const tops = [100, 900, 1500];
  const view = { stripBottom: 60, height: 900, pageHeight: 3000 };
  // The line: scrolled + 60 + (900 - 60) / 3, so scrolled + 340.
  assert.equal(currentPart(tops, { ...view, scrolled: 0 }), 0);
  assert.equal(currentPart(tops, { ...view, scrolled: 559 }), 0);
  assert.equal(currentPart(tops, { ...view, scrolled: 560 }), 1);
  assert.equal(currentPart(tops, { ...view, scrolled: 1160 }), 2);
});

test("at the page's end the last part in view is the one, however short", () => {
  const tops = [100, 900, 2800];
  const view = { stripBottom: 60, height: 900, pageHeight: 3000 };
  // Its start never reaches the line (at most 2,100 + 340 = 2,440); the end
  // is the last 2px of scroll (2,100 is as far as the page goes).
  assert.equal(currentPart(tops, { ...view, scrolled: 2097 }), 1);
  assert.equal(currentPart(tops, { ...view, scrolled: 2098 }), 2);
  assert.equal(currentPart(tops, { ...view, scrolled: 2100 }), 2);
});

test("the strip says what is not saved, or nothing", () => {
  assert.equal(unsavedWords({ situation: 0, words: 0, goals: 0 }), null);
  assert.equal(unsavedWords({ situation: 1, words: 0, goals: 0 }), "1 change not saved");
  assert.equal(unsavedWords({ situation: 2, words: 0, goals: 1 }), "3 changes not saved");
});

test("leaving asks how many changes wait, and in which parts", () => {
  assert.equal(leaveQuestion({ situation: 0, words: 0, goals: 0 }), null);
  assert.equal(
    leaveQuestion({ situation: 1, words: 0, goals: 2 }),
    "Your profile has 3 changes not saved: 1 in your situation and 2 in your goals. Leave without saving them?",
  );
  assert.equal(
    leaveQuestion({ situation: 0, words: 1, goals: 0 }),
    "Your profile has 1 change not saved: 1 in your words. Leave without saving them?",
  );
  assert.equal(
    leaveQuestion({ situation: 2, words: 1, goals: 1 }),
    "Your profile has 4 changes not saved: 2 in your situation, 1 in your words and 1 in your goals. Leave without saving them?",
  );
});

test("a ledger write from the banner remounts the page in view, never the Profile", () => {
  assert.equal(mainKey("profile", 0), mainKey("profile", 1));
  assert.notEqual(mainKey("dashboard", 0), mainKey("dashboard", 1));
  assert.notEqual(mainKey("portfolio", 3), mainKey("portfolio", 4));
});
