/* The chat's menu of models says what OpenRouter's public list says of each.

   Brief BB: the backend reads the list once a day and gives each entry the
   day after which the model may be removed (`retires`) and whether the list
   has it (`listed`, null when it has not been read today). The menu says it
   beside the name; the "?" says it in a sentence; a model the list lacks stays
   offered, marked; and a pick the menu no longer offers is not sent.

   Run by `npm test` with Node's own test runner. Type-checked by `tsc -b`
   through tsconfig.node.json. The models are the app's own, the dates
   invented. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { modelName, modelsHelp, optionLabel, pickToSend } from "../src/components/modelMenu.ts";

const OPUS = "anthropic/claude-opus-5.5";
const SONNET = "anthropic/claude-sonnet-4.6";
const KIMI = "moonshotai/kimi-k2.6";

function entry(slug: string, retires: string | null, listed: boolean | null, note = "a note") {
  return { slug, note, retires, listed };
}

const MENU = {
  default: OPUS,
  models: [
    entry(OPUS, null, true, "the app's built-in default"),
    entry(SONNET, "2026-10-31", true, "1M context"),
    entry(KIMI, null, false, "about six times cheaper than K3"),
  ],
};

test("a model the list dates reads its date beside its name", () => {
  assert.equal(optionLabel(entry(SONNET, "2026-10-31", true), false), "claude-sonnet-4.6 · may be retired after 2026-10-31");
  assert.equal(
    optionLabel(entry(OPUS, "2026-11-11", true), true),
    "claude-opus-5.5 · default · may be retired after 2026-11-11",
  );
});

test("a model the list lacks stays offered, marked", () => {
  assert.equal(optionLabel(entry(KIMI, null, false), false), "kimi-k2.6 · no longer listed by OpenRouter");
  assert.equal(optionLabel(entry(KIMI, null, false), true), "kimi-k2.6 · default · no longer listed by OpenRouter");
});

test("with no date, or no read of the list today, the option is the name as it was", () => {
  assert.equal(optionLabel(entry(OPUS, null, true), true), "claude-opus-5.5 · default");
  assert.equal(optionLabel(entry(SONNET, null, null), false), "claude-sonnet-4.6");
});

test("the panel's ? lists the models, then says what the list says of each it dates or lacks", () => {
  assert.equal(
    modelsHelp(MENU),
    "The models: claude-opus-5.5, the app's built-in default; claude-sonnet-4.6, 1M context; " +
      "kimi-k2.6, about six times cheaper than K3. " +
      "OpenRouter may retire claude-sonnet-4.6 after 2026-10-31. OpenRouter no longer lists kimi-k2.6.",
  );
  const unread = { default: OPUS, models: [entry(OPUS, null, null, "the default")] };
  assert.equal(modelsHelp(unread), "The models: claude-opus-5.5, the default.");
});

test("a pick the menu offers is sent, one it no longer offers is not, and the default answers", () => {
  assert.equal(pickToSend(SONNET, MENU), SONNET);
  assert.equal(pickToSend(KIMI, MENU), KIMI, "a model the list lacks is still offered, so still sent");
  assert.equal(pickToSend("moonshotai/kimi-k3", MENU), null);
  assert.equal(pickToSend(null, MENU), null);
});

test("before the menu has loaded, a pick goes as it is", () => {
  assert.equal(pickToSend("moonshotai/kimi-k3", null), "moonshotai/kimi-k3");
  assert.equal(pickToSend(null, null), null);
});

test("a name is said without its provider", () => {
  assert.equal(modelName("anthropic/claude-opus-5.5"), "claude-opus-5.5");
  assert.equal(modelName("~anthropic/claude-opus-latest"), "claude-opus-latest");
  assert.equal(modelName("no-provider"), "no-provider");
});
