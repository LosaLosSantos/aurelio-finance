/* The start-up banner says which figure corrects a recorded dividend: the
   broker's credit, after tax, since the market's figure is gross (brief AF).
   Every expected value is written here. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { dividendsNote, recordedFor, type Created } from "../src/components/catchUpNote.ts";

test("no dividend recorded, nothing added", () => {
  assert.equal(dividendsNote(0), null);
});

test("one dividend: gross, and corrected with the broker's credit", () => {
  assert.equal(
    dividendsNote(1),
    "The dividend is the market's gross figure, before tax: correct it with what your broker credited.",
  );
});

test("the dividends recorded are counted by ticker and account (brief AZ)", () => {
  const div = (symbol: string, institution_id: number): Created => ({ kind: "dividend", symbol, institution_id });
  const accounts = { "7": "Broker A", "8": "Broker B" };
  const created = [div("XDIV.MI", 7), div("XDIV.MI", 7), { kind: "buy", symbol: "XWLD.MI", institution_id: 7 }, div("YDIV.MI", 8), div("XDIV.MI", 7)];
  assert.equal(recordedFor(created, accounts), "Recorded for XDIV.MI at Broker A (3) and YDIV.MI at Broker B (1).");
  assert.equal(recordedFor([div("XDIV.MI", 7)], accounts), "Recorded for XDIV.MI at Broker A (1).");
  assert.equal(
    recordedFor([div("A.MI", 7), div("B.MI", 7), div("C.MI", 8)], accounts),
    "Recorded for A.MI at Broker A (1), B.MI at Broker A (1) and C.MI at Broker B (1).",
  );
  assert.equal(recordedFor([{ kind: "buy", symbol: "XWLD.MI", institution_id: 7 }], accounts), null);
});

test("several dividends: each corrected on its own", () => {
  assert.equal(
    dividendsNote(4),
    "The dividends are the market's gross figures, before tax: correct each with what your broker credited.",
  );
});
