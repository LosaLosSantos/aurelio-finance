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
import { menuFace, modelName, modelNotices, modelsHelp, optionLabel, pickToSend } from "../src/components/modelMenu.ts";

const OPUS = "anthropic/claude-opus-5.5";
const SONNET = "anthropic/claude-sonnet-4.6";
const KIMI = "moonshotai/kimi-k2.6";

function entry(
  slug: string,
  retires: string | null,
  listed: boolean | null,
  note = "a note",
  warning: string | null = null,
  searches = false,
) {
  return { slug, note, retires, listed, warning, searches, thinking: null };
}

const MENU = {
  default: OPUS,
  models: [
    entry(OPUS, null, true, "the app's built-in default"),
    entry(SONNET, "2026-10-31", true, "1M context"),
    entry(KIMI, null, false, "about six times cheaper than K3"),
  ],
  search_warning: null,
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
  const unread = { default: OPUS, models: [entry(OPUS, null, null, "the default")], search_warning: null };
  assert.equal(modelsHelp(unread), "The models: claude-opus-5.5, the default.");
});

// The sentences are the backend's (`model_list.warning`), invented here.
const SAID = "OpenRouter may retire anthropic/claude-sonnet-4.6 after 2026-10-31, the date its list of models gives.";
const SEARCH_SAID = "The web searches run on anthropic/claude-haiku-5.5, which OpenRouter may retire after 2026-11-11.";

test("above the question box: the warning of the model the question goes to, and the search's when it searches", () => {
  const menu = {
    default: SONNET,
    models: [
      entry(SONNET, "2026-10-31", true, "1M context", SAID, true),
      entry("qwen/qwen3.8-max-0902", null, true, "1M context", null, false),
    ],
    search_warning: SEARCH_SAID,
  };
  assert.deepEqual(modelNotices(SONNET, menu), [SAID, SEARCH_SAID]);
  assert.deepEqual(modelNotices("qwen/qwen3.8-max-0902", menu), [], "a model that does not search says nothing of the search's");
  assert.deepEqual(modelNotices("not/in-the-menu", menu), []);
  assert.deepEqual(modelNotices(SONNET, null), [], "nothing before the menu has loaded");
  const quiet = { ...menu, models: [entry(SONNET, null, true, "1M context", null, true)], search_warning: null };
  assert.deepEqual(modelNotices(SONNET, quiet), []);
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

/* Closed, the menu shows a face (brief BD): the name, then the date or the
   mark, short enough for a phone; the open list keeps the whole labels. */

const TODAY = "2026-10-20";

test("closed, a model the list dates says its name and until when", () => {
  assert.deepEqual(menuFace(SONNET, MENU, TODAY, "en-US"), { name: "claude-sonnet-4.6", mark: "until Oct 31" });
  const later = { ...MENU, models: [entry("moonshotai/kimi-k3", "2027-01-15", true)] };
  assert.deepEqual(menuFace("moonshotai/kimi-k3", later, TODAY, "en-US"), { name: "kimi-k3", mark: "until Jan 15, 2027" });
});

test("closed, a model the list lacks says so, the default too, which the open list names", () => {
  assert.deepEqual(menuFace(KIMI, MENU, TODAY, "en-US"), { name: "kimi-k2.6", mark: "not listed" });
  const gone = { ...MENU, default: KIMI };
  assert.deepEqual(menuFace(KIMI, gone, TODAY, "en-US"), { name: "kimi-k2.6", mark: "not listed" });
  assert.equal(optionLabel(gone.models[2], true), "kimi-k2.6 · default · no longer listed by OpenRouter");
});

test("closed, a model with no date, one the menu does not offer and the menu not loaded say the name alone", () => {
  assert.deepEqual(menuFace(OPUS, MENU, TODAY, "en-US"), { name: "claude-opus-5.5", mark: null });
  assert.deepEqual(menuFace("moonshotai/kimi-k3", MENU, TODAY, "en-US"), { name: "kimi-k3", mark: null });
  assert.deepEqual(menuFace(SONNET, null, TODAY, "en-US"), { name: "claude-sonnet-4.6", mark: null });
  assert.deepEqual(menuFace("", null, TODAY, "en-US"), { name: "model…", mark: null });
});
