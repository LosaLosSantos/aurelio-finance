/* Where an open "?" panel sits: under its "?", over it when there is no room
   under it, and inside the window either way.

   Run by `npm test` like explain.test.ts. Every expected value is worked out
   here, not read from the module. A "?" is 24px square (`h-6 w-6`); the window
   is 1440 by 900 unless a test says otherwise. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { EDGE, GAP, placePanel } from "../src/components/explain.ts";

const wide = { width: 1440, height: 900 };
const at = (left: number, top: number) => ({ left, top, bottom: top + 24 });

test("8px between the ? and its panel, 16px between the panel and the window's edges", () => {
  assert.equal(GAP, 8);
  assert.equal(EDGE, 16);
});

test("it opens under its ?, its left edge at the ?'s, when there is room on both sides", () => {
  // Under: 400 + 24 + 8.
  assert.deepEqual(placePanel(at(300, 400), { width: 400, height: 120 }, wide), { left: 300, top: 432, maxHeight: null });
});

test("it opens over its ? when there is no room under it", () => {
  // Room under: 900 - 16 - (824 + 8) = 52, short of 120. Over: 800 - 8 - 120.
  assert.deepEqual(placePanel(at(300, 800), { width: 400, height: 120 }, wide), { left: 300, top: 672, maxHeight: null });
});

test("a panel that fits under its ? to the pixel stays under; one pixel more and it goes over", () => {
  // Room under: 900 - 16 - (756 + 8) = 120, exactly the panel; it ends at 884.
  assert.deepEqual(placePanel(at(300, 732), { width: 400, height: 120 }, wide), { left: 300, top: 764, maxHeight: null });
  // Room under: 119. Over: 733 - 8 - 120.
  assert.deepEqual(placePanel(at(300, 733), { width: 400, height: 120 }, wide), { left: 300, top: 605, maxHeight: null });
});

test("a panel that fits over its ? to the pixel goes over, uncapped; one pixel less room and it is capped", () => {
  const short = { width: 1440, height: 300 };
  // Under: 300 - 16 - (168 + 8) = 108, short of 120. Over: 144 - 8 - 16 = 120, exactly the panel.
  assert.deepEqual(placePanel(at(300, 144), { width: 400, height: 120 }, short), { left: 300, top: 16, maxHeight: null });
  // Over: 119, under: 109. It fits on neither side, and over has more room.
  assert.deepEqual(placePanel(at(300, 143), { width: 400, height: 120 }, short), { left: 300, top: 16, maxHeight: 119 });
});

test("when it fits on neither side it takes the side with more room, its height capped to that room", () => {
  const short = { width: 1440, height: 300 };
  const tall = { width: 400, height: 200 };
  // Under: 300 - 16 - (124 + 8) = 152. Over: 100 - 8 - 16 = 76.
  assert.deepEqual(placePanel(at(300, 100), tall, short), { left: 300, top: 132, maxHeight: 152 });
  // Under: 300 - 16 - (224 + 8) = 52. Over: 200 - 8 - 16 = 176, from the top edge down to 8px above the ?.
  assert.deepEqual(placePanel(at(300, 200), tall, short), { left: 300, top: 16, maxHeight: 176 });
  // Under: 300 - 16 - (162 + 8) = 114. Over: 138 - 8 - 16 = 114. A tie goes under.
  assert.deepEqual(placePanel(at(300, 138), tall, short), { left: 300, top: 170, maxHeight: 114 });
});

test("near the right edge it slides left only as far as it takes to stay 16px inside", () => {
  // 1000 + 400 ends at 1400, inside 1424: not moved.
  assert.equal(placePanel(at(1000, 400), { width: 400, height: 120 }, wide).left, 1000);
  // 1300 + 400 would end at 1700: slid to 1440 - 16 - 400.
  assert.equal(placePanel(at(1300, 400), { width: 400, height: 120 }, wide).left, 1024);
});

test("it never comes closer than 16px to the left edge", () => {
  assert.equal(placePanel(at(4, 400), { width: 400, height: 120 }, wide).left, 16);
});

test("at 390px a ? on the right gives a panel as wide as it may be, 16px from both edges", () => {
  // 358 = 390 - 2 * 16, the widest a panel is allowed there. Under: 300 + 24 + 8.
  const phone = { width: 390, height: 844 };
  assert.deepEqual(placePanel(at(330, 300), { width: 358, height: 80 }, phone), { left: 16, top: 332, maxHeight: null });
});

test("wherever its ? is in the window, the panel lies 16px inside it, never over the ?, and beside it sideways", () => {
  const cases = [
    { viewport: wide, sizes: [{ width: 300, height: 60 }, { width: 520, height: 200 }, { width: 520, height: 420 }] },
    { viewport: { width: 390, height: 844 }, sizes: [{ width: 300, height: 60 }, { width: 358, height: 200 }, { width: 358, height: 400 }] },
  ];
  let checked = 0;
  for (const { viewport, sizes } of cases) {
    for (const size of sizes) {
      for (let left = 0; left <= viewport.width - 24; left += 37) {
        for (let top = 0; top <= viewport.height - 24; top += 41) {
          const q = at(left, top);
          const p = placePanel(q, size, viewport);
          const height = p.maxHeight == null ? size.height : Math.min(size.height, p.maxHeight);
          const where = `? at ${left},${top}, panel ${size.width}x${size.height}, window ${viewport.width}x${viewport.height}`;
          assert.ok(p.left >= 16 && p.left + size.width <= viewport.width - 16, `sideways, ${where}`);
          assert.ok(p.top >= 16 && p.top + height <= viewport.height - 16, `up and down, ${where}`);
          assert.ok(p.top >= q.bottom + 8 || p.top + height <= q.top - 8, `clear of the ?, ${where}`);
          assert.ok(p.left < q.left + 24 && p.left + size.width > q.left, `beside the ?, ${where}`);
          checked++;
        }
      }
    }
  }
  assert.ok(checked > 1000, `only ${checked} placements checked`);
});
