/* What a holding's line says about its dividends (brief AF).

   A stated policy is said as before. An empty one is followed through the
   holding's own dividend history, and the line says when it last paid: a
   share has no policy to choose. Every expected value is written here. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { dividendWord, policyWord } from "../src/components/dividendLine.ts";

test("a stated policy is said, whatever the history lists", () => {
  assert.equal(dividendWord("acc", "2026-09-15"), "Accumulating");
  assert.equal(dividendWord("dist", null), "Distributing");
  assert.equal(dividendWord("dist", "2026-09-15"), "Distributing");
});

test("with no policy stated, the line says when the holding last paid", () => {
  assert.equal(dividendWord(null, "2026-09-15"), "last dividend 2026-09-15");
  assert.equal(dividendWord("", "2024-08-07"), "last dividend 2024-08-07");
});

test("with no policy and no dividend listed, the line says nothing", () => {
  assert.equal(dividendWord(null, null), null);
  assert.equal(dividendWord(undefined, undefined), null);
});

test("a token the app does not know is shown as stored", () => {
  assert.equal(policyWord("semi"), "semi");
  assert.equal(policyWord(""), null);
});
