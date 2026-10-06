/* When a "?" is open, and where its panel sits: the two decisions behind
   `Explainer` in ui.tsx.

   A "?" holds a definition or a rule read once, for a reader who knows they
   have a question. It opens only on the reader's own press, never on hover,
   and closes on the next press, on Escape, on a press anywhere outside it, or
   when keyboard focus moves to an element outside it. A press inside its panel
   (selecting the text, say) keeps it open, though it takes focus off the "?"
   and gives it to no element at all.

   Pure, and with no runtime imports, so `tests/explain.test.ts` and
   `tests/explainPlacement.test.ts` run it under Node without a bundler. */

export type ExplainEvent =
  /** The "?" button itself: a click, a tap, Enter or Space. */
  | { kind: "press" }
  | { kind: "escape" }
  /** A press anywhere in the document while it is open; `inside` when it
      landed on the button or in the panel. */
  | { kind: "pointer"; inside: boolean }
  /** Focus moved while it is open: to the button or into the panel, to an
      element outside both, or to nothing. A press on the panel's text sends
      it to nothing (the "?" loses focus and no element gains it), and so
      does the window losing focus: neither is the reader moving elsewhere in
      the page. */
  | { kind: "focus"; to: "inside" | "outside" | "nothing" };

export function nextOpen(open: boolean, event: ExplainEvent): boolean {
  switch (event.kind) {
    case "press":
      return !open;
    case "escape":
      return false;
    case "pointer":
      return open && event.inside;
    case "focus":
      return open && event.to !== "outside";
  }
}

/* Where an open panel sits. It floats above the page, attached to its "?":
   under it when it fits, over it when it does not, and when it fits on
   neither side (a very short window), on the side with more room, its height
   capped to that room so its text scrolls inside it. Sideways its left edge
   is the "?"'s, slid left only as far as it takes to stay EDGE inside the
   window. So it lies wholly inside the window when it is placed.

   Everything here is in the window's coordinates, as `getBoundingClientRect`
   and `clientWidth` give them; the caller adds the scroll offsets. */

/** Between the "?" and its panel, in px: the old in-flow panel's `mt-2`. */
export const GAP = 8;
/** The least distance between a panel and the window's edges, in px. */
export const EDGE = 16;

export type Size = { width: number; height: number };
export type Placement = {
  left: number;
  top: number;
  /** The room it was given when it fits on neither side; null when it fits. */
  maxHeight: number | null;
};

export function placePanel(
  button: { left: number; top: number; bottom: number },
  panel: Size,
  viewport: Size,
): Placement {
  const below = viewport.height - EDGE - (button.bottom + GAP);
  const above = button.top - GAP - EDGE;
  const left = Math.max(EDGE, Math.min(button.left, viewport.width - EDGE - panel.width));
  if (panel.height <= below) return { left, top: button.bottom + GAP, maxHeight: null };
  if (panel.height <= above) return { left, top: button.top - GAP - panel.height, maxHeight: null };
  if (below >= above) return { left, top: button.bottom + GAP, maxHeight: below };
  return { left, top: EDGE, maxHeight: above };
}
