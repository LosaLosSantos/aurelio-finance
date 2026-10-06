/* Whether the transcript should follow an answer as it arrives.

   The panel used to call `bottomRef.scrollIntoView({ block: "end" })` on every
   change of `messages` — which is every delta of the stream, measured at 14
   calls in five seconds. That one call produced all three of the symptoms the
   reader reported, and neutralising it mid-stream (same page load, same answer
   still arriving) made all three disappear: the chat's own transcript went from
   undone 3 of 3 to 0 of 3, the page behind it from 3 of 3 to 0 of 3, and the
   page with the panel CLOSED from 2 of 3 to 0 of 3.

   Two different failures came out of the one call, and they need separating
   because only one of them is about the transcript:

   THE PAGE. `scrollIntoView` scrolls every scrollable ancestor, the window
   included. The target's bottom sits above the viewport's, so `block: "end"`
   asks the window to scroll UP by that gap; the panel is `sticky top-0
   h-screen`, so the gap does not close when the window moves, the same request
   repeats on the next delta, and it saturates at 0. Measured: every attempt to
   scroll the page during a stream came back to exactly 0, never to a partway
   resting point. Nothing here scrolls the window at all any more — the pane's
   own `scrollTop` is written instead — which is what ends that half, and it
   ends it whether the panel is open or closed.

   THE TRANSCRIPT. This module is the other half: WHEN to pin the pane to the
   bottom. Following is right while the reader is at the bottom and wrong the
   moment they have deliberately gone looking for something further up.

   WHY DIRECTION AND NOT DISTANCE. The obvious rule — "follow while the gap to
   the bottom is under N pixels" — cannot work, and the measurement says so.
   Parked exactly at the bottom the gap reads 0.00, but one arriving delta puts
   it at 22-46px within 400ms, and a wheel that reaches the bottom reads 0 or
   45-46 depending on whether text landed between the gesture and the read. A
   reader who deliberately scrolls up one line reads 40. There is no N that
   admits the 46 and refuses the 40. So the decision is made from the DIRECTION
   of the reader's own movement, where it is unambiguous, and the distance is
   used only to let them back in.

   WHY A SHRINK IS NOT A GESTURE. `Thought` folds itself the instant the answer
   begins, removing up to its `max-h-48` from the transcript, and the browser
   clamps `scrollTop` to the shorter content. Measured, parked at the bottom:
   a scroll event with scrollTop 4743 -> 4600 and scrollHeight 5444 -> 5301 —
   the fall and the shrink are the same 143. Direction alone would read that as
   the reader leaving, at the exact instant the answer starts, and follow would
   stay off for the rest of it. A clamp can only account for a fall as large as
   the shrink; anything beyond that is the reader's hand, and that is the test.

   WHY THE LAST WRITTEN VALUE AND NOT A FLAG. Our own write fires its scroll
   event asynchronously and they coalesce — one wheel gesture produced 48
   events in 300ms — so a boolean set before the write and cleared in the
   handler loses sync exactly when the stream is busiest. The value we asked
   for is compared against the value observed instead. It is self-correcting:
   a stale `wrote` costs at most one misread event, and it is decidable here,
   in a module with no imports, which is the only way `npm test` can reach it. */

/** What the transcript's scrollport reads at one moment. */
export type Pane = {
  /** `scrollTop` */
  top: number;
  /** `scrollHeight` */
  height: number;
  /** `clientHeight` */
  client: number;
};

export type Follow = {
  /** Pin the pane to the bottom as content arrives. */
  following: boolean;
  /** The `scrollTop` this module last asked for, or null if it never has.
      An observed value at least this high is our own write echoing back. */
  wrote: number | null;
  /** The previous reading, for the direction test. */
  seen: Pane | null;
};

/** A reader who has just opened the panel is at the bottom of nothing, and
    wants to see what arrives. */
export const FOLLOWING: Follow = { following: true, wrote: null, seen: null };

/* Sub-pixel layout, not intent. Scroll offsets are fractional on a scaled
   display and the readings here are rounded by the caller, so a fall of one
   pixel says nothing. */
const NOISE = 2;

/* How close to the bottom counts as arriving back. Deliberately larger than
   the 46px of residue one delta leaves, because this threshold is only ever
   applied to a reader moving TOWARDS the bottom, where being generous costs
   nothing: they are going there. It is never used to decide that someone has
   left. */
const ARRIVED = 64;

/** How far the bottom is from view. */
export function gap(p: Pane): number {
  return p.height - p.top - p.client;
}

/** The scroll event the browser fires — the reader's gesture, the clamp after
    a block folds, or our own write coming back. */
export function onScroll(state: Follow, now: Pane): Follow {
  const prev = state.seen;
  const next: Follow = { ...state, seen: now };
  if (prev === null) return next;

  /* Our own write, echoing. It lands at the bottom, so anything at or beyond
     what we asked for is ours and says nothing about the reader.

     Only while FOLLOWING, and that guard is the whole of a bug the browser
     found and these tests did not. Once the reader has scrolled away we stop
     writing, so `wrote` is frozen at some old bottom — and when they scroll
     back down, their own `scrollTop` passes it. Without the guard that gesture
     is read as our echo and swallowed, so following never comes back: measured
     in the built app, the reader returned to a gap of 46 and the pane simply
     kept drifting away from them. We only write while following, so an echo is
     only possible while following. */
  if (state.following && state.wrote !== null && now.top >= state.wrote - NOISE) {
    return next;
  }

  // A shrink above the reader forces a clamp. It can move `scrollTop` down by
  // at most what it removed; a larger fall than that is a hand on the wheel.
  const shrank = Math.max(0, prev.height - now.height);
  const fell = prev.top - now.top;

  if (fell > shrank + NOISE) {
    return { ...next, following: false };
  }
  // Moving down, or held still: the reader is back once the bottom is in view.
  if (gap(now) <= ARRIVED) {
    return { ...next, following: true };
  }
  return next;
}

/** Content arrived. Returns the `scrollTop` to write, or null to leave the
    pane exactly where the reader put it. */
export function onContent(
  state: Follow,
  now: Pane,
): { state: Follow; scrollTo: number | null } {
  if (!state.following) {
    return { state: { ...state, seen: now }, scrollTo: null };
  }
  const bottom = Math.max(0, now.height - now.client);
  return {
    state: { ...state, wrote: bottom, seen: { ...now, top: bottom } },
    scrollTo: bottom,
  };
}

/** The reader sent a question. Whatever they were reading before, they are
    here now and waiting for an answer — so following comes back on. Without
    this, one scroll up during one answer would silently stop every answer for
    the rest of the session. */
export function onSend(state: Follow): Follow {
  return { ...state, following: true };
}
