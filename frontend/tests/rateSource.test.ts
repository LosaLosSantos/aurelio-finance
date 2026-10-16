/* Whose rate, said beside its day (brief BA). Every expected value is
   written here. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { fxProvenance, rateLine } from "../src/components/rateSource.ts";

const short = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;

test("the Portfolio says each source beside its own day", () => {
  assert.equal(fxProvenance("2026-10-15", null, short), "FX ECB 15/10");
  assert.equal(fxProvenance("2026-10-15", "2026-10-14", short), "FX ECB 15/10 · FX Yahoo 14/10");
  assert.equal(fxProvenance(null, "2026-10-14", short), "FX Yahoo 14/10");
  assert.equal(fxProvenance(null, null, short), null);
});

test("a fixed sum says whose rate it took", () => {
  assert.equal(rateLine("2026-01-05", "Yahoo"), "at the Yahoo rate of 2026-01-05");
  assert.equal(rateLine("2026-01-05", "ECB"), "at the ECB rate of 2026-01-05");
  assert.equal(rateLine("2026-01-05", null), "at the ECB rate of 2026-01-05");
});
