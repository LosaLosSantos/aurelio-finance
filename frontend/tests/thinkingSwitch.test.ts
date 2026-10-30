/* The chat's Thinking control: normal, the model's lighter position, and on
   Opus 5.5 two positions above normal.

   Brief BF: the backend's menu gives each model its lighter position
   ("light" where it reasons less, "off" where it stops) and what was measured
   of it, or none. The control shows the position kept for the model in view,
   sends the lighter word or nothing, keeps a choice per model, and drops a
   kept choice the model no longer offers rather than sending it.

   Brief BH: the menu now lists every position in the control's order, and
   Opus 5.5 has four, light, normal, high and max, the last two each with a
   line the panel shows under the control while it is chosen. Every other
   model reads as it did.

   Run by `npm test` with Node's own test runner. Type-checked by `tsc -b`
   through tsconfig.node.json. The models are the app's own; the measured
   sentences and the lines stand-ins. */

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  lineOf,
  positionLabel,
  positionOf,
  positionsOf,
  readChoices,
  thinkingHelp,
  thinkingToSend,
  withPosition,
} from "../src/components/thinkingSwitch.ts";

const OPUS = "anthropic/claude-opus-5.5";
const SONNET = "anthropic/claude-sonnet-4.6";
const K26 = "moonshotai/kimi-k2.6";
const ELSEWHERE = "someone/a-model-set-in-env";

type Word = "normal" | "light" | "off" | "high" | "max";
type Thinking = {
  lighter: "light" | "off";
  measured: string;
  positions: Word[];
  lines: Record<string, string>;
  heavier_measured: string | null;
};

function entry(slug: string, thinking: Thinking | null) {
  return { slug, note: "a note", retires: null, listed: true, warning: null, searches: false, thinking };
}

const HIGH_LINE = "High thinks longer, a stand-in line.";
const MAX_LINE = "Max thinks the most, a stand-in line.";

const MENU = {
  default: OPUS,
  models: [
    entry(OPUS, {
      lighter: "light",
      measured: "light answered sooner",
      positions: ["light", "normal", "high", "max"],
      lines: { high: HIGH_LINE, max: MAX_LINE },
      heavier_measured: "Max took longer.",
    }),
    entry(SONNET, null),
    entry(K26, {
      lighter: "off",
      measured: "off answered sooner still",
      positions: ["normal", "off"],
      lines: {},
      heavier_measured: null,
    }),
    entry(ELSEWHERE, null),
  ],
  search_warning: null,
};

test("each model lists its own positions in the control's order, or none", () => {
  assert.deepEqual(positionsOf(OPUS, MENU), ["light", "normal", "high", "max"]);
  assert.deepEqual(positionsOf(K26, MENU), ["normal", "off"]);
  assert.equal(positionsOf(SONNET, MENU), null);
  assert.equal(positionsOf(ELSEWHERE, MENU), null);
  assert.equal(positionsOf("not/in-the-menu", MENU), null);
  assert.equal(positionsOf(OPUS, null), null);
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

test("high and max on Opus are shown and sent", () => {
  const high = withPosition({}, OPUS, "high");
  assert.deepEqual(high, { [OPUS]: "high" });
  assert.equal(positionOf(high, OPUS, MENU), "high");
  assert.equal(thinkingToSend(high, OPUS, MENU), "high");
  const max = withPosition(high, OPUS, "max");
  assert.deepEqual(max, { [OPUS]: "max" });
  assert.equal(positionOf(max, OPUS, MENU), "max");
  assert.equal(thinkingToSend(max, OPUS, MENU), "max");
});

test("choosing normal again removes the model's entry", () => {
  const kept = withPosition(withPosition({}, OPUS, "max"), K26, "off");
  assert.deepEqual(withPosition(kept, OPUS, "normal"), { [K26]: "off" });
  assert.deepEqual(kept, { [OPUS]: "max", [K26]: "off" });
});

test("a kept word the model does not offer is neither shown nor sent", () => {
  const stale = { [OPUS]: "off" as const, [SONNET]: "light" as const, [K26]: "max" as const };
  assert.equal(positionOf(stale, OPUS, MENU), "normal");
  assert.equal(thinkingToSend(stale, OPUS, MENU), null);
  assert.equal(positionOf(stale, SONNET, MENU), "normal");
  assert.equal(thinkingToSend(stale, SONNET, MENU), null);
  assert.equal(positionOf(stale, K26, MENU), "normal");
  assert.equal(thinkingToSend(stale, K26, MENU), null);
});

test("before the menu has loaded the kept choice goes as it is", () => {
  assert.equal(thinkingToSend({ [OPUS]: "light" }, OPUS, null), "light");
  assert.equal(thinkingToSend({ [OPUS]: "max" }, OPUS, null), "max");
  assert.equal(thinkingToSend({}, OPUS, null), null);
});

test("the positions are worded for the reader", () => {
  assert.equal(positionLabel("normal"), "Thinking: normal");
  assert.equal(positionLabel("light"), "Thinking: light");
  assert.equal(positionLabel("off"), "Thinking: off");
  assert.equal(positionLabel("high"), "Thinking: high");
  assert.equal(positionLabel("max"), "Thinking: max");
});

test("high and max each have their line under the control, and nothing else does", () => {
  assert.equal(lineOf(OPUS, "high", MENU), HIGH_LINE);
  assert.equal(lineOf(OPUS, "max", MENU), MAX_LINE);
  assert.equal(lineOf(OPUS, "normal", MENU), null);
  assert.equal(lineOf(OPUS, "light", MENU), null);
  assert.equal(lineOf(K26, "off", MENU), null);
  assert.equal(lineOf(K26, "normal", MENU), null);
  assert.equal(lineOf(SONNET, "normal", MENU), null);
  assert.equal(lineOf(OPUS, "max", null), null);
});

test("the panel's question mark says what the positions do and what was measured", () => {
  assert.equal(
    thinkingHelp(OPUS, MENU),
    "Thinking: normal is what claude-opus-5.5 does when nothing is said; light asks it to " +
      "reason less, high to reason more, and max to reason the most. Measured on one " +
      "look-through question (Oct 22, 2026), light found what normal found; light answered " +
      "sooner. Max took longer. A Stop ends what you see; OpenRouter stops the model and its " +
      "billing only on the providers that support it.",
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
  assert.deepEqual(readChoices({ [OPUS]: "max", [ELSEWHERE]: "high" }), { [OPUS]: "max", [ELSEWHERE]: "high" });
  assert.deepEqual(readChoices({ [OPUS]: "deep", [K26]: 3, [SONNET]: null }), {});
  assert.deepEqual(readChoices({ [OPUS]: "normal" }), {});
  assert.deepEqual(readChoices(undefined), {});
  assert.deepEqual(readChoices(null), {});
  assert.deepEqual(readChoices("light"), {});
  assert.deepEqual(readChoices([OPUS]), {});
});
