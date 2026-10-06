/* The transcript follows an answer while the reader is at the bottom, and
   stops the moment they go looking further up.

   Every case here is a measurement taken against the built app during a real
   stream, written down as a test so the next change to the rule has to argue
   with the numbers rather than with an opinion.

   Run by `npm test` with Node's own test runner, which strips the types
   itself: no bundler and no test framework, because the module under test has
   no runtime imports. Type-checked by `tsc -b` through tsconfig.node.json. */

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  FOLLOWING,
  gap,
  onContent,
  onScroll,
  onSend,
  type Follow,
  type Pane,
} from "../src/components/followStream.ts";

/** A transcript 701px tall — the panel's scrollport at 1440x900, measured —
    holding `height` of content, scrolled to `top`. */
function pane(height: number, top: number): Pane {
  return { height, top, client: 701 };
}

/** The bottom of a pane that tall. */
function bottomOf(height: number): number {
  return height - 701;
}

/** A state that has seen one reading, so the direction test has a `prev`. */
function watching(p: Pane, over: Partial<Follow> = {}): Follow {
  return { ...FOLLOWING, seen: p, ...over };
}

test("a fresh panel follows", () => {
  assert.equal(FOLLOWING.following, true);
});

test("content arriving pins the pane to the bottom, and records what it asked for", () => {
  const p = pane(1470, bottomOf(1470));
  const { state, scrollTo } = onContent(watching(p), pane(1516, bottomOf(1470)));
  assert.equal(scrollTo, bottomOf(1516));
  assert.equal(state.wrote, bottomOf(1516));
});

test("the write echoing back is not read as the reader", () => {
  // measured: one wheel gesture produced 48 coalesced scroll events, so a
  // boolean guard cleared in the handler cannot stay in sync. The value we
  // asked for is compared against the value observed instead.
  const asked = bottomOf(1516);
  const before = watching(pane(1470, bottomOf(1470)), { wrote: asked });
  const after = onScroll(before, pane(1516, asked));
  assert.equal(after.following, true);
});

test("a deliberate scroll up stops the following, at 40px", () => {
  // measured: a reader who scrolls up one line reads a gap of exactly 40.00,
  // which is SMALLER than the 46px a single arriving delta leaves behind —
  // which is why no distance threshold can tell them apart and the rule reads
  // direction instead.
  const before = watching(pane(1470, 769));
  const after = onScroll(before, pane(1470, 729));
  assert.equal(after.following, false);
});

test("46px of residue from an arriving delta is not a gesture", () => {
  // measured: parked exactly at the bottom reads 0.00, and 120-400ms later the
  // gap is 22-46px purely from text that arrived. scrollTop never moved.
  const before = watching(pane(1470, bottomOf(1470)));
  const after = onScroll(before, pane(1516, bottomOf(1470)));
  assert.equal(gap(after.seen!), 46);
  assert.equal(after.following, true);
});

test("the Thought fold clamps the pane, and that is not a gesture", () => {
  // measured, parked at the bottom when the answer begins: a scroll event with
  // scrollTop 4743 -> 4600 and scrollHeight 5444 -> 5301. The fall and the
  // shrink are the same 143, so the clamp explains all of it.
  const before = watching(pane(5444, 4743));
  const after = onScroll(before, pane(5301, 4600));
  assert.equal(after.following, true);
});

test("a reader who scrolls up THROUGH a fold is still a reader", () => {
  // the same 143px shrink, but the pane fell 400 further than the clamp can
  // account for. A rule that only asked "did the height change?" would call
  // this the fold and carry on scrolling under their hands.
  const before = watching(pane(5444, 4743));
  const after = onScroll(before, pane(5301, 4200));
  assert.equal(after.following, false);
});

test("growth alone never stops the following", () => {
  let s = watching(pane(1470, bottomOf(1470)));
  for (const h of [1516, 1562, 1608, 1654]) {
    const { state, scrollTo } = onContent(s, pane(h, s.seen!.top));
    assert.equal(scrollTo, bottomOf(h));
    s = onScroll(state, pane(h, bottomOf(h)));
  }
  assert.equal(s.following, true);
});

test("once stopped, content is left exactly where the reader put it", () => {
  const stopped = onScroll(watching(pane(5444, 4743)), pane(5444, 4200));
  assert.equal(stopped.following, false);
  const { scrollTo } = onContent(stopped, pane(5490, 4200));
  assert.equal(scrollTo, null);
});

test("scrolling back down to the bottom resumes it", () => {
  let s = onScroll(watching(pane(5444, 4743)), pane(5444, 4200));
  assert.equal(s.following, false);
  s = onScroll(s, pane(5444, 4500)); // moving down, still 243 from the bottom
  assert.equal(s.following, false);
  s = onScroll(s, pane(5444, bottomOf(5444) - 30)); // within reach of the end
  assert.equal(s.following, true);
});

test("coming back works even though a stale `wrote` sits below them", () => {
  /* The browser found this and the tests above did not, because they built
     their states with `wrote: null`. Real use never does: by the time anyone
     scrolls away, we have been writing the bottom on every delta, so `wrote`
     is frozen at some old offset — and the reader's own journey back down
     passes straight through it. Read as our echo, that gesture is swallowed
     and following never returns. Measured in the built app before the fix: the
     reader came back to a gap of 46 and the pane kept drifting, 319px away
     within two and a half seconds. */
  const following = { ...FOLLOWING, wrote: 4419, seen: pane(5120, 4419) };
  const away = onScroll(following, pane(5120, 4019));
  assert.equal(away.following, false);
  assert.equal(away.wrote, 4419, "the stale value is still there");

  /* And the content grew while they were away — 5,120px to 6,112px in the
     measured run — so the bottom they come back to is well PAST the offset we
     last wrote. That is what makes the echo test misfire, and it is why the
     first version of this test proved nothing: it had them return to 4,373,
     below the stale 4,419, where the test never fired at all. */
  const back = onScroll(away, pane(6112, bottomOf(6112)));
  assert.ok(bottomOf(6112) > 4419, "the new bottom is past the stale value");
  assert.equal(back.following, true);
});

test("a gap of 64 is back, a gap of 65 is not", () => {
  // the threshold is only ever applied to someone moving TOWARDS the bottom,
  // where generosity is free; it is never used to decide that someone left.
  const down = (g: number) => {
    const s = onScroll(watching(pane(5444, 4743)), pane(5444, 4200));
    return onScroll(s, pane(5444, bottomOf(5444) - g)).following;
  };
  assert.equal(down(64), true);
  assert.equal(down(65), false);
});

test("sending a question brings the following back", () => {
  // without this, one scroll up during one answer would silently stop every
  // answer for the rest of the session.
  const stopped = onScroll(watching(pane(5444, 4743)), pane(5444, 4200));
  assert.equal(stopped.following, false);
  assert.equal(onSend(stopped).following, true);
});

test("a pane with nothing in it asks for 0, not a negative offset", () => {
  const { scrollTo } = onContent(FOLLOWING, { height: 120, top: 0, client: 701 });
  assert.equal(scrollTo, 0);
});

test("a closed panel has no scrollport, and following it writes nothing wrong", () => {
  // the aside animates to w-0 and stays mounted, so the effect still runs with
  // a zero-height scrollport. It must not produce a negative scrollTop, and it
  // must not touch the window — which it cannot, because it only ever returns
  // a number for the caller to write to the pane.
  const { scrollTo } = onContent(FOLLOWING, { height: 0, top: 0, client: 0 });
  assert.equal(scrollTo, 0);
});
