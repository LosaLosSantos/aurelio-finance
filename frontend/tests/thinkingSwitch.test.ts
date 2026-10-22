/* The chat's Thinking control: normal, or the model's one lighter position.

   Brief BF: the backend's menu gives each model its lighter position
   ("light" where it reasons less, "off" where it stops) and what was measured
   of it, or none. The control shows the position kept for the model in view,
   sends the lighter word or nothing, keeps a choice per model, and drops a
   kept choice the model no longer offers rather than sending it.

   Run by `npm test` with Node's own test runner. Type-checked by `tsc -b`
   through tsconfig.node.json. The models are the app's own; the measured
   sentences stand-ins. */

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  lighterOf,
  positionLabel,
  positionOf,
  readChoices,
  thinkingHelp,
  thinkingToSend,
  withPosition,
} from "../src/components/thinkingSwitch.ts";

const OPUS = "anthropic/claude-opus-5.5";
const SONNET = "anthropic/claude-sonnet-4.6";
const K26 = "moonshotai/kimi-k2.6";
const ELSEWHERE = "someone/a-model-set-in-env";

function entry(slug: string, thinking: { lighter: "light" | "off"; measured: string } | null) {
  return { slug, note: "a note", retires: null, listed: true, warning: null, searches: false, thinking };
}

const MENU = {
  default: OPUS,
  models: [
    entry(OPUS, { lighter: "light", measured: "light answered sooner" }),
    entry(SONNET, null),
    entry(K26, { lighter: "off", measured: "off answered sooner still" }),
    entry(ELSEWHERE, null),
  ],
  search_warning: null,
};

test("each model offers its own lighter position, or none", () => {
  assert.equal(lighterOf(OPUS, MENU), "light");
  assert.equal(lighterOf(K26, MENU), "off");
  assert.equal(lighterOf(SONNET, MENU), null);
  assert.equal(lighterOf(ELSEWHERE, MENU), null);
  assert.equal(lighterOf("not/in-the-menu", MENU), null);
  assert.equal(lighterOf(OPUS, null), null);
});

test("a model never touched reads normal, and sends nothing", () => {
  assert.equal(positionOf({}, OPUS, MENU), "normal");
  assert.equal(thinkingToSend({}, OPUS, MENU), null);
});

test("the kept choice is shown and sent for its own model only", () => {
  const kept = withPosition({}, OPUS, "light");
  assert.deepEqual(kept, { [OPUS]: "light" });
  assert.equal(positionOf(kept, OPUS, MENU), "light");
  assert.equal(thinkingToSend(kept, OPUS, MENU), "light");
  assert.equal(positionOf(kept, K26, MENU), "normal");
  assert.equal(thinkingToSend(kept, K26, MENU), null);
});

test("choosing normal again removes the model's entry", () => {
  const kept = withPosition(withPosition({}, OPUS, "light"), K26, "off");
  assert.deepEqual(withPosition(kept, OPUS, "normal"), { [K26]: "off" });
  assert.deepEqual(kept, { [OPUS]: "light", [K26]: "off" });
});

test("a kept word the model does not offer is neither shown nor sent", () => {
  const stale = { [OPUS]: "off" as const, [SONNET]: "light" as const };
  assert.equal(positionOf(stale, OPUS, MENU), "normal");
  assert.equal(thinkingToSend(stale, OPUS, MENU), null);
  assert.equal(positionOf(stale, SONNET, MENU), "normal");
  assert.equal(thinkingToSend(stale, SONNET, MENU), null);
});

test("before the menu has loaded the kept choice goes as it is", () => {
  assert.equal(thinkingToSend({ [OPUS]: "light" }, OPUS, null), "light");
  assert.equal(thinkingToSend({}, OPUS, null), null);
});

test("the positions are worded for the reader", () => {
  assert.equal(positionLabel("normal"), "Thinking: normal");
  assert.equal(positionLabel("light"), "Thinking: light");
  assert.equal(positionLabel("off"), "Thinking: off");
});

test("the panel's question mark says what the positions do and what was measured", () => {
  assert.equal(
    thinkingHelp(OPUS, MENU),
    "Thinking: normal is what claude-opus-5.5 does when nothing is said, and light asks it to " +
      "reason less. Measured on one look-through question (Oct 22, 2026), every setting found " +
      "the same thing; light answered sooner.",
  );
  assert.equal(
    thinkingHelp(K26, MENU),
    "Thinking: normal is what kimi-k2.6 does when nothing is said, and off asks it not to " +
      "reason. Measured on one look-through question (Oct 22, 2026), every setting found the " +
      "same thing; off answered sooner still.",
  );
  assert.equal(thinkingHelp(SONNET, MENU), null);
  assert.equal(thinkingHelp(OPUS, null), null);
});

test("what the tab kept is read back whatever it holds", () => {
  assert.deepEqual(readChoices({ [OPUS]: "light", [K26]: "off" }), { [OPUS]: "light", [K26]: "off" });
  assert.deepEqual(readChoices({ [OPUS]: "deep", [K26]: 3, [SONNET]: null }), {});
  assert.deepEqual(readChoices(undefined), {});
  assert.deepEqual(readChoices(null), {});
  assert.deepEqual(readChoices("light"), {});
  assert.deepEqual(readChoices([OPUS]), {});
});
