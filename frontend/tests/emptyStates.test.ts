import { test } from "node:test";
import assert from "node:assert/strict";

import { EMPTY_LINES, EMPTY_PANELS } from "../src/components/emptyStates.ts";

const lines = Object.entries(EMPTY_LINES);
const panels = Object.entries(EMPTY_PANELS);
const all = [...lines, ...panels.map(([k, p]) => [k, p.text] as const)];

// Where a first step is taken: the form above the line, a page of Records, or
// the chat.
const PLACES = /\babove\b|\bRecords\b|\bthe chat\b/;

test("every empty section says where its first step is taken", () => {
  for (const [key, text] of all) assert.match(text, PLACES, `${key}: ${text}`);
});

test("every empty section says more than that it is empty: what it is for, then the step", () => {
  for (const [key, text] of all) {
    assert.doesNotMatch(text, /^No [\w ]+ yet\.$/, `${key} is a bare line`);
    // A second clause after the first: a colon, a semicolon or a sentence.
    assert.match(text, /[.:;] \S/, `${key} says one thing only: ${text}`);
  }
});

test("the words are the reader's, not the app's tables", () => {
  for (const [key, text] of all) {
    assert.doesNotMatch(text, /\binstitutions?\b|\banchors?\b|\bsnapshots?\b/i, `${key}: ${text}`);
  }
});

test("each is a line of its own: one paragraph, ended, with no long dash", () => {
  for (const [key, text] of all) {
    assert.ok(!text.includes("\n"), `${key} breaks a line`);
    assert.ok(text.endsWith("."), `${key} is not ended`);
    assert.ok(!text.includes(String.fromCharCode(0x2014)), `${key} has an em dash`);
    assert.ok(!text.includes(String.fromCharCode(0x2013)), `${key} has an en dash`);
  }
});

test("the two pages empty as a whole name their first step on a button", () => {
  assert.deepEqual(panels.map(([k]) => k), ["dashboard", "portfolio"]);
  for (const [key, p] of panels) {
    assert.ok(p.title.length > 0, `${key} has no title`);
    assert.equal(p.action, "Add a bank or broker");
  }
});

test("the Dashboard's panel no longer says that only Wealth draws the page", () => {
  assert.doesNotMatch(EMPTY_PANELS.dashboard.text, /from nothing else/);
});
