/* A chosen answer is told from the others by more than its colour (brief AY,
   WCAG 1.4.1): the Profile's yes/no questions and the Theme card draw their
   buttons with components/choice.ts. Every expected class is written out. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { choiceClass } from "../src/components/choice.ts";

const classes = (chosen: boolean) => new Set(choiceClass(chosen).split(/\s+/).filter(Boolean));

test("the chosen answer is underscored, 2px thick and 4px below its word; the others are not", () => {
  for (const cue of ["underline", "decoration-2", "underline-offset-4"]) {
    assert.ok(classes(true).has(cue), `the chosen answer lacks ${cue}`);
    assert.ok(!classes(false).has(cue), `an answer not chosen has ${cue}`);
  }
});

test("the chosen answer keeps its colours: filled with the olive tint, framed in the olive, in the deep olive", () => {
  for (const c of ["border-olive", "bg-olive-tint", "text-olive-deep"]) assert.ok(classes(true).has(c), c);
  for (const c of ["border-rule", "text-ink-soft", "hover:bg-ground"]) assert.ok(classes(false).has(c), c);
});

test("the chosen answer and the others share one box, so pressing an answer moves nothing", () => {
  const box = ["rounded-sm", "border", "px-3", "py-1.5", "text-sm"];
  for (const c of box) {
    assert.ok(classes(true).has(c), `the chosen answer lacks ${c}`);
    assert.ok(classes(false).has(c), `an answer not chosen lacks ${c}`);
  }
  // A weight, a size or a padding on one side only would move the answers after it.
  const sized = (s: Set<string>) => [...s].filter((c) => /^(font-|text-(xs|sm|base|lg)|p[xytrbl]?-|border-[0-9])/.test(c));
  assert.deepEqual(sized(classes(true)).sort(), sized(classes(false)).sort());
});
