import { test } from "node:test";
import assert from "node:assert/strict";

import { STALE_LINE, heading, waiting } from "../src/components/cardOutcome.ts";

test("a card waits only while nothing became of it", () => {
  assert.equal(waiting("pending"), true);
  assert.equal(waiting(undefined), true, "a card stored before outcomes were written");
  for (const decided of ["confirmed", "rejected", "stale"] as const) {
    assert.equal(waiting(decided), false, decided);
  }
});

test("each outcome has its own word over the card", () => {
  assert.equal(heading("pending"), "Proposed");
  assert.equal(heading("confirmed", "Added to your watchlist"), "Added to your watchlist");
  assert.equal(heading("confirmed"), "Recorded");
  assert.equal(heading("rejected"), "Rejected");
  assert.equal(heading("stale"), "Out of date");
});

test("a stale card says nothing was written and how to get a fresh one", () => {
  assert.match(STALE_LINE, /nothing was written/);
  assert.match(STALE_LINE, /Ask again for a fresh one/);
  assert.equal(STALE_LINE.includes(String.fromCharCode(0x2014)), false, "no em dash");
});
