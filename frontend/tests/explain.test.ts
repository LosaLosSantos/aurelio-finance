/* A "?" opens only on the reader's press, and closes on anything that means
   they are done with it: a second press, Escape, a press outside, or focus
   moving to an element outside.

   Run by `npm test` with Node's own test runner, which strips the types itself.
   Every expected value is written here, not read from the module. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { nextOpen } from "../src/components/explain.ts";

test("a press opens a closed ?, and a second press closes it", () => {
  assert.equal(nextOpen(false, { kind: "press" }), true);
  assert.equal(nextOpen(true, { kind: "press" }), false);
});

test("Escape closes an open ?", () => {
  assert.equal(nextOpen(true, { kind: "escape" }), false);
});

test("a press inside the panel keeps it open", () => {
  assert.equal(nextOpen(true, { kind: "pointer", inside: true }), true);
});

test("a press outside closes it", () => {
  assert.equal(nextOpen(true, { kind: "pointer", inside: false }), false);
});

test("keyboard focus moving to an element outside closes it", () => {
  assert.equal(nextOpen(true, { kind: "focus", to: "outside" }), false);
});

test("focus moving to the ? or into the panel keeps it open", () => {
  assert.equal(nextOpen(true, { kind: "focus", to: "inside" }), true);
});

test("a press inside the panel to select its text keeps it open, though focus leaves the ? for nothing", () => {
  // The two events that press sends, in the order it sends them.
  let open = nextOpen(true, { kind: "pointer", inside: true });
  open = nextOpen(open, { kind: "focus", to: "nothing" });
  assert.equal(open, true);
});

test("nothing but a press opens it", () => {
  assert.equal(nextOpen(false, { kind: "escape" }), false);
  assert.equal(nextOpen(false, { kind: "pointer", inside: true }), false);
  assert.equal(nextOpen(false, { kind: "pointer", inside: false }), false);
  assert.equal(nextOpen(false, { kind: "focus", to: "inside" }), false);
  assert.equal(nextOpen(false, { kind: "focus", to: "outside" }), false);
  assert.equal(nextOpen(false, { kind: "focus", to: "nothing" }), false);
});
