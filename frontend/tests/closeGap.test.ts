/* A close four days from a situation is near enough, on whichever day the
   clocks change.

   Turning a situation's value into units refuses a close more than four days
   from the situation's date, since dividing one day's value by another day's
   price invents a quantity. Counted in milliseconds between the two local
   midnights, the four days from 2026-10-25 to 2026-10-29 read 4.0417 in Rome,
   where the clocks go back on the 25th, and the close was refused (measured
   2026-10-05). New York's clocks go back on 2026-11-01, the same way.

   Each test sets the time zone it needs (`process.env.TZ`, which Node applies
   at once). Every expected value is written here. */

import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { CLOSE_ALLOWANCE_DAYS, closeTooFar } from "../src/components/closeGap.ts";

const ZONE = process.env.TZ;
afterEach(() => {
  if (ZONE === undefined) delete process.env.TZ;
  else process.env.TZ = ZONE;
});

const ZONES = ["UTC", "Europe/Rome", "America/New_York", "Pacific/Kiritimati", "Pacific/Pago_Pago"];

test("four days across Rome's autumn clock change are near enough, either way round", () => {
  process.env.TZ = "Europe/Rome";
  assert.equal(closeTooFar("2026-10-25", "2026-10-29"), false);
  assert.equal(closeTooFar("2026-10-29", "2026-10-25"), false);
});

test("four days are near enough in every zone, the days the clocks change included", () => {
  for (const zone of ZONES) {
    process.env.TZ = zone;
    for (const [situation, close] of [
      ["2026-10-05", "2026-10-09"],
      ["2026-10-25", "2026-10-29"],
      ["2026-11-01", "2026-11-05"],
      ["2026-03-29", "2026-04-02"],
      ["2026-03-08", "2026-03-12"],
    ]) {
      assert.equal(closeTooFar(situation, close), false, `${zone}: ${situation} to ${close}`);
    }
  }
});

test("five days are too far in every zone, the days the clocks change included", () => {
  for (const zone of ZONES) {
    process.env.TZ = zone;
    for (const [situation, close] of [
      ["2026-10-05", "2026-10-10"],
      ["2026-10-24", "2026-10-29"],
      ["2026-03-28", "2026-04-02"],
      ["2026-10-29", "2026-10-24"],
    ]) {
      assert.equal(closeTooFar(situation, close), true, `${zone}: ${situation} to ${close}`);
    }
  }
});

test("the allowance is four days", () => {
  assert.equal(CLOSE_ALLOWANCE_DAYS, 4);
});
